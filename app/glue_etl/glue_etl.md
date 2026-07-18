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
2. Lê o JSON do S3 SOR para o ano especificado (`read_from_sor`) — o `overview` já vem em pt-BR nativo do TMDB (buscado pelo `lambda_api` com `language=pt-BR`), sem nenhuma etapa de tradução aqui. `read_from_sor` adiciona `overview_idioma_detectado` (via `langdetect`, com fallback AWS Comprehend — ver `shared_utils.idioma`), um sinal **puro de diagnóstico**: confirma se o TMDB de fato devolveu a sinopse em português, ou se caiu silenciosamente para outro idioma quando não tinha tradução. O `glue_agg` usa essa coluna para decidir se confia no `overview` do discover ou cai para `overview_pt`/`overview_en` do `glue_details`. Não existe `overview_traduzido_pt_br` aqui — não há tradução para sinalizar
3. Escreve Parquet na SOT particionado por `year`, modo `overwrite_partitions` (`write_parquet_to_sot`)
4. Aciona Glue Data Quality para a tabela processada (`trigger_glue_job`)
5. Aciona Glue Details para enriquecimento (`trigger_glue_job`)

**Fluxo para tabelas estáticas (genre, configuration, watch_providers_ref):**
1–4 iguais ao discover, sem step 5.
Para `configuration` de TV (países): após ler o JSON, detecta o idioma de `english_name` (`name_idioma_detectado` — mesma detecção do discover) e traduz para português via `resolve_translate_fn(TRANSLATE_PROVIDER)` — `"google"` (default deste job) ou `"aws"` — e grava como coluna `name_pt` na SOT (~250 países). O serviço não escolhido é usado automaticamente como fallback caso o primário falhe. Quando `english_name` já é detectado como `"pt"` (caso raro, já que é sempre nome próprio em inglês), copia direto sem chamar tradução — mesma otimização do `glue_details` contra retradução infinita — e `name_traduzido_pt_br` fecha o estado final.
Para `configuration` de Movie (idiomas): mesma abordagem — detecta idioma, traduz `english_name` dos idiomas para português pelo mesmo serviço e grava como coluna `name_pt` na SOT (~190 idiomas), com as mesmas colunas `name_idioma_detectado`/`name_traduzido_pt_br`.
**Cache de tradução:** como `configuration` é regravada por completo a cada execução (`mode="overwrite"`, sem partição) e a Lambda aciona esse job mensalmente, `read_from_sor` lê a tabela `configuration` já gravada na SOT (`read_existing_configuration`) antes de traduzir e reaproveita `name_pt` para os registros cujo `english_name` não mudou desde a última execução — evita retraduzir países/idiomas cujo nome em inglês é idêntico ao já processado (ver `reuse_existing_translation` em `shared_utils.traducao`). Registros novos (chave ausente no histórico) ou com `english_name` alterado são traduzidos normalmente.

**Fluxo para `now_playing`:**
Igual ao fluxo estático (sem partição, sem acionar Details). Diferencial: `read_from_sor` lê todos os arquivos da pasta `tmdb/now_playing/movie/` de uma vez e deduplica por `id` antes de gravar.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos do Glue job: `MEDIA_TYPE`, `TABLE_TYPE`, `TABLE_NAME`, `DATABASE`, `YEAR` (apenas discover), `END_YEAR`, nomes dos buckets e jobs, `TRANSLATE_PROVIDER` (opcional, default `"google"` — serviço de tradução primário usado em `configuration`; o outro é usado automaticamente como fallback — ver `resolve_translate_fn` em `shared_utils.traducao`) |
| **Leitura** | S3 SOR — JSON bruto por tipo de tabela e ano |
| **Escrita** | S3 SOT — Parquet particionado (ou não) + registro no Glue Catalog |
| **Aciona** | Glue Data Quality (sempre) + Glue Details (apenas para `TABLE_TYPE=discover`, repassando `TRANSLATE_PROVIDER`) |

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job (inclui leitura opcional de `YEAR`/`END_YEAR` e `TRANSLATE_PROVIDER`) |
| `read_from_sor(bucket, media_type, table_type, year=None, translate_fn=None, s3_bucket_sot=None, table_name=None, detect_fn=None)` | Lê JSON/Parquet da camada SOR; para `discover` adiciona `overview_idioma_detectado` (diagnóstico, via `detect_fn`); para `configuration` adiciona tradução `name_pt` (countries em tv, languages em movie) via `translate_fn`, mais `name_idioma_detectado`/`name_traduzido_pt_br` via `detect_fn`. Quando `s3_bucket_sot`/`table_name` são informados (só relevante para `configuration`), lê a tabela já gravada na SOT via `read_existing_configuration` e usa como cache de tradução (`_add_name_pt_countries`/`_add_name_pt_languages`) |
| `_add_translation(df, description, key_column, translate_fn=None, previous_df=None, detect_fn=None)` | Detecta `name_idioma_detectado` (via `shared_utils.idioma.add_detected_language_column`) antes de tudo. Traduz `english_name → name_pt` sequencialmente (sem `ThreadPoolExecutor` — volumes pequenos, ~250 itens). Antes de traduzir, reaproveita `name_pt` de `previous_df` via `reuse_existing_translation` (`shared_utils.traducao`) quando `english_name` não mudou para a mesma `key_column`; para o que sobrar com idioma já detectado como `"pt"`, copia `english_name` direto (sem tradução); só traduz os registros restantes. Grava `name_traduzido_pt_br` no fim via `shared_utils.traducao.is_translated_mask` |
| `_add_name_pt_countries(df, translate_fn=None, previous_df=None, detect_fn=None)` / `_add_name_pt_languages(df, translate_fn=None, previous_df=None, detect_fn=None)` | Wrappers de `_add_translation` para países (`key_column="iso_3166_1"`) e idiomas (`key_column="iso_639_1"`) |
| `read_existing_configuration(s3_bucket_sot, table_name)` | Lê a tabela `configuration` já gravada na SOT (cache de tradução); retorna `DataFrame` vazio se a tabela ainda não existir (primeira execução) ou a leitura falhar |
| `write_parquet_to_sot(df, bucket, table_name, database, partition_cols, mode)` | Escreve Parquet e registra no Glue Catalog via AWS Wrangler |
| `derive_canonical_name(name)` | Padroniza um nome de plataforma de streaming (ex: "Netflix Standard with Ads" → "Netflix"); usada internamente por `read_from_sor()` |

