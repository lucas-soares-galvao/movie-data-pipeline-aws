# lambda_api — Coletor de Dados (TMDB)

## O que é

A Lambda API é o ponto de entrada do pipeline. É uma função serverless (sem servidor dedicado — você paga apenas pelo tempo em que ela roda) acionada automaticamente pelo **EventBridge** (serviço de agendamento da AWS, funciona como um cron) em cinco agendamentos: semanal (discover do ano atual + now_playing), mensal (discover do ano anterior + dados de referência), mensal de ano futuro (discover de `current_year + 1`, para título já anunciado pela TMDB mas ainda não catalogado — ver "Modo ano futuro" abaixo), semanal de changes (refresh de títulos já catalogados de qualquer ano, via Changes API do TMDB) e semanal de rotation refresh (refresh forçado de 1 ano do catálogo antigo por vez) — ver "Modo changes" e "Modo rotation refresh" abaixo. Ela busca dados de filmes e séries na API do TMDB, salva os resultados em S3 na camada **SOR** (dados brutos, sem transformação) e aciona o Glue ETL para cada lote.

## Por que existe

Isola a camada de ingestão (HTTP → S3) da camada de transformação (S3 → Parquet). Ao separar essa responsabilidade, é possível reprocessar ou modificar a coleta sem tocar nos jobs de transformação, e vice-versa.

## Como funciona

1. O EventBridge dispara a Lambda com um payload JSON indicando o tipo de mídia (`movie` ou `tv`) e os nomes das tabelas do Glue Catalog.
2. A Lambda busca a chave da API do TMDB no **Secrets Manager** (cofre de senhas da AWS — armazena credenciais com segurança, evitando que a chave fique exposta no código) — uma única vez por execução, independente de quantos anos existam.
3. Dependendo dos flags recebidos no evento:
   - **`only_weekly_tables=True`** (execução semanal): pula gêneros, idiomas, países e plataformas de referência.
   - **`only_annual_tables=True`** (backfill manual de múltiplos anos): mesmo efeito do `only_weekly_tables` — pula referências e roda apenas o discover.
   - **`only_monthly_tables=True`** (execução mensal): coleta referências e roda o discover apenas para `current_year - 1`, sem now_playing.
   - **`only_future_year_tables=True`** (execução mensal de ano futuro, ver "Modo ano futuro" abaixo): pula referências (já cobertas pelo modo mensal) e roda o discover apenas para `current_year + 1`, sem now_playing.
   - **`only_changes_tables=True`** (execução semanal de changes, ver "Modo changes" abaixo): sai antes de qualquer coleta de referência/discover.
   - **`only_rotation_refresh=True`** (execução semanal de rotation refresh, ver "Modo rotation refresh" abaixo): sai antes de qualquer coleta de referência/discover.
   - Sem flags: coleta tudo.
4. Para dados de referência (gêneros, idiomas/países, plataformas): faz uma chamada à API e salva um único arquivo JSON no S3 SOR, depois aciona o Glue ETL. Todo acionamento do Glue ETL repassa `TRANSLATE_PROVIDER` (lido de `event.get("translate_provider", "google")`) — `"google"` é o default deste caminho automático via EventBridge, já que o payload configurado em `eventbridge.tf` nunca define esse campo; é grátis, com AWS Translate disponível como fallback automático (capado por caracteres) caso o Google falhe. Backfills manuais podem sobrescrever para `"aws"` para testar tradução real da AWS num período curto.

   **Backfill manual**: `scripts/backfill_referencias.py` roda a mesma coleta (genre/configuration/watch_providers_ref) sob demanda, mas **sem invocar esta Lambda nem o Glue ETL**: chama `collect_genre_data()`/`collect_configuration_data()`/`collect_watch_providers_ref()` e a transformação equivalente ao Glue ETL (`read_from_sor()`/`write_parquet_to_sot()`, de `app/glue_etl/src/utils.py`) diretamente no processo do backfill — o mesmo padrão de reuso fora do runtime de nuvem já usado por `scripts/backfill_enriquecimento.py` (Glue Details) e `scripts/backfill_changes.py` (Lambda + Glue Details). Ver `scripts/scripts.md`.
