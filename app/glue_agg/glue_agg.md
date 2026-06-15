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
3. Seleciona `title_pt` e `overview_pt` já traduzidos — a tradução é feita pelo Glue Details e armazenada nas tabelas `tb_details_*`; o AGG as lê via `COALESCE` no SQL
4. Grava o DataFrame final como Parquet com `mode="overwrite"` particionado por `(media_type, year)` na camada SPEC
5. O AWS Wrangler registra automaticamente a tabela no Glue Catalog (`db_unified_tmdb`)
6. Aciona o Glue Data Quality para validar a tabela unificada completa (sem filtro de ano)

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `DB_MOVIE`, `DB_TV`, `DB_UNIFIED`, `S3_BUCKET_SPEC`, `S3_BUCKET_TEMP`, `TABLE_NAME`, `GLUE_DATA_QUALITY_JOB_NAME` |
| **Leitura** | Athena — tabelas da SOT: `tb_discover_*`, `tb_details_*`, `tb_genre_*`, `tb_configuration_*`, `tb_watch_providers_*`, `tb_now_playing_movie_tmdb` |
| **Escrita** | S3 SPEC — `tb_discover_unified_tmdb` particionada por `(media_type, year)` + Glue Catalog |
| **Aciona** | Glue Data Quality (tabela unificada completa, sem partição de ano) |

## SQL de unificação (resumo)

```sql
WITH filmes AS (
  SELECT d.*, det.runtime
  FROM tb_discover_movie_tmdb d
  LEFT JOIN tb_details_movie_tmdb det ON d.id = det.id
  -- deduplica por id mantendo mais recente/popular
),
series AS (
  SELECT d.*, det.number_of_seasons, det.number_of_episodes
  FROM tb_discover_tv_tmdb d
  LEFT JOIN tb_details_tv_tmdb det ON d.id = det.id
),
unificado AS (
  SELECT * FROM filmes UNION ALL SELECT * FROM series
)
SELECT u.*, g.genre_names, l.language_name, wp.streaming_providers,
       CASE WHEN np.id IS NOT NULL THEN TRUE ELSE FALSE END AS in_theaters,
       np.theater_start_date, np.theater_end_date
FROM unificado u
LEFT JOIN tb_genre_* g ON ...
LEFT JOIN tb_configuration_languages_tmdb l ON ...
LEFT JOIN tb_watch_providers_* wp ON ...
LEFT JOIN tb_now_playing_movie_tmdb np ON np.id = u.id AND u.media_type = 'movie'
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
