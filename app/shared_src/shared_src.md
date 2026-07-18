# Shared Src — Funções compartilhadas entre componentes do pipeline

## Objetivo

Pacote Python reutilizado por múltiplos jobs Glue e pela Lambda API. Evita duplicação de código entre componentes que precisam das mesmas funções.

## Estrutura

```
app/shared_src/
├── shared_src.md          ← este arquivo
└── shared_utils/          ← pacote Python (importado como shared_utils)
    ├── __init__.py
    ├── api_client.py      ← acesso a APIs externas (retry, Secrets Manager)
    ├── glue_helpers.py    ← utilitários compartilhados de jobs Glue
    ├── traducao.py        ← orquestração de tradução: elegibilidade, cache, paralelismo, escolha do serviço
    ├── traducao_google.py ← tradução via Google Translate (deep_translator)
    ├── traducao_aws.py    ← tradução via AWS Translate (boto3)
    ├── idioma.py          ← orquestração de detecção de idioma: local + fallback AWS, aplicação em coluna
    ├── idioma_langdetect.py ← detecção de idioma local (langdetect, offline, sem custo)
    ├── idioma_aws.py      ← detecção de idioma via AWS Comprehend (boto3)
    └── triggers.py        ← disparo genérico de jobs Glue
```

## Funções

### `shared_utils/api_client.py`

| Função | Responsabilidade |
|---|---|
| `api_get(url, params, max_retries)` | GET com retry/backoff exponencial para lidar com rate limits de APIs (429, 5xx) |
| `get_api_secret(secret_arn, key_name)` | Busca um segredo no AWS Secrets Manager |

### `shared_utils/glue_helpers.py`

| Função | Responsabilidade |
|---|---|
| `get_resolved_option(args)` | Wrapper de `getResolvedOptions` — converte lista de nomes em dicionário nome→valor |
| `configure_glue_logging()` | Configura logging padrão para jobs Glue (stdout, INFO, formato com timestamp) e retorna o logger raiz |

### `shared_utils/traducao_google.py`

| Função | Responsabilidade |
|---|---|
| `translate_text(text, context)` | Traduz texto para português via Google Translate com detecção automática do idioma de origem (`source="auto"`), com backoff entre tentativas (mesmo padrão de `api_get`); uma exceção usa o orçamento completo de 5 tentativas (tende a ser transitório — rede, rate limit), enquanto um resultado idêntico ao original sem exceção desiste em só 2 (normalmente indica que não há o que traduzir — nome próprio, termo emprestado — não bloqueio); retorna o original se as tentativas se esgotarem, para não interromper o job |

### `shared_utils/traducao_aws.py`

| Função | Responsabilidade |
|---|---|
| `translate_text_aws(text, region="us-east-1")` | Chama `boto3.client("translate").translate_text(..., SourceLanguageCode="auto", TargetLanguageCode="pt")`. Sem retry manual (API oficial, sem o bloqueio silencioso do endpoint não-oficial do Google Translate; boto3 já reaplica retry em erros transitórios). Nunca lança exceção — devolve o texto original em caso de erro. **`region` default é `us-east-1`, não `sa-east-1`** (região principal do pipeline) — AWS Translate não está disponível em São Paulo; a chamada é stateless, então usar outra região não tem custo de localidade |

### `shared_utils/traducao.py`

Fachada de orquestração — reexporta `translate_text` e `translate_text_aws` dos dois módulos acima (nenhum
chamador precisa importar diretamente de `traducao_google`/`traducao_aws`), além das funções genéricas que
recebem qualquer `translate_fn` como parâmetro:

