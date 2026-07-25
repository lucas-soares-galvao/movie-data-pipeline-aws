# =============================================================================
# provider.tf — Configuração base do Terraform
# Backend vazio: configurações passadas via -backend-config no pipeline (dev/prod usam buckets diferentes)
# =============================================================================
#
# Fluxo do pipeline de dados:
#
#   EventBridge (agendador)
#       │
#       ▼
#   Lambda API  ──► S3 SOR (JSON bruto da API TMDB)
#       │
#       ▼
#   Glue ETL  ──► S3 SOT (Parquet processado)
#       │               │
#       │               ▼
#       │         Glue Details ──► S3 SOT (runtime, temporadas, watch providers)
#       │               │
#       │               ▼
#       │         Glue AGG ──► S3 SPEC (tabela unificada filmes+séries)
#       │                               │
#       └──► Glue DQ (valida SOT) ◄────┘
#
#   FilmBot (Lightsail) consulta S3 SPEC via Athena
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }

    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = "sa-east-1"

  default_tags {
    tags = local.default_resource_tags
  }
}

# Lightsail requer us-east-1; recursos que usam essa região referenciam provider = aws.lightsail
provider "aws" {
  alias  = "lightsail"
  region = "us-east-1"
}
