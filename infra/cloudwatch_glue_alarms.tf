resource "aws_cloudwatch_event_rule" "glue_etl_failed" {
  name        = "${local.tmdb_prefix}-glue-etl-failed-${var.env}"
  description = "Notifica quando o job Glue ETL falha ou e interrompido"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_etl_job_name]
      state   = ["FAILED", "TIMEOUT", "STOPPED"]
    }
  })

  tags = local.component_tags.glue_etl
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

resource "aws_cloudwatch_event_rule" "glue_data_quality_failed" {
  name        = "${local.tmdb_prefix}-glue-data-quality-failed-${var.env}"
  description = "Notifica quando o job Glue Data Quality falha ou e interrompido"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_data_quality_job_name]
      state   = ["FAILED", "TIMEOUT", "STOPPED"]
    }
  })

  tags = local.component_tags.glue_data_quality
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
  name        = "${local.tmdb_prefix}-glue-agg-succeeded-${var.env}"
  description = "Notifica quando o job Glue AGG conclui com sucesso e a pipeline e finalizada"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_agg_job_name]
      state   = ["SUCCEEDED"]
    }
  })

  tags = local.component_tags.glue_agg
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
  name        = "${local.tmdb_prefix}-glue-agg-failed-${var.env}"
  description = "Notifica quando o job Glue AGG falha ou e interrompido"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_agg_job_name]
      state   = ["FAILED", "TIMEOUT", "STOPPED"]
    }
  })

  tags = local.component_tags.glue_agg
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

resource "aws_cloudwatch_event_rule" "glue_details_failed" {
  name        = "${local.tmdb_prefix}-glue-details-failed-${var.env}"
  description = "Notifica quando o job Glue Details falha ou e interrompido"

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Job State Change"]
    detail = {
      jobName = [local.envs.glue_details_job_name]
      state   = ["FAILED", "TIMEOUT", "STOPPED"]
    }
  })

  tags = local.component_tags.glue_details
}

resource "aws_cloudwatch_event_target" "glue_details_failed_target" {
  rule      = aws_cloudwatch_event_rule.glue_details_failed.name
  target_id = "glue-details-failed-sns"
  arn       = aws_sns_topic.glue_details_failure_notifications.arn

  input_transformer {
    input_paths = {
      job_name   = "$.detail.jobName"
      state      = "$.detail.state"
      job_run_id = "$.detail.jobRunId"
      reason     = "$.detail.message"
      event_time = "$.time"
      region     = "$.region"
    }

    input_template = local.glue_details_failed_input_template
  }
}

# =============================================================================
# STEP FUNCTIONS BACKFILL — Falha / Abort / Timeout
# =============================================================================

resource "aws_cloudwatch_event_rule" "sfn_backfill_failed" {
  name        = "${local.tmdb_prefix}-sfn-backfill-failed-${var.env}"
  description = "Notifica quando o backfill historico falha, e abortado ou expira"

  event_pattern = jsonencode({
    source        = ["aws.states"]
    "detail-type" = ["Step Functions Execution Status Change"]
    detail = {
      stateMachineArn = [aws_sfn_state_machine.backfill.arn]
      status          = ["FAILED", "TIMED_OUT", "ABORTED"]
    }
  })

  tags = local.component_tags.sfn_backfill
}

resource "aws_cloudwatch_event_target" "sfn_backfill_failed_target" {
  rule      = aws_cloudwatch_event_rule.sfn_backfill_failed.name
  target_id = "sfn-backfill-failed-sns"
  arn       = aws_sns_topic.sfn_backfill_failure_notifications.arn

  input_transformer {
    input_paths = {
      state_machine = "$.detail.stateMachineArn"
      status        = "$.detail.status"
      execution_arn = "$.detail.executionArn"
      cause         = "$.detail.cause"
      event_time    = "$.time"
      region        = "$.region"
    }

    input_template = local.sfn_backfill_failed_input_template
  }
}
