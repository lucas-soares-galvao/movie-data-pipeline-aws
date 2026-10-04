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
    ├── gmail_helpers.py   ← credenciais e envio de e-mail via Gmail/SMTP
    ├── llm_client.py      ← carregamento compartilhado da chave de API do LLM (OpenRouter)
    ├── secret_redaction.py ← mascaramento de segredos (api_key do TMDB etc.) em logs e exceções
    ├── llm_metrics.py     ← uso do LLM (chamadas, falhas por causa, modelo, tokens, custo) e balanço de tradução, para os logs
    ├── traducao.py        ← orquestração de tradução: elegibilidade, cache, paralelismo
    ├── traducao_llm.py    ← tradução via LLM (OpenRouter, litellm)
    ├── idioma.py          ← orquestração de detecção de idioma: aplicação em coluna de DataFrame
    ├── idioma_llm.py      ← detecção de idioma via LLM (OpenRouter, litellm)
    └── triggers.py        ← disparo genérico de jobs Glue
```

## Funções

### `shared_utils/api_client.py`

| Função | Responsabilidade |
|---|---|
| `api_get(url, params, max_retries)` | GET com retry/backoff exponencial para lidar com rate limits de APIs (429, 5xx). As exceções que propaga (`HTTPError` e `ConnectionError`/`Timeout`) saem **sem a chave de API**: a mensagem do `requests` embute a URL completa com a query (`...for url: ...?api_key=...`), e o TMDB recebe a chave como parâmetro de query — por isso `scrub_exception` limpa a exceção antes de logar/propagar. Foi o que vazou num log público do Actions (`logger.warning(f"...: {exc}")`) |
| `get_api_secret(secret_arn, key_name)` | Busca um segredo no AWS Secrets Manager e o registra em `secret_redaction.register_secret`, para ser mascarado por valor em qualquer log/exceção. Instancia o cliente com `connect_timeout`/`read_timeout`/`retries` explícitos (via `botocore.config.Config`) — sem isso, uma chamada sem resposta pode pendurar o chamador (ex.: Lambda `lambda_api`) até o limite de execução |

### `shared_utils/glue_helpers.py`

| Função | Responsabilidade |
|---|---|
| `get_resolved_option(args)` | Wrapper de `getResolvedOptions` — converte lista de nomes em dicionário nome→valor |
| `configure_glue_logging()` | Configura logging padrão para jobs Glue (stdout, INFO, formato com timestamp), instala a máscara de segredos nos handlers (`install_log_redaction`) e retorna o logger raiz |

### `shared_utils/secret_redaction.py`

Mascaramento de segredos em logs e exceções. A API v3 do TMDB recebe a chave como parâmetro de query e as exceções do `requests` embutem a URL completa na mensagem, então qualquer `logger.warning(f"...: {exc}")`, `logger.exception(...)` ou traceback não tratado imprime a chave — num repositório público, no log público do Actions (aconteceu num run de backfill de dev; a chave foi rotacionada e o log apagado). Defesa em camadas: na origem (`scrub_exception`, que também cobre tracebacks que o `logging` não vê, como os do Lambda/Glue), no log (`RedactingFormatter`) e por valor (`register_secret`).

| Função | Responsabilidade |
|---|---|
| `register_secret(value)` | Registra um segredo (e a versão URL-encoded) para ser mascarado onde quer que apareça. Ignora não-string e valores com menos de 8 caracteres (mascarariam trechos comuns). Chamada por `get_api_secret` e `load_llm_api_key` |
| `redact(text)` | Troca por `***` os segredos registrados e padrões conhecidos que funcionam mesmo sem registro: `api_key=`/`access_token=` (query), `Bearer <token>`, chaves OpenRouter `sk-or-…` e Access Key IDs AWS (`AKIA…`/`ASIA…`) |
| `scrub_exception(exc)` | Limpa `exc.args` com `redact` e **corta a cadeia** `__cause__`/`__context__` (o traceback encadeado imprimiria a mensagem original). Uso: `raise scrub_exception(exc)` dentro do próprio `except` |
| `RedactingFormatter(inner=None)` | Formatter que envolve outro e aplica `redact` ao texto final (mensagem **e** traceback) |
| `install_log_redaction(logger=None)` | Envolve o formatter de cada handler do logger (raiz por padrão) num `RedactingFormatter`, preservando o formato (inclusive o do handler que o runtime do Lambda já instala). Idempotente. Chamada por `configure_glue_logging` (4 jobs Glue), `backfill_shared.setup_logging` (scripts) e `lambda_api/main.py` |

### `shared_utils/gmail_helpers.py`

| Função | Responsabilidade |
|---|---|
| `load_gmail_credentials()` | Busca remetente + senha de app do Gmail: do `FILMBOT_SECRET_ARN` (chaves `gmail_sender_email`/`gmail_app_password`) em produção, ou das env vars `GMAIL_SENDER_EMAIL`/`GMAIL_APP_PASSWORD` como fallback de dev local. Retorna `None` se nenhuma das duas fontes tiver as duas credenciais |
| `send_gmail_email(to_email, subject, body)` | Monta e envia (via Gmail/SMTP, `smtplib.SMTP_SSL` com timeout de 10s) um e-mail de texto puro. Nunca lança exceção — retorna se o envio teve sucesso, para o chamador decidir o que fazer sem que uma falha de e-mail derrube uma ação já concluída (trigger do Cognito, decisão do admin) |

### `shared_utils/llm_client.py`

| Função | Responsabilidade |
|---|---|
| `load_llm_api_key(secret_field, env_var, region="sa-east-1", required=True)` | Registra o valor lido em `secret_redaction.register_secret` (mascarado nos logs) e busca uma chave de API de LLM do secret unificado (`FILMBOT_SECRET_ARN`, em produção) ou de uma variável de ambiente (dev local/CI). `secret_field` indexa qual campo buscar dentro do secret (ex.: `"llm_api_key"`, `"transcription_api_key"`) — diferentes chamadores (agente de recomendação em `lightsail_ia`, tradução via LLM em `traducao_llm.py`/`idioma_llm.py`) reaproveitam o mesmo secret sem duplicar a lógica de busca. `required=True` indexa direto (levanta `KeyError` se ausente); `required=False` usa `.get()` (devolve `None` se ausente, para campo opcional) |

### `shared_utils/llm_metrics.py`

Métricas de uso do LLM e do balanço de tradução, para os logs dos jobs Glue e dos scripts de backfill. Cada chamada de `translate_text_llm`/`detect_language_llm` se registra aqui (sem mudar o retorno nem a política de "nunca lança"); o estado só é acumulado enquanto há um escopo aberto, e tudo é protegido por lock porque as chamadas rodam em `ThreadPoolExecutor`.

| Função | Responsabilidade |
|---|---|
| `llm_usage_scope()` | Context manager que abre um escopo acumulador (`LlmUsage`). Escopos podem ser aninhados (uma unidade dentro do run): cada chamada soma em todos os abertos. Não usa `threading.local` de propósito — as chamadas rodam em threads de um pool criado dentro do escopo, que não herdariam o valor |
| `record_call(operation, response, text, outcome)` / `record_failure(operation, exc, text)` | Registram uma chamada com resposta (`OK`, `NO_CHANGE` = tradução igual ao original, `EMPTY`, `INVALID` = código fora do ISO 639-1) ou uma que lançou exceção (causa = nome da classe, ex.: `ImportError`, com um exemplo truncado — texto 80 caracteres, mensagem 100 — para até 3 exemplos por causa). Modelo, tokens e custo são lidos da resposta, sem nunca lançar: o OpenRouter devolve `usage.cost` em toda resposta, enquanto `litellm.completion_cost()` não conhece os modelos do projeto (`This model isn't mapped yet`); campo ausente vira "modelo indisponível"/"custo indisponível" |
| `log_llm_usage(label, usage)` | Loga `LLM [<rótulo>]: N chamada(s) (tradução x, detecção y) | modelos: … | tokens a in / b out | US$ …` (+ `sem mudança N` quando o LLM devolveu o próprio texto) e, havendo falhas, uma linha WARNING `LLM [<rótulo>] falhas: N de M — <Exceção> n (ex.: '<texto>': <mensagem>)`. Sem chamadas: `LLM [<rótulo>]: nenhuma chamada ao LLM (tudo reaproveitado ou já em português)` |
| `record_balance(label, **counts)` / `log_balance_totals(label, usage)` | Acumulam o balanço por coluna de tradução (`fonte`, `reaproveitadas`, `ja_pt`, `traduzidas`, `ok`, `iguais`, `mantidas`, `pendentes`) — alimentado por `resolve_pt_translation` e `reuse_existing_translation` — e logam uma linha `Balanço total [<execução>] '<coluna>'` com o % reaproveitado |
| `@log_llm_usage_summary(label)` | Decorador para `main()`: loga `LLM [<label> — total]` e o balanço total num `finally`, então também aparece quando a execução sai por exceção ou exit 75 (o gasto já aconteceu). Usado em `glue_etl`, `glue_details` e nos 6 scripts de backfill que usam o LLM |

