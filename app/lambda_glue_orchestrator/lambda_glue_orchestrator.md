# lambda_glue_orchestrator — Orquestrador Assíncrono de Jobs Glue

## O que é

Lambda pequena e genérica que recebe uma lista de `{job_name, run_id}`, espera todos atingirem um estado terminal e aciona um job Glue alvo. Sempre invocada de forma **assíncrona** (`InvocationType="Event"`) por outra Lambda — nunca síncrona, nunca por EventBridge diretamente.

## Por que existe

Nasceu de um incidente em produção: a `lambda_api`, no modo `skip_weekly` (atualização isolada das tabelas de referência — genre/configuration/watch_providers_ref), passou a esperar (polling em `glue:GetJobRun`) os 3 `glue_etl` de referência terminarem antes de acionar o `glue_agg`, para evitar que o AGG lesse dados desatualizados. Isso fez a invocação da `lambda_api` durar ~4-5 minutos — muito além do `read_timeout` padrão de 60s do cliente boto3 usado pelo script de backfill síncrono (`scripts/backfill_referencias.py`). Como `lambda:Invoke` não é idempotente, o retry automático do botocore após o timeout gerou múltiplas execuções concorrentes e independentes da `lambda_api`, cada uma reacionando os mesmos 3 `glue_etl` e o `glue_agg` — causa de uma corrida de escrita/leitura no S3 (Glue Data Quality lendo um parquet sobrescrito por uma execução concorrente).

A solução: extrair a espera para uma Lambda separada, invocada sem que ninguém fique esperando a resposta HTTP dela. A `lambda_api` volta a ser rápida/fire-and-forget nas duas pernas (movie e tv), eliminando a classe inteira do bug. O payload é genérico (não amarrado a "referências" ou a `lambda_api`) para poder ser reaproveitado por qualquer disparo futuro que precise de um "espera N jobs, depois aciona job X" — hoje só usado pelo modo `skip_weekly`, mas o mesmo padrão poderia futuramente substituir a convenção implícita "tv é sempre o último a terminar" usada em `app/glue_details/main.py` para acionar o AGG no ciclo semanal/mensal.

## Como funciona

1. Recebe o payload (ver "Entradas e saídas") — nunca validado além do acesso direto às chaves: só a `lambda_api` tem permissão IAM para invocar esta função, então um payload malformado não é um cenário real.
2. `wait_for_job_runs()` (`src/utils.py`) faz polling em `glue:GetJobRun` para cada `{job_name, run_id}` de `wait_for`, a cada 15s, até cada um atingir um estado terminal (`SUCCEEDED`, `FAILED`, `STOPPED`, `ERROR`, `TIMEOUT`). Um job que não termina em `SUCCEEDED` é logado como erro, mas não interrompe a espera pelos demais — evita perder o acionamento do job alvo por causa de uma falha isolada.
3. Aciona `target_job_name` via `trigger_glue_job()` (`shared_utils.triggers`), repassando `target_job_args` se informado.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Evento JSON (sempre via invocação assíncrona): `wait_for` (lista de `{"job_name": str, "run_id": str}`), `target_job_name` (str), `target_job_args` (dict opcional) |
| **Leitura** | AWS Glue — `get_job_run` para cada item de `wait_for` |
| **Aciona** | O job Glue de `target_job_name` |

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `wait_for_job_runs(glue_client, wait_for, poll_interval=15)` | Polling até todos os jobs de `wait_for` atingirem estado terminal; loga (sem levantar) os que não terminaram em `SUCCEEDED` |

## Funções compartilhadas (`shared_utils/`)

| Função | Origem | Responsabilidade |
|---|---|---|
| `trigger_glue_job(job_name, **kwargs)` | `shared_utils.triggers` | Aciona o job alvo (`target_job_name`), repassando `target_job_args` como argumentos |

## Quem aciona esta Lambda hoje

`app/lambda_api/main.py`, modo `skip_weekly`, perna `content_type="tv"` — depois de disparar os 3 `glue_etl` de referência (genre/configuration/watch_providers_ref), invoca esta função de forma assíncrona com os 3 `run_id`s capturados e `target_job_name=GLUE_AGG_JOB_NAME`. Ver `app/lambda_api/lambda_api.md`.

## Tecnologias

- **boto3** — integração com AWS Glue (`get_job_run`, via `trigger_glue_job`)
