"""
utils.py — Funções Auxiliares do Job Glue ETL

==============================================================================
RESPONSABILIDADES
==============================================================================
- Ler argumentos do job (obrigatórios e opcionais)
- Ler dados do bucket SOR de acordo com o tipo de tabela (TABLE_TYPE)
- Normalizar nomes de plataformas de streaming (watch providers)
- Escrever DataFrame como Parquet no SOT e registrar no Glue Catalog
- Disparar jobs downstream (Data Quality, Details)

TECNOLOGIAS USADAS:
- AWS Wrangler (awswrangler): biblioteca Python para facilitar operações
  de dados na AWS (S3, Glue Catalog, Athena, Redshift).
  É a "ponte" entre Pandas e o ecossistema AWS.
- Pandas: biblioteca Python para manipulação de dados em DataFrames
  (tabelas em memória, similares a planilhas Excel).
- boto3: SDK oficial Python para AWS (S3, Glue, etc.)
"""

import json
import logging
import sys
from typing import Any, Dict, List, Optional

import boto3
import awswrangler as wr
import pandas as pd
from awsglue.utils import getResolvedOptions

# ==============================================================================
# MAPEAMENTO: Caminhos dos Arquivos no SOR por media_type e table_type
# ==============================================================================
# Em vez de if/elif para cada combinação, usamos um dicionário aninhado.
# Exemplo: SOR_KEYS["movie"]["discover"].format(year="2024")
# → "tmdb/discover/movie/ano=2024/"
SOR_KEYS = {
    "movie": {
        "genre":                "tmdb/genre/movie/generos_filmes.json",
        "configuration":        "tmdb/configuration/languages/idiomas.json",
        "discover":             "tmdb/discover/movie/ano={year}/",
        "watch_providers_ref":  "tmdb/watch_providers_ref/movie/watch_providers_ref.json",
    },
    "tv": {
        "genre":                "tmdb/genre/tv/generos_series.json",
        "configuration":        "tmdb/configuration/countries/paises.json",
        "discover":             "tmdb/discover/tv/ano={year}/",
        "watch_providers_ref":  "tmdb/watch_providers_ref/tv/watch_providers_ref.json",
    },
}

# ==============================================================================
# NORMALIZAÇÃO DE NOMES DE PLATAFORMAS (Canonical Names)
# ==============================================================================
# A API TMDB retorna variações do mesmo serviço com nomes diferentes.
# Ex: "Netflix", "Netflix basic with Ads", "Netflix Standard with Ads"
# → Todos devem ser normalizados para "Netflix"
#
# ESTRATÉGIA:
# 1. Remove sufixos conhecidos de variantes (ex: " with Ads", " Premium")
# 2. Aplica overrides manuais para casos especiais (ex: "Paramount Plus" → "Paramount+")

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
    Normaliza o nome de uma plataforma de streaming removendo sufixos de variante.

    EXEMPLO:
    "Netflix Standard with Ads" → "Netflix"
    "Paramount Plus Premium"    → "Paramount+"
    "HBO Max"                   → "HBO Max" (sem mudança)

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


# ==============================================================================
# LEITURA DE ARGUMENTOS DO JOB GLUE
# ==============================================================================


def get_resolved_option(args: list) -> Dict[str, Any]:
    """
    Converte a lista de argumentos do Glue em um dicionário Python.

    O Glue passa argumentos via sys.argv no formato:
    ["--S3_BUCKET_SOR", "meu-bucket", "--MEDIA_TYPE", "movie", ...]

    getResolvedOptions() processa esses argumentos e retorna:
    {"S3_BUCKET_SOR": "meu-bucket", "MEDIA_TYPE": "movie", ...}

    Args:
        args: Lista de NOMES de argumentos a resolver (sem o prefixo "--")

    Returns:
        Dicionário com nome → valor de cada argumento
    """
    return getResolvedOptions(sys.argv, args)


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê todos os argumentos do job Glue ETL e retorna em um dicionário.

    ARGUMENTOS OBRIGATÓRIOS (sempre presentes):
    - S3_BUCKET_SOR: Bucket de onde ler os dados brutos
    - S3_BUCKET_SOT: Bucket de onde gravar os dados processados
    - MEDIA_TYPE: "movie" ou "tv"
    - DATABASE: Nome do banco no Glue Catalog
    - TABLE_NAME: Nome da tabela de destino
    - TABLE_TYPE: "genre", "discover", "configuration" ou "watch_providers_ref"
    - GLUE_DATA_QUALITY_JOB_NAME: Job de validação a disparar após
    - GLUE_AGG_JOB_NAME: Job de agregação (referenciado pelo Details)
    - GLUE_DETAILS_JOB_NAME: Job de enriquecimento

    ARGUMENTOS OPCIONAIS:
    - YEAR: Ano da partição (presente apenas quando TABLE_TYPE="discover")
    - END_YEAR: Último ano do ciclo (para o Details saber quando disparar o AGG)

    O try/except captura o SystemExit que getResolvedOptions lança quando
    um argumento não está presente — forma padrão de tratar args opcionais no Glue.

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
        "GLUE_AGG_JOB_NAME",
        "GLUE_DETAILS_JOB_NAME",
    ]
    args = get_resolved_option(required_args)

    # Tenta ler YEAR e END_YEAR — só presentes nos runs de discover
    try:
        args.update(get_resolved_option(["YEAR", "END_YEAR"]))
    except SystemExit:
        pass  # Argumentos opcionais ausentes — comportamento esperado para genre/config

    return args