### `shared_utils/traducao_llm.py`

| Função | Responsabilidade |
|---|---|
| `translate_text_llm(text)` | Traduz texto para português via LLM (OpenRouter, `litellm.completion`), com fallback nativo de modelo (`extra_body.models`) se o primário falhar — mesmo mecanismo já usado em `app/lightsail_ia/src/agent.py`. Modelo primário `TRANSLATE_LLM_MODEL` (default `openrouter/qwen/qwen3.8-flash` — mais barato por token, adequado para tarefa estruturada sem necessidade de raciocínio); fallback `TRANSLATE_LLM_FALLBACK_MODELS` (default `deepseek/deepseek-v4.1-flash`). `reasoning.enabled=False` no `extra_body` desliga chain-of-thought cobrado como output. `temperature=0` reduz (não elimina) variação de saída entre execuções para o mesmo texto — relevante para a idempotência do cache em `reuse_existing_translation`/`resolve_pt_translation`. Nunca lança exceção — texto vazio devolve `""` sem chamar a API; qualquer falha (rede, timeout, 401/402/429 do OpenRouter, resposta vazia) devolve o texto original, logado em DEBUG. Sem forma de detectar "orçamento esgotado" distinta de uma falha comum — esgotamento de crédito no OpenRouter aparece como exceção HTTP igual a qualquer outra. Limpa aspas/cercas de markdown que o modelo eventualmente envolva ao redor do resultado, mesmo com instrução explícita de não fazer isso |

