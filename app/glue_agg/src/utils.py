"""utils.py — Funções auxiliares do job Glue AGG."""

import logging
import sys
from typing import Any, Dict, Optional

import awswrangler as wr
import boto3
import pandas as pd
from awsglue.utils import getResolvedOptions

logger = logging.getLogger()

# Os placeholders {db_movie}, {db_tv}, {db_unified} são substituídos em
# tempo de execução com os nomes reais dos bancos de dados no Glue Catalog.
_DISCOVER_UNIFIED_QUERY = """
WITH
-- ============================================================================
-- CTEs (blocos nomeados que serão reutilizados na query final)
-- Leia de cima para baixo como uma sequência de etapas:
-- 1. movies_ranked / movies: filmes deduplicados (mais recente + mais popular)
-- 2. tv_shows_ranked / tv_shows: séries deduplicadas
-- 3. unified: filmes + séries empilhados (UNION ALL)
-- 4. genres_combined: todos os gêneros (movie + tv) sem duplicata
-- 5. genre_names: nome dos gêneros de cada título (ex: "Ação, Aventura")
-- 6. movie_details / tv_details: duração e temporadas vindas do Glue Details
-- 7. providers_ref_*: referência de plataformas de streaming normalizada
-- 8. movie_providers / tv_providers: plataformas disponíveis no BR por título
-- SELECT final: junta tudo e constrói as colunas finais (URLs completas, etc.)
-- ============================================================================

movies_ranked AS (
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
        CAST(NULL AS ARRAY<VARCHAR>) AS origin_country,
        -- ROW_NUMBER() PARTITION BY id: para cada ID único, numera as ocorrências.
        -- Ordenando por year DESC e popularity DESC: a ocorrência mais recente e
        -- popular recebe rn=1. WHERE rn=1 na CTE "movies" abaixo mantém apenas ela.
        -- Por que deduplicar? O mesmo filme pode aparecer em múltiplas partições de ano
        -- (ex: lançado em 2022 mas recoletado em 2023 por ainda ser popular).
        ROW_NUMBER() OVER (PARTITION BY id ORDER BY year DESC, popularity DESC) AS rn
    FROM {db_movie}.tb_discover_movie_tmdb
),

movies AS (
    SELECT * FROM movies_ranked WHERE rn = 1
),

tv_shows_ranked AS (
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
        origin_country,
        ROW_NUMBER() OVER (PARTITION BY id ORDER BY year DESC, popularity DESC) AS rn
    FROM {db_tv}.tb_discover_tv_tmdb
),

tv_shows AS (
    SELECT * FROM tv_shows_ranked WHERE rn = 1
),

unified AS (
    -- UNION ALL empilha filmes e séries numa única tabela.
    -- UNION ALL mantém duplicatas entre as duas fontes (isso é ok aqui porque
    -- filmes e séries têm IDs separados — um ID 123 de filme não é o mesmo que
    -- ID 123 de série na TMDB).
    SELECT * FROM movies
    UNION ALL
    SELECT * FROM tv_shows
),

genres_combined AS (
    -- Une os gêneros de filmes e séries numa lista única sem duplicatas (UNION sem ALL).
    -- Por que unir? Gêneros como "Ação" (id=28) existem em ambas as listas e
    -- o JOIN mais abaixo precisa encontrar o nome pelo ID independente do tipo.
    SELECT id, name FROM {db_movie}.tb_genre_movie_tmdb
    UNION  -- UNION (sem ALL) remove linhas idênticas automaticamente
    SELECT id, name FROM {db_tv}.tb_genre_tv_tmdb
),

genre_names AS (
    -- Para cada título, transforma a lista de IDs de gênero em nomes separados por vírgula.
    -- Ex: genre_ids=[28, 12] → genre_names="Ação, Aventura"
    -- CROSS JOIN UNNEST(genre_ids): "expande" o array em linhas individuais.
    -- array_agg(g.name) + array_join: reagrupa os nomes em uma string formatada.
    SELECT
        u.id,
        u.media_type,
        array_join(array_agg(g.name), ', ') AS genre_names
    FROM unified u
    CROSS JOIN UNNEST(u.genre_ids) AS t(genre_id)  -- expande ex: [28,12] → linha com 28, linha com 12
    LEFT JOIN genres_combined g
        ON g.id = t.genre_id  -- busca o nome pelo ID (ex: 28 → "Ação")
    GROUP BY u.id, u.media_type  -- reagrupa para um resultado por título
),

-- Duração dos filmes em minutos, vinda da tabela de detalhes coletada pelo Glue Details.
-- title_pt/overview_pt são as traduções EN→PT gravadas pelo Glue Details (only for original_language='en').
-- ROW_NUMBER() deduplica IDs que aparecem mais de uma vez (cada refresh mensal insere novas linhas
-- via append); ORDER BY dt_processamento DESC mantém o registro mais recente.
movie_details_ranked AS (
    SELECT id, runtime, title_en, title_pt, overview_en, overview_pt, poster_path_en, backdrop_path_en,
        ROW_NUMBER() OVER (PARTITION BY id ORDER BY dt_processamento DESC) AS rn
    FROM {db_movie}.tb_details_movie_tmdb
),

movie_details AS (
    SELECT id, runtime, title_en, title_pt, overview_en, overview_pt, poster_path_en, backdrop_path_en
    FROM movie_details_ranked
    WHERE rn = 1
),

-- Quantidade de temporadas, episódios e duração média por episódio das séries.
-- element_at(episode_run_time, 1) pega o primeiro valor do array retornado pelo TMDB
-- (a API geralmente retorna um único elemento com a duração padrão do episódio).
-- Mesmo padrão de deduplicação por dt_processamento DESC que movie_details_ranked acima.
tv_details_ranked AS (
    SELECT
        id,
        number_of_seasons,
        number_of_episodes,
        element_at(episode_run_time, 1) AS episode_runtime_minutes,
        title_en,
        title_pt,
        overview_en,
        overview_pt,
        poster_path_en,
        backdrop_path_en,
        ROW_NUMBER() OVER (PARTITION BY id ORDER BY dt_processamento DESC) AS rn
    FROM {db_tv}.tb_details_tv_tmdb
),

tv_details AS (
    SELECT id, number_of_seasons, number_of_episodes, episode_runtime_minutes,
           title_en, title_pt, overview_en, overview_pt, poster_path_en, backdrop_path_en
    FROM tv_details_ranked
    WHERE rn = 1
),

-- Referência unificada de provedores (union de movie + tv), desduplicada por provider_id,
-- com canonical_name normalizado e prioridade de exibição no BR.
providers_ref_union AS (
    SELECT * FROM {db_movie}.tb_watch_providers_ref_movie_tmdb
    UNION
    SELECT * FROM {db_tv}.tb_watch_providers_ref_tv_tmdb
),

providers_ref_ranked AS (
    SELECT
        provider_id,
        provider_name,
        canonical_name,
        display_priority_br,
        ROW_NUMBER() OVER (
            PARTITION BY provider_id
            ORDER BY COALESCE(display_priority_br, 999) ASC
        ) AS rn
    FROM providers_ref_union
),

provider_ref AS (
    SELECT
        provider_name,
        canonical_name,
        COALESCE(display_priority_br, 999) AS priority_br
    FROM providers_ref_ranked
    WHERE rn = 1
),

-- Seleciona apenas o ano mais recente por ID em watch_providers (filmes e séries).
-- Evita duplicar providers quando o mesmo ID aparece em múltiplas partições de ano.
-- DENSE_RANK (não ROW_NUMBER): atribui rank=1 a TODAS as linhas do ano mais recente por ID,
-- preservando todos os provedores daquele ano (Netflix, Amazon, etc.) ao invés de apenas um.
movie_wp_recent AS (
    SELECT id, provider_type, provider_name,
           DENSE_RANK() OVER (PARTITION BY id ORDER BY CAST(year AS INTEGER) DESC) AS rn
    FROM {db_movie}.tb_watch_providers_movie_tmdb
    WHERE provider_type = 'flatrate'
),

tv_wp_recent AS (
    SELECT id, provider_type, provider_name,
           DENSE_RANK() OVER (PARTITION BY id ORDER BY CAST(year AS INTEGER) DESC) AS rn
    FROM {db_tv}.tb_watch_providers_tv_tmdb
    WHERE provider_type = 'flatrate'
),

-- Provedores de streaming BR (flatrate) por filme:
-- JOIN com provider_ref para normalizar nomes e obter prioridade,
-- desduplicado por canonical_name, ordenado por prioridade BR crescente.
movie_providers_ranked AS (
    SELECT wp.id, r.canonical_name, MIN(r.priority_br) AS min_priority
    FROM movie_wp_recent wp
    JOIN provider_ref r ON r.provider_name = wp.provider_name
    WHERE wp.rn = 1
    GROUP BY wp.id, r.canonical_name
),

movie_providers AS (
    SELECT
        id,
        array_join(
            array_agg(canonical_name ORDER BY min_priority ASC),
            ', '
        ) AS streaming_providers
    FROM movie_providers_ranked
    GROUP BY id
),

-- Provedores de streaming BR (flatrate) por série: mesma lógica.
tv_providers_ranked AS (
    SELECT wp.id, r.canonical_name, MIN(r.priority_br) AS min_priority
    FROM tv_wp_recent wp
    JOIN provider_ref r ON r.provider_name = wp.provider_name
    WHERE wp.rn = 1
    GROUP BY wp.id, r.canonical_name
),

tv_providers AS (
    SELECT
        id,
        array_join(
            array_agg(canonical_name ORDER BY min_priority ASC),
            ', '
        ) AS streaming_providers
    FROM tv_providers_ranked
    GROUP BY id
),

-- ============================================================================
-- SELECT FINAL: combina todas as CTEs e constrói a tabela SPEC
-- ============================================================================
spec_raw AS (
    SELECT
        u.id,
        u.media_type,
        -- Prioriza a tradução PT gravada pelo Glue Details (title_pt/overview_pt),
        -- que existe apenas para original_language='en'. Para outros idiomas title_pt é NULL
        -- e o COALESCE cai para o título original do discover ou para o fallback em inglês.
        COALESCE(md.title_pt, tv.title_pt, NULLIF(TRIM(u.title), ''), md.title_en, tv.title_en)          AS title,
        u.original_title,
        COALESCE(md.overview_pt, tv.overview_pt, NULLIF(TRIM(u.overview), ''), md.overview_en, tv.overview_en) AS overview,
        u.air_date,
        u.original_language,
        lang.english_name                                                       AS language_name,
        u.genre_ids,
        gn.genre_names,
        -- Constrói a URL completa do pôster adicionando o prefixo da CDN do TMDB.
        -- O TMDB armazena apenas o caminho relativo (ex: "/abc123.jpg").
        -- "w342" é o tamanho da imagem em pixels de largura.
        CASE
            WHEN COALESCE(NULLIF(TRIM(u.poster_path), ''),
                          md.poster_path_en, tv.poster_path_en) IS NULL THEN NULL
            ELSE CONCAT('https://image.tmdb.org/t/p/w342',
                        COALESCE(NULLIF(TRIM(u.poster_path), ''),
                                 md.poster_path_en, tv.poster_path_en))
        END                                                                     AS poster_url,
        -- Constrói a URL da imagem de fundo (backdrop). "w780" = largura 780px.
        CASE
            WHEN COALESCE(NULLIF(TRIM(u.backdrop_path), ''),
                          md.backdrop_path_en, tv.backdrop_path_en) IS NULL THEN NULL
            ELSE CONCAT('https://image.tmdb.org/t/p/w780',
                        COALESCE(NULLIF(TRIM(u.backdrop_path), ''),
                                 md.backdrop_path_en, tv.backdrop_path_en))
        END                                                                     AS backdrop_url,
        u.popularity,
        u.vote_average,
        u.vote_count,
        u.origin_country,
        ctry.native_name                          AS origin_country_name,
        u.adult,
        u.year,
        md.runtime                                AS runtime_minutes,
        tv.number_of_seasons,
        tv.number_of_episodes,
        tv.episode_runtime_minutes,
        -- Provedores de streaming BR disponíveis (apenas flatrate = assinatura).
        -- COALESCE(mp, tp): tenta o provider de filme; se nulo, usa o de série.
        -- Na prática, um mesmo registro é só filme ou só série, então apenas
        -- um dos dois JOINs retornará dados (o outro será NULL).
        COALESCE(mp.streaming_providers, tp.streaming_providers) AS streaming_providers
    FROM unified u
    LEFT JOIN genre_names gn
        ON  gn.id         = u.id
        AND gn.media_type = u.media_type
    LEFT JOIN {db_movie}.tb_configuration_languages_tmdb lang
        ON lang.iso_639_1 = u.original_language
    LEFT JOIN {db_tv}.tb_configuration_countries_tmdb ctry
        ON ctry.iso_3166_1 = element_at(u.origin_country, 1)
    LEFT JOIN movie_details md
        ON  md.id = u.id AND u.media_type = 'movie'
    LEFT JOIN tv_details tv
        ON  tv.id = u.id AND u.media_type = 'tv'
    LEFT JOIN movie_providers mp
        ON  mp.id = u.id AND u.media_type = 'movie'
    LEFT JOIN tv_providers tp
        ON  tp.id = u.id AND u.media_type = 'tv'
),

-- Deduplicação final: garante um único registro por (id, media_type) na saída SPEC,
-- mesmo que restem duplicatas cross-year após os ROW_NUMBER anteriores.
spec_deduped AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY id, media_type
               ORDER BY year DESC, popularity DESC
           ) AS rn_final
    FROM spec_raw
)

SELECT
    id, media_type, title, original_title, overview, air_date, original_language,
    language_name, genre_ids, genre_names, poster_url, backdrop_url, popularity,
    vote_average, vote_count, origin_country, origin_country_name, adult, year,
    runtime_minutes, number_of_seasons, number_of_episodes, episode_runtime_minutes,
    streaming_providers
FROM spec_deduped
WHERE rn_final = 1
"""


