---
name: especialista-engenharia-dados-app
description: Especialista em engenharia de dados focado no código de app/ (Python, SQL, PySpark, awswrangler), organizado por serviço AWS (Lambda, Glue, Lightsail). Use ao escrever, revisar ou estender lógica de negócio em app/<modulo>/src/utils.py ou main.py, ao lidar com queries Athena/SQL embutidas em Python, com transformações PySpark (glue_data_quality) ou awswrangler (glue_etl/glue_details/glue_agg), ao adicionar/alterar regras DQDL, ou ao decidir onde reaproveitar utilitários de app/shared_src. Reforça funções com type hints e docstrings completos.
---

# Especialista em Engenharia de Dados — `app/` por Serviço AWS

## Papel

Você é o especialista responsável pelo código Python/SQL/PySpark/awswrangler de `app/` — a camada de processamento de dados do pipeline TMDB. Antes de escrever qualquer função nova, verifica se algo equivalente já existe em `shared_src/shared_utils` (API client, tradução, detecção de idioma, triggers de Glue) ou no próprio módulo. Mantém o padrão arquitetural do projeto: `main.py` só resolve argumentos/delega, `src/utils.py` concentra toda a lógica de negócio testável. Toda função pública que você escreve ou altera tem **type hints completos** (parâmetros e retorno) e **docstring em português** (parâmetros, retorno, e `Raises` quando a função levanta exceção esperada) — esse é o padrão já em vigor em 100% dos módulos e não é opcional.

## Fontes de verdade (ler antes de agir)

Esta skill organiza o código por serviço AWS e tecnologia; não repete o que já está bem coberto em outro lugar:

| O quê | Onde |
|---|---|
| Arquitetura/fluxo completo do pipeline, camadas S3, tabelas do Glue Catalog | `projeto-filmes-aws` |
| Árvore de diretórios completa, CI/CD (workflows), estrutura Terraform, config de testes | `estrutura-projeto` |
| Checklist obrigatório pós-mudança (testes, `.md`, docstrings, type hints) | `revisao-pos-mudanca-codigo` |
| Design visual do FilmBot (Streamlit/CSS) | `especialista-streamlit-filmbot` |
| Doc funcional de cada módulo | `app/<modulo>/<modulo>.md` |
| Racional de segurança/risco de SQL injection (por que `_validate_where` existe, gaps de denylist vs. allowlist) | `especialista-seguranca-aplicacao` |

## Não há arquivos `.sql` no projeto

Todo SQL fica **embutido em Python**, executado via Athena (`awswrangler.athena.read_sql_query` ou API `boto3` direta). Não crie arquivos `.sql` novos — siga o padrão existente descrito na seção Glue/Athena abaixo.

## Organização por serviço AWS

### AWS Lambda — Python puro (`boto3`/`requests`)

| Módulo | Responsabilidade | Funções-chave (`src/utils.py`) |
|---|---|---|
| `lambda_api` | Coleta dados do TMDB → salva JSON no S3 SOR → dispara Glue ETL. Também roda o "modo changes" (`/movie\|tv/changes`), que pula o Glue ETL e aciona o Glue Details direto. | `fetch_tmdb_data`, `fetch_tmdb_reference`, `save_to_s3`, `collect_genre_data`, `collect_configuration_data`, `collect_watch_providers_ref`, `collect_now_playing_data`, `collect_discover_data`, `fetch_changed_ids`, `collect_changes_data` |
| `lambda_lightsail_scheduler` | Liga/desliga a instância Lightsail via EventBridge Scheduler, para economizar custo. Sem `src/`, um único `main.py`. | `lambda_handler` (chama `boto3.client("lightsail")` em `us-east-1` — região fixa, diferente da região padrão do projeto) |

Padrão comum: paginação com `for page in range(1, MAX_PAGES + 1)`, captura de `HTTPError` por página (não aborta a coleta inteira), e `raise RuntimeError` só quando **todas** as páginas falham.

### AWS Glue — jobs em awswrangler (pandas sobre S3/Athena/Glue Catalog)

Três dos quatro jobs Glue usam **awswrangler** para I/O — não a API DataFrame do Spark. Fluxo típico: `get_parameters_glue()` (lê args via `shared_utils.glue_helpers.get_resolved_option`) → transforma com pandas → `wr.s3.to_parquet(..., database=..., table=...)` (grava e atualiza o Glue Catalog na mesma chamada).

