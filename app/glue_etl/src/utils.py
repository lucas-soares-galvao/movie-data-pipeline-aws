"""utils.py — Funções auxiliares do Glue ETL."""

import json
import logging
from typing import Any, Callable, Dict, List, Optional

import awswrangler as wr
import boto3
import pandas as pd

from shared_utils.glue_helpers import get_resolved_option  # noqa: F401
from shared_utils.idioma import (  # noqa: F401
    add_detected_language_column,
    detect_language_aws,
    detect_language_langdetect,
    resolve_detect_language_fn,
)
from shared_utils.traducao import (  # noqa: F401
    resolve_pt_translation,
    reuse_existing_translation,
    resolve_translate_fn,
    translate_text,
    translate_text_aws,
)
from shared_utils.triggers import trigger_glue_job  # noqa: F401

# Caminhos no S3 SOR organizados por media_type e table_type.
# O placeholder {year} é substituído em tempo de execução em read_from_sor().
SOR_KEYS = {
    "movie": {
        "genre":                "tmdb/genre/movie/generos_filmes.json",
        "configuration":        "tmdb/configuration/languages/idiomas.json",
        "discover":             "tmdb/discover/movie/ano={year}/",
        "watch_providers_ref":  "tmdb/watch_providers_ref/movie/watch_providers_ref.json",
        "now_playing":          "tmdb/now_playing/movie/",
    },
    "tv": {
        "genre":                "tmdb/genre/tv/generos_series.json",
        "configuration":        "tmdb/configuration/countries/paises.json",
        "discover":             "tmdb/discover/tv/ano={year}/",
        "watch_providers_ref":  "tmdb/watch_providers_ref/tv/watch_providers_ref.json",
    },
}

# A TMDB retorna variações do mesmo serviço (ex: "Netflix", "Netflix Standard with Ads").
# Estratégia: remove sufixos comuns, depois aplica overrides manuais para casos especiais.
# IMPORTANTE: a ordem importa — sufixos mais específicos devem vir antes dos genéricos.
# Ex: " Standard with Ads" deve vir antes de " with Ads"; senão "Netflix Standard with Ads"
# removeria só " with Ads" e viraria "Netflix Standard" em vez de "Netflix".
_CANONICAL_SUFFIXES = [
    " Amazon Channel",
    " Apple TV Channel",
    " Apple Channel",
    " Plus Premium",
    " Premium",
    " Standard with Ads",
    " with Ads",
]

_CANONICAL_OVERRIDES = {
    "Paramount Plus": "Paramount+",
    "Paramount":      "Paramount+",   # "Paramount Plus Premium" → strip " Plus Premium" → aqui
    "MGM Plus":       "MGM+",         # "MGM Plus Amazon Channel" → strip sufixo → aqui
    "Claro video":    "Claro Video",  # Padroniza capitalização
}


def derive_canonical_name(name: str) -> str:
    """
    Normaliza o nome de uma plataforma removendo sufixos de variante.

    Ex: "Netflix Standard with Ads" → "Netflix", "Paramount Plus Premium" → "Paramount+"

    Args:
        name: Nome original retornado pela API TMDB

    Returns:
        Nome canônico normalizado
    """
    result = name.strip()
    name_lower = result.lower()

    # Remove o primeiro sufixo que corresponder (por ordem de especificidade)
    for suffix in _CANONICAL_SUFFIXES:
        if name_lower.endswith(suffix.lower()):
            result = result[: -len(suffix)]  # Remove os últimos N caracteres
            break

    # Aplica override manual se o resultado estiver na lista
    return _CANONICAL_OVERRIDES.get(result, result)


