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
# invocar a Lambda API, iniciar/monitorar os jobs Glue Data Quality e AGG,
# ler/gravar checkpoints no bucket TEMP, ler/gravar parquet no bucket SOT,
# ler/gravar partições no Glue Data Catalog (usado implicitamente pelo
# awswrangler em backfill_traducao.py), e consultar Athena + Secrets Manager
# (backfill_enriquecimento.py, que roda a lógica de enriquecimento do Glue
# Details diretamente no processo do backfill em vez de acionar esse job —
# ver run_details_and_watch_providers_for_year em
# app/glue_details/src/utils.py).
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
# POLICY 2 — Glue Jobs Data Quality e AGG (disparo fire-and-forget do Data
# Quality ao final de backfill_enriquecimento.py/backfill_data_quality.py, e o
# disparo + polling do glue_agg ao final de qualquer grupo elegível — todos
# exceto data_quality, ver step "Run backfill" em 05_backfill.yml). GetJobRun
# também é usado para o AGG porque o workflow faz polling do estado até um
# estado terminal, não é fire-and-forget.
#
# details_job_pythonshell NÃO está mais no Resource: backfill_enriquecimento.py
# passou a rodar a lógica de enriquecimento diretamente no processo do backfill
# (ver run_details_and_watch_providers_for_year em app/glue_details/src/utils.py),
# sem mais chamar start_job_run/get_job_run para o Glue Details.
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
        aws_glue_job.data_quality_job.arn,
        aws_glue_job.agg_job_pythonshell.arn,
      ]
    }]
  })
}

# =============================================================================
# POLICY 3 — Athena (backfill_enriquecimento.py, via
# run_details_and_watch_providers_for_year → fetch_ids_from_sot/
# fetch_existing_ids_from_details/fetch_ids_stale_watch_providers, que usam
# wr.athena.read_sql_query). Mesmo shape de glue_details_athena
# (infra/iam_policies.tf), já que é o mesmo código rodando fora do Glue.
# =============================================================================
resource "aws_iam_role_policy" "backfill_athena" {
  name = "${local.tmdb_prefix}-backfill-athena-${var.env}"
  role = aws_iam_role.backfill.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AthenaQueryExecution"
      Effect = "Allow"
      Action = [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
        "athena:GetWorkGroup",
      ]
      Resource = "arn:aws:athena:sa-east-1:${data.aws_caller_identity.current.account_id}:workgroup/primary"
    }]
  })
}

# =============================================================================
# POLICY 4 — Secrets Manager (backfill_enriquecimento.py: get_api_secret busca
# a chave de API do TMDB antes de chamar a API). Mesmo shape de
# glue_details_secrets (infra/iam_policies.tf).
# =============================================================================
resource "aws_iam_role_policy" "backfill_secrets" {
  name = "${local.tmdb_prefix}-backfill-secrets-${var.env}"
  role = aws_iam_role.backfill.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "GetTmdbApiKey"
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = var.filmbot_secret_arn
    }]
  })
}