# ==============================================================================
# LEITURA DO SOR — Dispatch por TABLE_TYPE
# ==============================================================================


def read_from_sor(
    s3_bucket_sor: str,
    media_type: str,
    table_type: str,
    year: Optional[str] = None,
) -> pd.DataFrame:
    """
    Lê dados do bucket SOR e retorna como DataFrame Pandas.

    O comportamento de leitura é diferente para cada TABLE_TYPE:

    "DISCOVER":
    - Lê múltiplos arquivos JSON paginados usando wr.s3.read_json()
    - O path termina com "/" → o Wrangler lê TODOS os arquivos da pasta
    - Adiciona coluna "year" ao DataFrame (usada como partição no SOT)
    - Remove duplicatas por "id" (pode haver títulos repetidos entre páginas)

    "WATCH_PROVIDERS_REF":
    - Lê um único arquivo JSON via boto3 (arquivo não paginado)
    - Deriva "canonical_name" para normalizar nomes das plataformas
    - Ex: "Netflix Standard with Ads" → "Netflix"

    "GENRE" e "CONFIGURATION":
    - Lê um único arquivo JSON via boto3
    - Converte diretamente para DataFrame

    POR QUE USAR boto3 PARA ARQUIVOS ÚNICOS EM VEZ DE wr.s3.read_json()?
    Para arquivos únicos pequenos, boto3 é mais direto e sem overhead.
    O Wrangler é mais vantajoso para leitura de múltiplos arquivos em paralelo.

    Args:
        s3_bucket_sor: Nome do bucket SOR
        media_type:    "movie" ou "tv"
        table_type:    Tipo da tabela (determina como ler)
        year:          Ano para o discover (ex: "2024")

    Returns:
        DataFrame com os dados lidos e prontos para gravação no SOT
    """
    # Monta o caminho S3 usando o dicionário SOR_KEYS
    # .format(year=year) substitui "{year}" no path de discover
    s3_key = SOR_KEYS[media_type][table_type].format(year=year)
    logger.info(f"Lendo {table_type} de s3://{s3_bucket_sor}/{s3_key}")

    if table_type == "discover":
        # Lê todos os arquivos JSON da pasta (múltiplas páginas)
        # orient="records" indica que cada arquivo é uma lista de objetos JSON
        df = wr.s3.read_json(path=f"s3://{s3_bucket_sor}/{s3_key}", orient="records")
        # Adiciona a coluna de partição — o SOT organiza por pasta "year=2024"
        df["year"] = year
        # Remove títulos duplicados entre páginas (mesmo ID em páginas diferentes)
        df = df.drop_duplicates(subset=["id"])

    elif table_type == "watch_providers_ref":
        # Arquivo único — usa boto3 para leitura direta
        s3_client = boto3.client("s3")
        response = s3_client.get_object(Bucket=s3_bucket_sor, Key=s3_key)
        data = json.loads(response["Body"].read())
        df = pd.DataFrame(data)
        # Normaliza nomes de plataformas para uso como chave de join
        df["canonical_name"] = df["provider_name"].apply(derive_canonical_name)

    else:
        # genre e configuration: arquivo único, sem transformação especial
        s3_client = boto3.client("s3")
        response = s3_client.get_object(Bucket=s3_bucket_sor, Key=s3_key)
        data = json.loads(response["Body"].read())
        df = pd.DataFrame(data)

    logger.info(f"Lidos {len(df)} registros.")
    return df


# ==============================================================================
# ESCRITA NO SOT — Parquet + Registro no Glue Catalog
# ==============================================================================


