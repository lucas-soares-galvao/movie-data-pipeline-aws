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
| `resolve_translate_fn(provider, translate_google=translate_text, translate_aws=translate_text_aws, aws_fallback_max_chars=6_000)` | Resolve `"google"`/`"aws"` para uma função **composta primário+fallback**: o provider escolhido é tentado primeiro; se falhar (resultado igual ao texto original), o outro serviço é tentado automaticamente. `"google"` (default em todo o pipeline — `glue_details`/`glue_etl` via EventBridge e os backfills manuais) usa AWS Translate como fallback, capado por `aws_fallback_max_chars` caracteres nesta execução (proteção de custo — AWS Translate é pago por caractere; o default de 6.000 mantém o caminho automático abaixo de US$1/mês mesmo no pior caso, a US$15/milhão de caracteres, considerando as ~11 execuções/mês do Glue Details via EventBridge). `"aws"` (escolha explícita, ex.: testar tradução real da AWS num período curto) usa Google como fallback, sem limite (grátis). `translate_google`/`translate_aws` são parâmetros (mesmo motivo de `translate_in_parallel`) para que o chamador passe sua própria referência local — a mesma que seus testes fazem mock. Levanta `ValueError` para qualquer outro valor de `provider` |
| `translate_in_parallel(values, translate_fn, max_workers)` | Aplica `translate_fn` a cada item de `values` em paralelo via `ThreadPoolExecutor`; recebe a função de tradução como parâmetro (em vez de chamar `translate_text` diretamente) para que os chamadores continuem passando sua própria referência local, preservando os mocks de teste existentes em `glue_details` e `backfill_traducao.py` |
| `resolve_pt_translation(df, source_column, target_column, detected_language_en_column, detected_language_pt_column, translation_attempts_column, detect_fn, translate_fn, max_workers=10, max_attempts=3, needs_translation_column=None)` | Sincroniza `target_column` (já inicializada pelo chamador — nativo do TMDB, cache reaproveitado ou vazia) com `source_column`: detecta `detected_language_en_column`/`detected_language_pt_column` (só onde ainda vazios — não recalcula o que já foi detectado em execuções anteriores), copia a fonte direto quando ela já é `"pt"` (sem chamar tradutor), traduz as linhas elegíveis (fonte preenchida, `detected_language_pt_column != "pt"`, `translation_attempts_column < max_attempts`) via `translate_in_parallel`, incrementa `translation_attempts_column` e redetecta `detected_language_pt_column` só nas linhas recém-traduzidas. Basear a elegibilidade no idioma real do **resultado** (em vez de comparar string com a fonte, heurística antiga) evita tanto retraduzir o que já está correto quanto deixar uma mistradução silenciosa (resultado diferente da fonte, mas em outro idioma) marcada como concluída para sempre; `translation_attempts_column` evita retry infinito de conteúdo genuinamente não traduzível (nomes próprios, termos curtos). Se `needs_translation_column` for informado, grava nela um booleano com "fonte preenchida E `detected_language_pt_column != 'pt'`" — mesmo critério da elegibilidade, mas **sem** o teto de tentativas: reflete se o campo, como está agora, ainda não está em português, mesmo que o pipeline já tenha desistido de retentar essa linha; `None` (default) não cria a coluna. Devolve `(df, quantidade traduzida com sucesso)`. Usada por `glue_details` e `scripts/backfill_traducao.py` (passando `needs_translation_column` para `overview`/`tagline`/`keywords`) e por `glue_etl` (`name_pt` de países/idiomas, sem `needs_translation_column`) |
| `make_capped_fallback(fallback_fn, max_chars, on_over_budget)` | Envolve `fallback_fn` com um orçamento de caracteres thread-safe (contador mutável + `threading.Lock`); textos que excederiam o restante recebem `on_over_budget(text)` em vez de `fallback_fn(text)`. Compartilhada entre `resolve_translate_fn` (fallback AWS Translate, `on_over_budget=lambda text: text`) e `shared_utils.idioma.resolve_detect_language_fn` (fallback AWS Comprehend, `on_over_budget=lambda text: None`) |
| `reuse_existing_translation(df, previous_df, source_column, target_column, key_column="id")` | Pré-preenche `target_column` com a tradução já persistida (`previous_df`) quando `source_column` não mudou para o mesmo `key_column` — evita retraduzir texto idêntico ao da última execução. Não sobrescreve valor já preenchido (prioridade da tradução nativa do TMDB); a checagem final de "já traduzido" continua em `resolve_pt_translation`. Compartilhada entre `glue_details` (`key_column="id"`, default) e `glue_etl` (`key_column="iso_3166_1"`/`"iso_639_1"` para a tabela `configuration`) |
| `LEGACY_TRANSLATION_COLUMNS` (constante) | Lista das colunas `overview`/`tagline`/`keywords` com nomenclatura pré-rename (`*_idioma_detectado_en/pt`, `*_tentativas_traducao`, `*_precisa_traducao`) — registros lidos de partições gravadas antes da padronização de identificadores para inglês (ver CLAUDE.md) ainda carregam essas colunas. Como `resolve_pt_translation` só *adiciona* as colunas novas (nunca remove as antigas) e o awswrangler sincroniza o schema do Glue Catalog com as colunas do DataFrame gravado, deixar essas colunas passarem adiante reintroduz o schema antigo (com dados stale em pt-BR) na tabela. Usada por `glue_details.collect_and_write_details` e `scripts/backfill_traducao.py._backfill_year` para descartar essas colunas antes de escrever |

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
| `add_detected_language_column(df, source_column, target_column, detect_fn=None, only_missing=False)` | Aplica `detect_fn` (default `resolve_detect_language_fn()`) a cada valor de `source_column`, tratando nulo/NaN como string vazia, e grava o resultado em `target_column`. Com `only_missing=True`, só detecta onde `target_column` ainda está vazia/nula — preserva valores já calculados em execuções anteriores (usado internamente por `resolve_pt_translation`, em `traducao.py`, para evitar recomputar detecção à toa em reruns). Sem `ThreadPoolExecutor` — a maioria das chamadas é local/CPU-bound; o fallback AWS é raro o bastante (só quando o local falha) para não justificar paralelismo. Usada diretamente por `glue_etl` (`overview` em discover, sem `only_missing` — a partição é sempre reconstruída do zero, não há o que preservar) |

