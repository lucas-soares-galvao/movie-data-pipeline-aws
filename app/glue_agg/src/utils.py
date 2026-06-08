"""
utils.py — Funções auxiliares do job Glue AGG.

Responsabilidades:
  - Ler argumentos do job
  - Executar a query de unificação/enriquecimento no Athena via AWS Wrangler
  - Escrever o resultado como Parquet particionado por media_type e year no bucket SPEC

Query executada:
  Unifica os dados de discover (filmes e séries) da camada SOT,
  enriquece com gêneros, idiomas e países, e produz a tabela unificada
  para a camada SPEC.
"""

import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

import awswrangler as wr
import pandas as pd
from awsglue.utils import getResolvedOptions
from deep_translator import GoogleTranslator

logger = logging.getLogger()

_TRANSLATE_MAX_WORKERS = 10

# ---------------------------------------------------------------------------
# Query de unificação e enriquecimento das tabelas de discover.
# O placeholder {database} é substituído em tempo de execução pelo nome real
# do banco de dados no Glue Catalog.
# ---------------------------------------------------------------------------
_DISCOVER_UNIFIED_QUERY = """
WITH

movies AS (
    SELECT
        id,
        'movie'                      AS media_type,
        title,
        original_title,
        overview,
        release_date                 AS air_date,
        original_language,
        CAST(adult AS BOOLEAN)       AS adult,
        genre_ids,
        poster_path,
        backdrop_path,
        popularity,
        vote_average,
        vote_count,
        year,
        CAST(NULL AS ARRAY<VARCHAR>) AS origin_country
    FROM {db_movie}.tb_discover_movie_tmdb
),

tv_shows AS (
    SELECT
        id,
        'tv'                   AS media_type,
        name                   AS title,
        original_name          AS original_title,
        overview,
        first_air_date         AS air_date,
        original_language,
        CAST(NULL AS BOOLEAN)  AS adult,
        genre_ids,
        poster_path,
        backdrop_path,
        popularity,
        vote_average,
        vote_count,
        year,
        origin_country
    FROM {db_tv}.tb_discover_tv_tmdb
),

unified AS (
    SELECT * FROM movies
    UNION ALL
    SELECT * FROM tv_shows
),

genres_combined AS (
    SELECT id, name FROM {db_movie}.tb_genre_movie_tmdb
    UNION
    SELECT id, name FROM {db_tv}.tb_genre_tv_tmdb
),

genre_names AS (
    SELECT
        u.id,
        u.media_type,
        array_join(array_agg(g.name), ', ') AS genre_names
    FROM unified u
    CROSS JOIN UNNEST(u.genre_ids) AS t(genre_id)
    LEFT JOIN genres_combined g
        ON g.id = t.genre_id
    GROUP BY u.id, u.media_type
),

-- Duração dos filmes em minutos, vinda da tabela de detalhes coletada pelo Glue Details.
movie_details AS (
    SELECT id, runtime, title_en, overview_en, poster_path_en, backdrop_path_en
    FROM {db_movie}.tb_details_movie_tmdb
),

-- Quantidade de temporadas, episódios e duração média por episódio das séries.
-- element_at(episode_run_time, 1) pega o primeiro valor do array retornado pelo TMDB
-- (a API geralmente retorna um único elemento com a duração padrão do episódio).
tv_details AS (
    SELECT
        id,
        number_of_seasons,
        number_of_episodes,
        element_at(episode_run_time, 1) AS episode_runtime_minutes,
        title_en,
        overview_en,
        poster_path_en,
        backdrop_path_en
    FROM {db_tv}.tb_details_tv_tmdb
),

-- Referência unificada de provedores (union de movie + tv), desduplicada por provider_id,
-- com canonical_name normalizado e prioridade de exibição no BR.
provider_ref AS (
    SELECT provider_name, canonical_name,
           COALESCE(display_priority_br, 999) AS priority_br
    FROM (
        SELECT provider_name, canonical_name, display_priority_br,
               ROW_NUMBER() OVER (
                   PARTITION BY provider_id
                   ORDER BY COALESCE(display_priority_br, 999) ASC
               ) AS rn
        FROM (
            SELECT * FROM {db_movie}.tb_watch_providers_ref_movie_tmdb
            UNION
            SELECT * FROM {db_tv}.tb_watch_providers_ref_tv_tmdb
        )
    )
    WHERE rn = 1
),

-- Provedores de streaming BR (flatrate) por filme:
-- JOIN com provider_ref para normalizar nomes e obter prioridade,
-- desduplicado por canonical_name, ordenado por prioridade BR crescente.
movie_providers AS (
    SELECT
        id,
        array_join(
            array_agg(canonical_name ORDER BY min_priority ASC),
            ', '
        ) AS streaming_providers
    FROM (
        SELECT wp.id, r.canonical_name, MIN(r.priority_br) AS min_priority
        FROM {db_movie}.tb_watch_providers_movie_tmdb wp
        JOIN provider_ref r ON r.provider_name = wp.provider_name
        WHERE wp.provider_type = 'flatrate'
        GROUP BY wp.id, r.canonical_name
    )
    GROUP BY id
),

-- Provedores de streaming BR (flatrate) por série: mesma lógica.
tv_providers AS (
    SELECT
        id,
        array_join(
            array_agg(canonical_name ORDER BY min_priority ASC),
            ', '
        ) AS streaming_providers
    FROM (
        SELECT wp.id, r.canonical_name, MIN(r.priority_br) AS min_priority
        FROM {db_tv}.tb_watch_providers_tv_tmdb wp
        JOIN provider_ref r ON r.provider_name = wp.provider_name
        WHERE wp.provider_type = 'flatrate'
        GROUP BY wp.id, r.canonical_name
    )
    GROUP BY id
)

SELECT
    u.id,
    u.media_type,
    COALESCE(NULLIF(TRIM(u.title), ''), md.title_en, tv.title_en)       AS title,
    u.original_title,
    COALESCE(NULLIF(TRIM(u.overview), ''), md.overview_en, tv.overview_en) AS overview,
    u.air_date,
    u.original_language,
    lang.english_name                                                    AS language_name,
    u.genre_ids,
    gn.genre_names,
    CASE
        WHEN COALESCE(NULLIF(TRIM(u.poster_path), ''),
                      md.poster_path_en, tv.poster_path_en) IS NULL THEN NULL
        ELSE CONCAT('https://image.tmdb.org/t/p/w342',
                    COALESCE(NULLIF(TRIM(u.poster_path), ''),
                             md.poster_path_en, tv.poster_path_en))
    END                                                                  AS poster_url,
    CASE
        WHEN COALESCE(NULLIF(TRIM(u.backdrop_path), ''),
                      md.backdrop_path_en, tv.backdrop_path_en) IS NULL THEN NULL
        ELSE CONCAT('https://image.tmdb.org/t/p/w780',
                    COALESCE(NULLIF(TRIM(u.backdrop_path), ''),
                             md.backdrop_path_en, tv.backdrop_path_en))
    END                                                                  AS backdrop_url,
    u.popularity,
    u.vote_average,
    u.vote_count,
    u.origin_country,
    ctry.native_name                         AS origin_country_name,
    u.adult,
    u.year,
    -- Duração do filme em minutos (NULL para séries)
    md.runtime                               AS runtime_minutes,
    -- Dados de séries (NULL para filmes)
    tv.number_of_seasons,
    tv.number_of_episodes,
    tv.episode_runtime_minutes,
    -- Provedores de streaming BR onde o título está disponível (flatrate)
    COALESCE(mp.streaming_providers, tp.streaming_providers) AS streaming_providers
FROM unified u
LEFT JOIN genre_names gn
    ON  gn.id         = u.id
    AND gn.media_type = u.media_type
LEFT JOIN {db_unified}.tb_configuration_languages_tmdb lang
    ON lang.iso_639_1 = u.original_language
LEFT JOIN {db_unified}.tb_configuration_countries_tmdb ctry
    ON ctry.iso_3166_1 = element_at(u.origin_country, 1)
LEFT JOIN movie_details md
    ON  md.id = u.id AND u.media_type = 'movie'
LEFT JOIN tv_details tv
    ON  tv.id = u.id AND u.media_type = 'tv'
LEFT JOIN movie_providers mp
    ON  mp.id = u.id AND u.media_type = 'movie'
LEFT JOIN tv_providers tp
    ON  tp.id = u.id AND u.media_type = 'tv'
"""


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
    Lê os argumentos obrigatórios do job Glue AGG.

    Argumentos obrigatórios: S3_BUCKET_SPEC, S3_BUCKET_TEMP, DB_MOVIE, DB_TV,
    DB_UNIFIED, TABLE_NAME.

    Returns:
        Dicionário com todos os argumentos resolvidos.
    """
    required_args = [
        "S3_BUCKET_SPEC",
        "S3_BUCKET_TEMP",
        "DB_MOVIE",
        "DB_TV",
        "DB_UNIFIED",
        "TABLE_NAME",
    ]
    return get_resolved_option(required_args)


# ---------------------------------------------------------------------------
# Execução da query Athena
# ---------------------------------------------------------------------------


def run_athena_query(
    db_movie: str,
    db_tv: str,
    db_unified: str,
    s3_bucket_temp: str,
) -> pd.DataFrame:
    """
    Executa a query de unificação no Athena e retorna o resultado como DataFrame.

    Usa wr.athena.read_sql_query com ctas_approach=True para suportar colunas
    do tipo ARRAY (genre_ids, origin_country) presentes no resultado da query.

    Args:
        db_movie:       Banco de dados de filmes no Glue Catalog.
        db_tv:          Banco de dados de séries no Glue Catalog.
        db_unified:     Banco de dados unificado (configurações e tabela final).
        s3_bucket_temp: Nome do bucket S3 para os resultados temporários do Athena.

    Returns:
        DataFrame com o resultado da query.
    """
    query = _DISCOVER_UNIFIED_QUERY.format(
        db_movie=db_movie,
        db_tv=db_tv,
        db_unified=db_unified,
    )
    s3_output = f"s3://{s3_bucket_temp}/athena/glue_agg/"

    logger.info(
        f"Executando query Athena | db_movie='{db_movie}' | db_tv='{db_tv}' | db_unified='{db_unified}'"
    )
    df = wr.athena.read_sql_query(
        sql=query,
        database=db_unified,
        s3_output=s3_output,
        ctas_approach=True,
    )
    logger.info(f"Query executada com sucesso. {len(df)} registros retornados.")
    return df


# ---------------------------------------------------------------------------
# Tradução de campos em inglês para português
# ---------------------------------------------------------------------------


def traduzir_colunas_en(df: pd.DataFrame) -> pd.DataFrame:
    """Traduz overview e title para pt quando original_language == 'en'."""
    mask = df["original_language"] == "en"
    if not mask.any():
        return df

    total = mask.sum()
    logger.info(f"Traduzindo {total} registros com original_language='en' ({_TRANSLATE_MAX_WORKERS} workers).")

    def _translate(texto: str) -> str:
        if not texto:
            return ""
        try:
            return GoogleTranslator(source="en", target="pt").translate(texto)
        except Exception as exc:
            logger.warning(f"Falha ao traduzir: {exc}. Mantendo original.")
            return texto

    for col in ("title", "overview"):
        valores = df.loc[mask, col].fillna("").tolist()
        with ThreadPoolExecutor(max_workers=_TRANSLATE_MAX_WORKERS) as executor:
            traduzidos = list(executor.map(_translate, valores))
        df.loc[mask, col] = traduzidos

    return df


# ---------------------------------------------------------------------------
# Gravação na camada SPEC
# ---------------------------------------------------------------------------


def write_parquet_to_spec(
    df: pd.DataFrame,
    s3_bucket_spec: str,
    table_name: str,
    database: str,
) -> None:
    """
    Escreve o DataFrame como Parquet no bucket SPEC, particionado por media_type e year.

    Usa overwrite_partitions para substituir apenas as combinações (media_type, year)
    presentes no DataFrame, sem afetar outras partições existentes.
    O AWS Wrangler registra/atualiza a tabela no Glue Catalog automaticamente.

    Args:
        df:             DataFrame a ser gravado.
        s3_bucket_spec: Nome do bucket SPEC de destino.
        table_name:     Nome da tabela de destino no Catalog e como prefixo no S3.
        database:       Nome do banco de dados no Glue Catalog.
    """
    s3_path = f"s3://{s3_bucket_spec}/{table_name}/"
    logger.info(
        f"Escrevendo {len(df)} registros em {s3_path} | "
        f"particoes=[media_type, year] | mode=overwrite_partitions"
    )
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=["media_type", "year"],
        mode="overwrite_partitions",
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' gravada com sucesso no SPEC.")