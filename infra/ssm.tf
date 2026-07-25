# =============================================================================
# ssm.tf — Ponteiro do rotation refresh (only_rotation_refresh)
# =============================================================================
# Guarda só "último ano processado" pelo refresh contínuo do catálogo antigo
# (2000 até current_year - 3, ver app/lambda_api/main.py). Não é um checkpoint
# de loop — é um valor único, lido e regravado a cada execução semanal.
#
# Um parâmetro por content_type evita corrida entre as execuções de movie e tv
# (schedules independentes, ver eventbridge.tf).
#
# Sem sufixo de ambiente no nome: dev e prod já são contas AWS separadas (ver
# CLAUDE.md), então o parâmetro não colide entre ambientes mesmo com o mesmo
# nome — e o nome precisa bater exatamente com o hardcoded em
# app/lambda_api/main.py (only_rotation_refresh), que não tem acesso a var.env.
#
# value = "1999" faz a primeira execução calcular 2000 (last_year + 1). Depois
# da primeira execução real, o valor é sobrescrito pela Lambda — ignore_changes
# evita que um "terraform apply" reverta o progresso da rotação para 1999.
# =============================================================================

resource "aws_ssm_parameter" "rotation_year_pointer_movie" {
  name        = "/tmdb-pipeline/rotation-year-pointer-movie"
  description = "Ultimo ano processado pelo rotation refresh (filmes) — ver only_rotation_refresh em app/lambda_api/main.py"
  type        = "String"
  value       = "1999"
  tags        = local.component_tags.lambda_api

  depends_on = [terraform_data.cicd_policies_ready]

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "rotation_year_pointer_tv" {
  name        = "/tmdb-pipeline/rotation-year-pointer-tv"
  description = "Ultimo ano processado pelo rotation refresh (series) — ver only_rotation_refresh em app/lambda_api/main.py"
  type        = "String"
  value       = "1999"
  tags        = local.component_tags.lambda_api

  depends_on = [terraform_data.cicd_policies_ready]

  lifecycle {
    ignore_changes = [value]
  }
}