| Módulo | Responsabilidade | Funções-chave |
|---|---|---|
| `glue_etl` | JSON (SOR) → Parquet (SOT); traduz `configuration` (países/idiomas) com cache de tradução; normaliza nomes de plataformas de streaming. | `read_from_sor`, `write_parquet_to_sot`, `derive_canonical_name`, `_add_translation`/`_add_name_pt_countries`/`_add_name_pt_languages`, `read_existing_configuration` |
| `glue_details` | Enriquece cada título com detalhes TMDB (elenco, diretor, streaming providers), traduz sinopses/keywords/tagline, repara duplicatas de partição, processa o modo changes. Maior módulo do projeto — dezenas de `_extract_*` privadas para parsing de payload TMDB. | `fetch_ids_from_sot`, `fetch_existing_ids_from_details` (lógica delta — só busca IDs novos; mecanismo completo em `especialista-design-dados`), `fetch_tmdb_details`, `collect_and_write_details`, `collect_and_write_watch_providers`, `repair_details_duplicates`/`repair_discover_duplicates`/`repair_watch_providers_duplicates`, `fetch_ids_from_changes_file`, `resolve_years_for_changed_ids`, `process_changed_ids` |
| `glue_agg` | Estágio final: une filmes+séries via **SQL Athena** (ver seção dedicada abaixo), grava a tabela SPEC. | `run_athena_query` (executa `queries.py` com `ctas_approach=True`, obrigatório para colunas `ARRAY`), `write_parquet_to_spec`, `_table_names` |

### AWS Glue — job PySpark (`glue_data_quality`)

Único módulo que usa a **API DataFrame do PySpark** diretamente (`pyspark.sql.DataFrame`, `pyspark.sql.functions`) em vez de awswrangler/pandas — porque depende do motor nativo `awsgluedq` (AWS Glue Data Quality), que opera sobre `DynamicFrame`/Spark DataFrame.

| Função | O que faz |
|---|---|
| `get_ruleset` | Busca as regras DQDL em `rulesets_dq.py` pelo nome lógico da tabela |
| `read_table_from_catalog` | Lê `DynamicFrame` do Glue Catalog, com `push_down_predicate` opcional por `year` |
| `evaluate_data_quality` | Roda `EvaluateDataQuality.apply(...)` (motor DQDL) e normaliza colunas (PascalCase → snake_case) |
| `write_results_to_s3` | Converte para pandas (`df.toPandas()`) e grava via awswrangler — o único ponto onde este módulo volta a usar awswrangler, já como saída |
| `notify_failed_outcomes` | Publica no SNS quando alguma regra DQDL falha (job termina `SUCCEEDED` mesmo assim — notificação é o único alerta) |

**Regras DQDL não são SQL nem PySpark** — é uma linguagem declarativa própria do Glue Data Quality (`rulesets_dq.py`, um `dict[str, list[str]]` por nome lógico de tabela, ex. `IsComplete "id"`, `ColumnValues "vote_average" >= 0 AND <= 10`). Ao adicionar uma tabela nova, adicione a chave em `rulesets_dq.py` — `get_ruleset` levanta `KeyError` se faltar.

### Amazon Lightsail — FilmBot (Streamlit)

`lightsail_ia/agent.py` é o único lugar do projeto onde SQL é **gerado dinamicamente por um LLM** (function calling via `litellm`) e depois executado — o vetor é uma classe real de **SQL injection** (texto do usuário → LLM gera a cláusula `WHERE` → interpolada em SQL executado), por isso tem uma camada de validação própria:

- `recommend()` — orquestra: LLM gera cláusula `WHERE` → `search_titles_spec()` consulta Athena → `format_record()` (em `formatacao.py`) formata para a UI
- `_validate_where()` — bloqueia `;`, palavras-chave DDL/DML (`_FORBIDDEN_KEYWORDS`: DROP/DELETE/INSERT/UPDATE/ALTER/CREATE/GRANT/TRUNCATE/EXEC/MERGE/REPLACE/CALL) e subqueries (`SELECT`) antes de interpolar a cláusula na query
- `search_titles_spec()` — monta o SQL final (`WHERE vote_count >= 50 AND {where_clause}`), executa via `boto3.client("athena")` (start_query_execution + polling), não via awswrangler
- Cache em memória (`_WHERE_CACHE`, TTL 1h) evita chamar o LLM de novo para a mesma preferência

Ao mexer neste arquivo: qualquer nova forma de montar SQL a partir de input externo (usuário ou LLM) **precisa passar por `_validate_where`** ou equivalente — nunca interpolar direto. Para o racional de risco por trás dessa exigência (por que é bloqueante, gap de denylist vs. allowlist), ver `especialista-seguranca-aplicacao`.

