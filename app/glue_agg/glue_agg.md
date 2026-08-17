# glue_agg — Unificador (Camada SPEC)

## O que é

O Glue AGG é o estágio final de transformação do pipeline. Roda em agendamento próprio — um `aws_glue_trigger` nativo do Glue (`type = "SCHEDULED"`, sem EventBridge/Lambda no meio), sábado e domingo às 08:00 BRT (`infra/glue_agg.tf`) — independente do restante do pipeline: não espera nenhum sinal de conclusão do Glue Details, apenas une todas as tabelas da camada SOT disponíveis no momento em uma única tabela consolidada na camada SPEC (Gold) e grava o resultado pronto para consumo pelo aplicativo de recomendações (FilmBot). A única exceção a esse desacoplamento é o backfill manual (`.github/workflows/06_backfill.yml`): ao final de qualquer `table_group` exceto `data_quality`, o workflow dispara o AGG uma vez, como última etapa, para não esperar até 6 dias pelo próximo ciclo agendado (ver seção "Agendamento" abaixo).

## Por que existe

Os dados de filmes e séries chegam em tabelas separadas (discover, details, genres, languages, watch_providers). O aplicativo precisa de uma visão única e enriquecida. Este job faz essa consolidação via SQL no Athena, garantindo que o app consulte apenas uma tabela final, já traduzida e sem duplicatas.

## Agendamento (`aws_glue_trigger`, sábado e domingo às 08:00 BRT)

Antes, o AGG era acionado por código a partir do `glue_details` (`media_type == "tv" and year == end_year`, ou `media_type == "tv" and affected_years` no modo changes) — uma condição que garantia que todas as tabelas de origem já estivessem gravadas antes da unificação. Isso foi substituído por um agendamento fixo, tratando o AGG como independente do resto do pipeline: menos acoplamento, ao custo de aceitar o risco de o AGG rodar antes do ciclo semanal terminar e unificar dados incompletos até o próximo ciclo bem-sucedido (o job sempre faz `overwrite` total, sem validar completude).

O horário (11:00 UTC) foi calibrado com o histórico real de execução do Glue Details: no pior caso observado (rotation + discover semanal + monthly coincidindo no mesmo sábado — confirmado via CloudWatch, já que dia 1 do mês caindo num sábado dispara os três ciclos juntos), o `glue_details` terminou às 06:42 BRT. 08:00 BRT dá ~77 min de folga sobre esse cenário. O modo changes (Domingo) nunca colide com rotation/discover/monthly de sábado, já que roda isolado — o único caso não medido é monthly caindo num domingo (colidindo com changes), mas a contribuição marginal do monthly observada no sábado (~3-4 min) sugere folga bem maior que a necessária mesmo nesse cenário.

**Disparo adicional pelo backfill manual:** o desacoplamento acima vale para o pipeline automático. Para o backfill sob demanda (`scripts/backfill_*.py` via `.github/workflows/06_backfill.yml`), o gap de até 6 dias até o próximo sábado/domingo era indesejado — dado corrigido/preenchido via backfill devia chegar à camada SPEC no mesmo dia. O workflow dispara `glue:StartJobRun` no AGG logo após o loop de retry do script terminar com sucesso, para todo `table_group` exceto `data_quality` (que só valida, não escreve dado novo), e faz polling do `JobRunId` (`glue:GetJobRun` a cada 30s) até um estado terminal, escrevendo o resultado (`SUCCEEDED`/`FAILED`/`STOPPED`/`ERROR`/`TIMEOUT`) no step summary do GitHub Actions. Como o job já tem `job_run_queuing_enabled = true`, esse disparo extra não conflita com o trigger agendado nem com outro backfill em paralelo — apenas entra na fila (o que também significa que o polling pode demorar bem mais que o timeout de 30min do job, se houver fila). Nem falha ao disparar nem uma conclusão diferente de `SUCCEEDED` derrubam o workflow de backfill: o trigger agendado do fim de semana e o alarme SNS dedicado (`aws_cloudwatch_event_rule.glue_agg_failed`, `infra/cloudwatch_glue_alarms.tf`) continuam sendo a rede de segurança para esse cenário — o step summary é só visibilidade extra durante o próprio backfill, não a via de alerta principal.

