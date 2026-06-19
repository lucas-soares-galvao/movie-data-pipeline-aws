# =============================================================================
# sqs.tf — Dead Letter Queue para eventos EventBridge que falharam
# =============================================================================
# Quando o EventBridge não consegue invocar o target (Lambda ou Step Functions),
# o evento é enviado para esta fila SQS em vez de ser descartado silenciosamente.
# Um alarme CloudWatch monitora a fila e notifica via SNS quando há mensagens.
# =============================================================================

resource "aws_sqs_queue" "eventbridge_dlq" {
  name                      = "${local.tmdb_prefix}-eventbridge-dlq-${var.env}"
  message_retention_seconds = 1209600 # 14 dias
  tags                      = local.component_tags.eventbridge
}

resource "aws_sqs_queue_policy" "eventbridge_dlq" {
  queue_url = aws_sqs_queue.eventbridge_dlq.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowEventBridgeSendMessage"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.eventbridge_dlq.arn
      Condition = {
        ArnLike = {
          "aws:SourceArn" = "arn:aws:events:sa-east-1:${data.aws_caller_identity.current.account_id}:rule/${local.tmdb_prefix}-*"
        }
      }
    }]
  })
}
