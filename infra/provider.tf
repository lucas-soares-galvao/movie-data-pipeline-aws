# Raciocinio: define backend e providers Terraform para execucao reproduzivel por ambiente.

terraform {
  # Backend remoto definido no pipeline via -backend-config.
  backend "s3" {}

  required_providers {
    aws = {
      source = "hashicorp/aws"
    }

    archive = {
      source = "hashicorp/archive"
    }
  }
}

provider "aws" {
  # Regiao padrao para criar/gerenciar os recursos.
  region = "sa-east-1"
}