| Função | Responsabilidade |
|---|---|
| `resolve_translate_fn(provider, translate_google=translate_text, translate_aws=translate_text_aws, aws_fallback_max_chars=6_000)` | Resolve `"google"`/`"aws"` para uma função **composta primário+fallback**: o provider escolhido é tentado primeiro; se falhar (resultado igual ao texto original, mesmo sinal usado em `translate_pending_column`), o outro serviço é tentado automaticamente. `"google"` (default em todo o pipeline — `glue_details`/`glue_etl` via EventBridge e os backfills manuais) usa AWS Translate como fallback, capado por `aws_fallback_max_chars` caracteres nesta execução (proteção de custo — AWS Translate é pago por caractere; o default de 6.000 mantém o caminho automático abaixo de US$1/mês mesmo no pior caso, a US$15/milhão de caracteres, considerando as ~11 execuções/mês do Glue Details via EventBridge). `"aws"` (escolha explícita, ex.: testar tradução real da AWS num período curto) usa Google como fallback, sem limite (grátis). `translate_google`/`translate_aws` são parâmetros (mesmo motivo de `translate_in_parallel`) para que o chamador passe sua própria referência local — a mesma que seus testes fazem mock. Levanta `ValueError` para qualquer outro valor de `provider` |
| `translate_in_parallel(values, translate_fn, max_workers)` | Aplica `translate_fn` a cada item de `values` em paralelo via `ThreadPoolExecutor`; recebe a função de tradução como parâmetro (em vez de chamar `translate_text` diretamente) para que os chamadores continuem passando sua própria referência local, preservando os mocks de teste existentes em `glue_details` e `backfill_traducao.py` |
| `translate_pending_column(df, source_column, target_column, eligible_mask, translate_fn, max_workers)` | Orquestra a tradução de `source_column` → `target_column` para os registros elegíveis ainda pendentes: pula registros já traduzidos via `is_translated_mask` (nativo do TMDB, run anterior ou fonte já detectada no idioma-alvo), retenta os que ficaram iguais à fonte (fallback de uma tradução que falhou — ver `translate_text`/`translate_text_aws`), grava o resultado via `translate_in_parallel` e devolve a contagem de sucesso. Substitui a lógica que antes estava duplicada (com pequenas divergências) em `glue_details/src/utils.py` e `scripts/backfill_traducao.py` |
| `is_translated_mask(df, source_column, target_column, already_native_mask=None)` | Máscara de registros "já traduzidos": `target_column` preenchida e diferente de `source_column`. Com `already_native_mask` informado, também conta como traduzido quando `target == source` mas a máscara é `True` (caso "fonte já era pt-BR, copiada direto sem chamar tradução" — ver `shared_utils.idioma`). Usada internamente por `translate_pending_column` (sem o parâmetro extra) e por `glue_details`/`glue_etl`/`backfill_traducao.py` para gravar `<campo>_traduzido_pt_br` |
| `make_capped_fallback(fallback_fn, max_chars, on_over_budget)` | Envolve `fallback_fn` com um orçamento de caracteres thread-safe (contador mutável + `threading.Lock`); textos que excederiam o restante recebem `on_over_budget(text)` em vez de `fallback_fn(text)`. Compartilhada entre `resolve_translate_fn` (fallback AWS Translate, `on_over_budget=lambda text: text`) e `shared_utils.idioma.resolve_detect_language_fn` (fallback AWS Comprehend, `on_over_budget=lambda text: None`) |
| `reuse_existing_translation(df, previous_df, source_column, target_column, key_column="id")` | Pré-preenche `target_column` com a tradução já persistida (`previous_df`) quando `source_column` não mudou para o mesmo `key_column` — evita retraduzir texto idêntico ao da última execução. Não sobrescreve valor já preenchido (prioridade da tradução nativa do TMDB); a checagem final de "já traduzido" continua em `translate_pending_column` ou na máscara do chamador. Compartilhada entre `glue_details` (`key_column="id"`, default) e `glue_etl` (`key_column="iso_3166_1"`/`"iso_639_1"` para a tabela `configuration`) |
| `eligible_overview_pt(df)` | Mask de candidatos à tradução de overview: `overview_en` não-vazio **e** `overview_idioma_detectado` (quando presente) diferente de `"pt"` — evita reenviar ao Google/AWS um texto já confirmado em português (ver `shared_utils.idioma`), prevenindo a retradução infinita de fontes sem tradução nativa do TMDB. `original_language` não é critério (é o idioma de produção original do título, não o idioma do texto retornado pela API — não garante que `overview_en` já esteja em português). Compartilhada entre `glue_details` e `scripts/backfill_traducao.py` |
| `eligible_tagline_pt(df)` | Mask de candidatos à tradução de tagline: campo não-vazio e `tagline_idioma_detectado` diferente de `"pt"` (mesmo raciocínio de `eligible_overview_pt`). Compartilhada entre `glue_details` e `scripts/backfill_traducao.py` |
| `eligible_keywords_pt(df)` | Mask de candidatos à tradução de keywords: campo não-vazio e `keywords_idioma_detectado` diferente de `"pt"` (mesmo raciocínio de `eligible_overview_pt`; TMDB não localiza keywords por idioma, então nem títulos com `original_language == 'pt'` têm keywords em português nativamente). Compartilhada entre `glue_details` e `scripts/backfill_traducao.py` |

### `shared_utils/idioma_langdetect.py`

| Função | Responsabilidade |
|---|---|
| `detect_language_langdetect(text)` | Detecta o idioma (ISO 639-1) via `langdetect`, offline e sem custo. `DetectorFactory.seed = 0` fixado no import do módulo — sem isso, a amostragem probabilística de n-gramas do `langdetect` pode devolver idiomas diferentes entre execuções para o mesmo texto. Nunca lança exceção: devolve `None` para texto vazio, `LangDetectException` (comum em textos curtos/sem sinal linguístico, ex.: keywords) ou qualquer erro inesperado |