Efeitos de módulo de `traducao_llm.py`: silencia o logger `LiteLLM` (INFO → WARNING; o LiteLLM emitia 2 linhas INFO por chamada, e num lote de ~1000 detecções isso afogava o log do backfill e escondia as linhas do pipeline — WARNING/ERROR continuam passando) e protege o cache da chave de API (`_get_llm_api_key`) com `threading.Lock`, já que tradução e detecção rodam em `ThreadPoolExecutor` (sem o lock, várias threads com o cache vazio leriam o secret uma vez cada). Cada chamada de tradução/detecção é registrada em `llm_metrics` (desfecho, modelo, tokens, custo) — é o que permite separar, no resumo, erro de infraestrutura (ex.: `ImportError` do `tenacity`, 429, timeout) de "o LLM devolveu o próprio texto".

### `shared_utils/idioma_llm.py`

| Função | Responsabilidade |
|---|---|
| `detect_language_llm(text)` | Detecta o idioma (código ISO 639-1) de um texto via LLM (OpenRouter), reaproveitando modelo/chave/fallback de `traducao_llm.py` (import cruzado, mesmo padrão já existente entre `idioma.py`/`traducao.py`). Nunca lança exceção — texto vazio, falha na chamada, ou resposta fora do padrão `^[a-z]{2}$` (regex) devolvem `None`, para não poluir `detected_language_*_column` com um valor inválido — único caso em que o contrato é mais estrito que o de `translate_text_llm` (que aceita qualquer saída de texto livre) |

