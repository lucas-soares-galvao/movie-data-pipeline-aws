locals {
  glue_src_path  = "${path.root}/../app"
  glue_role_name = var.create_role ? aws_iam_role.glue_job_role[0].name : data.aws_iam_role.glue_job_role[0].name
  glue_role_arn  = var.create_role ? aws_iam_role.glue_job_role[0].arn : data.aws_iam_role.glue_job_role[0].arn
}