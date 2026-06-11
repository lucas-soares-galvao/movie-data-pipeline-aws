# =============================================================================
# ARQUIVO: provider.tf — Configuração Base do Terraform
# =============================================================================
#
# O QUE É UM "PROVIDER" NO TERRAFORM?
# Um provider é um plugin que sabe como se comunicar com uma plataforma
# específica (AWS, Azure, Google Cloud, etc.). Sem o provider, o Terraform
# não sabe o que significa "criar um bucket S3" ou "criar uma função Lambda".
#
# ANALOGIA: Se o Terraform é um arquiteto, o provider é o tradutor que
# converte os planos do arquiteto para a linguagem específica de cada
# construtora (AWS, Azure, GCP).
#
# POR QUE FIXAR VERSÕES?
# Se não fixarmos as versões, o Terraform sempre usaria a versão mais nova.
# Uma atualização automática pode mudar o comportamento de recursos e
# quebrar a infraestrutura sem aviso. Versões fixas garantem
# comportamento idêntico em todos os ambientes e execuções.
# =============================================================================

terraform {
  # Versão mínima do Terraform CLI necessária para executar este projeto.
  # ">= 1.5.0" significa "qualquer versão 1.5.0 ou superior".
  required_version = ">= 1.5.0"

  # ==========================================================================
  # BACKEND REMOTO (S3)
  # ==========================================================================
  # O Terraform precisa guardar um arquivo de "estado" (terraform.tfstate)
  # que registra o que existe na AWS. Se fosse salvo localmente, cada máquina
  # teria um estado diferente e o Terraform ficaria confuso.
  #
  # Guardando no S3:
  # - Qualquer máquina (ou workflow no GitHub Actions) usa o mesmo estado
  # - O estado é versionado (histórico de mudanças)
  # - O DynamoDB (configurado no pipeline) age como cadeado para evitar
  #   que dois Terraforms rodem ao mesmo tempo e corrompam o estado
  #
  # "backend 's3' {}" está vazio aqui porque as configurações são passadas
  # dinamicamente pelo pipeline via "-backend-config=" (ver 02_terraform.yml).
  # Isso permite usar buckets diferentes para dev e prod.
  # ==========================================================================
  backend "s3" {}

  required_providers {
    # Provider AWS: permite criar/gerenciar todos os recursos AWS
    # (S3, Lambda, Glue, IAM, CloudWatch, etc.)
    # "~> 6.0" significa "versão 6.x qualquer, mas não 7.x"
    # (aceita patches de segurança mas não mudanças que podem quebrar)
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }

    # Provider Archive: cria arquivos .zip localmente para depois enviar à AWS.
    # Usado para empacotar o código Python da Lambda antes do deploy.
    # "~> 2.0" = versão 2.x
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

# =============================================================================
# PROVIDER AWS PRINCIPAL (Região São Paulo)
# =============================================================================
# A maioria dos recursos deste projeto (S3, Lambda, Glue, etc.) são criados
# em sa-east-1 (São Paulo) — a região AWS mais próxima do Brasil.
#
# "default_tags" aplica automaticamente estas tags em TODOS os recursos criados
# por este provider. Tags são metadados que facilitam:
# - Identificar a quais projeto/ambiente um recurso pertence
# - Filtrar recursos no console AWS
# - Monitorar custos por projeto (FinOps)
#
# Os valores das tags vêm do arquivo locals.tf (local.default_resource_tags).
# =============================================================================
provider "aws" {
  region = "sa-east-1"

  default_tags {
    tags = local.default_resource_tags
  }
}

# =============================================================================
# PROVIDER AWS SECUNDÁRIO (Região US East — para Lightsail)
# =============================================================================
# AWS Lightsail tem algumas limitações regionais. A instância que hospeda
# o app FilmBot (Streamlit) é criada em us-east-1 (Virgínia do Norte).
#
# "alias = 'lightsail'" cria um segundo provider com nome alternativo.
# Recursos que precisam usar esta região referenciam:
#   provider = aws.lightsail
# =============================================================================
provider "aws" {
  alias  = "lightsail"
  region = "us-east-1"
}

# =============================================================================
# DATA SOURCE: Identidade da Conta AWS Atual
# =============================================================================
# "data" no Terraform lê informações existentes na AWS sem criar nada.
# "aws_caller_identity.current" retorna dados sobre quem está autenticado:
#   - data.aws_caller_identity.current.account_id → ID numérico da conta AWS
#   - data.aws_caller_identity.current.arn         → ARN do usuário/role
#
# Usado em outros arquivos para construir ARNs dinamicamente, evitando
# hardcodar o ID da conta (que é diferente para cada conta AWS).
# =============================================================================
data "aws_caller_identity" "current" {}
