# =============================================================================
# budgets.tf — Trava de custo do AWS Translate/Comprehend como primário
# =============================================================================
# resolve_translate_fn (shared_utils.traducao) nunca limita o serviço PRIMÁRIO — só o
# fallback tem teto (make_capped_fallback/aws_translate_monthly_max_chars). Com
# var.translate_provider="aws" (glue_details.tf/glue_etl.tf), o AWS Translate/Comprehend
# passa a ser primário e, por design, sem teto algum — o Google é que vira o fallback
# grátis. Este budget é a rede de segurança de custo desse caminho, olhando o gasto real
# em dólar (Cost Explorer) em vez de tentar somar a métrica CharacterCount do CloudWatch:
# essa métrica só existe por par de idioma (dimensão LanguagePair) e não há como somar
# todos os pares num alarme estático (não dá pra prever quais idiomas de origem vão
# aparecer no futuro, e CloudWatch não permite alarme baseado em expressão SEARCH — ver
# https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/using-search-expressions.html).
#
# limit_amount=5: pedido explícito do usuário, mais apertado que o consumo histórico real
# (~US$2,90 até set/2026) mas abaixo do custo de fechar todo o backlog pendente de uma vez
# (~US$12,19) e do cenário hipotético de retraduzir tudo que não é nativo do TMDB
# (~US$69,11, não é o caminho escolhido) — ambos medidos nesta investigação. Um evento
# pontual desses dois tipos passaria de US$5 e dispararia a notificação mesmo sem ser uma
# anomalia real; ajustar aqui se isso gerar alarme falso.
resource "aws_budgets_budget" "translate_monthly_cost" {
  name         = "${local.tmdb_prefix}-translate-monthly-cost-${var.env}"
  budget_type  = "COST"
  time_unit    = "MONTHLY"
  limit_amount = "5"
  limit_unit   = "USD"

  cost_filter {
    name = "Service"
    # Conferir a grafia exata no Cost Explorer/Billing antes do primeiro apply — um nome de
    # serviço incorreto aqui nunca dá erro, o budget só nunca encontra gasto pra somar.
    values = ["Amazon Translate"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.translate_cost_notification_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.translate_cost_notification_email]
  }

  tags = local.component_tags.glue_details
}