Antes da seção do AGG, o step summary também mostra uma seção "Backfill" com o resumo real do que o script fez (extraído do log via `grep`, mesmo formato de log de todos os 8 scripts) e qualquer linha `ERROR` registrada — relevante porque `exit 0` nem sempre significa "toda unidade teve sucesso" (`backfill_enriquecimento.py`/`backfill_historico.py` são soft-fail-continue, `backfill_data_quality.py` é fire-and-forget; ver `scripts/scripts.md`).

## Conceitos-chave

- **SPEC / Gold layer** — a camada final e mais refinada do pipeline. Contém uma única tabela com todos os dados integrados, sem duplicatas, já traduzidos e prontos para consumo direto pelo app. É chamada de "Gold" porque é o produto acabado de todo o processamento anterior.
- **DENSE_RANK** — função SQL de janela (window function) que atribui uma posição a cada linha dentro de um grupo. Aqui é usada para identificar o registro mais recente de watch providers por filme/série: rank=1 significa "do ano mais recente disponível", e só esses registros são incluídos na saída.
- **CTE (Common Table Expression)** — blocos SQL nomeados com `WITH nome AS (...)` que simplificam queries complexas, permitindo referenciar o resultado de uma subquery por nome em vez de aninhar selects.

## Como funciona

1. Lê os argumentos do job (nomes dos databases, buckets, tabela de destino, nome do job de Data Quality)
2. Executa uma query SQL complexa no **Athena** que:
   - Une filmes e séries via `UNION ALL`
   - Deduplica watch providers por `DENSE_RANK` sobre o ano mais recente (CTEs `movie_wp_recent` / `tv_wp_recent`), preservando todos os provedores do ano mais recente por ID
   - Constrói `streaming_provider_logos`/`rent_buy_provider_logos` (CTE `provider_ref`) a partir de `logo_path` (coletado em `lambda_api`), montando a URL da CDN do TMDB (`https://image.tmdb.org/t/p/w45{logo_path}`). São colunas string comma-joined **paralelas** a `streaming_providers`/`rent_buy_providers` — mesmo `GROUP BY`/`ORDER BY min_priority ASC`, alinhadas posição a posição — em vez de um tipo `ARRAY<ROW>`, porque o consumidor (`app/lightsail_ia/agent.py`) lê o Athena via boto3 cru (`get_query_results`), que devolve tudo como string; e porque `streaming_providers` continua sendo usado como filtro (`LIKE`) pelo LLM, o que exige mantê-lo como string simples
   - Faz `LEFT JOIN` com gêneros, idiomas, países, detalhes (runtime/temporadas, elenco, diretor, roteiristas, compositor, produtor, cinematógrafo, montador, keywords_pt, país de origem, países de produção, classificação indicativa, trailer, coleção, produtoras, status, tagline, IMDB ID, títulos recomendados/similares/alternativos, campos TV — incluindo próximo episódio agendado `next_episode_air_date`/`next_episode_number`/`next_episode_season_number`/`next_episode_name` e temporadas `season_numbers`/`season_air_dates`/`season_episode_counts`/`season_names`, NULL do lado filme), plataformas de streaming (assinatura e aluguel/compra) e a tabela `now_playing` (para filmes em cartaz nos cinemas)
   - Resolve `recommended_titles` e `similar_titles` para pt-BR cruzando os IDs (`recommended_ids`/`similar_ids`) com a tabela `unified` (discover pt-BR) via CTEs `recommended_resolved` e `similar_resolved`, com fallback para o título em inglês quando o ID não existe no discover
   - Traduz `tv_type` de inglês para português via `CASE WHEN` (ex: `Scripted` → `Roteirizada`, `Documentary` → `Documentário`)
   - Traduz `status` de inglês para português via `CASE WHEN` (ex: `Released` → `Lançado`, `Canceled` → `Cancelado`)
   - Usa `COALESCE(d.tagline_pt, d.tagline)` para priorizar tagline traduzida
   - Resolve países de produção via lookup de códigos ISO na `tb_configuration_countries` (CTE `production_countries_resolved`), com fallback para nomes em inglês
   - Resolve idiomas falados via lookup de códigos ISO na `tb_configuration_languages` (CTE `spoken_languages_resolved`), com fallback para nomes em inglês
   - Usa `COALESCE(collection_name_pt, collection_name)` para priorizar nome da coleção em pt-BR
   - Usa `COALESCE(lang.name_pt, lang.english_name, lang.name)` para `language_name`, priorizando tradução em pt-BR
   - Usa `ctry.name_pt` (nome traduzido em pt-BR) em vez de `ctry.native_name` para `origin_country_name`
   - Aplica deduplicação final via `spec_deduped` — garante um único registro por `(id, media_type)` na saída mesmo que restem duplicatas cross-year
