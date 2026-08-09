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
# iniciar/monitorar os jobs Glue Data Quality e AGG, ler/gravar checkpoints
# no bucket TEMP, ler/gravar JSON bruto no bucket SOR e parquet no bucket
# SOT, ler/gravar partições no Glue Data Catalog (usado implicitamente pelo
# awswrangler em backfill_traducao.py), e consultar Athena + Secrets Manager
# (backfill_enriquecimento.py, que roda a lógica de enriquecimento do Glue
# Details diretamente no processo do backfill em vez de acionar esse job —
# ver run_details_and_watch_providers_for_year em
# app/glue_details/src/utils.py — e backfill_changes.py, que aplica o mesmo
# racional ao modo changes: coleta os IDs mudados e roda o enriquecimento
# diretamente no processo, sem acionar Lambda nem o job Glue Details).
# backfill_referencias.py e backfill_discover.py aplicam o mesmo racional à
# coleta de genre/configuration/watch_providers_ref e discover,
# respectivamente: chamam a API do TMDB e gravam JSON no SOR + Parquet no
# SOT diretamente no processo, sem acionar a Lambda nem o job Glue ETL.
# Nenhum dos 7 scripts invoca a Lambda API hoje.
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
# POLICY 1 — Glue Jobs Data Quality e AGG (disparo fire-and-forget do Data
# Quality ao final de backfill_discover.py/backfill_enriquecimento.py/
# backfill_data_quality.py/backfill_changes.py, e o disparo + polling do
# glue_agg ao final de qualquer grupo elegível — todos exceto data_quality,
# ver step "Run backfill" em 05_backfill.yml). GetJobRun também é usado para
# o AGG porque o workflow faz polling do estado até um estado terminal, não
# é fire-and-forget.
#
# details_job_pythonshell NÃO está mais no Resource: backfill_enriquecimento.py
# e backfill_changes.py passaram a rodar a lógica de enriquecimento diretamente
# no processo do backfill (ver run_details_and_watch_providers_for_year e
# process_changed_ids em app/glue_details/src/utils.py), sem mais chamar
# start_job_run/get_job_run para o Glue Details. glue_etl_job_pythonshell
# também nunca esteve no Resource — backfill_discover.py sempre rodou (agora
# in-process) a transformação equivalente ao Glue ETL sem acionar esse job.
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
# POLICY 2 — Athena (backfill_enriquecimento.py, via
# run_details_and_watch_providers_for_year → fetch_ids_from_sot/
# fetch_existing_ids_from_details/fetch_ids_stale_watch_providers; e
# backfill_changes.py, via resolve_matched_ids_for_changed_ids, que cruza os
# IDs mudados com a tabela discover — ambas usam wr.athena.read_sql_query).
# Mesmo shape de glue_details_athena (infra/iam_policies.tf), já que é o mesmo
# código rodando fora do Glue.
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
# POLICY 3 — Secrets Manager (backfill_discover.py, backfill_enriquecimento.py
# e backfill_changes.py: get_api_secret busca a chave de API do TMDB antes de
# chamar a API). Mesmo shape de glue_details_secrets (infra/iam_policies.tf).
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
# POLICY 4 — S3: checkpoints no bucket TEMP (todos os scripts, exceto
# backfill_referencias.py/backfill_changes.py), tabelas discover/details
# movie/tv no bucket SOT (backfill_traducao.py e backfill_discover.py, via
# awswrangler), tabelas details/watch_providers movie/tv no bucket SOT
# (backfill_rename_colunas.py, via awswrangler — details já coberto pela
# mesma resource de backfill_traducao.py acima), JSON bruto no bucket SOR e
# as 6 tabelas de referência no bucket SOT (backfill_referencias.py — ver
# comentários nos statements abaixo), e JSON bruto de discover no bucket SOR
# (backfill_discover.py — ver comentários nos statements abaixo)
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
              "tmdb/${aws_glue_catalog_table.tb_genre_movie_tmdb.name}/*",
              "tmdb/${aws_glue_catalog_table.tb_genre_tv_tmdb.name}/*",
              "tmdb/${aws_glue_catalog_table.tb_configuration_languages_tmdb.name}/*",
              "tmdb/${aws_glue_catalog_table.tb_configuration_countries_tmdb.name}/*",
              "tmdb/${aws_glue_catalog_table.tb_watch_providers_ref_movie_tmdb.name}/*",
              "tmdb/${aws_glue_catalog_table.tb_watch_providers_ref_tv_tmdb.name}/*",
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
              "tmdb/changes/*",
            ]
          }
        }
      },
      {
        # read_from_sor para table_type="discover" (backfill_discover.py) lê uma pasta
        # inteira via wr.s3.read_json (uma página por objeto, ver collect_discover_data em
        # app/lambda_api/src/utils.py) — precisa listar objetos antes de ler, diferente de
        # genre/configuration/watch_providers_ref (arquivo único, GetObject direto, sem
        # ListBucket). Único ListBucket sobre o bucket SOR nesta policy.
        Sid      = "ListScopedPrefixesSor"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.sor_bucket.arn
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "tmdb/discover/movie/*",
              "tmdb/discover/tv/*",
            ]
          }
        }
      },
      {
        # GetBucketLocation é ação de bucket (sem sub-recurso e sem chave de condition
        # "s3:prefix" no contexto da requisição), por isso não pode entrar nos statements
        # acima com Condition por prefixo — precisa de statement próprio. Sem ela, o
        # Athena StartQueryExecution falha com "Unable to verify/create output bucket" ao
        # validar o bucket de output (S3_OUTPUT_LOCATION = bucket TEMP), e o awswrangler
        # (wr.s3.read_parquet/to_parquet contra discover/details/watch_providers no SOT,
        # dentro de run_details_and_watch_providers_for_year, e contra as 6 tabelas de
        # referência no SOT, dentro de backfill_referencias.py) também depende dela para
        # resolver o bucket antes de ler/escrever. Mesmo par de buckets (SOT + TEMP) já
        # concedido à role glue_details_role (infra/iam_policies.tf) para o mesmo código.
        Sid    = "GetBucketLocationSorSotTemp"
        Effect = "Allow"
        Action = "s3:GetBucketLocation"
        Resource = [
          aws_s3_bucket.sor_bucket.arn,
          aws_s3_bucket.sot_bucket.arn,
          aws_s3_bucket.temporary_bucket.arn,
        ]
      },
      {
        # JSON bruto gravado por collect_genre_data/collect_configuration_data/
        # collect_watch_providers_ref (backfill_referencias.py, chamadas diretamente no
        # processo do backfill — mesmo código que a Lambda API usaria, ver
        # app/lambda_api/src/utils.py) e lido de volta logo em seguida por read_from_sor
        # (app/glue_etl/src/utils.py, _read_json_from_s3) para a transformação equivalente
        # ao Glue ETL — mesmo par escrever-e-reler que o Glue ETL real faz entre a Lambda e
        # o próprio job. GetObject além de PutObject, por isso.
        Sid    = "ReadWriteReferenceRawDataInSor"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
        ]
        Resource = [
          "${aws_s3_bucket.sor_bucket.arn}/tmdb/genre/movie/*",
          "${aws_s3_bucket.sor_bucket.arn}/tmdb/genre/tv/*",
          "${aws_s3_bucket.sor_bucket.arn}/tmdb/configuration/languages/*",
          "${aws_s3_bucket.sor_bucket.arn}/tmdb/configuration/countries/*",
          "${aws_s3_bucket.sor_bucket.arn}/tmdb/watch_providers_ref/movie/*",
          "${aws_s3_bucket.sor_bucket.arn}/tmdb/watch_providers_ref/tv/*",
        ]
      },
      {
        # JSON bruto gravado por collect_discover_data (backfill_discover.py, chamada
        # diretamente no processo do backfill — mesmo código que a Lambda API usaria, ver
        # app/lambda_api/src/utils.py), uma página por objeto, e lido de volta por
        # read_from_sor (app/glue_etl/src/utils.py, wr.s3.read_json) para a transformação
        # equivalente ao Glue ETL. Mesmo par escrever-e-reler de ReadWriteReferenceRawDataInSor
        # acima, para discover em vez de genre/configuration/watch_providers_ref.
        Sid    = "ReadWriteDiscoverRawDataInSor"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
        ]
        Resource = [
          "${aws_s3_bucket.sor_bucket.arn}/tmdb/discover/movie/*",
          "${aws_s3_bucket.sor_bucket.arn}/tmdb/discover/tv/*",
        ]
      },
      {
        # Parquet das 6 tabelas de referência gravado por write_parquet_to_sot
        # (backfill_referencias.py — mesma função usada pelo Glue ETL real, ver
        # app/glue_etl/src/utils.py). mode="overwrite" faz list+delete antes de escrever
        # (ver ListScopedPrefixesSot acima), por isso também precisa de DeleteObject, não
        # só GetObject/PutObject.
        Sid    = "ReadWriteReferenceTablesInSot"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = [
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_genre_movie_tmdb.name}/*",
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_genre_tv_tmdb.name}/*",
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_configuration_languages_tmdb.name}/*",
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_configuration_countries_tmdb.name}/*",
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_watch_providers_ref_movie_tmdb.name}/*",
          "${aws_s3_bucket.sot_bucket.arn}/tmdb/${aws_glue_catalog_table.tb_watch_providers_ref_tv_tmdb.name}/*",
        ]
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
        # Lista de IDs mudados gravada por collect_changes_data (agora chamada diretamente
        # por backfill_changes.py, não mais pela Lambda) e os logs de descartados/ambíguos
        # gravados por resolve_matched_ids_for_changed_ids — mesmo prefixo já usado pela
        # lambda_api real (ver infra/iam_policies.tf) para o mesmo código.
        Sid    = "ChangesS3Handoff"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = "${aws_s3_bucket.temporary_bucket.arn}/tmdb/changes/*"
      },
      {
        # GetObject: backfill_traducao.py só lê as tabelas discover (não escreve). PutObject/
        # DeleteObject: backfill_discover.py escreve write_parquet_to_sot(partition_cols=
        # ["year"], mode="overwrite_partitions") — precisa apagar a partição do ano antes de
        # regravar (BatchDeletePartition no Catalog, DeleteObject nos arquivos Parquet
        # correspondentes), além de GetObject/PutObject para reler e escrever.
        Sid    = "ReadWriteDiscoverSot"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
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
# POLICY 5 — Glue Data Catalog (backfill_traducao.py e backfill_rename_colunas.py,
# via chamadas implícitas do awswrangler: GetTable/GetPartition(s) ao ler,
# BatchCreatePartition/BatchDeletePartition/UpdateTable ao escrever com
# mode="overwrite_partitions"; backfill_enriquecimento.py, cujo Athena precisa
# de GetTable/GetPartition/GetPartitions nas tabelas de discover para resolver
# fetch_ids_from_sot; e backfill_changes.py, mesma necessidade via
# resolve_matched_ids_for_changed_ids — GetPartition, no singular, é chamada
# separadamente de GetPartitions pelo motor do Athena e precisa das duas,
# mesmo padrão já usado por todas as policies de Glue Catalog em
# infra/iam_policies.tf). Restrito às tabelas de discover, details e
# watch_providers — mesmas databases (movie/tv), por isso sem ARNs de
# database adicionais. Statement à parte (DeleteCtasTempTable) para
# CreateTable/DeleteTable da tabela temporária de CTAS usada por
# backfill_changes.py — ver comentário no statement.
# =============================================================================
resource "aws_iam_role_policy" "backfill_glue_catalog" {
  name = "${local.tmdb_prefix}-backfill-glue-catalog-${var.env}"
  role = aws_iam_role.backfill.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TranslateDetailsCatalogAccess"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:UpdateTable",
          "glue:GetPartition",
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
      },
      {
        # resolve_matched_ids_for_changed_ids (backfill_changes.py) usa ctas_approach=True
        # (ARRAY_AGG exige CTAS). O awswrangler cria uma tabela temporária com nome gerado no
        # Glue Catalog para a CTAS e a apaga logo em seguida — sem CreateTable/DeleteTable a
        # limpeza falha com AccessDeniedException. Mesmo Sid, mesmo racional e mesmo escopo de
        # recurso (wildcard table/{database}/* — o nome da tabela temp não é previsível) já
        # usado por glue_details_catalog (infra/iam_policies.tf), restrito às databases
        # movie/tv deste job.
        Sid    = "DeleteCtasTempTable"
        Effect = "Allow"
        Action = [
          "glue:CreateTable",
          "glue:DeleteTable",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_table.tb_details_movie_tmdb.database_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_table.tb_details_tv_tmdb.database_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_details_movie_tmdb.database_name}/*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_details_tv_tmdb.database_name}/*",
        ]
      },
      {
        # write_parquet_to_sot (backfill_referencias.py) grava as 6 tabelas de referência via
        # wr.s3.to_parquet(..., database=..., table=...) — mesma função usada pelo Glue ETL
        # real (app/glue_etl/src/utils.py). Sequência exata de chamadas Glue confirmada lendo
        # o código-fonte instalado do awswrangler (catalog/_create.py:_create_table,
        # catalog/_delete.py:delete_all_partitions), já que as 6 tabelas SEMPRE existem no
        # Catalog (criadas pelo Terraform, ver infra/glue_catalog.tf) antes deste script
        # rodar:
        #   1. GetTable (catalog._get_table_input) — resolve o table_input existente.
        #   2. Como a tabela já existe (table_exist=True) e mode="overwrite", GetPartitions
        #      (delete_all_partitions → catalog._get_partitions) — mesmo sem nenhuma
        #      tabela aqui ser particionada, essa chamada acontece incondicionalmente
        #      (retorna lista vazia; BatchDeletePartition só seria chamado se houvesse
        #      partições a apagar, o que nunca é o caso destas 6 tabelas).
        #   3. UpdateTable — aplica o table_input (schema/localização) resolvido no passo 1.
        # CreateTable é mantido mesmo não sendo exercido neste caminho específico (só
        # rodaria se a tabela não existisse no Catalog) — mesma permissão que a role do job
        # Glue ETL real (glue_etl_catalog, Sid "WriteSOTTable" acima nesta mesma policy.tf)
        # já concede para o mesmo tipo de escrita, cobrindo o caso de a tabela ser recriada
        # manualmente no futuro.
        Sid    = "ReferenceTablesCatalogAccess"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions",
          "glue:CreateTable",
          "glue:UpdateTable",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_table.tb_genre_movie_tmdb.database_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_table.tb_genre_tv_tmdb.database_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_genre_movie_tmdb.database_name}/${aws_glue_catalog_table.tb_genre_movie_tmdb.name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_genre_tv_tmdb.database_name}/${aws_glue_catalog_table.tb_genre_tv_tmdb.name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_configuration_languages_tmdb.database_name}/${aws_glue_catalog_table.tb_configuration_languages_tmdb.name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_configuration_countries_tmdb.database_name}/${aws_glue_catalog_table.tb_configuration_countries_tmdb.name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_watch_providers_ref_movie_tmdb.database_name}/${aws_glue_catalog_table.tb_watch_providers_ref_movie_tmdb.name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_table.tb_watch_providers_ref_tv_tmdb.database_name}/${aws_glue_catalog_table.tb_watch_providers_ref_tv_tmdb.name}",
        ]
      },
    ]
  })
}

# =============================================================================
# POLICY 6 — AWS Translate. Usado quando TRANSLATE_PROVIDER=aws é escolhido em
# qualquer backfill manual (backfill_traducao.py, backfill_discover.py,
# backfill_referencias.py, backfill_enriquecimento.py, backfill_changes.py) — default é "google"
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