# =============================================================================
# POLICY 5 — S3: checkpoints no bucket TEMP (todos os scripts, exceto
# backfill_referencias.py), tabelas discover/details movie/tv no bucket SOT
# (backfill_traducao.py, via awswrangler) e tabelas details/watch_providers
# movie/tv no bucket SOT (backfill_rename_colunas.py, via awswrangler —
# details já coberto pela mesma resource de backfill_traducao.py acima)
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
              "tmdb/${aws_glue_catalog_table.tb_watch_providers_movie_tmdb.name}/*",
              "tmdb/${aws_glue_catalog_table.tb_watch_providers_tv_tmdb.name}/*",
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
              "tmdb/athena/glue_details/*",
            ]
          }
        }
      },
      {
        # GetBucketLocation é ação de bucket (sem sub-recurso e sem chave de condition
        # "s3:prefix" no contexto da requisição), por isso não pode entrar no statement
        # acima com Condition por prefixo — precisa de statement próprio. Sem ela, o
        # Athena StartQueryExecution falha com "Unable to verify/create output bucket"
        # ao tentar validar o bucket de output (S3_OUTPUT_LOCATION = bucket TEMP). Mesma
        # permissão já concedida à role glue_details_role (infra/iam_policies.tf).
        Sid      = "GetBucketLocationTemp"
        Effect   = "Allow"
        Action   = "s3:GetBucketLocation"
        Resource = aws_s3_bucket.temporary_bucket.arn
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
        # Resultados temporários de wr.athena.read_sql_query — path hardcoded dentro de
        # app/glue_details/src/utils.py (fetch_ids_from_sot e afins), reaproveitado sem
        # alteração pelo backfill_enriquecimento.py. Mesmo prefixo já concedido à role
        # glue_details_role (Sid "AthenaTemp" em infra/iam_policies.tf).
        Sid    = "AthenaResultsGlueDetails"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = "${aws_s3_bucket.temporary_bucket.arn}/tmdb/athena/glue_details/*"
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
      {
        Sid    = "ReadWriteWatchProvidersForRenameColunas"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = [
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_watch_providers_movie_tmdb.name}/*",
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_watch_providers_tv_tmdb.name}/*",
        ]
      },
    ]
  })
}

# =============================================================================
# POLICY 6 — Glue Data Catalog (backfill_traducao.py e backfill_rename_colunas.py,
# via chamadas implícitas do awswrangler: GetTable/GetPartitions ao ler,
# BatchCreatePartition/BatchDeletePartition/UpdateTable ao escrever com
# mode="overwrite_partitions"; e backfill_enriquecimento.py, cujo Athena
# precisa de GetTable/GetPartitions nas tabelas de discover para resolver
# fetch_ids_from_sot). Restrito às tabelas de discover, details e
# watch_providers — mesmas databases (movie/tv), por isso sem ARNs de
# database adicionais.
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
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_movie_tmdb.database_name}/${aws_glue_catalog_table.tb_movie_tmdb.name}",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_tv_tmdb.database_name}/${aws_glue_catalog_table.tb_tv_tmdb.name}",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_details_movie_tmdb.database_name}/${aws_glue_catalog_table.tb_details_movie_tmdb.name}",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_details_tv_tmdb.database_name}/${aws_glue_catalog_table.tb_details_tv_tmdb.name}",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_watch_providers_movie_tmdb.database_name}/${aws_glue_catalog_table.tb_watch_providers_movie_tmdb.name}",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_watch_providers_tv_tmdb.database_name}/${aws_glue_catalog_table.tb_watch_providers_tv_tmdb.name}",
      ]
    }]
  })
}

# =============================================================================
# POLICY 7 — AWS Translate. Usado quando TRANSLATE_PROVIDER=aws é escolhido em
# qualquer backfill manual (backfill_traducao.py, backfill_historico.py,
# backfill_referencias.py, backfill_enriquecimento.py) — default é "google"
# (grátis); "aws" existe para testar um período menor sob demanda. Mesmo com
# default "google", o AWS Translate também é acionado como fallback automático
# quando o Google falha ou devolve o texto sem alteração (resolve_translate_fn
# em shared_utils.traducao). Mantido o Sid histórico "TranslateFallback" para
# não gerar diff de Terraform sem necessidade. translate:TranslateText não tem
# restrição por recurso na AWS (Resource = "*"). comprehend:DetectDominantLanguage
# é obrigatório porque translate_text_aws sempre chama TranslateText com
# SourceLanguageCode="auto", que aciona o Comprehend internamente para detectar
# o idioma de origem; também não suporta restrição por recurso.
# =============================================================================
resource "aws_iam_role_policy" "backfill_translate" {
  name = "${local.tmdb_prefix}-backfill-translate-${var.env}"
  role = aws_iam_role.backfill.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "TranslateFallback"
      Effect   = "Allow"
      Action   = ["translate:TranslateText", "comprehend:DetectDominantLanguage"]
      Resource = "*"
    }]
  })
}

output "backfill_role_arn" {
  description = "ARN da role de backfill manual (usar como valor da secret AWS_ASSUME_ROLE_ARN_BACKFILL_{DEV|PROD})"
  value       = aws_iam_role.backfill.arn
}