logger = logging.getLogger()


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê todos os argumentos do job Glue ETL e retorna em um dicionário.

    Returns:
        Dicionário com todos os argumentos disponíveis nesta execução
    """
    required_args = [
        "S3_BUCKET_SOR",
        "S3_BUCKET_SOT",
        "MEDIA_TYPE",
        "DATABASE",
        "TABLE_NAME",
        "TABLE_TYPE",
        "GLUE_DATA_QUALITY_JOB_NAME",
        "GLUE_DETAILS_JOB_NAME",
    ]
    args = get_resolved_option(required_args)

    # Tenta ler YEAR e END_YEAR — só presentes nos runs de discover (não em genre/config).
    # getResolvedOptions usa argparse internamente; argparse chama sys.exit() (não raise KeyError)
    # quando um argumento obrigatório está ausente. Capturar SystemExit aqui é o padrão oficial
    # do Glue para argumentos opcionais que não fazem parte de todos os runs.
    try:
        args.update(get_resolved_option(["YEAR", "END_YEAR"]))
    except SystemExit:
        pass

    # Opcional: qual serviço de tradução usar para name_pt de países/idiomas
    # ("google" ou "aws"). Ausente = "google" (caminho automático via EventBridge não
    # passa esse argumento) — mesmo padrão de opcional usado acima para YEAR/END_YEAR.
    try:
        args.update(get_resolved_option(["TRANSLATE_PROVIDER"]))
    except SystemExit:
        args["TRANSLATE_PROVIDER"] = "google"

    return args


def _add_translation(
    df: pd.DataFrame,
    description: str,
    key_column: str,
    translate_fn: Optional[Callable[[str], str]] = None,
    previous_df: Optional[pd.DataFrame] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> pd.DataFrame:
    """
    Traduz a coluna english_name de inglês para português e grava como name_pt,
    junto com name_idioma_detectado_en, name_idioma_detectado_pt e
    name_tentativas_traducao.

    Antes de traduzir, reaproveita name_pt já existente em previous_df quando
    english_name não mudou desde a última execução (ver reuse_existing_translation em
    shared_utils.traducao) — evita chamar a API de tradução para países/idiomas cujo
    nome em inglês é idêntico ao já processado. O resto do fluxo (detecção de idioma,
    cópia direta quando a fonte já é pt, tradução via Google/AWS e teto de tentativas)
    é responsabilidade de resolve_pt_translation — ver sua docstring em
    shared_utils.traducao.

    Args:
        df:           DataFrame com coluna english_name.
        description:  Descrição dos itens para o log (ex: "países", "idiomas").
        key_column:   Coluna usada para casar registros antigos e novos no cache
                      de tradução (ex: "iso_3166_1" para países, "iso_639_1" para idiomas).
        translate_fn: Função de tradução (texto) -> texto traduzido. Por padrão usa
                      translate_text puro (Google Translate); os chamadores em produção
                      passam o resultado de resolve_translate_fn (google ou aws).
        previous_df:  Tabela configuration já gravada na SOT (ver read_existing_configuration),
                      usada como cache de tradução, ou None se não há histórico.
        detect_fn:    Função de detecção de idioma (texto) -> idioma detectado (ou
                      None). Por padrão usa resolve_detect_language_fn().

    Returns:
        DataFrame com as colunas name_idioma_detectado_en, name_idioma_detectado_pt,
        name_pt e name_tentativas_traducao adicionadas.
    """
    if "english_name" not in df.columns:
        return df

    # translate_fn resolvido em runtime (não como default de parâmetro) para que
    # patch("src.utils.translate_text", ...) nos testes continue funcionando quando
    # o chamador não passa um translate_fn explícito.
    fn = translate_fn or (lambda t: translate_text(t, context=description))
    detect_fn = detect_fn or resolve_detect_language_fn()

    df["name_pt"] = None
    df = reuse_existing_translation(
        df, previous_df, "english_name", "name_pt", key_column=key_column
    )

    # Loop sequencial (max_workers=1): genre e configuration têm no máximo ~250 itens.
    # Para volumes pequenos, o overhead do ThreadPoolExecutor supera o ganho de paralelismo.
    # O glue_details usa mais workers porque processa milhares de IDs por execução.
    df, _ = resolve_pt_translation(
        df,
        source_column="english_name",
        target_column="name_pt",
        idioma_en_column="name_idioma_detectado_en",
        idioma_pt_column="name_idioma_detectado_pt",
        tentativas_column="name_tentativas_traducao",
        detect_fn=detect_fn,
        translate_fn=fn,
        max_workers=1,
    )
    return df


def _add_name_pt_countries(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    previous_df: Optional[pd.DataFrame] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> pd.DataFrame:
    """Traduz english_name dos países para português e grava como name_pt."""
    return _add_translation(df, "países", "iso_3166_1", translate_fn, previous_df, detect_fn)


def _add_name_pt_languages(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    previous_df: Optional[pd.DataFrame] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> pd.DataFrame:
    """Traduz english_name dos idiomas para português e grava como name_pt."""
    return _add_translation(df, "idiomas", "iso_639_1", translate_fn, previous_df, detect_fn)


def read_existing_configuration(s3_bucket_sot: str, table_name: str) -> pd.DataFrame:
    """
    Lê a tabela configuration já gravada na SOT, usada como cache de tradução em
    _add_translation (reaproveita name_pt quando english_name não mudou desde
    a última execução).

    Args:
        s3_bucket_sot: Nome do bucket SOT.
        table_name:    Nome da tabela configuration no Glue Catalog.

    Returns:
        DataFrame com os registros existentes, ou vazio se a tabela ainda não
        existir (primeira execução) ou a leitura falhar por qualquer outro motivo.
    """
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"
    try:
        return wr.s3.read_parquet(path=s3_path, dataset=True)
    except Exception as exc:
        logger.info(f"Sem dados existentes para '{table_name}' (provavelmente primeira execução): {exc}")
        return pd.DataFrame()


def _read_json_from_s3(bucket: str, key: str) -> list:
    """Lê um arquivo JSON de um único objeto S3 e retorna como lista Python."""
    s3_client = boto3.client("s3")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read())


def read_from_sor(
    s3_bucket_sor: str,
    media_type: str,
    table_type: str,
    year: Optional[str] = None,
    translate_fn: Optional[Callable[[str], str]] = None,
    s3_bucket_sot: Optional[str] = None,
    table_name: Optional[str] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> pd.DataFrame:
    """
    Lê dados do bucket SOR e retorna como DataFrame Pandas.

    discover: lê pasta inteira com wr.s3.read_json, adiciona coluna year, remove
        duplicatas por id, e adiciona overview_idioma_detectado e
        overview_traduzido_pt_br (diagnóstico — o overview já vem em pt-BR nativo
        do TMDB via lambda_api, sem etapa de tradução; as colunas só sinalizam se
        o TMDB de fato devolveu o texto em português; overview_idioma_detectado é
        usada como gate em glue_agg, overview_traduzido_pt_br é só um booleano
        derivado dela, sem chamada de tradução).
    watch_providers_ref: lê arquivo único, deriva canonical_name.
    genre: lê arquivo único diretamente.
    configuration: lê arquivo único; tv adiciona name_pt (países), movie adiciona name_pt (idiomas).

    Args:
        s3_bucket_sor: Nome do bucket SOR
        media_type:    "movie" ou "tv"
        table_type:    Tipo da tabela (determina como ler)
        year:          Ano para o discover (ex: "2024")
        translate_fn:  Função de tradução usada para name_pt em configuration (ver
                       _add_translation); só relevante para table_type="configuration".
        s3_bucket_sot: Bucket SOT, usado para ler a tabela configuration já gravada
                       (cache de tradução, ver read_existing_configuration); só
                       relevante para table_type="configuration". Se omitido, a
                       tradução roda sem cache (comportamento anterior).
        table_name:    Nome da tabela configuration no Glue Catalog; ver s3_bucket_sot.
        detect_fn:     Função de detecção de idioma usada em name_idioma_detectado_en/
                       name_idioma_detectado_pt (configuration) e overview_idioma_detectado
                       (discover). Por padrão usa resolve_detect_language_fn().

    Returns:
        DataFrame com os dados lidos e prontos para gravação no SOT
    """
    s3_key = SOR_KEYS[media_type][table_type].format(year=year)
    logger.info(f"Lendo {table_type} de s3://{s3_bucket_sor}/{s3_key}")

    if table_type == "discover":
        df = wr.s3.read_json(path=f"s3://{s3_bucket_sor}/{s3_key}", orient="records")
        df["year"] = year
        df = df.drop_duplicates(subset=["id"])
        if "overview" in df.columns:
            df = add_detected_language_column(df, "overview", "overview_idioma_detectado", detect_fn)
            df["overview_traduzido_pt_br"] = df["overview_idioma_detectado"] == "pt"

    elif table_type == "now_playing":
        df = wr.s3.read_json(path=f"s3://{s3_bucket_sor}/{s3_key}", orient="records")
        df = df.drop_duplicates(subset=["id"])

    # discover e now_playing: wr.s3.read_json funciona porque os arquivos são arrays JSON puros.
    # watch_providers_ref, genre e configuration: usamos _read_json_from_s3 (boto3 + json.loads)
    # porque lida melhor com arquivo único — wrangler pode ter comportamento inesperado nesses casos.
    elif table_type == "watch_providers_ref":
        df = pd.DataFrame(_read_json_from_s3(s3_bucket_sor, s3_key))
        df["canonical_name"] = df["provider_name"].apply(derive_canonical_name)

    elif table_type in ("genre", "configuration"):
        df = pd.DataFrame(_read_json_from_s3(s3_bucket_sor, s3_key))

        if table_type == "configuration":
            previous_df = None
            if s3_bucket_sot and table_name:
                previous_df = read_existing_configuration(s3_bucket_sot, table_name)

            if media_type == "tv":
                df = _add_name_pt_countries(df, translate_fn, previous_df, detect_fn)

            elif media_type == "movie":
                df = _add_name_pt_languages(df, translate_fn, previous_df, detect_fn)

    logger.info(f"Lidos {len(df)} registros.")
    return df


def write_parquet_to_sot(
    df: pd.DataFrame,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
    partition_cols: Optional[List[str]] = None,
    mode: str = "overwrite_partitions",
) -> None:
    """
    Grava um DataFrame como Parquet no SOT e atualiza o Glue Catalog via AWS Wrangler.

    Args:
        df:             DataFrame com os dados transformados
        s3_bucket_sot:  Nome do bucket SOT de destino
        table_name:     Nome da tabela no Catalog
        database:       Nome do banco no Catalog
        partition_cols: Lista de colunas de partição (ex: ["year"]) ou None
        mode:           "overwrite_partitions" ou "overwrite"
    """
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"
    logger.info(
        f"Escrevendo {len(df)} registros em {s3_path} | particao={partition_cols} | mode={mode}"
    )
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=partition_cols,
        mode=mode,
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' atualizada com sucesso no SOT.")
