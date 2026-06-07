"""
utils.py — Funções auxiliares do job Glue ETL.

Responsabilidades:
  - Ler argumentos do job (obrigatórios e opcionais)
  - Ler dados do bucket SOR de acordo com o tipo de tabela (table_type)
  - Escrever DataFrame como Parquet no bucket SOT e registrar no Glue Catalog

Estrutura dos arquivos no SOR (gravados pela Lambda):
  tmdb/discover/{media_type}/ano={year}/pagina_NNN.json  → array de objetos
  tmdb/genre/movie/generos_filmes.json                   → array de objetos
  tmdb/genre/tv/generos_series.json                      → array de objetos
  tmdb/configuration/languages/idiomas.json              → array de objetos
  tmdb/configuration/countries/paises.json               → array de objetos

Tipos de tabela (TABLE_TYPE) enviados pela Lambda ao acionar o job:
  "discover"      → dados paginados por ano (precisa do arg --YEAR)
  "genre"         → tabela de gêneros de filmes ou séries
  "configuration" → tabela de idiomas (movie) ou países (tv)
"""

import json
import logging
import sys
from typing import Any, Dict, List, Optional

import boto3
import awswrangler as wr
import pandas as pd
from awsglue.utils import getResolvedOptions

SOR_KEYS = {
    "movie": {
        "genre": "tmdb/genre/movie/generos_filmes.json",
        "configuration": "tmdb/configuration/languages/idiomas.json",
        "discover": "tmdb/discover/movie/ano={year}/",
    },
    "tv": {
        "genre": "tmdb/genre/tv/generos_series.json",
        "configuration": "tmdb/configuration/countries/paises.json",
        "discover": "tmdb/discover/tv/ano={year}/",
    },
}

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Utilitários gerais
# ---------------------------------------------------------------------------


def get_resolved_option(args: list) -> Dict[str, Any]:
    """
    Converte a lista de argumentos do Glue (ex.: ["--S3_BUCKET_SOR", "my-sor", ...])
    em um dicionário { "S3_BUCKET_SOR": "my-sor", ... }.

    Args:
        args: Lista de nomes de argumentos a resolver (sem o prefixo "--").

    Returns:
        Dicionário mapeando nome do argumento para seu valor.
    """
    return getResolvedOptions(sys.argv, args)


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos obrigatórios e opcionais do job Glue e os retorna em um dicionário.

    Argumentos obrigatórios: S3_BUCKET_SOR, S3_BUCKET_SOT, MEDIA_TYPE, DATABASE,
    TABLE_NAME, TABLE_TYPE, GLUE_DATA_QUALITY_JOB_NAME.
    Argumento opcional: YEAR (presente apenas para runs de discover).

    Returns:
        Dicionário com todos os argumentos resolvidos. "YEAR" estará ausente
        quando o job não for acionado para discover.
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

    try:
        args.update(get_resolved_option(["YEAR"]))
    except SystemExit:
        pass

    return args


# ---------------------------------------------------------------------------
# Leitura unificada dos dados da camada SOR
# ---------------------------------------------------------------------------


def read_from_sor(
    s3_bucket_sor: str,
    media_type: str,
    table_type: str,
    year: Optional[str] = None,
) -> pd.DataFrame:
    """
    Lê dados do bucket SOR de acordo com o tipo de tabela (table_type).

    Despacha para a lógica correta dependendo do valor de table_type:

      "discover"
        Lê JSON paginado do prefixo tmdb/discover/{media_type}/ano={year}/
        usando wr.s3.read_json. Requer o argumento year.
        Adiciona a coluna "year" ao DataFrame (usada como partição no SOT).

      "genre"
        Lê tmdb/genre/{media_type}/generos_filmes.json (movie) ou
        generos_series.json (tv) via boto3. O payload é um array direto de objetos.

      "configuration"
        Lê tmdb/configuration/languages/idiomas.json (movie) ou
        configuration/countries/paises.json (tv) via boto3.
        O payload é um array direto de objetos.

    Args:
        s3_bucket_sor: Nome do bucket SOR.
        media_type:    "movie" ou "tv".
        table_type:    "discover", "genre" ou "configuration".
        year:          Ano da partição. Obrigatório quando table_type="discover".

    Returns:
        DataFrame com os dados lidos do SOR.
    """
    s3_key = SOR_KEYS[media_type][table_type].format(year=year)
    logger.info(f"Lendo {table_type} de s3://{s3_bucket_sor}/{s3_key}")

    if table_type == "discover":
        df = wr.s3.read_json(path=f"s3://{s3_bucket_sor}/{s3_key}", orient="records")
        df["year"] = year
    else:
        s3_client = boto3.client("s3")
        response = s3_client.get_object(Bucket=s3_bucket_sor, Key=s3_key)
        data = json.loads(response["Body"].read())
        df = pd.DataFrame(data)

    logger.info(f"Lidos {len(df)} registros.")
    return df


