---
name: especialista-observabilidade-qualidade-dados
description: Especialista em observabilidade (alarmes CloudWatch, tópicos SNS, logs) e qualidade de dados (Glue Data Quality/DQDL) do pipeline. Use ao criar/alterar um alarme ou notificação, adicionar uma tabela nova ao Glue Catalog (precisa de ruleset DQDL), decidir se um evento novo deve notificar por e-mail, revisar `rulesets_dq.py`, avaliar se uma falha silenciosa pode passar despercebida, ou decidir onde/como logar algo novo. Cobre o racional por trás do padrão já implementado (EventBridge→SNS sem Lambda, dois canais de notificação distintos) e as lacunas de observabilidade ainda não endereçadas (sem dashboard, sem X-Ray, sem métrica de negócio custom).
---

# Especialista em Observabilidade e Qualidade de Dados

## Papel

Você avalia toda mudança pela pergunta: **"se isso quebrar, ou se o dado vier corrompido, alguém fica sabendo — com o motivo exato, não só um alarme genérico?"**. Observabilidade e qualidade de dados são a mesma camada de confiança operacional neste projeto: o próprio Glue Data Quality notifica falhas de regra via SNS, o mesmo canal usado para falha de execução de job. Preserva o padrão já maduro (alarmes escopados, dois canais de notificação distintos, rulesets DQDL nas 4 dimensões) e não introduz alarme "melhor esforço" ou log solto quando já existe um padrão a seguir.

## Fontes de verdade (ler antes de agir)

Esta skill cobre o racional de observabilidade/qualidade; não duplica a descrição de recurso ou de código:

| O quê | Onde |
|---|---|
| Argumentos exatos de `aws_cloudwatch_metric_alarm`, `aws_sns_topic`, `aws_cloudwatch_log_group` | `especialista-infraestrutura-terraform` |
| Código Python do Glue Data Quality e demais jobs Glue | `especialista-engenharia-dados-app` |
| Retenção de log por ambiente como alavanca de custo | `especialista-finops-aws` |
| Schedules EventBridge, tópicos SNS, mecânica do DLQ | `infra/docs/pipeline.md` |
| Fluxo funcional do Glue Data Quality | `app/glue_data_quality/glue_data_quality.md` |

## Práticas já aplicadas — preservar (Observabilidade)

- **`CloudWatch Alarm State Change` / `Glue Job State Change` → EventBridge → SNS, sem Lambda no meio** (`cloudwatch_alarms.tf`, `cloudwatch_glue_alarms.tf`): menos um ponto de falha entre o evento e a notificação. `input_transformer` monta a mensagem do e-mail direto a partir do payload do evento (`alarmName`/`jobName`, `state`, `reason`, `region`).
- **8 tópicos SNS, um por evento, cada um com um único subscriber de e-mail**, nome sufixado por ambiente (`-{env}`) — correção deliberada de um problema anterior em que dev/prod compartilhavam tópico e inscrição.
- **SNS topic policy restrita por `Condition ArnEquals aws:SourceArn`** à regra EventBridge específica — impede que qualquer outra regra da conta publique no tópico.
- **DLQ do EventBridge com alarme dedicado** (`ApproximateNumberOfMessagesVisible > 0` na fila `eventbridge_dlq`) — captura falha de entrega de evento, não só falha de execução.
- **Retenção de log por ambiente** via uma única variável (`var.log_retention_days`: dev=1 dia, prod=5 dias) — nunca hardcodada por recurso individual.
- **Padrão de log consistente entre módulos**: contadores nomeados (`saved_pages`/`failed_pages`), `logger.info` em marcos (início/fim de coleta, gravação), `logger.warning` só em falha parcial (com o resumo `X salvas, Y com erro`), `raise RuntimeError` apenas quando a falha é total — replicado em `collect_now_playing_data`, `collect_discover_data`, `fetch_changed_ids` (`app/lambda_api/src/utils.py`) e no fluxo do Glue Data Quality.

## Lacunas encontradas — avaliar risco x esforço antes de agir

