## Basic configuration of Terraform and providers used in the project.
terraform {
  # Remote backend defined in the pipeline via -backend-config.
  backend "s3" {
    bucket         = ""
    key            = ""
    region         = ""
    dynamodb_table = ""
  }

  required_providers {
    aws = {
      source = "hashicorp/aws"
    }

    archive = {
      source = "hashicorp/archive"
    }

    null = {
      source = "hashicorp/null"
    }
  }
}

provider "aws" {
  # Default region to create/manage resources.
  region = "sa-east-1"
}
