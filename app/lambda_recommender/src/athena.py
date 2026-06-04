"""
athena.py — Busca filmes no catálogo TMDB via Athena.

Executa uma query SQL dinâmica contra tb_discover_unified_tmdb,
aplicando filtros opcionais de gênero, idioma, período e nota mínima.
"""

import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ATHENA_DATABASE = os.environ["ATHENA_DATABASE"]
S3_BUCKET_TEMP = os.environ["S3_BUCKET_TEMP"]
ATHENA_OUTPUT = f"s3://{S3_BUCKET_TEMP}/athena/lambda_recommender/"
POLL_INTERVAL = 1   # segundos entre cada verificação de status
POLL_TIMEOUT = 30   # segundos máximos de espera


def search_catalog(
    genres: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    language: str | None = None,
    min_rating: float | None = None,
    limit: int = 40,
) -> list[dict]:
    """
    Busca filmes e séries em tb_discover_unified_tmdb com filtros opcionais.

    Args:
        genres:     Lista de gêneros em inglês (ex.: ["Action", "Drama"]).
        year_min:   Ano mínimo de lançamento.
        year_max:   Ano máximo de lançamento.
        language:   Código ISO do idioma original (ex.: "en", "pt", "ja").
        min_rating: Nota mínima TMDB (0–10).
        limit:      Máximo de filmes retornados.

    Returns:
        Lista de dicts com os campos: id, media_type, title, original_title,
        overview, year, genre_names, vote_average, language_name, origin_country_name.
    """
    where_clauses = ["vote_count >= 30"]

    if genres:
        genre_filters = " OR ".join(
            f"LOWER(genre_names) LIKE '%{g.lower()}%'" for g in genres
        )
        where_clauses.append(f"({genre_filters})")

    if year_min:
        where_clauses.append(f"year >= {year_min}")

    if year_max:
        where_clauses.append(f"year <= {year_max}")

    if language:
        where_clauses.append(f"original_language = '{language}'")

    if min_rating:
        where_clauses.append(f"vote_average >= {min_rating}")

    where_sql = " AND ".join(where_clauses)

    query = f"""
        SELECT
            id,
            media_type,
            title,
            original_title,
            overview,
            year,
            genre_names,
            vote_average,
            language_name,
            origin_country_name
        FROM {ATHENA_DATABASE}.tb_discover_unified_tmdb
        WHERE {where_sql}
        ORDER BY popularity DESC, vote_average DESC
        LIMIT {limit}
    """

    client = boto3.client("athena")

    start = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
    )
    execution_id = start["QueryExecutionId"]
    logger.info(f"Athena query iniciada: {execution_id}")

    _wait_for_query(client, execution_id)

    return _parse_results(client, execution_id)


def _wait_for_query(client, execution_id: str) -> None:
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        response = client.get_query_execution(QueryExecutionId=execution_id)
        state = response["QueryExecution"]["Status"]["State"]

        if state == "SUCCEEDED":
            logger.info(f"Athena query concluída: {execution_id}")
            return

        if state in ("FAILED", "CANCELLED"):
            reason = response["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query falhou ({state}): {reason}")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError(f"Athena query excedeu {POLL_TIMEOUT}s: {execution_id}")


def _parse_results(client, execution_id: str) -> list[dict]:
    response = client.get_query_results(QueryExecutionId=execution_id)
    rows = response["ResultSet"]["Rows"]

    if len(rows) <= 1:
        return []

    headers = [col["VarCharValue"] for col in rows[0]["Data"]]
    movies = []
    for row in rows[1:]:
        values = [cell.get("VarCharValue", "") for cell in row["Data"]]
        movies.append(dict(zip(headers, values)))

    logger.info(f"{len(movies)} filmes encontrados no catálogo.")
    return movies
