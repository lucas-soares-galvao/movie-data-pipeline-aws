# infra — Infraestrutura AWS (Terraform)

## Visão geral

Toda a infraestrutura do projeto é gerenciada como código com **Terraform**. Isso garante que os ambientes `dev` e `prod` sejam idênticos em estrutura, reproduzíveis e auditáveis via Git. Os valores sensíveis (e-mails, ARNs, chaves) são passados via arquivos `.tfvars` por ambiente.

O estado do Terraform é armazenado remotamente em um bucket S3 com backend configurado em `provider.tf`.

Todos os recursos AWS deste projeto recebem o prefixo `tmdb-` (ou `tmdb_` para databases/tabelas do Glue Catalog), definido em `local.tmdb_prefix` (`locals.tf`). O objetivo é isolar os recursos deste projeto de outros que eventualmente compartilhem a mesma conta/região AWS.

## Ambientes

| Ambiente | Conta AWS | Arquivo de variáveis |
|---|---|---|
| `dev` | `<AWS_ACCOUNT_ID_DEV>` | `infra/envs/dev/terraform.tfvars` |
| `prod` | `<AWS_ACCOUNT_ID_PROD>` | `infra/envs/prod/terraform.tfvars` |

Cada recurso recebe o sufixo `-dev` ou `-prod` automaticamente via `locals.tf`, garantindo isolamento total entre ambientes na mesma conta (quando aplicável) ou contas separadas.

## CI/CD — GitHub Actions (`.github/workflows/`)

| Arquivo | Papel |
|---|---|
| `00_pipeline.yml` | Orquestrador: chama test → terraform → PR em sequência |
| `01_test.yml` | Reusável: roda pytest, ruff (lint), mypy (tipos), bandit (segurança) |
| `02_terraform.yml` | Reusável: `terraform init` + `apply` ou `destroy` |
| `03_pr_auto.yml` | Reusável: cria PR automático após deploy |
| `04_deploy_lightsail.yml` | Deploy do app FilmBot na instância Lightsail |

Autenticação com AWS via **OIDC** (sem chaves de acesso hardcodadas) — o GitHub Actions assume a role `lsg-github-actions-{env}` com políticas de privilégio mínimo gerenciadas pelo Terraform (`iam_cicd.tf`).

## Como aplicar

### Pré-requisitos
- Terraform `>= 1.5.0` instalado (provider AWS `~> 6.0` — ver `provider.tf`)
- AWS CLI configurado com credenciais do ambiente-alvo
- Arquivo `.tfvars` preenchido para o ambiente

### Comandos

```bash
# A partir da pasta infra/
terraform init -backend-config="envs/dev/backend.hcl"
terraform plan -var-file="envs/dev/terraform.tfvars"
terraform apply -var-file="envs/dev/terraform.tfvars"
```

### Build dos artefatos de código

Antes do `terraform apply`, os artefatos Python precisam existir no bucket AUX:

```bash
python infra/scripts/build_lambda_package.py   # gera zip da Lambda
python infra/scripts/build_glue_wheel.py       # gera wheel dos jobs Glue
```

No CI/CD, o build da Lambda é automatizado pelo workflow `02_terraform.yml`. O wheel do Glue (`build_glue_wheel.py`) deve ser gerado e enviado ao bucket AUX manualmente antes do primeiro `apply` — após isso, só precisa ser regerado quando o código dos jobs Glue mudar.