### `shared_utils/traducao.py`

Orquestração de tradução — elegibilidade, cache e paralelismo (o serviço de tradução em si é `translate_text_llm`, acima):

| Função | Responsabilidade |
|---|---|
| `translate_in_parallel(values, translate_fn, max_workers, progress_label=None)` | Aplica `translate_fn` a cada item de `values` em paralelo via `ThreadPoolExecutor` (genérica: serve a qualquer função texto → valor, ex.: `detect_language_llm`); com `progress_label` e lote de ao menos 20 itens, loga o progresso a cada 10% (`rótulo: 400/928 (43%) — 3m12s`); recebe a função de tradução como parâmetro (em vez de chamar `translate_text_llm` diretamente) para que os chamadores continuem passando sua própria referência local, preservando os mocks de teste existentes em `glue_details` e `backfill_traducao.py` |
| `detect_in_parallel(texts, detect_fn, max_workers=DETECT_MAX_WORKERS_DEFAULT, label=None)` | Aplica `detect_fn` a cada texto em paralelo (via `translate_in_parallel`) e, com `label`, loga o progresso e um resumo final (`N detectado(s), M falha(s), K vazio(s) em T texto(s) (tempo)`; `K vazio(s)` só aparece se K > 0 — os vazios nunca vão ao LLM, então sem essa parcela "N detectado(s) em T texto(s)" parece perda). Falha = texto não vazio cujo `detect_fn` devolveu `None` (chamada ao LLM falhou ou resposta fora do padrão ISO 639-1); texto vazio devolve `None` sem chamada de rede e não conta como falha. O resumo existe porque cada falha individual só vira um WARNING solto — com milhares de linhas, sem ele não dá para saber se o LLM está degradado. `DETECT_MAX_WORKERS_DEFAULT = 10` (chamadas curtas, `max_tokens=10`; modelo pago do OpenRouter sem teto de requisições da plataforma). Usada por `add_detected_language_column`, `resolve_pt_translation` e, via estes, por `glue_etl`, `glue_details` e `scripts/backfill_traducao.py` |
| `format_elapsed(seconds)` | Formata uma duração como `"45s"`, `"3m12s"` ou `"1h05m10s"` — usada nos logs de progresso/etapa (`detect_in_parallel`, `glue_details`, `scripts/backfill_discover.py`) |
| `resolve_pt_translation(df, source_column, target_column, detected_language_en_column, detected_language_pt_column, translation_attempts_column, detect_fn, translate_fn, max_workers=5, max_attempts=3, needs_translation_column=None, sample_id_column=None)` | Sincroniza `target_column` (já inicializada pelo chamador — nativo do TMDB, cache reaproveitado ou vazia) com `source_column`. Detecta `detected_language_en_column`/`detected_language_pt_column` (só onde ainda vazios, em paralelo via `detect_in_parallel` com o mesmo `max_workers` da tradução), copia a fonte direto quando ela já é `"pt"` (sem chamar tradutor), traduz as linhas elegíveis (fonte preenchida, `detected_language_pt_column != "pt"`, `translation_attempts_column < max_attempts`, idioma do destino disponível) via `translate_in_parallel`. Se o destino tem texto mas a detecção do idioma dele falhou (idioma nulo — erro/timeout/resposta inválida do LLM), o idioma real é desconhecido, não "diferente de pt": a linha é mantida como está (não vai ao tradutor, não gasta tentativa, não sobrescreve uma tradução nativa do TMDB) e a detecção é refeita na próxima execução; destino vazio continua elegível. Loga em INFO quantas linhas foram poupadas por esse motivo, incrementa `translation_attempts_column` e redetecta `detected_language_pt_column` (também em paralelo) só nas linhas recém-traduzidas. Basear a elegibilidade no idioma real do **resultado** (em vez de comparar string com a fonte) evita tanto retraduzir o que já está correto quanto deixar uma mistradução silenciosa marcada como concluída para sempre; `translation_attempts_column` evita retry infinito de conteúdo genuinamente não traduzível (nomes próprios, termos curtos) — relevante também para o LLM, que não é determinístico. Se `needs_translation_column` for informado, grava nela um booleano com "fonte preenchida E idioma do destino ≠ `"pt"` E texto do destino **não alterado** em relação à fonte (sem diferença de caixa/espaços nas pontas). O último termo existe porque o detector de idioma erra em textos curtos — listas de keywords como `turkish drama => drama turco` saíam detectadas como `tr`/`en`/`es` e eram marcadas pendentes mesmo traduzidas (44% dos pendentes de keywords no backfill de dev de 04/10/2026); se o texto mudou, alguém o traduziu. Só afeta o sinal e o log de balanço: quais linhas vão ao tradutor (elegibilidade) continua decidido pelo idioma detectado", sem o teto de tentativas (definição única em `_pending_mask`, também usada pelo "pendentes" do balanço). Ao final, loga em INFO o resumo agregado de sucessos e falhas; falhas individuais ficam em DEBUG. Também loga uma linha de balanço da coluna (`Balanço '<coluna>': N com fonte | N já em pt | N traduzida(s) (N ok, N igual(is) à fonte) | N mantida(s) por detecção indisponível | N pendente(s) (ex.: id …)`, com até 3 ids de exemplo das pendentes quando `sample_id_column` existe no `df`) e soma as mesmas contagens em `llm_metrics` para o total da execução Devolve `(df, quantidade traduzida com sucesso)`. Usada por `glue_details` e `scripts/backfill_traducao.py` (passando `needs_translation_column` para `overview`/`tagline`/`keywords`) e por `glue_etl` (`name_pt` de países/idiomas, sem `needs_translation_column`) |
| `reuse_existing_translation(df, previous_df, source_column, target_column, key_column="id", detected_language_en_column=None, detected_language_pt_column=None)` | Pré-preenche `target_column` com a tradução já persistida (`previous_df`) quando `source_column` não mudou para o mesmo `key_column` — evita retraduzir texto idêntico ao da última execução; loga `X de Y registro(s) (Z%)` reaproveitados e soma em `llm_metrics`. Não sobrescreve valor já preenchido (prioridade da tradução nativa do TMDB); a checagem final de "já traduzido" continua em `resolve_pt_translation`. Compartilhada entre `glue_details` (`key_column="id"`, default) e `glue_etl` (`key_column="iso_3166_1"`/`"iso_639_1"` para a tabela `configuration`). Com `detected_language_en_column`/`detected_language_pt_column` informadas, também reaproveita o idioma já detectado da fonte e do destino (via `reuse_detected_language`), poupando a redetecção — uma chamada ao LLM por linha por coluna |
| `reuse_detected_language(df, previous_df, text_column, language_column, key_column="id")` | Preenche `language_column` com o idioma já detectado em `previous_df` quando `text_column` não mudou (texto idêntico, mesma `key_column`). Só reaproveita valor não nulo/vazio: uma detecção que falhou (`None`) na execução anterior não é "congelada", fica pendente e é tentada de novo. Texto alterado força nova detecção; valor já preenchido em `df` nunca é sobrescrito. Para o idioma do destino, a comparação é sobre o texto traduzido atual vs. o antigo — se a tradução mudou (ex.: tradução nativa do TMDB diferente da traduzida antes), o idioma antigo descreve outro texto e não é reaproveitado. Schema antigo sem a coluna, ou `previous_df` vazio/`None`, não afeta nada. Usada por `reuse_existing_translation` (glue_details/glue_etl `configuration`) e diretamente por `glue_etl._read_discover` (`overview_detected_language`) |