5. Para dados de discover: itera por cada ano no intervalo `[start_year, loop_end_year]` (`start_year` padrão = ano atual; `end_year` padrão = ano atual, se não fornecidos no evento; `loop_end_year` padrão = `end_year`, mas pode ser passado separadamente no evento para desacoplar o limite real do loop do `end_year` usado como marcador de "último ano do ciclo" repassado ao Glue), faz requisições paginadas à API (até `MAX_PAGES = 100` páginas por ano — TMDB permite até 500, mas o limite evita estourar o timeout da Lambda), salva um arquivo JSON por página no S3 SOR (`pagina_001.json`, `pagina_002.json`, ...) e aciona o Glue ETL para aquele ano.

   **Backfill manual**: `scripts/backfill_discover.py` roda a mesma coleta de discover (2000 até o ano atual) sob demanda, mas **sem invocar esta Lambda nem o Glue ETL**: chama `collect_discover_data()` e a transformação equivalente ao Glue ETL (`read_from_sor()`/`write_parquet_to_sot()`, de `app/glue_etl/src/utils.py`) diretamente no processo do backfill — mesmo padrão de reuso fora do runtime de nuvem de `scripts/backfill_referencias.py` (acima). Não dispara o Glue Details — usar `scripts/backfill_enriquecimento.py` à parte para popular details/watch_providers do range coletado. Ver `scripts/scripts.md`.
6. Para filmes (`content_type="movie"`), após o loop de discover, coleta também os filmes em cartaz nos cinemas via `collect_now_playing_data()`: pagina o endpoint `/movie/now_playing`, extrai as datas da janela teatral (`theater_start_date`, `theater_end_date`) e salva os resultados no S3 SOR, depois aciona o Glue ETL com `table_type="now_playing"`. Esse passo é condicional: só ocorre se `table_now_playing` estiver presente no evento **e** `only_monthly_tables` for `False` (execuções mensais nunca coletam now_playing, mesmo com a tabela presente no evento).

### Modo changes (TMDB Changes API)

Fecha o gap de staleness em títulos de qualquer ano — não só o ano atual/anterior cobertos pelos modos semanal/mensal. `/movie/changes` e `/tv/changes` retornam, para uma janela de data, os IDs que sofreram qualquer alteração no período, independente do ano de lançamento.

Acionado por `only_changes_tables=True` (regras EventBridge `lambda_api_movie_changes_weekly`/`..._tv_changes_weekly`, domingos, um dia inteiro depois do discover semanal de sábado — roda isolado, sem nenhum outro job Glue Details no mesmo dia, e já com o catálogo atualizado com os títulos novos da semana). Sai cedo — antes de qualquer coleta de referência/discover, já que este modo é estruturalmente diferente dos demais: não usa `/discover`, não escreve no SOR e não passa pelo Glue ETL.

Fluxo: `collect_changes_data()` calcula a janela `[domingo passado, sábado de ontem]` (7 dias corridos, `end_date` = ontem, `start_date` = 6 dias antes — contígua com a janela da semana anterior, sem gap e sem sobreposição, ainda dentro do limite de 14 dias da Changes API), pagina `fetch_changed_ids()`, grava a lista de IDs no bucket **TEMP** (`tmdb/changes/{movie|tv}/{data}.json` — handoff efêmero, não dado a catalogar) e aciona o **Glue Details** diretamente com `CHANGES_S3_PATH` apontando para esse arquivo. O Glue Details resolve o `year` de cada ID via Athena na tabela discover e reaproveita o mesmo enriquecimento do fluxo normal — ver `app/glue_details/glue_details.md`.

Cadência semanal (não diária) para economizar custo do Glue Details, que é acionado a cada execução.

