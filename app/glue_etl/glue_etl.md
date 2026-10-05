# glue_etl — Transformador (JSON → Parquet)

## O que é

O Glue ETL é o segundo estágio do pipeline. Recebe dados brutos em JSON salvos pela Lambda no S3 SOR, os transforma para o formato Parquet estruturado e os grava na camada SOT (Source of Truth). Também registra as tabelas no Glue Catalog para que sejam consultáveis via Athena. Ao final, aciona o Glue Data Quality e, para tabelas `discover`, aciona o Glue Details.

## Por que existe

JSON bruto é flexível mas ineficiente para análise. Parquet é colunar, comprimido e nativo para consultas SQL via Athena. Este job faz essa conversão garantindo schema consistente e particionamento correto por ano.

## Conceitos-chave

- **SOR (System of Record)** — camada de dados brutos. Contém os JSONs exatamente como vieram da API TMDB, sem nenhuma modificação.
- **SOT (Source of Truth)** — camada refinada. Dados convertidos para Parquet, com schema fixo e particionamento, prontos para consulta via SQL.
- **Parquet** — formato de arquivo colunar e comprimido, muito mais eficiente que JSON para análise de dados: ocupa menos espaço em disco e é mais rápido para leitura por ferramentas como Athena e Spark.
- **Glue Catalog** — catálogo centralizado de metadados da AWS. Registra onde cada tabela está no S3 e qual é o seu schema, permitindo consultá-la com SQL via Athena sem precisar especificar o caminho manualmente.

## Como funciona

O job recebe argumentos dinâmicos injetados pela Lambda no momento do disparo (`start_job_run`). O comportamento varia conforme `TABLE_TYPE`:

| `TABLE_TYPE` | Particionamento | Modo de escrita | Aciona Details? |
|---|---|---|---|
| `discover` | Por `year` | `overwrite_partitions` (preserva outros anos) | Sim |
| `genre` | Sem partição | `overwrite` (substitui tudo) | Não |
| `configuration` | Sem partição | `overwrite` | Não |
| `watch_providers_ref` | Sem partição | `overwrite` | Não |
| `now_playing` | Sem partição | `overwrite` (snapshot semanal completo) | Não |

**Fluxo para `discover`:**
1. Lê os argumentos do Glue (`get_parameters_glue`)
2. Lê o JSON do S3 SOR para o ano especificado (`read_from_sor`) — o `overview` já vem em pt-BR nativo do TMDB (buscado pelo `lambda_api` com `language=pt-BR`), sem nenhuma etapa de tradução aqui. `read_from_sor` adiciona `overview_detected_language_pt` (via LLM/OpenRouter — ver `shared_utils.idioma_llm`) e `overview_translated_pt` (booleano puramente derivado, `overview_detected_language_pt == "pt"`, sem nenhuma chamada de tradução) — sinais **puros de diagnóstico**: confirmam se o TMDB de fato devolveu a sinopse em português, ou se caiu silenciosamente para outro idioma quando não tinha tradução. O `glue_agg` usa `overview_detected_language_pt` para decidir se confia no `overview` do discover ou cai para `overview_pt`/`overview_en` do `glue_details`
3. Escreve Parquet na SOT particionado por `year`, modo `overwrite_partitions` (`write_parquet_to_sot`)
4. Aciona Glue Data Quality para a tabela processada (`trigger_glue_job`)
5. Aciona Glue Details para enriquecimento (`trigger_glue_job`)

**Fluxo para tabelas estáticas (genre, configuration, watch_providers_ref):**
1–4 iguais ao discover, sem step 5.
Para `configuration` de TV (países): após ler o JSON, `_add_translation` traduz `english_name` para português via LLM (`translate_text_llm` — ver `shared_utils.traducao_llm`) e grava como coluna `name_pt` na SOT (~250 países), delegando a `shared_utils.traducao.resolve_pt_translation` a detecção de idioma da fonte (`name_detected_language_en`) e do resultado (`name_detected_language_pt`), a cópia direta quando `english_name` já é detectado como `"pt"` (caso raro, já que é sempre nome próprio em inglês — mesma otimização do `glue_details` contra retradução infinita) e o teto de tentativas (`name_translation_attempts`).
Para `configuration` de Movie (idiomas): mesma abordagem — traduz `english_name` dos idiomas para português pelo mesmo serviço e grava como coluna `name_pt` na SOT (~190 idiomas), com as mesmas colunas `name_detected_language_en`/`name_detected_language_pt`/`name_translation_attempts`.