## Funções compartilhadas (`shared_utils/`)

Importadas do pacote `shared_utils`, reutilizadas por múltiplos componentes do pipeline:

| Função | Origem | Responsabilidade |
|---|---|---|
| `trigger_glue_job(job_name, **arguments)` | `shared_utils.triggers` | Dispara qualquer job Glue (DQ, Details, AGG) com argumentos dinâmicos |
| `get_resolved_option(args)` | `shared_utils.glue_helpers` | Resolve argumentos do job Glue (`getResolvedOptions`), usada por `get_parameters_glue()` |
| `configure_glue_logging()` | `shared_utils.glue_helpers` | Configura e retorna o `logger` padrão dos jobs Glue |
| `translate_text(texto, contexto)` | `shared_utils.traducao_google` (reexportada em `shared_utils.traducao`) | Traduz texto via Google Translate; default do parâmetro `translate_fn` de `_add_translation` quando não informado |
| `translate_text_aws(texto, region)` | `shared_utils.traducao_aws` (reexportada em `shared_utils.traducao`) | Traduz texto via AWS Translate; usado automaticamente como fallback capado por caracteres do serviço default deste job (`TRANSLATE_PROVIDER="google"`) |
| `resolve_translate_fn(provider, translate_google=translate_text, translate_aws=translate_text_aws, aws_fallback_max_chars=6_000)` | `shared_utils.traducao` | Resolve `TRANSLATE_PROVIDER` para uma função composta primário+fallback; montada uma vez em `main()` e passada a `read_from_sor`, e repassada ao acionar `glue_details` |
| `reuse_existing_translation(df, previous_df, source_column, target_column, key_column)` | `shared_utils.traducao` | Pré-preenche `name_pt` com o valor já persistido na SOT quando `english_name` não mudou para o mesmo `iso_3166_1`/`iso_639_1` — evita retraduzir países/idiomas sem mudança. Compartilhada com `glue_details` (que usa `key_column="id"`, default) |
| `is_translated_mask(df, source_column, target_column, already_native_mask=None)` | `shared_utils.traducao` | Grava `name_traduzido_pt_br`: `name_pt` preenchida e (diferente de `english_name` **ou** já detectado como `"pt"`) |
| `detect_language_langdetect(text)` | `shared_utils.idioma_langdetect` | Detecção de idioma local via `langdetect` (offline, sem custo) |
| `detect_language_aws(text, region="us-east-1")` | `shared_utils.idioma_aws` | Detecção de idioma via AWS Comprehend — fallback do `langdetect`. Mesma permissão IAM já concedida ao AWS Translate |
| `resolve_detect_language_fn(detect_local=detect_language_langdetect, detect_aws=detect_language_aws, aws_fallback_max_chars=6_000)` | `shared_utils.idioma` | Resolve a função composta de detecção: local primeiro, AWS Comprehend como fallback capado por caracteres se o local falhar; montada uma vez em `main()` e passada a `read_from_sor` |
| `add_detected_language_column(df, source_column, target_column, detect_fn=None)` | `shared_utils.idioma` | Aplica `detect_fn` a cada valor de `source_column`, gravando o idioma detectado em `target_column` — usada tanto para `overview_idioma_detectado` (discover) quanto `name_idioma_detectado` (configuration) |

## Tecnologias

- **awswrangler** — leitura/escrita de Parquet no S3 e registro no Glue Catalog
- **pandas** — manipulação de DataFrames
- **boto3** — acionamento de outros jobs Glue
- **shared_utils** — logging, resolução de argumentos do Glue e tradução compartilhados entre módulos do pipeline
- **langdetect** — detecção local de idioma para `overview_idioma_detectado` (discover) e `name_idioma_detectado` (configuration)
- **AWS Comprehend** (`DetectDominantLanguage`) — fallback do `langdetect`
- **Glue runtime** — execução do job no ambiente AWS Glue