def write_parquet_to_sot(
    df: pd.DataFrame,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
    partition_cols: Optional[List[str]] = None,
    mode: str = "overwrite_partitions",
) -> None:
    """
    Grava um DataFrame como Parquet no SOT e atualiza o Glue Catalog.

    O QUE É AWS WRANGLER (wr.s3.to_parquet)?
    Uma biblioteca que combina gravação em S3 com atualização automática
    do Glue Catalog. Em vez de precisar:
    1. Gravar o arquivo Parquet no S3
    2. Criar/atualizar a tabela no Glue Catalog manualmente
    3. Executar "MSCK REPAIR TABLE" para registrar novas partições

    O Wrangler faz TUDO isso em uma única chamada.

    PARÂMETROS CHAVE DO wr.s3.to_parquet:
    - dataset=True:    Trata o path como uma tabela (não arquivo único)
    - partition_cols:  Colunas que viram subpastas (year=2024/, year=2023/)
    - mode:            Como lidar com dados existentes:
                       "overwrite_partitions" → substitui só as partições do df
                       "overwrite" → substitui tudo
    - database+table:  Registra/atualiza a tabela no Glue Catalog

    Args:
        df:             DataFrame com os dados transformados
        s3_bucket_sot:  Nome do bucket SOT de destino
        table_name:     Nome da tabela no Catalog (ex: "tb_discover_movie_tmdb")
        database:       Nome do banco no Catalog (ex: "db_movie_tmdb")
        partition_cols: Lista de colunas de partição (ex: ["year"]) ou None
        mode:           Modo de escrita ("overwrite_partitions" ou "overwrite")
    """
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"
    logger.info(
        f"Escrevendo {len(df)} registros em {s3_path} | particao={partition_cols} | mode={mode}"
    )
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,              # Trata como tabela gerenciada (não arquivo avulso)
        partition_cols=partition_cols,
        mode=mode,
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' atualizada com sucesso no SOT.")


# ==============================================================================
# DISPARO DE JOBS DOWNSTREAM
# ==============================================================================


def trigger_data_quality(
    dq_job_name: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
) -> str:
    """
    Dispara o job Glue Data Quality para validar a tabela recém-gravada.

    Chamado após TODA gravação no SOT — garante que os dados passaram pelas
    regras de qualidade antes de serem usados em produção.

    O DQ roda em paralelo (não bloqueante): este job não espera o DQ terminar.
    Se o DQ encontrar violações, ele notifica via SNS (email para a equipe).

    Args:
        dq_job_name: Nome do job DQ registrado na AWS
        table_name:  Nome da tabela a validar (para carregar o ruleset correto)
        database:    Banco no Glue Catalog onde a tabela está registrada
        year:        Ano da partição (para DQ validar apenas o ano recém-gravado)

    Returns:
        JobRunId da execução iniciada
    """
    arguments = {
        "--TABLE_NAME": table_name,
        "--DATABASE": database,
    }
    if year is not None:
        arguments["--YEAR"] = year

    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(
        JobName=dq_job_name,
        Arguments=arguments,
    )
    run_id = response["JobRunId"]
    logger.info(
        f"Job Data Quality '{dq_job_name}' iniciado para tabela '{table_name}'. RunId: {run_id}"
    )
    return run_id


def trigger_agg(agg_job_name: str) -> str:
    """
    Dispara o job Glue AGG para unificar dados de filmes e séries no SPEC.

    POR QUE SÓ O GLUE DETAILS CHAMA ESTA FUNÇÃO?
    O AGG só faz sentido quando AMBAS as tabelas (movie e tv) já foram processadas
    e estão no SOT. O Glue ETL processa movie e tv em paralelo, então não dá para
    saber aqui qual terminou por último. O Glue Details coordena isso: ele só
    dispara o AGG quando recebe media_type="tv" + year==end_year (o último run).

    Args:
        agg_job_name: Nome do job AGG na AWS

    Returns:
        JobRunId da execução
    """
    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(JobName=agg_job_name)
    run_id = response["JobRunId"]
    logger.info(f"Job AGG '{agg_job_name}' iniciado. RunId: {run_id}")
    return run_id


def trigger_details(
    details_job_name: str,
    media_type: str,
    year: str,
    end_year: str,
    database: str,
) -> str:
    """
    Dispara o job Glue Details para buscar detalhes adicionais da API TMDB.

    POR QUE EXISTE UM JOB SEPARADO (DETAILS) EM VEZ DE FAZER NO ETL?
    O ETL tem timeout de 30 minutos. Buscar detalhes individuais de milhares
    de títulos na API TMDB pode levar horas — o ETL não aguenta.
    O Details tem timeout de 2 horas e pode rodar até 4 execuções simultâneas.

    O Details busca para cada ID do discover:
    - Filmes: runtime (duração em minutos)
    - Séries: number_of_seasons, number_of_episodes

    LÓGICA DE DISPARO DO AGG (no Details):
    O AGG só é disparado quando media_type="tv" E year==end_year.
    Isso garante que filmes e séries de todos os anos já estão processados.

    Args:
        details_job_name: Nome do job Details na AWS
        media_type:       "movie" ou "tv" (para filtrar quais IDs buscar)
        year:             Ano específico do ciclo atual
        end_year:         Último ano do ciclo (o Details compara year==end_year)
        database:         Banco do Catalog correspondente ao media_type

    Returns:
        JobRunId da execução
    """
    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(
        JobName=details_job_name,
        Arguments={
            "--MEDIA_TYPE": media_type,
            "--YEAR":       year,
            "--END_YEAR":   end_year,
            "--DATABASE":   database,
        },
    )
    run_id = response["JobRunId"]
    logger.info(f"Job Details '{details_job_name}' iniciado. RunId: {run_id}")
    return run_id