**Cache de tradução:** como `configuration` é regravada por completo a cada execução (`mode="overwrite"`, sem partição) e a Lambda aciona esse job mensalmente, `read_from_sor` lê a tabela `configuration` já gravada na SOT (`read_existing_configuration`) antes de traduzir e reaproveita `name_pt` para os registros cujo `english_name` não mudou desde a última execução — evita retraduzir países/idiomas cujo nome em inglês é idêntico ao já processado (ver `reuse_existing_translation` em `shared_utils.traducao`). Registros novos (chave ausente no histórico) ou com `english_name` alterado são traduzidos normalmente. O mesmo cache também reaproveita `name_detected_language_en`/`name_detected_language_pt` (`reuse_existing_translation` com `detected_language_*_column`), poupando a redetecção por LLM dos nomes inalterados.

**Retradução forçada (backfill):** `backfill_referencias.py` com `BACKFILL_RETRANSLATE=true` (input "Retraduzir tudo" do workflow) chama `read_from_sor(..., force_retranslate=True)`: em `configuration` o texto de `name_pt` do cache é ignorado e todos os nomes são retraduzidos por LLM; só o idioma detectado de `english_name` é reaproveitado, e uma falha do LLM restaura a tradução antiga em vez de gravar o texto em inglês. `genre` e `watch_providers_ref` não traduzem e não são afetadas.

**Cache de idioma (discover):** `read_from_sor` com `table_type="discover"` lê da SOT, via `read_existing_discover`, só as colunas `id`/`overview`/`overview_detected_language_pt` da partição `year` já gravada e copia o idioma detectado dos overviews inalterados (`reuse_detected_language`); só o restante é detectado via LLM, em paralelo (`add_detected_language_column`, `max_workers=10`). A partição continua sendo regravada por completo (`overwrite_partitions`) — o cache só poupa chamadas ao LLM, não muda o resultado. Sem esse cache e em série, a detecção do overview de um ano de filmes (~1000 overviews preenchidos de ~2000 filmes) levava ~19 min por unidade no backfill histórico. **Permissão:** a role do job precisa de `s3:GetObject` nas tabelas lidas (Sid `ReadSotCache` em `glue_etl_sor_sot`, `infra/iam_policies.tf`); sem ela a leitura falha com `AccessDenied`, é capturada por `read_existing_*` e o job degrada para "sem cache" (detecta/traduz tudo) sem avisar.

**Logs de LLM:** `main()` loga ao fim `LLM [Glue ETL — total]` (chamadas por operação e modelo, tokens, custo, `sem mudança`) e, havendo falhas, uma linha WARNING por causa com exemplo (`shared_utils.llm_metrics`), mais o `Balanço '<coluna>'` das traduções de `configuration` (com a chave `iso_*` como id de exemplo das pendentes).

