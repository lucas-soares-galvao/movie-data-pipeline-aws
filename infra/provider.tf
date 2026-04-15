terraform {
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
  region = "sa-east-1"
}