### `shared_utils/triggers.py`

| Função | Responsabilidade |
|---|---|
| `trigger_glue_job(job_name, **arguments)` | Dispara qualquer job Glue (fire-and-forget), convertendo kwargs para o formato `--CHAVE` do Glue |

## Uso nos componentes

| Componente | Funções importadas |
|---|---|
| `lambda_api` | `api_get`, `get_api_secret`, `trigger_glue_job` |
| `glue_details` | `api_get`, `get_api_secret`, `get_resolved_option`, `translate_text`, `translate_text_aws`, `resolve_pt_translation`, `reuse_existing_translation`, `resolve_translate_fn`, `resolve_detect_language_fn`, `detect_language_langdetect`, `detect_language_aws`, `trigger_glue_job` |
| `glue_etl` | `get_resolved_option`, `translate_text`, `translate_text_aws`, `resolve_pt_translation`, `reuse_existing_translation`, `resolve_translate_fn`, `add_detected_language_column`, `resolve_detect_language_fn`, `detect_language_langdetect`, `detect_language_aws`, `trigger_glue_job` |
| `scripts/backfill_traducao.py` | `translate_text`, `translate_text_aws`, `resolve_pt_translation`, `resolve_translate_fn`, `resolve_detect_language_fn`, `detect_language_langdetect`, `detect_language_aws` |
| `glue_agg` | `get_resolved_option`, `trigger_glue_job` |
| `glue_agg/main` | `configure_glue_logging` |
| `glue_etl/main` | `configure_glue_logging` |
| `glue_data_quality/main` | `configure_glue_logging` |
| `glue_details/main` | `configure_glue_logging` |

## Deploy

- **Glue jobs**: empacotado como wheel (`tmdb_shared-0.0.0-py3-none-any.whl`) via `build_glue_wheel.py --package shared_utils` e referenciado no `--extra-py-files` de cada job
- **Lambda**: copiado para dentro do zip via `build_lambda_package.py --shared`
- **Terraform**: build e upload em `shared_src.tf`, paths em `locals.tf`
