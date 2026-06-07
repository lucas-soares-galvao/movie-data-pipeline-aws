"""
utils.py — Funções auxiliares do job Glue Details.

Responsabilidades:
  - Ler argumentos do job
  - Buscar IDs distintos das tabelas de discover no SOT via Athena
  - Chamar o endpoint de detalhes da API TMDB (/movie/{id} ou /tv/{id})
  - Gravar os detalhes diretamente no SOT como Parquet particionado por year
  - Acionar o job Glue AGG ao final

Por que este job existe separado da Lambda API?
  A Lambda já opera no limite máximo de timeout (900 s). Buscar detalhes
  individuais para cada ID descoberto adicionaria milhares de chamadas extras
  à execução. O Glue PythonShell não tem essa restrição de 15 minutos.
"""

import json
import logging
import sys
from typing import Any, Dict, List, Tuple

import awswrangler as wr
import boto3
import pandas as pd
import requests
from awsglue.utils import getResolvedOptions

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TMDB_BASE_URL = "https://api.themoviedb.org/3"


# ---------------------------------------------------------------------------
# Utilitários gerais
# ---------------------------------------------------------------------------


def get_resolved_option(args: list) -> Dict[str, Any]:
    """
    Converte a lista de argumentos do Glue em um dicionário.

    Args:
        args: Lista de nomes de argumentos a resolver (sem o prefixo "--").

    Returns:
        Dicionário mapeando nome do argumento para seu valor.
    """
    return getResolvedOptions(sys.argv, args)


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos obrigatórios do job Glue Details.

    Argumentos obrigatórios:
      S3_BUCKET_SOT            — bucket onde as tabelas de detalhe serão gravadas
      S3_BUCKET_TEMP           — bucket temporário para os resultados do Athena
      DATABASE                 — nome do banco no Glue Catalog
      TABLE_DISCOVER_MOVIE     — nome da tabela de discover de filmes no Catalog
      TABLE_DISCOVER_TV        — nome da tabela de discover de séries no Catalog
      TABLE_DETAILS_MOVIE      — nome da tabela de detalhes de filmes (destino)
      TABLE_DETAILS_TV         — nome da tabela de detalhes de séries (destino)
      TMDB_SECRET_ARN          — ARN do segredo com a API key do TMDB
      GLUE_AGG_JOB_NAME        — nome do job Glue AGG a ser acionado ao final

    Returns:
        Dicionário com todos os argumentos resolvidos.
    """
    required_args = [
        "S3_BUCKET_SOT",
        "S3_BUCKET_TEMP",
        "DATABASE",
        "TABLE_DISCOVER_MOVIE",
        "TABLE_DISCOVER_TV",
        "TABLE_DETAILS_MOVIE",
        "TABLE_DETAILS_TV",
        "TMDB_SECRET_ARN",
        "GLUE_AGG_JOB_NAME",
    ]
    return get_resolved_option(required_args)


# ---------------------------------------------------------------------------
# Secrets Manager
# ---------------------------------------------------------------------------


def get_tmdb_api_key(secret_arn: str) -> str:
    """
    Busca a chave de API do TMDB armazenada no AWS Secrets Manager.

    O segredo deve estar no formato JSON: {"tmdb_api_key": "sua-chave-aqui"}

    Args:
        secret_arn: ARN do segredo cadastrado no Secrets Manager.

    Returns:
        A chave de API do TMDB como string.
    """
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])
    return secret["tmdb_api_key"]


# ---------------------------------------------------------------------------
# Leitura dos IDs do SOT via Athena
# ---------------------------------------------------------------------------


def fetch_ids_from_sot(
    database: str,
    table_discover_movie: str,
    table_discover_tv: str,
    s3_bucket_temp: str,
) -> Tuple[List[int], List[int]]:
    """
    Busca os IDs distintos das tabelas de discover no SOT via Athena.

    Usar o SOT (e não o SOR) garante que os IDs retornados já passaram
    pela validação do Glue ETL e estão deduplicados entre anos.

    Args:
        database:             Nome do banco de dados no Glue Catalog.
        table_discover_movie: Nome da tabela de discover de filmes.
        table_discover_tv:    Nome da tabela de discover de séries.
        s3_bucket_temp:       Bucket S3 para os resultados temporários do Athena.

    Returns:
        Tupla (movie_ids, tv_ids) com listas de inteiros.
    """
    s3_output = f"s3://{s3_bucket_temp}/athena/glue_details/"

    query_movie = f"SELECT DISTINCT id FROM {database}.{table_discover_movie}"
    query_tv = f"SELECT DISTINCT id FROM {database}.{table_discover_tv}"

    logger.info(f"Buscando IDs de filmes em '{table_discover_movie}'...")
    df_movie = wr.athena.read_sql_query(
        sql=query_movie,
        database=database,
        s3_output=s3_output,
        ctas_approach=False,
    )

    logger.info(f"Buscando IDs de séries em '{table_discover_tv}'...")
    df_tv = wr.athena.read_sql_query(
        sql=query_tv,
        database=database,
        s3_output=s3_output,
        ctas_approach=False,
    )

    movie_ids = df_movie["id"].astype(int).tolist()
    tv_ids = df_tv["id"].astype(int).tolist()
    logger.info(f"IDs encontrados: {len(movie_ids)} filmes, {len(tv_ids)} séries.")
    return movie_ids, tv_ids


# ---------------------------------------------------------------------------
# TMDB API — detalhes individuais
# ---------------------------------------------------------------------------


def fetch_tmdb_details(api_key: str, content_type: str, item_id: int) -> dict:
    """
    Busca os detalhes de um filme ou série pelo ID na API do TMDB.

    Endpoints utilizados:
      - Filme: https://api.themoviedb.org/3/movie/{id}
      - Série:  https://api.themoviedb.org/3/tv/{id}

    Para filmes, o campo relevante é:
      - runtime (int): duração em minutos

    Para séries, os campos relevantes são:
      - number_of_seasons  (int): total de temporadas
      - number_of_episodes (int): total de episódios
      - episode_run_time   (list[int]): lista com duração(ões) típica(s) por episódio

    Args:
        api_key:      Chave de API do TMDB.
        content_type: "movie" ou "tv".
        item_id:      ID do filme ou série no TMDB.

    Returns:
        Dicionário com os campos retornados pela API.
    """
    endpoint = "movie" if content_type == "movie" else "tv"
    url = f"{TMDB_BASE_URL}/{endpoint}/{item_id}"
    params = {"api_key": api_key, "language": "pt-BR"}

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Coleta + gravação no SOT
# ---------------------------------------------------------------------------


def collect_and_write_details(
    api_key: str,
    ids: List[int],
    content_type: str,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
) -> None:
    """
    Chama a API de detalhes para cada ID e grava o resultado no SOT como Parquet.

    Para filmes extrai: id, runtime, year (ano de lançamento).
    Para séries extrai: id, number_of_seasons, number_of_episodes,
                        episode_run_time (array<int>), year (ano de estreia).

    O campo year é extraído da data de lançamento/estreia e usado como
    coluna de partição, mantendo o mesmo padrão das tabelas de discover.
    Quando um ID não retornar os dados esperados, o registro é incluído
    com os campos ausentes como None (sem interromper o processamento).

    Args:
        api_key:       Chave de API do TMDB.
        ids:           Lista de IDs a consultar.
        content_type:  "movie" ou "tv".
        s3_bucket_sot: Nome do bucket SOT de destino.
        table_name:    Nome da tabela no Glue Catalog (e prefixo no S3).
        database:      Nome do banco de dados no Glue Catalog.
    """
    registros = []

    for item_id in ids:
        try:
            detalhe = fetch_tmdb_details(api_key, content_type, item_id)
        except requests.RequestException as exc:
            # Falha em um ID não deve interromper o processamento dos demais
            logger.warning(f"Erro ao buscar detalhes do ID {item_id}: {exc}")
            continue

        if content_type == "movie":
            # release_date formato: "YYYY-MM-DD" — pega só o ano
            release_date = detalhe.get("release_date") or ""
            year = release_date[:4] if release_date else None

            registros.append({
                "id":      detalhe.get("id"),
                "runtime": detalhe.get("runtime"),
                "year":    year,
            })
        else:
            first_air_date = detalhe.get("first_air_date") or ""
            year = first_air_date[:4] if first_air_date else None

            registros.append({
                "id":                  detalhe.get("id"),
                "number_of_seasons":   detalhe.get("number_of_seasons"),
                "number_of_episodes":  detalhe.get("number_of_episodes"),
                "episode_run_time":    detalhe.get("episode_run_time", []),
                "year":                year,
            })

    if not registros:
        logger.warning(f"Nenhum detalhe coletado para '{content_type}'. Nada gravado.")
        return

    df = pd.DataFrame(registros)
    # Remove linhas sem year — não podem ser particionadas
    df = df.dropna(subset=["year"])

    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"
    logger.info(
        f"Gravando {len(df)} registros de detalhes em {s3_path} | "
        f"particao=[year] | mode=overwrite_partitions"
    )
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' gravada com sucesso no SOT.")


# ---------------------------------------------------------------------------
# Acionamento do Glue AGG
# ---------------------------------------------------------------------------


def trigger_agg(agg_job_name: str) -> str:
    """
    Aciona o job Glue AGG para unificar os dados de discover com os detalhes no SPEC.

    Chamado ao final do glue_details, quando os detalhes de filmes e séries
    já estão disponíveis no SOT e o AGG pode fazer os JOINs com segurança.

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