**Fluxo para `now_playing`:**
Igual ao fluxo estático (sem partição, sem acionar Details). Diferencial: `read_from_sor` lê todos os arquivos da pasta `tmdb/now_playing/movie/` de uma vez e deduplica por `id` antes de gravar.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos do Glue job: `MEDIA_TYPE`, `TABLE_TYPE`, `TABLE_NAME`, `DATABASE`, `YEAR` (apenas discover), `END_YEAR`, nomes dos buckets e jobs, `FILMBOT_SECRET_ARN` (secret unificado — usado pelo campo `llm_api_key`, para a tradução de `configuration` via LLM; publicado em `os.environ` dentro de `get_parameters_glue()`, mesmo padrão de `AWS_ACCOUNT_ID`) |
| **Leitura** | S3 SOR — JSON bruto por tipo de tabela e ano |
| **Escrita** | S3 SOT — Parquet particionado (ou não) + registro no Glue Catalog |
| **Aciona** | Glue Data Quality (sempre) + Glue Details (apenas para `TABLE_TYPE=discover`) |

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job (inclui leitura opcional de `YEAR`/`END_YEAR`); publica `AWS_ACCOUNT_ID` e `FILMBOT_SECRET_ARN` em `os.environ` |
| `read_from_sor(bucket, media_type, table_type, year=None, translate_fn=None, s3_bucket_sot=None, table_name=None, detect_fn=None, force_retranslate=False)` | Lê JSON/Parquet da camada SOR; para `discover` adiciona `overview_detected_language_pt` (diagnóstico, via `detect_fn`, default `detect_language_llm`) e `overview_translated_pt` (derivado, sem tradução); para `configuration` adiciona tradução `name_pt` (countries em tv, languages em movie) via `translate_fn` (default `translate_text_llm`), mais `name_detected_language_en`/`name_detected_language_pt`/`name_translation_attempts` via `detect_fn`. Quando `s3_bucket_sot`/`table_name` são informados, lê da SOT o que já foi gravado e usa como cache: para `configuration`, a tabela inteira via `read_existing_configuration` (tradução, `_add_name_pt_countries`/`_add_name_pt_languages`); para `discover`, a partição do ano via `read_existing_discover` (idioma detectado do overview, `_read_discover`). Sem eles, roda sem cache (detecta/traduz tudo) `force_retranslate=True` (só `configuration`, usado pelo `backfill_referencias.py`) ignora o cache de `name_pt` e retraduz tudo por LLM; o Glue ETL de produção não o passa |
| `_add_translation(df, key_column, translate_fn=None, previous_df=None, detect_fn=None, force_retranslate=False)` | Reaproveita `name_pt` de `previous_df` via `reuse_existing_translation` (`shared_utils.traducao`) quando `english_name` não mudou para a mesma `key_column`, antes de traduzir com `max_workers=_TRANSLATE_MAX_WORKERS_LLM` (5 — chamadas de LLM são bem mais lentas que uma API de tradução estruturada; valor inicial conservador, a recalibrar com a duração real do job em produção). O resto do fluxo (detecção de idioma da fonte e do resultado, cópia direta, tradução via `translate_fn`, teto de tentativas) é responsabilidade de `shared_utils.traducao.resolve_pt_translation` — grava `name_detected_language_en`, `name_detected_language_pt`, `name_pt` e `name_translation_attempts` Com `force_retranslate=True` não reaproveita o texto de `name_pt` (só o idioma detectado da fonte, `reuse_detected_language`) e, se o LLM falhar, restaura a tradução antiga (`restore_failed_translations`) |
| `_add_name_pt_countries(df, translate_fn=None, previous_df=None, detect_fn=None, force_retranslate=False)` / `_add_name_pt_languages(df, translate_fn=None, previous_df=None, detect_fn=None, force_retranslate=False)` | Wrappers de `_add_translation` para países (`key_column="iso_3166_1"`) e idiomas (`key_column="iso_639_1"`) |
| `read_existing_configuration(s3_bucket_sot, table_name)` | Lê a tabela `configuration` já gravada na SOT (cache de tradução); retorna `DataFrame` vazio se a tabela ainda não existir (primeira execução) ou a leitura falhar |
| `read_existing_discover(s3_bucket_sot, table_name, year)` | Lê `id`/`overview`/`overview_detected_language_pt` da partição `year` do discover já gravada na SOT (`wr.s3.read_parquet` com `partition_filter`), usadas como cache do idioma detectado em `_read_discover`; retorna `DataFrame` vazio se a partição ainda não existir (primeira execução do ano), não tiver as colunas (schema antigo) ou a leitura falhar por qualquer motivo |
| `_read_discover(s3_bucket_sor, s3_key, year, detect_fn, previous_df=None)` | Lê a pasta inteira do discover (array JSON puro por arquivo), adiciona `year`, remove duplicatas por `id`; com coluna `overview`, reaproveita o idioma já detectado de `previous_df` (`reuse_detected_language`) e detecta o restante em paralelo (`add_detected_language_column(only_missing=True)`), derivando `overview_translated_pt` |
| `write_parquet_to_sot(df, bucket, table_name, database, partition_cols, mode)` | Adiciona `processed_date` (`add_processed_date`, tipo `date`, última coluna, data em `America/Sao_Paulo`) ao DataFrame, escreve Parquet e registra no Glue Catalog via AWS Wrangler. Carimbar aqui é seguro porque a partição/tabela é sempre reconstruída por completo; linhas de partições antigas não reprocessadas ficam com `NULL` (sem backfill) |
| `derive_canonical_name(name)` | Padroniza um nome de plataforma de streaming (ex: "Netflix Standard with Ads" → "Netflix"); usada internamente por `read_from_sor()` |

