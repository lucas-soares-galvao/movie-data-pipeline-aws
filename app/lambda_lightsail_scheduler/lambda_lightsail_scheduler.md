# lambda_lightsail_scheduler — Agendador de Instância Lightsail

## O que é

Uma função Lambda que liga e desliga uma instância Lightsail (servidor leve da AWS) conforme horários programados. É acionada automaticamente pelo **EventBridge** (serviço de agendamento da AWS, funciona como um cron) em três schedules distintos, otimizando custo ao manter a instância ativa apenas nos horários de uso.

## Por que existe

A instância Lightsail (que hospeda o bot FilmBot) não precisa ficar ligada 24 horas. Desligá-la durante a madrugada e religá-la antes do horário de uso reduz o custo sem impactar a disponibilidade do serviço.

## Como funciona

1. O EventBridge dispara a Lambda com um payload JSON contendo a ação desejada (`start` ou `stop`).
2. A Lambda lê a variável de ambiente `LIGHTSAIL_INSTANCE_NAME` para identificar qual instância operar.
3. Conforme a ação recebida:
   - **`stop`**: chama `stop_instance` na API do Lightsail.
   - **`start`**: chama `start_instance` na API do Lightsail.
   - Qualquer outro valor levanta `ValueError`.
4. Retorna um dict com o status da operação (`starting` ou `stopping`) e o nome da instância.

## Agendamentos (horários BRT)

| Regra | Horário (BRT) | Dias | Ação |
|---|---|---|---|
| `lightsail_stop` | 00:00 | Todos os dias | `stop` |
| `lightsail_start_weekday` | 18:00 | Seg–Sex | `start` |
| `lightsail_start_weekend` | 08:00 | Sáb–Dom | `start` |

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Evento JSON do EventBridge com campo `action` (`"start"` ou `"stop"`) |
| **Leitura** | Variável de ambiente `LIGHTSAIL_INSTANCE_NAME` |
| **Escrita** | Nenhuma (apenas chamada à API Lightsail) |
| **Aciona** | Nenhum outro componente |

## Infraestrutura

- Só é provisionada quando `var.lightsail_enabled = true` (produção) — todos os recursos usam `count` condicional.
- Runtime Python 3.11, arquitetura arm64, timeout de 30 s.
- Permissões IAM restritas a `StartInstance`, `StopInstance` e `GetInstance` sobre a instância específica, além de escrita de logs no CloudWatch.
- Falhas de entrega do EventBridge são enviadas para a DLQ (SQS) compartilhada do projeto.
