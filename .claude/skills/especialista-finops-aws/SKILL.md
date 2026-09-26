---
name: especialista-finops-aws
description: Especialista em FinOps para os serviços AWS do projeto (S3, Lambda, Glue, Lightsail, CloudWatch, EventBridge, Athena, Secrets Manager). Use ao avaliar custo x benefício de um recurso novo ou existente, revisar lifecycle de S3, capacidade de Glue Job/Lambda, bundle do Lightsail, retenção de logs, ou ao decidir se vale a pena adicionar Budgets/anomaly detection. Cobre o racional de custo por trás de decisões já tomadas na infra e lacunas ainda não endereçadas.
---

# Especialista em FinOps — Custo x Benefício na AWS

## Papel

Você é o especialista responsável por avaliar toda mudança de infraestrutura pela lente de custo x benefício, sem sacrificar confiabilidade ou observabilidade por economia marginal. Este é um projeto de baixo volume — uma pipeline serverless com um único ambiente de produção pequeno — onde a maior alavanca de custo é **eliminar tempo ocioso** e **usar a menor capacidade que atende**, não comprar desconto de compromisso de longo prazo. Savings Plans e Reserved Instances não se aplicam a este stack: é 100% serverless on-demand (Lambda, Glue) mais uma única instância Lightsail de bundle fixo já no menor tier pago. Antes de sugerir qualquer alavanca nova, considera se ela se paga no volume real deste projeto — não recomenda otimizações de escala (Intelligent-Tiering, Savings Plans, multi-AZ redundante) que fazem sentido em workloads maiores mas só adicionam complexidade aqui.

## Fontes de verdade (ler antes de agir)

Esta skill cobre o racional de custo por trás de decisões já tomadas e lacunas não endereçadas; não duplica a descrição técnica de argumentos de recurso:

| O quê | Onde |
|---|---|
| Argumentos exatos de recurso (lifecycle S3, DPU Glue, bundle Lightsail, `depends_on`) | `especialista-infraestrutura-terraform` |
| Inventário de recursos por serviço | `infra/docs/recursos.md` |
| Schedules EventBridge, tópicos SNS, alarmes CloudWatch | `infra/docs/pipeline.md` |
| Contrato do Infracost em `terraform.yml`, secrets `infracost-api-key`/`notification-email` | `especialista-workflows-github` |
| Estrutura geral de diretórios e workflows | `estrutura-projeto` |

## Alavancas de custo já aplicadas — preservar

Ao mexer nos arquivos abaixo, não reverta essas escolhas "para simplificar" sem entender o racional de custo por trás delas.