# ---------------------------------------------------------------------------
# Gravação na camada SOT
# ---------------------------------------------------------------------------


def write_parquet_to_sot(
    df: pd.DataFrame,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
    partition_cols: Optional[List[str]] = None,
    mode: str = "overwrite_partitions",
) -> None:
    """
    Escreve um DataFrame como Parquet no bucket SOT e atualiza o Glue Catalog.

    Usa o AWS Wrangler para gravar e registrar/atualizar as partições automaticamente,
    evitando a necessidade de executar MSCK REPAIR TABLE após cada escrita.

    Args:
        df:             DataFrame a ser gravado.
        s3_bucket_sot:  Nome do bucket SOT.
        table_name:     Nome da tabela de destino (usado como subpasta e no Glue Catalog).
        database:       Nome do banco de dados no Glue Catalog.
        partition_cols: Colunas de partição, ou None para tabelas não particionadas.
        mode:           Modo de escrita do AWS Wrangler. Padrão: "overwrite_partitions"
                        (substitui apenas as partições presentes no DataFrame).
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


# ---------------------------------------------------------------------------
# Acionamento do Glue Data Quality
# ---------------------------------------------------------------------------


def trigger_data_quality(
    dq_job_name: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
) -> str:
    """
    Aciona o job Glue Data Quality para validar uma tabela no SOT.

    Args:
        dq_job_name: Nome do job Glue Data Quality cadastrado na AWS.
        table_name:  Nome da tabela a validar (usado para buscar o ruleset).
        database:    Nome do banco de dados no Glue Catalog.
        year:        Ano da partição. Informado apenas para discover.

    Returns:
        O ID de execução do job (JobRunId).
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


# ---------------------------------------------------------------------------
# Acionamento do Glue AGG
# ---------------------------------------------------------------------------


def trigger_agg(agg_job_name: str) -> str:
    """
    Aciona o job Glue AGG para unificar os dados de discover no bucket SPEC.

    Deve ser chamado apenas no run de media_type="tv", pois esse é o último
    processo a concluir, garantindo que ambas as tabelas (movie e tv) já
    foram gravadas no SOT antes da agregação.

    Args:
        agg_job_name: Nome do job Glue AGG cadastrado na AWS.

    Returns:
        O ID de execução do job (JobRunId).
    """
    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(JobName=agg_job_name)
    run_id = response["JobRunId"]
    logger.info(f"Job AGG '{agg_job_name}' iniciado. RunId: {run_id}")
    return run_id


# ---------------------------------------------------------------------------
# Acionamento do Glue Details
# ---------------------------------------------------------------------------


def trigger_details(details_job_name: str) -> str:
    """
    Aciona o job Glue Details para buscar runtime/temporadas via API TMDB.

    Chamado no run de media_type="tv" + table_type="discover" — o último
    processo de discover a completar, garantindo que os IDs de filmes e séries
    já estão disponíveis no SOT antes da coleta de detalhes.

    O Glue Details é responsável por chamar /movie/{id} e /tv/{id} para cada
    ID descoberto e gravar as tabelas tb_details_movie_tmdb e tb_details_tv_tmdb
    no SOT. Ao final, ele mesmo aciona o Glue AGG.

    Args:
        details_job_name: Nome do job Glue Details cadastrado na AWS.

    Returns:
        O ID de execução do job (JobRunId).
    """
    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(JobName=details_job_name)
    run_id = response["JobRunId"]
    logger.info(f"Job Details '{details_job_name}' iniciado. RunId: {run_id}")
    return run_id