- **Nenhum `aws_cloudwatch_dashboard`, nenhum X-Ray, nenhuma métrica de negócio custom** (EMF/`put_metric_data`) em lugar nenhum do projeto — toda visibilidade operacional hoje é log em texto livre ou alarme sobre métrica nativa de serviço (`AWS/Lambda Errors`, `AWS/Events FailedInvocations`, `AWS/SQS ApproximateNumberOfMessagesVisible`). Não há, por exemplo, uma métrica de "número de regras DQ falhas por execução" ou "páginas coletadas por run" fora do texto do log. Só implementar mediante pedido explícito — não é urgente para o volume atual do projeto, mas é a lacuna mais concreta se o objetivo for observabilidade de verdade além de "recebo um e-mail quando quebra".
- **`eventbridge_failed_alarm` soma só 4 das 9 regras de schedule** (`FailedInvocations` de `lambda_api_movie_weekly`, `lambda_api_tv_weekly`, `lambda_api_movie_monthly`, `lambda_api_tv_monthly`) — as regras `rotation_weekly` e `changes_weekly` (e as demais) não entram nessa soma. Uma falha recorrente nelas não dispara esse alarme específico. Validar se isso é intencional (talvez essas regras tenham um caminho de detecção próprio) antes de simplesmente adicionar as métricas faltantes à expressão.
- **`enableDataQualityCloudWatchMetrics=True`** faz o motor DQDL publicar métricas nativas no CloudWatch (Data Quality Results), mas nada no Terraform lê essas métricas em alarme ou dashboard — o canal de notificação real de falha de regra é outro, todo em Python (`notify_failed_outcomes` → SNS). As métricas nativas ficam publicadas e não utilizadas; não é um bug, mas é redundância que vale ter em mente antes de propor "adicionar mais uma fonte de métrica" sem antes aproveitar essa que já existe.
- **Backfill manual (`06_backfill.yml`) não tem observabilidade equivalente ao pipeline agendado** — falhas dentro de um backfill não geram alarme/SNS automaticamente, dependem do operador acompanhar o log do workflow no GitHub Actions.

## Práticas já aplicadas — preservar (Qualidade de dados)

- **`rulesets_dq.py`**: regras organizadas nas 4 dimensões DQDL (Completude `IsComplete`, Unicidade `IsUnique`/`Uniqueness`, Validade `ColumnValues`, Integridade `RowCount`), com `RowCount > 0` presente nas **14 tabelas sem exceção** — o piso mínimo de qualidade é uniforme mesmo quando as demais dimensões variam por tabela.
- **`get_ruleset` levanta `KeyError` explícito** se uma tabela não tiver entrada no dicionário — falha ruidosa e imediata (não silenciosa) quando alguém esquece de cadastrar o ruleset de uma tabela nova.
- **Dois canais de notificação distintos para dois tipos de "falha"**: falha de execução do job (crash/timeout/stop) → `Glue Job State Change` nativo → EventBridge → tópico `..._failure_notifications`; falha de **regra de qualidade** (`outcome=Failed` numa avaliação que rodou com sucesso) → `notify_failed_outcomes` → tópico `..._metrics_notifications`. Não confundir os dois ao adicionar uma notificação nova — cada tipo de problema tem seu próprio tópico e formato de mensagem.
- **O job nunca lança exceção por regra de qualidade reprovada** — termina `SUCCEEDED` mesmo com regras falhando, decisão deliberada e documentada no próprio docstring de `notify_failed_outcomes`: um dado imperfeito não deve travar o pipeline inteiro, mas o time precisa ser notificado mesmo assim. Não "corrigir" isso fazendo o job falhar quando uma regra falha — mudaria um comportamento intencional.
- **Guards estruturais antes/depois de gravar**, em `glue_agg/src/utils.py`: DataFrame vazio não sobrescreve dado existente (só loga e retorna); se a escrita não produzir nenhum arquivo confirmado, `raise RuntimeError` explicitamente **antes** de deixar o Glue Data Quality rodar sobre uma partição vazia/ausente. `glue_details` tem guards equivalentes (`if not records`, `if df.empty`) para as mesmas decisões de fluxo.

## Lacunas encontradas — Qualidade de dados

- Nada no CI garante que uma tabela nova no Glue Catalog tenha ruleset em `rulesets_dq.py` — a única rede de segurança é o `KeyError` em runtime, que só aparece quando o job de DQ roda pela primeira vez contra a tabela nova (tarde, não no momento do PR).

## Regras práticas ao escrever/revisar mudança nova

- **Tabela nova no Glue Catalog**: cadastrar o ruleset em `rulesets_dq.py` no mesmo PR que cria a tabela — no mínimo `RowCount > 0`, mais as dimensões que fizerem sentido (completude de colunas-chave, unicidade de ID, validade de ranges/enums conhecidos). Não depender do `KeyError` em produção para lembrar.
- **Alarme ou notificação nova**: seguir o padrão `EventBridge → SNS` direto, sem Lambda no meio; tópico dedicado por evento (não reaproveitar um tópico existente para um evento não relacionado); policy do tópico restrita por `Condition ArnEquals aws:SourceArn`.
- **Gravação nova de DataFrame em qualquer job Glue**: considerar o padrão de guard de `glue_agg` — não sobrescrever dado existente com resultado vazio, e confirmar a escrita antes de disparar a etapa seguinte do pipeline (DQ, próximo job).
- **Log novo**: seguir o padrão já estabelecido — contador nomeado de sucesso/falha, `logger.info` em marcos, `logger.warning` em falha parcial com resumo, exceção só quando a falha é total.
- **Antes de propor uma métrica/dashboard/tracing novo**: verificar primeiro se as métricas nativas do DQDL (`enableDataQualityCloudWatchMetrics`) já resolvem o caso de uso, em vez de instrumentar do zero.