**Ordem de colunas em `watch_providers_ref`:** após adicionar `canonical_name`, `read_from_sor()` reindexa explicitamente o DataFrame para `provider_id, provider_name, display_priority_br, canonical_name, logo_path` — a mesma ordem declarada em `infra/glue_catalog.tf` para `tb_watch_providers_ref_movie`/`_tv`. Isso é necessário porque o `ParquetHiveSerDe` (serde dessas tabelas) resolve colunas por **posição**, não por nome: sem a reindexação, a ordem natural do DataFrame (colunas do JSON, com `canonical_name` anexada por último) deixaria `logo_path` antes de `canonical_name`, fazendo o Athena ler os valores de uma coluna como se fossem da outra.

## Funções compartilhadas (`shared_utils/`)

Importadas do pacote `shared_utils`, reutilizadas por múltiplos componentes do pipeline:

| Função | Origem | Responsabilidade |
|---|---|---|
| `trigger_glue_job(job_name, **arguments)` | `shared_utils.triggers` | Dispara qualquer job Glue (DQ, Details, AGG) com argumentos dinâmicos |
| `get_resolved_option(args)` | `shared_utils.glue_helpers` | Resolve argumentos do job Glue (`getResolvedOptions`), usada por `get_parameters_glue()` |
| `configure_glue_logging()` | `shared_utils.glue_helpers` | Configura e retorna o `logger` padrão dos jobs Glue |
| `translate_text_llm(text)` | `shared_utils.traducao_llm` | Traduz texto para português via LLM (OpenRouter, `litellm`), com fallback nativo de modelo; default do parâmetro `translate_fn` de `_add_translation` quando não informado |
| `reuse_existing_translation(df, previous_df, source_column, target_column, key_column, detected_language_en_column=None, detected_language_pt_column=None)` | `shared_utils.traducao` | Pré-preenche `name_pt` com o valor já persistido na SOT quando `english_name` não mudou para o mesmo `iso_3166_1`/`iso_639_1` — evita retraduzir países/idiomas sem mudança; com as colunas de idioma informadas, também reaproveita `name_detected_language_en`/`name_detected_language_pt`. Compartilhada com `glue_details` (que usa `key_column="id"`, default) |
| `resolve_pt_translation(df, source_column, target_column, detected_language_en_column, detected_language_pt_column, translation_attempts_column, detect_fn, translate_fn, max_workers, max_attempts)` | `shared_utils.traducao` | Detecta o idioma da fonte e do resultado (só onde ainda vazios), copia a fonte direto quando ela já é `"pt"`, traduz as linhas elegíveis e incrementa o contador de tentativas. Usada por `_add_translation` (`name_pt`); compartilhada com `glue_details` e `scripts/backfill_traducao.py` |
| `detect_language_llm(text)` | `shared_utils.idioma_llm` | Detecção de idioma via LLM (OpenRouter), devolvendo o código ISO 639-1 ou `None`; default do parâmetro `detect_fn` quando não informado |
| `add_detected_language_column(df, source_column, target_column, detect_fn=None, only_missing=False, max_workers=10)` | `shared_utils.idioma` | Aplica `detect_fn` a cada valor de `source_column` em paralelo (`detect_in_parallel`, com progresso e resumo de falhas), gravando o idioma detectado em `target_column` — usada diretamente para `overview_detected_language_pt` (discover, com `only_missing=True` depois do cache de `reuse_detected_language`) |
| `reuse_detected_language(df, previous_df, text_column, language_column, key_column="id")` | `shared_utils.traducao` | Copia o idioma já detectado de `previous_df` quando o texto não mudou (só valores não nulos); usada por `_read_discover` para `overview_detected_language_pt` |

## Tecnologias

- **awswrangler** — leitura/escrita de Parquet no S3 e registro no Glue Catalog
- **pandas** — manipulação de DataFrames
- **boto3** — acionamento de outros jobs Glue e leitura do secret unificado (Secrets Manager)
- **shared_utils** — logging, resolução de argumentos do Glue e tradução compartilhados entre módulos do pipeline
- **litellm** — tradução e detecção de idioma via LLM (OpenRouter), para `overview_detected_language_pt` (discover) e `name_pt`/`name_detected_language_en`/`name_detected_language_pt` (configuration); o `tenacity` também fica em `requirements.txt` porque o `litellm` só o importa ao retentar (`num_retries`) e não o declara — sem ele, todo erro transitório (429/timeout) vira falha na hora
- **Glue runtime** — execução do job no ambiente AWS Glue