**Backfill manual**: `scripts/backfill_changes.py` roda o mesmo fluxo sob demanda — útil quando o cron semanal falha ou é pulado — mas **sem invocar esta Lambda**: chama `collect_changes_data()` diretamente no processo do backfill (GitHub Actions), o mesmo padrão de reuso fora do runtime de nuvem já usado por `scripts/backfill_enriquecimento.py` para o Glue Details (ver `app/glue_details/glue_details.md`, seção "Reuso fora do Glue"). A janela continua sendo sempre `[domingo passado, sábado de ontem]`, calculada por `collect_changes_data()` no momento da invocação; o script não escolhe uma janela histórica. Depois de coletar os IDs, o script também chama `fetch_ids_from_changes_file()`/`process_changed_ids()` diretamente (em vez de acionar o Glue Details como job) — ver `scripts/scripts.md`.

### Modo ano futuro (título anunciado ainda não catalogado)

Fecha um gap diferente dos demais modos: nenhum discover hoje aponta pra `current_year + 1`, então título anunciado pela TMDB (`status` `"Planned"`/`"In Production"`/`"Post Production"`, `release_date`/`first_air_date` futuro) pra o ano que vem só entraria no catálogo quando aquele ano virasse o `current_year`, meses depois de já existir na TMDB.

Acionado por `only_future_year_tables=True` (regras EventBridge `lambda_api_movie_future_monthly`/`..._tv_future_monthly`, dia 1 do mês, 10:00/10:05 UTC — horário deslocado de todas as demais regras do pipeline, que ficam entre 09:00-09:35 UTC). Sobrescreve `start_year`/`end_year`/`loop_end_year` para `current_year + 1` e segue o mesmo fluxo `YEAR`/`END_YEAR` do modo mensal (item 5 acima) — não sai cedo como changes/rotation refresh, já que ainda passa por `/discover` e pelo Glue ETL normalmente.

Sem referências (já cobertas pelo modo mensal) e sem `now_playing` (título ainda não lançado não está em cartaz nos cinemas). Uma vez que um título entra no catálogo por este modo, o **modo changes** (qualquer ano) já mantém ele atualizado sem depender deste modo rodar de novo — este modo só precisa capturar título **novo**, não manter frescor do que já foi capturado.

### Modo rotation refresh (catálogo antigo, 1 ano por vez)

Fecha o gap de staleness no restante do catálogo (2000 até `current_year - 3`) sem reprocessar tudo de uma vez — dado que `details` quase não muda para títulos antigos, o refresh existe como rede de segurança contra o gap do `/changes`, não como atualização de dados voláteis. O ano corrente e o anterior não têm um modo forçado equivalente: já são refeitos naturalmente pelo cascade do discover semanal/mensal → Glue ETL → Glue Details (`app/glue_etl/main.py`, quando `table_type == "discover"`, sem `FORCE_REFETCH`) — a lógica de delta do Glue Details já refaz qualquer ID não tocado no mês calendário corrente, cobrindo os 2 anos mais recentes ~mensalmente de graça, sem custo adicional.

Acionado por `only_rotation_refresh=True` (regras EventBridge `lambda_api_movie_rotation_weekly`/`..._tv_rotation_weekly`, sábados, 30 min antes do discover semanal — nunca colide de partição com ele, catálogo antigo vs. ano corrente). Sai cedo, como o modo changes.

Fluxo: lê o ponteiro "último ano processado" de um parâmetro SSM Parameter Store (`/tmdb-pipeline/rotation-year-pointer-{movie|tv}`, um por `content_type` para evitar corrida entre as execuções de movie e tv — ver `infra/ssm.tf`), soma 1, e se o resultado ultrapassar `current_year - 3` (recalculado a cada execução, nunca hardcoded) reinicia em 2000. Dispara o Glue Details para esse único ano com `FORCE_REFETCH=True` e `END_YEAR` igual ao próprio ano (cada execução é um ciclo de 1 ano), depois grava o novo valor no SSM. Não é um checkpoint de loop sequencial (como o de `scripts/backfill_shared.py`) — é um valor único, sem lógica de retomada: se uma execução falhar antes de gravar, a próxima simplesmente reprocessa o mesmo ano.