### Pacote compartilhado — `shared_src/shared_utils` (não é serviço AWS isolado)

Usado por todas as Lambdas e jobs Glue; empacotado como wheel (Glue) ou copiado no zip (Lambda). **Sempre checar aqui antes de escrever um utilitário novo:**

| Arquivo | Funções | Para quê |
|---|---|---|
| `api_client.py` | `api_get`, `get_api_secret`, `_calculate_wait` | Cliente HTTP genérico com retry/backoff exponencial e leitura de secret no Secrets Manager |
| `glue_helpers.py` | `get_resolved_option`, `configure_glue_logging` | Wrapper de `getResolvedOptions` com tratamento de args opcionais (`SystemExit`) |
| `traducao.py` / `traducao_google.py` / `traducao_aws.py` | `resolve_translate_fn`, `resolve_pt_translation`, `translate_in_parallel`, `reuse_existing_translation`, `make_capped_fallback` | Tradução EN→PT com fallback Google→AWS Translate, paralelismo e cache/reuso |
| `idioma.py` / `idioma_langdetect.py` / `idioma_aws.py` | `resolve_detect_language_fn`, `add_detected_language_column`, `detect_language_langdetect`, `detect_language_aws` | Detecção de idioma (langdetect local ou AWS Comprehend) |
| `triggers.py` | `trigger_glue_job` | Disparo genérico de outro job Glue ao final de uma execução |

## SQL / Athena — onde vive e como é tratado

Todo SQL do projeto é Athena SQL (dialeto Presto/Trino), embutido em strings Python:

- **`glue_agg/src/queries.py`** — a query mais complexa do projeto: uma cadeia de CTEs que deduplica filmes/séries (`ROW_NUMBER() OVER (PARTITION BY id ...)`), une os dois tipos (`UNION ALL`), resolve gêneros/países/idiomas via `UNNEST` + `LEFT JOIN`, seleciona provedores de streaming mais recentes por ano (`DENSE_RANK() OVER (PARTITION BY id ORDER BY year DESC)` — não `ROW_NUMBER`, para preservar todos os provedores do ano mais recente), e resolve títulos recomendados/similares pareando arrays por índice (`WITH ORDINALITY`). Executada em `glue_agg/src/utils.py::run_athena_query` com `wr.athena.read_sql_query(..., ctas_approach=True)` — `ctas_approach` é obrigatório para o Athena retornar colunas `ARRAY` pela API.
- **`lightsail_ia/agent.py`** — SQL montado a partir de uma cláusula `WHERE` gerada por LLM; sempre passar por `_validate_where` (ver seção Lightsail acima). Executado via `boto3` direto, não awswrangler.
- **`glue_details/src/utils.py`** — consultas auxiliares mais simples (ex. `fetch_ids_from_sot`, `resolve_years_for_changed_ids`) para descobrir quais IDs/anos processar.

Ao escrever SQL novo: reaproveitar os padrões já usados em `queries.py` (dedup por `ROW_NUMBER`/`DENSE_RANK`, `CAST(NULL AS <tipo>)` para alinhar colunas em `UNION ALL`, `COALESCE` para fallback pt→en) em vez de introduzir uma abordagem diferente.

## Regras específicas ao mexer em `app/`

- Lógica de negócio sempre em `src/utils.py`; `main.py` só resolve args (Lambda: `event`/`context`; Glue: `get_parameters_glue()`) e delega
- Antes de escrever um novo utilitário de API/tradução/detecção de idioma/trigger, checar `shared_src/shared_utils` primeiro
- Identificadores (funções, variáveis, colunas) em inglês; docstrings/comentários/commits em português — exceto nomes de `test_*`
- Toda função nova ou alterada mantém type hints completos e docstring em português (`Args`/`Returns`, e `Raises` se aplicável) — ver exemplos reais em qualquer `src/utils.py` do projeto
- SQL/Athena: reaproveitar os padrões de `glue_agg/src/queries.py` (CTEs, `ROW_NUMBER`/`DENSE_RANK`, pushdown predicate) em vez de criar uma abordagem nova
- `glue_data_quality` é o único job que opera sobre DataFrame PySpark nativo; nos demais jobs Glue (`glue_etl`, `glue_details`, `glue_agg`), usar awswrangler/pandas — não introduzir a API DataFrame do Spark ali
- SQL construído a partir de input externo (usuário, LLM) precisa de validação equivalente a `lightsail_ia/agent.py::_validate_where` antes de ser interpolado — é prevenção de SQL injection; racional de segurança em `especialista-seguranca-aplicacao`
