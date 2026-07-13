# =============================================================================
# iam_backfill.tf — Role e políticas IAM de privilégio mínimo para o backfill
# manual sob demanda (05_backfill.yml)
# =============================================================================
#
# Antes desta role, o workflow 05_backfill.yml assumia a mesma role de CI/CD
# (aws_iam_role.github_actions, em iam_cicd.tf) usada para o terraform apply
# completo — o que dava ao backfill manual acesso a IAM CRUD, gestão de
# buckets S3, Lightsail, etc., sem nenhuma necessidade real.
#
# Esta role cobre exatamente o que os scripts scripts/backfill_*.py usam:
# invocar a Lambda API, iniciar/monitorar os jobs Glue Details e Data Quality,
# ler/gravar checkpoints no bucket TEMP, ler/gravar parquet no bucket SOT, e
# ler/gravar partições no Glue Data Catalog (usado implicitamente pelo
# awswrangler em backfill_traducao.py).
#
# Não confundir com aws_iam_role.sfn_backfill_role (iam_roles.tf), que serve
# o backfill anual automático via Step Functions — mecanismo separado,
# assumido pelo serviço states.amazonaws.com, não por este workflow.
# =============================================================================

locals {
  # Restringe a role ao branch que resolve para o mesmo ambiente em
  # 05_backfill.yml (develop→dev, main→prod). Reforço de segurança além do
  # wildcard usado pela trust policy da role de CI/CD (que não restringe por
  # ref, só por repo).
  backfill_allowed_branch = { dev = "develop", prod = "main" }[var.env]
}

resource "aws_iam_role" "backfill" {
  name = "${local.tmdb_prefix}-backfill-role-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = [
            "repo:lucas-soares-galvao/*:ref:refs/heads/${local.backfill_allowed_branch}",
          ]
        }
      }
    }]
  })

  # Mesma duração da role de CI/CD (1h) — o mecanismo de retry do
  # 05_backfill.yml usa --duration-seconds 3600 hardcoded ao renovar a
  # credencial expirada via assume-role-with-web-identity.
  max_session_duration = 3600

  depends_on = [terraform_data.cicd_policies_ready]

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

# =============================================================================
# POLICY 1 — Invoke Lambda (backfill_historico.py, backfill_referencias.py)
# =============================================================================
resource "aws_iam_role_policy" "backfill_invoke_lambda" {
  name = "${local.tmdb_prefix}-backfill-invoke-lambda-${var.env}"
  role = aws_iam_role.backfill.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "InvokeLambdaApi"
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.simple_lambda.arn
    }]
  })
}

# =============================================================================
# POLICY 2 — Glue Jobs Details e Data Quality (backfill_enriquecimento.py,
# backfill_data_quality.py)
# =============================================================================
resource "aws_iam_role_policy" "backfill_glue_jobs" {
  name = "${local.tmdb_prefix}-backfill-glue-jobs-${var.env}"
  role = aws_iam_role.backfill.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "StartAndMonitorBackfillJobs"
      Effect = "Allow"
      Action = [
        "glue:StartJobRun",
        "glue:GetJobRun",
      ]
      Resource = [
        aws_glue_job.details_job_pythonshell.arn,
        aws_glue_job.data_quality_job.arn,
      ]
    }]
  })
}

# =============================================================================
# POLICY 3 — S3: checkpoints no bucket TEMP (todos os scripts, exceto
# backfill_referencias.py) e tabelas discover/details movie/tv no bucket SOT
# (backfill_traducao.py, via awswrangler)
# =============================================================================
resource "aws_iam_role_policy" "backfill_s3" {
  name = "${local.tmdb_prefix}-backfill-s3-${var.env}"
  role = aws_iam_role.backfill.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # awswrangler faz ListObjectsV2 para descobrir partições antes de
        # ler/escrever — exige o bucket inteiro como Resource, restrito por
        # Condition ao prefixo.
        Sid      = "ListScopedPrefixesSot"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.sot_bucket.arn
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "tmdb/${aws_glue_catalog_table.tb_movie_tmdb.name}/*",
              "tmdb/${aws_glue_catalog_table.tb_tv_tmdb.name}/*",
              "tmdb/${aws_glue_catalog_table.tb_details_movie_tmdb.name}/*",
              "tmdb/${aws_glue_catalog_table.tb_details_tv_tmdb.name}/*",
            ]
          }
        }
      },
      {
        Sid      = "ListScopedPrefixesTemp"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.temporary_bucket.arn
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "tmdb/backfill_checkpoints/*",
            ]
          }
        }
      },
      {
        Sid    = "CheckpointReadWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = "${aws_s3_bucket.temporary_bucket.arn}/tmdb/backfill_checkpoints/*"
      },
      {
        Sid    = "ReadDiscoverForTraducao"
        Effect = "Allow"
        Action = "s3:GetObject"
        Resource = [
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_movie_tmdb.name}/*",
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_tv_tmdb.name}/*",
        ]
      },
      {
        Sid    = "ReadWriteDetailsForTraducao"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = [
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_details_movie_tmdb.name}/*",
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_details_tv_tmdb.name}/*",
        ]
      },
    ]
  })
}

# =============================================================================
# POLICY 4 — Glue Data Catalog (só backfill_traducao.py, via chamadas
# implícitas do awswrangler: GetTable/GetPartitions ao ler,
# BatchCreatePartition/BatchDeletePartition/UpdateTable ao escrever com
# mode="overwrite_partitions"). Restrito às 2 tabelas de details.
# =============================================================================
resource "aws_iam_role_policy" "backfill_glue_catalog" {
  name = "${local.tmdb_prefix}-backfill-glue-catalog-${var.env}"
  role = aws_iam_role.backfill.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "TranslateDetailsCatalogAccess"
      Effect = "Allow"
      Action = [
        "glue:GetDatabase",
        "glue:GetTable",
        "glue:UpdateTable",
        "glue:GetPartitions",
        "glue:BatchCreatePartition",
        "glue:BatchDeletePartition",
      ]
      Resource = [
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_table.tb_details_movie_tmdb.database_name}",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_table.tb_details_tv_tmdb.database_name}",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_details_movie_tmdb.database_name}/${aws_glue_catalog_table.tb_details_movie_tmdb.name}",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_details_tv_tmdb.database_name}/${aws_glue_catalog_table.tb_details_tv_tmdb.name}",
      ]
    }]
  })
}

# =============================================================================
# POLICY 5 — AWS Translate. Usado quando TRANSLATE_PROVIDER=aws é escolhido em
# qualquer backfill manual (backfill_traducao.py, backfill_historico.py,
# backfill_referencias.py, backfill_enriquecimento.py) — default é "google"
# (grátis); "aws" existe para testar um período menor sob demanda. Mantido o
# Sid histórico "TranslateFallback" para não gerar diff de Terraform sem
# necessidade. translate:TranslateText não tem restrição por recurso na AWS
# (Resource = "*").
# =============================================================================
resource "aws_iam_role_policy" "backfill_translate" {
  name = "${local.tmdb_prefix}-backfill-translate-${var.env}"
  role = aws_iam_role.backfill.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "TranslateFallback"
      Effect   = "Allow"
      Action   = ["translate:TranslateText"]
      Resource = "*"
    }]
  })
}

output "backfill_role_arn" {
  description = "ARN da role de backfill manual (usar como valor da secret AWS_ASSUME_ROLE_ARN_BACKFILL_{DEV|PROD})"
  value       = aws_iam_role.backfill.arn
}
