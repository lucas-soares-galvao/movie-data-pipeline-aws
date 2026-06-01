# Raciocinio: define backend e providers Terraform para execucao reproduzivel por ambiente.
# As versoes sao fixadas para evitar que atualizacoes automaticas quebrem a infraestrutura.

terraform {
  # Versao minima do Terraform necessaria para este projeto.
  required_version = ">= 1.5.0"

  # Backend remoto definido no pipeline via -backend-config.
  backend "s3" {}

  required_providers {
    # Provider AWS: gerencia todos os recursos na nuvem Amazon.
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }

    # Provider Archive: cria arquivos .zip dos codigos Python para deploy.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  # Regiao padrao para criar/gerenciar os recursos.
  region = "sa-east-1"

  default_tags {
    tags = local.default_resource_tags
  }
}
