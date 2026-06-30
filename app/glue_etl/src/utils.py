"""utils.py — Funções auxiliares do Glue ETL."""

import json
import logging
import sys
from typing import Any, Dict, List, Optional

import awswrangler as wr
import boto3
import pandas as pd
from awsglue.utils import getResolvedOptions
from deep_translator import GoogleTranslator

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
    lower = result.lower()

    # Remove o primeiro sufixo que corresponder (por ordem de especificidade)
    for suffix in _CANONICAL_SUFFIXES:
        if lower.endswith(suffix.lower()):
            result = result[: -len(suffix)]  # Remove os últimos N caracteres
            break

    # Aplica override manual se o resultado estiver na lista
    return _CANONICAL_OVERRIDES.get(result, result)


logger = logging.getLogger()


def get_resolved_option(args: list) -> Dict[str, Any]:
    """Wrapper de getResolvedOptions — converte lista de nomes em dicionário nome→valor."""
    return getResolvedOptions(sys.argv, args)


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

    return args


def _adicionar_traducao(df: pd.DataFrame, descricao: str) -> pd.DataFrame:
    """
    Traduz a coluna english_name de inglês para português e grava como name_pt.

    Args:
        df:         DataFrame com coluna english_name.
        descricao:  Descrição dos itens para o log (ex: "países", "idiomas").

    Returns:
        DataFrame com coluna name_pt adicionada.
    """
    if "english_name" not in df.columns:
        return df

    mask = df["english_name"].notna() & (df["english_name"] != "")
    if not mask.any():
        df["name_pt"] = None
        return df

    logger.info(f"Traduzindo {mask.sum()} nomes de {descricao} para pt-BR...")

    def _translate(texto: str) -> str:
        if not texto:
            return ""
        try:
            return GoogleTranslator(source="en", target="pt").translate(texto)
        except Exception as exc:
            # Intencionalmente amplo: preferimos manter o original a falhar o job.
            logger.warning(f"Falha ao traduzir {descricao} '{texto}': {exc}. Mantendo original.")
            return texto

    # Loop sequencial (não paralelo): genre e configuration têm no máximo ~250 itens.
    # Para volumes pequenos, o overhead do ThreadPoolExecutor supera o ganho de paralelismo.
    # O glue_details usa ThreadPoolExecutor porque processa milhares de IDs por execução.
    df["name_pt"] = None
    valores = df.loc[mask, "english_name"].tolist()
    traduzidos = [_translate(v) for v in valores]
    df.loc[mask, "name_pt"] = traduzidos

    return df


def _adicionar_name_pt_countries(df: pd.DataFrame) -> pd.DataFrame:
    """Traduz english_name dos países para português e grava como name_pt."""
    return _adicionar_traducao(df, "países")


def _adicionar_name_pt_languages(df: pd.DataFrame) -> pd.DataFrame:
    """Traduz english_name dos idiomas para português e grava como name_pt."""
    return _adicionar_traducao(df, "idiomas")


def _ler_json_do_s3(bucket: str, key: str) -> list:
    """Lê um arquivo JSON de um único objeto S3 e retorna como lista Python."""
    s3_client = boto3.client("s3")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read())


def read_from_sor(
    s3_bucket_sor: str,
    media_type: str,
    table_type: str,
    year: Optional[str] = None,
) -> pd.DataFrame:
    """
    Lê dados do bucket SOR e retorna como DataFrame Pandas.

    discover: lê pasta inteira com wr.s3.read_json, adiciona coluna year, remove duplicatas por id.
    watch_providers_ref: lê arquivo único, deriva canonical_name.
    genre: lê arquivo único diretamente.
    configuration: lê arquivo único; tv adiciona name_pt (países), movie adiciona name_pt (idiomas).

    Args:
        s3_bucket_sor: Nome do bucket SOR
        media_type:    "movie" ou "tv"
        table_type:    Tipo da tabela (determina como ler)
        year:          Ano para o discover (ex: "2024")

    Returns:
        DataFrame com os dados lidos e prontos para gravação no SOT
    """
    s3_key = SOR_KEYS[media_type][table_type].format(year=year)
    logger.info(f"Lendo {table_type} de s3://{s3_bucket_sor}/{s3_key}")

    if table_type == "discover":
        df = wr.s3.read_json(path=f"s3://{s3_bucket_sor}/{s3_key}", orient="records")
        df["year"] = year
        df = df.drop_duplicates(subset=["id"])

    elif table_type == "now_playing":
        df = wr.s3.read_json(path=f"s3://{s3_bucket_sor}/{s3_key}", orient="records")
        df = df.drop_duplicates(subset=["id"])

    # discover e now_playing: wr.s3.read_json funciona porque os arquivos são arrays JSON puros.
    # watch_providers_ref, genre e configuration: usamos _ler_json_do_s3 (boto3 + json.loads)
    # porque lida melhor com arquivo único — wrangler pode ter comportamento inesperado nesses casos.
    elif table_type == "watch_providers_ref":
        df = pd.DataFrame(_ler_json_do_s3(s3_bucket_sor, s3_key))
        df["canonical_name"] = df["provider_name"].apply(derive_canonical_name)

    else:
        df = pd.DataFrame(_ler_json_do_s3(s3_bucket_sor, s3_key))

        if table_type == "configuration" and media_type == "tv":
            df = _adicionar_name_pt_countries(df)

        if table_type == "configuration" and media_type == "movie":
            df = _adicionar_name_pt_languages(df)

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
