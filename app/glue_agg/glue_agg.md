# glue_agg — Unificador (Camada SPEC)

## O que é

O Glue AGG é o estágio final de transformação do pipeline. Acionado pelo Glue Details após todos os detalhes de filmes e séries estarem prontos, ele une todas as tabelas da camada SOT em uma única tabela consolidada na camada SPEC (Gold). Traduz títulos e sinopses do inglês para o português e grava o resultado pronto para consumo pelo aplicativo de recomendações (FilmBot).

## Por que existe

Os dados de filmes e séries chegam em tabelas separadas (discover, details, genres, languages, watch_providers). O aplicativo precisa de uma visão única e enriquecida. Este job faz essa consolidação via SQL no Athena, garantindo que o app consulte apenas uma tabela final, já traduzida e sem duplicatas.

## Como funciona

1. Lê os argumentos do job (nomes dos databases, buckets, tabela de destino)
2. Executa uma query SQL complexa no **Athena** que:
   - Une filmes e séries via `UNION ALL`
   - Deduplica por ID (mantém o mais recente e mais popular em caso de conflito)
   - Faz `LEFT JOIN` com gêneros, idiomas, países, detalhes (runtime/temporadas) e plataformas de streaming
3. Traduz as colunas `title` e `overview` do inglês para o português para registros cujo idioma original é inglês — em paralelo via `ThreadPoolExecutor` usando a API do Google Translate
4. Grava o DataFrame final como Parquet particionado por `media_type` na camada SPEC
5. O AWS Wrangler registra automaticamente a tabela no Glue Catalog (`db_unified_tmdb`)

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `DB_MOVIE`, `DB_TV`, `DB_UNIFIED`, `S3_BUCKET_SPEC`, `S3_BUCKET_TEMP`, `TABLE_NAME` |
| **Leitura** | Athena — tabelas da SOT: `tb_discover_*`, `tb_details_*`, `tb_genre_*`, `tb_configuration_*`, `tb_watch_providers_*` |
| **Escrita** | S3 SPEC — `tb_discover_unified_tmdb` particionada por `media_type` + Glue Catalog |
| **Aciona** | Nada (último job do pipeline de dados) |

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
SELECT u.*, g.genre_names, l.language_name, wp.streaming_providers
FROM unificado u
LEFT JOIN tb_genre_* g ON ...
LEFT JOIN tb_configuration_languages_tmdb l ON ...
LEFT JOIN tb_watch_providers_* wp ON ...
```

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job |
| `run_athena_query(db_movie, db_tv, db_unified, s3_bucket_temp)` | Executa o SQL de unificação e retorna um DataFrame |
| `traduzir_colunas_en(df)` | Traduz `title` e `overview` inglês→português em paralelo |
| `write_parquet_to_spec(df, s3_bucket_spec, table_name, database)` | Grava Parquet particionado na SPEC e registra no Glue Catalog |

## Tecnologias

- **awswrangler** — consulta Athena, escrita Parquet, registro no Glue Catalog
- **pandas** — manipulação do DataFrame resultante
- **deep_translator** (Google Translate API) — tradução de título e sinopse
- **ThreadPoolExecutor** — paralelização das traduções
