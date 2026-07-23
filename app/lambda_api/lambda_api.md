# lambda_api — Coletor de Dados (TMDB)

## O que é

A Lambda API é o ponto de entrada do pipeline. É uma função serverless (sem servidor dedicado — você paga apenas pelo tempo em que ela roda) acionada automaticamente pelo **EventBridge** (serviço de agendamento da AWS, funciona como um cron) em quatro agendamentos: semanal (discover do ano atual + now_playing), mensal (discover do ano anterior + dados de referência), anual (backfill histórico) e semanal de changes (refresh de títulos já catalogados de qualquer ano, via Changes API do TMDB — ver "Modo changes" abaixo). Ela busca dados de filmes e séries na API do TMDB, salva os resultados em S3 na camada **SOR** (dados brutos, sem transformação) e aciona o Glue ETL para cada lote.

## Por que existe

Isola a camada de ingestão (HTTP → S3) da camada de transformação (S3 → Parquet). Ao separar essa responsabilidade, é possível reprocessar ou modificar a coleta sem tocar nos jobs de transformação, e vice-versa.

## Como funciona

1. O EventBridge dispara a Lambda com um payload JSON indicando o tipo de mídia (`movie` ou `tv`) e os nomes das tabelas do Glue Catalog.
2. A Lambda busca a chave da API do TMDB no **Secrets Manager** (cofre de senhas da AWS — armazena credenciais com segurança, evitando que a chave fique exposta no código) — uma única vez por execução, independente de quantos anos existam.
3. Dependendo dos flags recebidos no evento:
   - **`only_weekly_tables=True`** (execução semanal): pula gêneros, idiomas, países e plataformas de referência.
   - **`only_annual_tables=True`** (backfill anual via Step Functions): mesmo efeito do `only_weekly_tables` — pula referências e roda apenas o discover.
   - **`only_monthly_tables=True`** (execução mensal): coleta referências e roda o discover apenas para `current_year - 1`, sem now_playing.
   - **`skip_weekly=True`** (modo legado — referências apenas): pula o loop de discover.
   - **`only_changes_tables=True`** (execução semanal de changes, ver "Modo changes" abaixo): sai antes de qualquer coleta de referência/discover.
   - Sem flags: coleta tudo.
4. Para dados de referência (gêneros, idiomas/países, plataformas): faz uma chamada à API e salva um único arquivo JSON no S3 SOR, depois aciona o Glue ETL. Todo acionamento do Glue ETL repassa `TRANSLATE_PROVIDER` (lido de `event.get("translate_provider", "google")`) — `"google"` é o default deste caminho automático via EventBridge, já que o payload configurado em `eventbridge.tf` nunca define esse campo; é grátis, com AWS Translate disponível como fallback automático (capado por caracteres) caso o Google falhe. Backfills manuais podem sobrescrever para `"aws"` para testar tradução real da AWS num período curto.
5. Para dados de discover: itera por cada ano no intervalo `[start_year, loop_end_year]` (`start_year` padrão = ano atual; `end_year` padrão = ano atual, se não fornecidos no evento; `loop_end_year` padrão = `end_year`, mas pode ser passado separadamente no evento para desacoplar o limite real do loop do `end_year` usado como marcador de "último ano do ciclo" repassado ao Glue), faz requisições paginadas à API (até `MAX_PAGES = 100` páginas por ano — TMDB permite até 500, mas o limite evita estourar o timeout da Lambda), salva um arquivo JSON por página no S3 SOR (`pagina_001.json`, `pagina_002.json`, ...) e aciona o Glue ETL para aquele ano.
6. Para filmes (`content_type="movie"`), após o loop de discover, coleta também os filmes em cartaz nos cinemas via `collect_now_playing_data()`: pagina o endpoint `/movie/now_playing`, extrai as datas da janela teatral (`theater_start_date`, `theater_end_date`) e salva os resultados no S3 SOR, depois aciona o Glue ETL com `table_type="now_playing"`. Esse passo é condicional: só ocorre se `table_now_playing` estiver presente no evento **e** `only_monthly_tables` for `False` (execuções mensais nunca coletam now_playing, mesmo com a tabela presente no evento).

### Modo changes (TMDB Changes API)

Fecha o gap de staleness em títulos de qualquer ano — não só o ano atual/anterior cobertos pelos modos semanal/mensal. `/movie/changes` e `/tv/changes` retornam, para uma janela de data, os IDs que sofreram qualquer alteração no período, independente do ano de lançamento.

