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
- **Lightsail — só prod** (`lightsail_ia.tf`, `lightsail_scheduler.yml`, gated por `local.lightsail_prod_enabled`): FilmBot deixou de existir em dev — manter uma segunda instância (mesmo num bundle mais barato) mais o IAM user do agente e o DNS dedicado não compensava o custo de um ambiente de teste que raramente era usado. `bundle_id=var.lightsail_bundle_id` (`micro_3_0`). **Importante**: o Lightsail cobra a tarifa cheia do bundle tanto em `running` quanto em `stopped` (confirmado via fatura AWS real — só parar a instância não economiza nada). Por isso o scheduler não usa `StopInstance`/`StartInstance` — ele **destrói e recria** a instância via `terraform apply`/`destroy -target` nas janelas ociosas (**liga só sábado e domingo às 08:00 BRT, desliga todo dia às 00:00 BRT** — o FilmBot não é usado na semana; de segunda a sexta o desligar é no-op e serve de rede de segurança contra um push em `main` que recrie a instância), o que efetivamente zera a cobrança de `BundleUsage` fora do horário de uso.
- **Lightsail static IP** (`local.lightsail_prod_enabled`): um static IP "unattached" por mais de 1h cobra US$0,005/h (FAQ oficial do Lightsail). O IP de prod nunca é destruído, mas **fica sem instância anexada** enquanto o scheduler mantém a instância destruída — então essa cobrança **é ativada** (`USE1-UnusedStaticIP`). Confirmado no Cost Explorer de out/2026, ainda com a agenda diária (instância destruída 8h/dia): 248h × US$0,005 = US$1,24 de US$5,90 do Lightsail (o restante, US$4,66, é `USE1-BundleUsage:1GB`, 496h × US$0,0094; transferência de dados US$0,00). Com a agenda de fim de semana (instância existe 144h em out/2026, IP parado 600h) a estimativa é US$1,35 de instância + US$3,00 de IP = **~US$4,35/mês** (economia de ~US$1,55/mês vs. a agenda diária; ~US$2,65 vs. 24/7, US$7,00). É um custo aceito: manter o IP evita atualizar o DNS no registro.br a cada recriação. Cada hora desligada economiza US$0,0094 de bundle mas custa US$0,005 de IP (ganho líquido de só ~US$0,0044/h), e agora o IP parado já custa mais que a instância — não vale ampliar a janela de desligamento por economia marginal. O desligar diário (e não só dom/seg) é deliberado: sem ele, um push em `main` na segunda recriaria a instância (apply completo) e ela ficaria ligada até o fim de semana (~120h, ~US$1,13), anulando a economia.
- **CloudWatch Logs** (`cloudwatch_logs.tf`, via `var.log_retention_days`): retenção curta por ambiente (dev=1 dia, prod=5 dias) — o projeto não tem requisito de auditoria de longo prazo, então reter logs além disso só acumula custo de armazenamento sem benefício.
- **EventBridge** (`eventbridge.tf`, via `local.eventbridge_schedule_state`): regras `DISABLED` em dev, `ENABLED` só em prod — evita cobrança de invocação de Lambda/Glue e consumo da quota da API TMDB num ambiente que não precisa rodar automaticamente.
- **Secrets Manager**: um único secret compartilhado (`filmbot_secret_arn`, com `tmdb_api_key`+`llm_api_key`+`filmbot_password`) em vez de 3 secrets separados — Secrets Manager cobra por secret/mês, não por chave dentro do secret.
- **Tags** (`locals.tf`): `local.default_resource_tags.FinOps` (de `var.finops_tag_value`) vai no `default_tags` do provider e é herdada por todo recurso automaticamente — é o pré-requisito para qualquer análise de custo por projeto no Cost Explorer/CUR. Recurso novo nunca deve ser criado com um provider/tags customizados que fujam desse default.
- **Tradução/detecção de idioma via LLM** (`shared_utils.traducao_llm`/`idioma_llm`, OpenRouter via `litellm`): o controle de gasto é feito direto no painel do OpenRouter (limite de gasto configurável lá), fora da AWS, sem equivalente via Cost Explorer/CloudWatch e sem budget na AWS. Modelos `qwen/qwen3.8-flash` (primário) e `deepseek/deepseek-v4.1-flash` (fallback), de baixo custo por token no volume deste projeto. O gasto de cada unidade/execução também aparece no log (`LLM [...]: … | tokens a in / b out | US$ …`, de `shared_utils.llm_metrics`), lido de `usage.cost` da resposta do OpenRouter — o `litellm.completion_cost()` não conhece esses modelos, então não serve para isso; a taxa de uso do fallback (`deepseek`) sai da contagem de chamadas por modelo da mesma linha.

## Lacunas e oportunidades — avaliar custo x benefício antes de agir

- **S3 Intelligent-Tiering**: não recomendar trocar o lifecycle manual atual por Intelligent-Tiering. O padrão de acesso deste pipeline é previsível (batch ETL + leituras do FilmBot), então a taxa de monitoramento por objeto do Intelligent-Tiering tende a não se pagar aqui. Só reconsiderar se o padrão de acesso deixar de ser previsível.
- **Lambda `memory_size` fixo**: antes de ajustar, validar com métricas reais (`Max Memory Used` no CloudWatch) em vez de aumentar/reduzir especulativamente.
- **Savings Plans / Reserved Instances**: não se aplicam a este stack (serverless on-demand + Lightsail de bundle fixo já mínimo). Não sugerir como otimização — a alavanca real aqui já foi tomada (eliminar ociosidade, dimensionar mínimo).
- **Sem AWS Budgets nem Cost Anomaly Detection hoje**: o budget do Translate (`aws_budgets_budget.translate_monthly_cost`) foi removido quando a tradução migrou para LLM, e não existe um budget geral por ambiente. Só adicionar se pedido explicitamente.

## Regras ao avaliar custo em mudanças novas

- Recurso novo sempre dentro do provider default do projeto (herda a tag `FinOps`) — nunca criar via provider ou bloco de tags customizado que fuja do Cost Explorer.
- Antes de aumentar qualquer capacidade (DPU de Glue Job, memória/timeout de Lambda, bundle do Lightsail, `max_concurrent_runs`), buscar evidência em métrica do CloudWatch de que o valor atual é insuficiente — não superdimensionar preventivamente.
- Bucket S3 novo: sempre definir lifecycle conforme o padrão de acesso (efêmero → expiração curta sem IA, como TEMP; consultado raramente → IA em 30-90d, como os demais), seguindo a tabela de `especialista-infraestrutura-terraform`.
- Schedule EventBridge novo: usar `local.eventbridge_schedule_state`, nunca habilitar execução automática paga em dev.
- Log group novo: usar `var.log_retention_days`, nunca hardcodar uma retenção maior que o padrão do ambiente.
- Infracost está ativo em `terraform.yml` (breakdown no Job Summary + comentário no PR) — ao alterar esse step, validar no próximo run que o breakdown continua aparecendo em ambos os lugares.