- **S3** (`s3.tf`): lifecycle por padrão de acesso — bucket TEMP expira em 1 dia **sem** transição para IA porque é scratch efêmero do Athena (glue_agg); SOR/AUX/DQ transicionam para IA em 30d; SOT/SPEC em 90d porque são lidos com mais frequência (FilmBot/Athena consultam a SPEC continuamente). Parquet + particionamento por `year`/`media_type` reduz bytes escaneados no Athena, que cobra por dado escaneado — não trocar para um formato não-colunar nem remover partições.
- **AWS Glue PythonShell** (`glue_etl.tf`, `glue_agg.tf`, `glue_details.tf`): `max_capacity = local.pythonshell_min_capacity` (0.0625 DPU, o mínimo possível) nos 3 jobs; `max_retries = 0` evita re-execução paga em caso de falha — falha é tratada via alarme/SNS, não retry automático silencioso.
- **AWS Glue Spark — Data Quality** (`glue_data_quality.tf`): `execution_class = "FLEX"` — desconto sobre o preço on-demand em troca de possível fila de espera, aceitável porque DQ não é latência-crítica dentro do pipeline.
- **Lambda** (`lambda_api.tf`): `architecture = "arm64"` (Graviton, mais barato por GB-s que x86); `memory_size=512MB`/`timeout=900s` dimensionados para o workload real de coleta TMDB, não superdimensionados especulativamente.
- **Lightsail — só prod** (`lightsail_ia.tf`, `lightsail_scheduler.yml`, gated por `local.lightsail_prod_enabled`): FilmBot deixou de existir em dev — manter uma segunda instância (mesmo num bundle mais barato) mais o IAM user do agente e o DNS dedicado não compensava o custo de um ambiente de teste que raramente era usado. `bundle_id=var.lightsail_bundle_id` (`micro_3_0`). **Importante**: o Lightsail cobra a tarifa cheia do bundle tanto em `running` quanto em `stopped` (confirmado via fatura AWS real — só parar a instância não economiza nada). Por isso o scheduler não usa `StopInstance`/`StartInstance` — ele **destrói e recria** a instância via `terraform apply`/`destroy -target` nas janelas ociosas (desliga 00:00 BRT diário, liga 08:00 BRT diário), o que efetivamente zera a cobrança de `BundleUsage` fora do horário de uso.
- **Lightsail static IP** (`local.lightsail_prod_enabled`): um static IP "unattached" por mais de 1h cobra US$0,005/h (FAQ oficial do Lightsail) — como o IP de prod nunca é destruído (persiste sempre), essa cobrança nunca é ativada.
- **CloudWatch Logs** (`cloudwatch_logs.tf`, via `var.log_retention_days`): retenção curta por ambiente (dev=1 dia, prod=5 dias) — o projeto não tem requisito de auditoria de longo prazo, então reter logs além disso só acumula custo de armazenamento sem benefício.
- **EventBridge** (`eventbridge.tf`, via `local.eventbridge_schedule_state`): regras `DISABLED` em dev, `ENABLED` só em prod — evita cobrança de invocação de Lambda/Glue e consumo da quota da API TMDB num ambiente que não precisa rodar automaticamente.
- **Secrets Manager**: um único secret compartilhado (`filmbot_secret_arn`, com `tmdb_api_key`+`llm_api_key`+`filmbot_password`) em vez de 3 secrets separados — Secrets Manager cobra por secret/mês, não por chave dentro do secret.
- **Tags** (`locals.tf`): `local.default_resource_tags.FinOps` (de `var.finops_tag_value`) vai no `default_tags` do provider e é herdada por todo recurso automaticamente — é o pré-requisito para qualquer análise de custo por projeto no Cost Explorer/CUR. Recurso novo nunca deve ser criado com um provider/tags customizados que fujam desse default.
- **AWS Budgets** (`infra/budgets.tf`, `aws_budgets_budget.translate_monthly_cost`): budget mensal de US$5 filtrado por `Service = "Amazon Translate"`, com notificação por e-mail (`var.translate_cost_notification_email`) em 80% do gasto real e 100% do previsto. Valor apertado por escolha explícita do usuário — abaixo do custo de um evento pontual como fechar um backlog inteiro de uma vez (~US$12,19 medido nesta investigação), então um alarme aqui não necessariamente significa anomalia, pode ser um backfill/ajuste legítimo. Existe especificamente porque `var.translate_provider="aws"` (ver bullet abaixo) tirou o único teto de custo automático que o AWS Translate tinha (o cap do fallback, que só se aplica quando ele NÃO é o primário) — olha o gasto real em dólar via Cost Explorer, não uma métrica de caracteres (o `CharacterCount` do CloudWatch só existe por par de idioma, sem série agregada, e CloudWatch não permite alarme baseado em `SEARCH`, então um `aws_cloudwatch_metric_alarm` não serviria aqui). É o primeiro uso de AWS Budgets no projeto — se algum dia quiser réplicar esse padrão para outro serviço, o `cost_filter` aceita qualquer valor de `Service` do Cost Explorer, não só Translate.
- **AWS Translate como primário** (`var.translate_provider`, default `"aws"`, em `glue_details.tf`/`glue_etl.tf`): cobrado por caractere, mas sem custo prático no volume real deste projeto (histórico de US$2,90 até set/2026, medido via CloudWatch `CharacterCount`) — `resolve_translate_fn` nunca limita o serviço primário (só o fallback tem cap), por isso a trava real de custo é o AWS Budget acima, não um teto de caracteres. Não reverter para `"google"` como primário "para simplificar": foi a mudança que resolveu o "too many requests" do endpoint não-oficial do Google sob alto volume.

## Lacunas e oportunidades — avaliar custo x benefício antes de agir

- **S3 Intelligent-Tiering**: não recomendar trocar o lifecycle manual atual por Intelligent-Tiering. O padrão de acesso deste pipeline é previsível (batch ETL + leituras do FilmBot), então a taxa de monitoramento por objeto do Intelligent-Tiering tende a não se pagar aqui. Só reconsiderar se o padrão de acesso deixar de ser previsível.
- **Lambda `memory_size` fixo**: antes de ajustar, validar com métricas reais (`Max Memory Used` no CloudWatch) em vez de aumentar/reduzir especulativamente.
- **Savings Plans / Reserved Instances**: não se aplicam a este stack (serverless on-demand + Lightsail de bundle fixo já mínimo). Não sugerir como otimização — a alavanca real aqui já foi tomada (eliminar ociosidade, dimensionar mínimo).
- **AWS Budgets cobre só o Translate por ora**: `aws_budgets_budget.translate_monthly_cost` é o único budget do projeto — não existe Cost Anomaly Detection nem um budget geral por ambiente. Só expandir se pedido explicitamente; o padrão (`cost_filter` por `Service`) já está estabelecido em `infra/budgets.tf` caso outro serviço precise da mesma trava no futuro.

## Regras ao avaliar custo em mudanças novas

- Recurso novo sempre dentro do provider default do projeto (herda a tag `FinOps`) — nunca criar via provider ou bloco de tags customizado que fuja do Cost Explorer.
- Antes de aumentar qualquer capacidade (DPU de Glue Job, memória/timeout de Lambda, bundle do Lightsail, `max_concurrent_runs`), buscar evidência em métrica do CloudWatch de que o valor atual é insuficiente — não superdimensionar preventivamente.
- Bucket S3 novo: sempre definir lifecycle conforme o padrão de acesso (efêmero → expiração curta sem IA, como TEMP; consultado raramente → IA em 30-90d, como os demais), seguindo a tabela de `especialista-infraestrutura-terraform`.
- Schedule EventBridge novo: usar `local.eventbridge_schedule_state`, nunca habilitar execução automática paga em dev.
- Log group novo: usar `var.log_retention_days`, nunca hardcodar uma retenção maior que o padrão do ambiente.
- Infracost está ativo em `terraform.yml` (breakdown no Job Summary + comentário no PR) — ao alterar esse step, validar no próximo run que o breakdown continua aparecendo em ambos os lugares.