3. Seleciona `title` do discover (pt-BR nativo do TMDB) como primeira prioridade. Para `overview`, só confia no valor do discover quando `overview_detected_language` (gravado pelo Glue ETL via `langdetect`/AWS Comprehend — ver `glue_etl.md`) confirma que o texto é genuinamente `"pt"` — o TMDB às vezes devolve o campo em outro idioma silenciosamente mesmo com `language=pt-BR` pedido, então "não-vazio" sozinho não bastava como critério de confiança. Quando não confirmado (idioma diferente ou detecção nula), cai para `overview_pt` traduzido pelo Glue Details, com `overview_en` como último recurso
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

## SQL de unificação (resumo) — `src/queries.py`

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
  SELECT id, 'movie' AS media_type, streaming_providers, streaming_provider_logos FROM movie_providers
  UNION ALL
  SELECT id, 'tv'    AS media_type, streaming_providers, streaming_provider_logos FROM tv_providers
)
SELECT
  COALESCE(
    CASE WHEN u.overview_detected_language = 'pt' THEN NULLIF(TRIM(u.overview), '') END,
    d.overview_pt, d.overview_en
  ) AS overview,
  d.runtime AS runtime_minutes, d.number_of_seasons, d.number_of_episodes,
  p.streaming_providers, p.streaming_provider_logos,
  CASE WHEN np.id IS NOT NULL THEN TRUE ELSE FALSE END AS in_theaters,
  ...
FROM unified u
LEFT JOIN details   d  ON d.id = u.id AND d.media_type = u.media_type
LEFT JOIN providers p  ON p.id = u.id AND p.media_type = u.media_type
LEFT JOIN tb_tmdb_now_playing_movie_{env} np ON np.id = u.id AND u.media_type = 'movie'
```

## Funções principais (`src/utils.py` · query em `src/queries.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job (inclui `GLUE_DATA_QUALITY_JOB_NAME`) |
| `run_athena_query(db_movie, db_tv, db_unified, s3_bucket_temp, env)` | Executa o SQL de unificação (com dedup de watch providers por `DENSE_RANK`, dedup final por `spec_deduped` e LEFT JOIN com `now_playing` para enriquecer filmes com `in_theaters`, `theater_start_date`, `theater_end_date`) e retorna um DataFrame |
| `write_parquet_to_spec(df, s3_bucket_spec, s3_prefix_spec, table_name, database)` | Grava Parquet com `mode="overwrite"` particionado por `(media_type, year)` na SPEC e registra no Glue Catalog |

## Funções compartilhadas (`shared_utils/`)

| Função | Origem | Responsabilidade |
|---|---|---|
| `trigger_glue_job(job_name, **arguments)` | `shared_utils.triggers` | Dispara qualquer job Glue com argumentos dinâmicos; aqui usado para acionar o DQ sem `year` (avalia a tabela inteira) |

## Tecnologias

- **awswrangler** — consulta Athena, escrita Parquet, registro no Glue Catalog
- **pandas** — manipulação do DataFrame resultante