def get_resolved_option(args: list) -> Dict[str, Any]:
    """Wrapper de getResolvedOptions — converte lista de nomes em dicionário nome→valor."""
    return getResolvedOptions(sys.argv, args)


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos obrigatórios do job Glue AGG.

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
        "GLUE_DATA_QUALITY_JOB_NAME",
    ]
    return get_resolved_option(required_args)


def run_athena_query(
    db_movie: str,
    db_tv: str,
    db_unified: str,
    s3_bucket_temp: str,
) -> pd.DataFrame:
    """
    Executa a query de unificação no Athena e retorna o resultado como DataFrame.

    Usa ctas_approach=True para suportar colunas ARRAY (genre_ids, origin_country).

    Args:
        db_movie:       Banco de dados de filmes no Glue Catalog.
        db_tv:          Banco de dados de séries no Glue Catalog.
        db_unified:     Banco de dados unificado.
        s3_bucket_temp: Bucket S3 para os resultados temporários do Athena.

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



def write_parquet_to_spec(
    df: pd.DataFrame,
    s3_bucket_spec: str,
    table_name: str,
    database: str,
) -> None:
    """
    Escreve o DataFrame como Parquet no bucket SPEC, particionado por media_type e year.

    Usa overwrite para garantir que o Glue Catalog fique sempre sincronizado com o S3.
    overwrite_partitions pode deixar o Catalog apontando para arquivos antigos deletados
    caso a atualização do Catalog falhe parcialmente após a deleção dos arquivos S3.
    Como a tabela unificada é sempre escrita por completo (todos os anos/media_types),
    overwrite e overwrite_partitions produzem o mesmo resultado final.

    Args:
        df:             DataFrame a ser gravado.
        s3_bucket_spec: Nome do bucket SPEC de destino.
        table_name:     Nome da tabela de destino no Catalog e como prefixo no S3.
        database:       Nome do banco de dados no Glue Catalog.
    """
    if df.empty:
        logger.warning(
            f"DataFrame vazio recebido para '{table_name}'. "
            "Escrita ignorada para preservar dados existentes."
        )
        return

    s3_path = f"s3://{s3_bucket_spec}/{table_name}/"
    logger.info(
        f"Escrevendo {len(df)} registros em {s3_path} | "
        f"particoes=[media_type, year] | mode=overwrite"
    )
    result = wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=["media_type", "year"],
        mode="overwrite",
        database=database,
        table=table_name,
    )
    written_files = result.get("paths", [])
    if not written_files:
        raise RuntimeError(
            f"Escrita falhou: nenhum arquivo encontrado em '{s3_path}' após gravação. "
            "Abortando para não acionar o DQ contra dados ausentes."
        )
    logger.info(f"Tabela '{table_name}' gravada com sucesso no SPEC. {len(written_files)} arquivo(s) gravado(s).")


def trigger_data_quality(
    dq_job_name: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
) -> str:
    """
    Dispara o job Glue Data Quality e aguarda sua conclusão.

    Dispara o job de forma assíncrona (fire-and-forget): a escrita SPEC é concluída
    antes desta chamada, e o próximo trigger do EventBridge ocorre em 24h —
    sem risco de race condition com o mode="overwrite".

    Args:
        dq_job_name: Nome do job Glue Data Quality cadastrado na AWS.
        table_name:  Nome da tabela a validar.
        database:    Nome do banco de dados no Glue Catalog.
        year:        Ano da partição. None avalia a tabela toda.

    Returns:
        JobRunId da execução.
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