Acionado por `only_changes_tables=True` (regras EventBridge `lambda_api_movie_changes_weekly`/`..._tv_changes_weekly`, sábados, mesmo horário do discover semanal de domingo). Sai cedo — antes de qualquer coleta de referência/discover, já que este modo é estruturalmente diferente dos demais: não usa `/discover`, não escreve no SOR e não passa pelo Glue ETL.

Fluxo: `collect_changes_data()` calcula a janela `[hoje - 9 dias, hoje]` (9 dias, não 7 — cobre a semana cheia mais 2 dias de folga contra falha de execução, ainda dentro do limite de 14 dias da Changes API), pagina `fetch_changed_ids()`, grava a lista de IDs no bucket **TEMP** (`tmdb/changes/{movie|tv}/{data}.json` — handoff efêmero, não dado a catalogar) e aciona o **Glue Details** diretamente com `CHANGES_S3_PATH` apontando para esse arquivo. O Glue Details resolve o `year` de cada ID via Athena na tabela discover e reaproveita o mesmo enriquecimento do fluxo normal — ver `app/glue_details/glue_details.md`.

Cadência semanal (não diária) para economizar custo do Glue Details, que é acionado a cada execução.

### Tratamento de erros

- `collect_discover_data` e `collect_now_playing_data` levantam `RuntimeError` se nenhuma página for salva com sucesso (todas as tentativas falharam) — isso propaga a falha para o handler em vez de acionar o Glue com dados vazios.
- `collect_watch_providers_ref` é o único coletor de referência com tratamento especial: captura `HTTPError`, loga o erro e segue em frente sem interromper a execução, preservando os dados anteriores já salvos no S3. `collect_genre_data` e `collect_configuration_data` não têm esse tratamento — uma falha neles propaga normalmente.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Evento JSON do EventBridge com `type`, nomes de tabelas e flags opcionais (`only_weekly_tables`, `only_annual_tables`, `only_monthly_tables`, `skip_weekly`, `only_changes_tables`, `translate_provider`) |
| **Leitura** | API TMDB (HTTP), Secrets Manager (chave de API) |
| **Escrita** | S3 SOR — `tmdb/discover/{movie\|tv}/year={ano}/`, `tmdb/{genre\|configuration\|watch_providers_ref}/{movie\|tv}/` e `tmdb/now_playing/movie/pagina_NNN.json`; S3 TEMP — `tmdb/changes/{movie\|tv}/{data}.json` (modo changes) |
| **Aciona** | Glue ETL para cada tabela coletada (genre, configuration, watch_providers_ref, discover por ano, now_playing para filmes); Glue Details diretamente no modo changes |

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `collect_genre_data(...)` | Coleta mapeamento de IDs → nomes de gêneros |
| `collect_configuration_data(...)` | Coleta lista de idiomas ou países |
| `collect_watch_providers_ref(...)` | Coleta lista de plataformas de streaming disponíveis |
| `collect_discover_data(...)` | Coleta filmes/séries populares de um ano (paginado) |
| `collect_now_playing_data(...)` | Coleta filmes em cartaz nos cinemas no Brasil (`region=BR`, paginado), extrai datas de janela teatral e salva no S3 SOR |
| `fetch_changed_ids(...)` | Pagina `/movie/changes` ou `/tv/changes` numa janela de data e retorna IDs únicos que mudaram |
| `collect_changes_data(...)` | Calcula a janela `[hoje - lookback_days, hoje]`, chama `fetch_changed_ids` e grava a lista de IDs no S3 TEMP |

## Funções compartilhadas (`shared_utils/`)

| Função | Origem | Responsabilidade |
|---|---|---|
| `get_api_secret(secret_arn, key_name)` | `shared_utils.api_client` | Busca um segredo no Secrets Manager |
| `api_get(url, params, max_retries)` | `shared_utils.api_client` | GET com retry/backoff para lidar com rate limits de APIs |
| `trigger_glue_job(job_name, **kwargs)` | `shared_utils.triggers` | Aciona o job Glue ETL, repassando `**kwargs` como argumentos (`--TABLE_TYPE`, `--TABLE_NAME`, `--YEAR`, `--END_YEAR`, `--TRANSLATE_PROVIDER`, etc.) |

## Tecnologias

- **boto3** — integração com AWS (S3, Glue, Secrets Manager)
- **requests** — chamadas HTTP à API TMDB
- **EventBridge** — agendamento e disparo da função