### `shared_utils/idioma_aws.py`

| Função | Responsabilidade |
|---|---|
| `detect_language_aws(text, region="us-east-1")` | Detecta o idioma via AWS Comprehend (`DetectDominantLanguage`), devolvendo o `LanguageCode` de maior `Score`. Usada como fallback do `langdetect` — não introduz permissão IAM nova, já que a role dos jobs que usam AWS Translate já tem `comprehend:DetectDominantLanguage` (concedida porque o próprio AWS Translate aciona o Comprehend internamente via `SourceLanguageCode="auto"`). Nunca lança exceção — devolve `None` em qualquer erro. `region` default `us-east-1` pelo mesmo motivo de `translate_text_aws` (Comprehend não está em `sa-east-1`) |

### `shared_utils/idioma.py`

Fachada de orquestração de detecção de idioma — papel equivalente ao de `traducao.py` para tradução: reexporta
`detect_language_langdetect`/`detect_language_aws` e adiciona a lógica de composição/DataFrame:

| Função | Responsabilidade |
|---|---|
| `resolve_detect_language_fn(detect_local=detect_language_langdetect, detect_aws=detect_language_aws, aws_fallback_max_chars=6_000)` | Resolve a função de detecção composta: local (`langdetect`) primeiro; se devolver `None`, cai para AWS Comprehend, capado por `aws_fallback_max_chars` caracteres (via `make_capped_fallback` de `traducao.py`) — rede de segurança de custo, já que o Comprehend cobra por caractere processado. `detect_local`/`detect_aws` são parâmetros pelo mesmo motivo de `resolve_translate_fn` |
| `add_detected_language_column(df, source_column, target_column, detect_fn=None)` | Aplica `detect_fn` (default `resolve_detect_language_fn()`) a cada valor de `source_column`, tratando nulo/NaN como string vazia, e grava o resultado em `target_column`. Sem `ThreadPoolExecutor` — a maioria das chamadas é local/CPU-bound; o fallback AWS é raro o bastante (só quando o local falha) para não justificar paralelismo. Usada por `glue_details` (`overview_en`/`tagline`/`keywords`), `glue_etl` (`english_name` em configuration, `overview` em discover) e `scripts/backfill_traducao.py` |

### `shared_utils/triggers.py`

| Função | Responsabilidade |
|---|---|
| `trigger_glue_job(job_name, **arguments)` | Dispara qualquer job Glue (fire-and-forget), convertendo kwargs para o formato `--CHAVE` do Glue |

## Uso nos componentes

| Componente | Funções importadas |
|---|---|
| `lambda_api` | `api_get`, `get_api_secret`, `trigger_glue_job` |
| `glue_details` | `api_get`, `get_api_secret`, `get_resolved_option`, `translate_text`, `translate_text_aws`, `translate_pending_column`, `reuse_existing_translation`, `resolve_translate_fn`, `eligible_overview_pt`, `eligible_tagline_pt`, `eligible_keywords_pt`, `is_translated_mask`, `add_detected_language_column`, `resolve_detect_language_fn`, `detect_language_langdetect`, `detect_language_aws`, `trigger_glue_job` |
| `glue_etl` | `get_resolved_option`, `translate_text`, `translate_text_aws`, `reuse_existing_translation`, `resolve_translate_fn`, `is_translated_mask`, `add_detected_language_column`, `resolve_detect_language_fn`, `detect_language_langdetect`, `detect_language_aws`, `trigger_glue_job` |
| `scripts/backfill_traducao.py` | `translate_text`, `translate_text_aws`, `translate_pending_column`, `resolve_translate_fn`, `eligible_overview_pt`, `eligible_tagline_pt`, `eligible_keywords_pt`, `is_translated_mask`, `add_detected_language_column`, `resolve_detect_language_fn`, `detect_language_langdetect`, `detect_language_aws` |
| `glue_agg` | `get_resolved_option`, `trigger_glue_job` |
| `glue_agg/main` | `configure_glue_logging` |
| `glue_etl/main` | `configure_glue_logging` |
| `glue_data_quality/main` | `configure_glue_logging` |
| `glue_details/main` | `configure_glue_logging` |

## Deploy

- **Glue jobs**: empacotado como wheel (`tmdb_shared-0.0.0-py3-none-any.whl`) via `build_glue_wheel.py --package shared_utils` e referenciado no `--extra-py-files` de cada job
- **Lambda**: copiado para dentro do zip via `build_lambda_package.py --shared`
- **Terraform**: build e upload em `shared_src.tf`, paths em `locals.tf`