### `shared_utils/idioma.py`

| Função | Responsabilidade |
|---|---|
| `add_detected_language_column(df, source_column, target_column, detect_fn=None, only_missing=False, max_workers=10)` | Aplica `detect_fn` (default `detect_language_llm`) a cada valor de `source_column`, tratando nulo/NaN como string vazia, e grava o resultado em `target_column`. Com `only_missing=True`, só detecta onde `target_column` ainda está vazia/nula — preserva valores já calculados em execuções anteriores. Roda em paralelo via `detect_in_parallel` (`ThreadPoolExecutor`, `max_workers=10`) e loga progresso e resumo de falhas — em série (uma chamada de ~1s por linha), uma coluna com milhares de linhas, como o `overview` do discover de um ano inteiro, levava dezenas de minutos. Usada diretamente por `glue_etl` (`overview` em discover, com `only_missing=True` depois de `reuse_detected_language` copiar o idioma de overviews inalterados da SOT) |

### `shared_utils/triggers.py`

| Função | Responsabilidade |
|---|---|
| `trigger_glue_job(job_name, **arguments)` | Dispara qualquer job Glue (fire-and-forget), convertendo kwargs para o formato `--CHAVE` do Glue |

## Uso nos componentes

| Componente | Funções importadas |
|---|---|
| `lambda_api` | `api_get`, `get_api_secret`, `trigger_glue_job` |
| `lambda_cognito_email_sender` | `load_gmail_credentials`, `send_gmail_email` |
| `lightsail_ia` | `send_gmail_email`, `load_llm_api_key` |
| `glue_details` | `api_get`, `get_api_secret`, `get_resolved_option`, `translate_text_llm`, `detect_language_llm`, `resolve_pt_translation`, `reuse_existing_translation`, `trigger_glue_job` |
| `glue_etl` | `get_resolved_option`, `translate_text_llm`, `detect_language_llm`, `resolve_pt_translation`, `reuse_existing_translation`, `reuse_detected_language`, `add_detected_language_column`, `trigger_glue_job` |
| `scripts/backfill_traducao.py` | `translate_text_llm`, `detect_language_llm`, `resolve_pt_translation` |
| `glue_agg` | `get_resolved_option`, `trigger_glue_job` |
| `glue_agg/main` | `configure_glue_logging` |
| `glue_etl/main` | `configure_glue_logging` |
| `glue_data_quality/main` | `configure_glue_logging` |
| `glue_details/main` | `configure_glue_logging` |

## Deploy

- **Glue jobs**: empacotado como wheel (`tmdb_shared-0.0.0-py3-none-any.whl`) via `build_glue_wheel.py --package shared_utils` e referenciado no `--extra-py-files` de cada job. `glue_etl`/`glue_details` recebem `FILMBOT_SECRET_ARN` como argumento do job (`--FILMBOT_SECRET_ARN`), publicado em `os.environ` dentro de `get_parameters_glue()` — mesmo padrão já usado para `AWS_ACCOUNT_ID` — para que `load_llm_api_key` o leia como se fosse o ambiente real
- **Lambda** (`lambda_api`, `lambda_cognito_email_sender`): copiado para dentro do zip via `build_lambda_package.py --shared`
- **Lightsail** (`lightsail_ia`): não é empacotado — o deploy (`deploy_lightsail.yml`) clona o repositório inteiro, então `app/shared_src` já existe em disco ao lado de `app/lightsail_ia`; `app.py` insere esse caminho em `sys.path` antes de importar `src.*` (mesmo padrão usado em `scripts/backfill_*.py`)
- **Terraform**: build e upload em `shared_src.tf`, paths em `locals.tf`
