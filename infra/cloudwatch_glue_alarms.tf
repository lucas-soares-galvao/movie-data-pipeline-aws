# Raciocinio: cria eventos de monitoramento do Glue e notifica estados relevantes de execucao.

resource "aws_cloudwatch_event_rule" "glue_etl_succeeded" {
  name        = "glue-etl-succeeded-${var.env}"
  description = "Notifica quando o job Glue ETL conclui com sucesso"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_etl_job_name]
      state   = ["SUCCEEDED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "glue_etl_succeeded_target" {
  rule      = aws_cloudwatch_event_rule.glue_etl_succeeded.name
  target_id = "glue-etl-succeeded-sns"
  arn       = aws_sns_topic.glue_etl_success_notifications.arn

  input_transformer {
    input_paths = {
      job_name   = "$.detail.jobName"
      state      = "$.detail.state"
      job_run_id = "$.detail.jobRunId"
      event_time = "$.time"
      region     = "$.region"
    }

  input_template = local.glue_etl_succeeded_input_template
  }
}

resource "aws_cloudwatch_event_rule" "glue_etl_failed" {
  name        = "glue-etl-failed-${var.env}"
  description = "Notifica quando o job Glue ETL falha ou e interrompido"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_etl_job_name]
      state   = ["FAILED", "TIMEOUT", "STOPPED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "glue_etl_failed_target" {
  rule      = aws_cloudwatch_event_rule.glue_etl_failed.name
  target_id = "glue-etl-failed-sns"
  arn       = aws_sns_topic.glue_etl_failure_notifications.arn

  input_transformer {
    input_paths = {
      job_name   = "$.detail.jobName"
      state      = "$.detail.state"
      job_run_id = "$.detail.jobRunId"
      reason     = "$.detail.message"
      event_time = "$.time"
      region     = "$.region"
    }

  input_template = local.glue_etl_failed_input_template
  }
}

resource "aws_cloudwatch_event_rule" "glue_data_quality_succeeded" {
  name        = "glue-data-quality-succeeded-${var.env}"
  description = "Notifica quando o job Glue Data Quality conclui com sucesso"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_data_quality_job_name]
      state   = ["SUCCEEDED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "glue_data_quality_succeeded_target" {
  rule      = aws_cloudwatch_event_rule.glue_data_quality_succeeded.name
  target_id = "glue-data-quality-succeeded-sns"
  arn       = aws_sns_topic.glue_data_quality_success_notifications.arn

  input_transformer {
    input_paths = {
      job_name   = "$.detail.jobName"
      state      = "$.detail.state"
      job_run_id = "$.detail.jobRunId"
      event_time = "$.time"
      region     = "$.region"
    }

  input_template = local.glue_data_quality_succeeded_input_template
  }
}

resource "aws_cloudwatch_event_rule" "glue_data_quality_failed" {
  name        = "glue-data-quality-failed-${var.env}"
  description = "Notifica quando o job Glue Data Quality falha ou e interrompido"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_data_quality_job_name]
      state   = ["FAILED", "TIMEOUT", "STOPPED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "glue_data_quality_failed_target" {
  rule      = aws_cloudwatch_event_rule.glue_data_quality_failed.name
  target_id = "glue-data-quality-failed-sns"
  arn       = aws_sns_topic.glue_data_quality_failure_notifications.arn

  input_transformer {
    input_paths = {
      job_name   = "$.detail.jobName"
      state      = "$.detail.state"
      job_run_id = "$.detail.jobRunId"
      reason     = "$.detail.message"
      event_time = "$.time"
      region     = "$.region"
    }

  input_template = local.glue_data_quality_failed_input_template
  }
}

resource "aws_cloudwatch_event_rule" "glue_agg_succeeded" {
  name        = "glue-agg-succeeded-${var.env}"
  description = "Notifica quando o job Glue AGG conclui com sucesso"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_agg_job_name]
      state   = ["SUCCEEDED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "glue_agg_succeeded_target" {
  rule      = aws_cloudwatch_event_rule.glue_agg_succeeded.name
  target_id = "glue-agg-succeeded-sns"
  arn       = aws_sns_topic.glue_agg_success_notifications.arn

  input_transformer {
    input_paths = {
      job_name   = "$.detail.jobName"
      state      = "$.detail.state"
      job_run_id = "$.detail.jobRunId"
      event_time = "$.time"
      region     = "$.region"
    }

  input_template = local.glue_agg_succeeded_input_template
  }
}

resource "aws_cloudwatch_event_rule" "glue_agg_failed" {
  name        = "glue-agg-failed-${var.env}"
  description = "Notifica quando o job Glue AGG falha ou e interrompido"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_agg_job_name]
      state   = ["FAILED", "TIMEOUT", "STOPPED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "glue_agg_failed_target" {
  rule      = aws_cloudwatch_event_rule.glue_agg_failed.name
  target_id = "glue-agg-failed-sns"
  arn       = aws_sns_topic.glue_agg_failure_notifications.arn

  input_transformer {
    input_paths = {
      job_name   = "$.detail.jobName"
      state      = "$.detail.state"
      job_run_id = "$.detail.jobRunId"
      reason     = "$.detail.message"
      event_time = "$.time"
      region     = "$.region"
    }

  input_template = local.glue_agg_failed_input_template
  }
}
