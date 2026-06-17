# glue_agg — Unificador (Camada SPEC)

## O que é

O Glue AGG é o estágio final de transformação do pipeline. Acionado pelo Glue Details após todos os detalhes de filmes e séries estarem prontos, ele une todas as tabelas da camada SOT em uma única tabela consolidada na camada SPEC (Gold) e grava o resultado pronto para consumo pelo aplicativo de recomendações (FilmBot).

## Por que existe

Os dados de filmes e séries chegam em tabelas separadas (discover, details, genres, languages, watch_providers). O aplicativo precisa de uma visão única e enriquecida. Este job faz essa consolidação via SQL no Athena, garantindo que o app consulte apenas uma tabela final, já traduzida e sem duplicatas.

## Conceitos-chave

- **SPEC / Gold layer** — a camada final e mais refinada do pipeline. Contém uma única tabela com todos os dados integrados, sem duplicatas, já traduzidos e prontos para consumo direto pelo app. É chamada de "Gold" porque é o produto acabado de todo o processamento anterior.
- **DENSE_RANK** — função SQL de janela (window function) que atribui uma posição a cada linha dentro de um grupo. Aqui é usada para identificar o registro mais recente de watch providers por filme/série: rank=1 significa "do ano mais recente disponível", e só esses registros são incluídos na saída.
- **CTE (Common Table Expression)** — blocos SQL nomeados com `WITH nome AS (...)` que simplificam queries complexas, permitindo referenciar o resultado de uma subquery por nome em vez de aninhar selects.

## Como funciona

1. Lê os argumentos do job (nomes dos databases, buckets, tabela de destino, nome do job de Data Quality)
2. Executa uma query SQL complexa no **Athena** que:
   - Une filmes e séries via `UNION ALL`
   - Deduplica watch providers por `DENSE_RANK` sobre o ano mais recente (CTEs `movie_wp_recent` / `tv_wp_recent`), preservando todos os provedores do ano mais recente por ID
   - Faz `LEFT JOIN` com gêneros, idiomas, países, detalhes (runtime/temporadas), plataformas de streaming e a tabela `now_playing` (para filmes em cartaz nos cinemas)
   - Aplica deduplicação final via `spec_deduped` — garante um único registro por `(id, media_type)` na saída mesmo que restem duplicatas cross-year
3. Seleciona `title` e `overview` do discover (pt-BR nativo do TMDB) como primeira prioridade; `overview_pt` traduzido pelo Glue Details entra como fallback quando o discover retornou vazio, seguido por `overview_en` como último recurso
4. Grava o DataFrame final como Parquet com `mode="overwrite"` particionado por `(media_type, year)` na camada SPEC
5. O AWS Wrangler registra automaticamente a tabela no Glue Catalog (`db_tmdb_unified_{env}`)
6. Aciona o Glue Data Quality para validar a tabela unificada completa (sem filtro de ano)

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `S3_BUCKET_SPEC`, `S3_PREFIX_SPEC`, `S3_BUCKET_TEMP`, `DB_MOVIE`, `DB_TV`, `DB_UNIFIED`, `TABLE_NAME`, `GLUE_DATA_QUALITY_JOB_NAME`, `ENVIRONMENT` |
| **Leitura** | Athena — tabelas da SOT: `tb_tmdb_discover_*`, `tb_tmdb_details_*`, `tb_tmdb_genre_*`, `tb_tmdb_configuration_*`, `tb_tmdb_watch_providers_*`, `tb_tmdb_now_playing_movie_{env}` |
| **Escrita** | S3 SPEC — `tb_tmdb_discover_unified_{env}` particionada por `(media_type, year)` + Glue Catalog |
| **Aciona** | Glue Data Quality (tabela unificada completa, sem partição de ano) |

## SQL de unificação (resumo)

```sql
WITH unified AS (
  SELECT * FROM movies  -- deduplicados por (id, year DESC, popularity DESC)
  UNION ALL
  SELECT * FROM tv_shows
),
details AS (
  -- filmes e séries unidos por media_type; colunas exclusivas recebem NULL no outro lado
  SELECT id, 'movie' AS media_type, runtime, NULL AS number_of_seasons, ... FROM movie_details
  UNION ALL
  SELECT id, 'tv'    AS media_type, NULL AS runtime, number_of_seasons, ... FROM tv_details
),
providers AS (
  SELECT id, 'movie' AS media_type, streaming_providers FROM movie_providers
  UNION ALL
  SELECT id, 'tv'    AS media_type, streaming_providers FROM tv_providers
)
SELECT
  COALESCE(NULLIF(TRIM(u.overview), ''), d.overview_pt, d.overview_en) AS overview,
  d.runtime AS runtime_minutes, d.number_of_seasons, d.number_of_episodes,
  p.streaming_providers,
  CASE WHEN np.id IS NOT NULL THEN TRUE ELSE FALSE END AS in_theaters,
  ...
FROM unified u
LEFT JOIN details   d  ON d.id = u.id AND d.media_type = u.media_type
LEFT JOIN providers p  ON p.id = u.id AND p.media_type = u.media_type
LEFT JOIN tb_tmdb_now_playing_movie_{env} np ON np.id = u.id AND u.media_type = 'movie'
```

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job (inclui `GLUE_DATA_QUALITY_JOB_NAME`) |
| `run_athena_query(db_movie, db_tv, db_unified, s3_bucket_temp)` | Executa o SQL de unificação (com dedup de watch providers por `DENSE_RANK`, dedup final por `spec_deduped` e LEFT JOIN com `now_playing` para enriquecer filmes com `in_theaters`, `theater_start_date`, `theater_end_date`) e retorna um DataFrame |
| `write_parquet_to_spec(df, s3_bucket_spec, table_name, database)` | Grava Parquet com `mode="overwrite"` particionado por `(media_type, year)` na SPEC e registra no Glue Catalog |
| `trigger_data_quality(dq_job_name, table_name, database, year=None)` | Aciona o job de Data Quality; quando `year=None`, avalia a tabela inteira |

## Tecnologias

- **awswrangler** — consulta Athena, escrita Parquet, registro no Glue Catalog
- **pandas** — manipulação do DataFrame resultante