### Tratamento de erros

- `collect_discover_data` e `collect_now_playing_data` levantam `RuntimeError` se nenhuma página for salva com sucesso (todas as tentativas falharam) — isso propaga a falha para o handler em vez de acionar o Glue com dados vazios.
- `collect_watch_providers_ref` é o único coletor de referência com tratamento especial: captura `HTTPError`, loga o erro e segue em frente sem interromper a execução, preservando os dados anteriores já salvos no S3. `collect_genre_data` e `collect_configuration_data` não têm esse tratamento — uma falha neles propaga normalmente.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Evento JSON do EventBridge com `type`, nomes de tabelas e flags opcionais (`only_weekly_tables`, `only_annual_tables`, `only_monthly_tables`, `only_future_year_tables`, `only_changes_tables`, `only_rotation_refresh`, `translate_provider`) |
| **Leitura** | API TMDB (HTTP), Secrets Manager (chave de API), SSM Parameter Store (ponteiro do modo rotation refresh) |
| **Escrita** | S3 SOR — `tmdb/discover/{movie\|tv}/year={ano}/`, `tmdb/{genre\|configuration\|watch_providers_ref}/{movie\|tv}/` e `tmdb/now_playing/movie/pagina_NNN.json`; S3 TEMP — `tmdb/changes/{movie\|tv}/{data}.json` (modo changes); SSM Parameter Store — `/tmdb-pipeline/rotation-year-pointer-{movie\|tv}` (modo rotation refresh) |
| **Aciona** | Glue ETL para cada tabela coletada (genre, configuration, watch_providers_ref, discover por ano, now_playing para filmes); Glue Details diretamente nos modos changes e rotation refresh |

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `collect_genre_data(...)` | Coleta mapeamento de IDs → nomes de gêneros |
| `collect_configuration_data(...)` | Coleta lista de idiomas ou países |
| `collect_watch_providers_ref(...)` | Coleta lista de plataformas de streaming disponíveis (`provider_id`, `provider_name`, `display_priority_br`, `logo_path` — path relativo da logo na CDN do TMDB, usado por `glue_agg` para montar a URL completa) |
| `collect_discover_data(...)` | Coleta filmes/séries populares de um ano (paginado) |
| `collect_now_playing_data(...)` | Coleta filmes em cartaz nos cinemas no Brasil (`region=BR`, paginado), extrai datas de janela teatral e salva no S3 SOR |
| `fetch_changed_ids(...)` | Pagina `/movie/changes` ou `/tv/changes` numa janela de data e retorna IDs únicos que mudaram |
| `collect_changes_data(...)` | Calcula a janela `[ontem - lookback_days, ontem]`, chama `fetch_changed_ids` e grava a lista de IDs no S3 TEMP |

## Funções compartilhadas (`shared_utils/`)

| Função | Origem | Responsabilidade |
|---|---|---|
| `get_api_secret(secret_arn, key_name)` | `shared_utils.api_client` | Busca um segredo no Secrets Manager |
| `api_get(url, params, max_retries)` | `shared_utils.api_client` | GET com retry/backoff para lidar com rate limits de APIs |
| `trigger_glue_job(job_name, **kwargs)` | `shared_utils.triggers` | Aciona um job Glue, repassando `**kwargs` como argumentos (`--TABLE_TYPE`, `--TABLE_NAME`, `--YEAR`, `--END_YEAR`, `--TRANSLATE_PROVIDER`, etc.); usado para o Glue ETL (fluxo normal) e o Glue Details (modos changes/rotation refresh) |

## Tecnologias

- **boto3** — integração com AWS (S3, Glue, Lambda, Secrets Manager)
- **requests** — chamadas HTTP à API TMDB
- **EventBridge** — agendamento e disparo da função
