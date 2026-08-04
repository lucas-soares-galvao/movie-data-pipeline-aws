---
name: especialista-workflows-github
description: Especialista nos workflows GitHub Actions de .github/workflows/ (00_pipeline, 01_test, 02_terraform, 03_pr_auto, 04_deploy_lightsail, 05_backfill). Use ao criar/editar arquivos .yml de workflow, revisar triggers/permissions/concurrency, contratos de workflow_call (inputs/secrets/outputs), condicionais if: entre jobs, pinning de actions de terceiros, ou ao avaliar risco de supply-chain em CI/CD. Cobre a mecânica YAML que a documentação narrativa (estrutura-projeto, .github/workflow.md) não detalha.
---

# Especialista em Workflows GitHub Actions

## Papel

Você é o especialista responsável por `.github/workflows/`. Antes de alterar um workflow reutilizável, confere o contrato exato de `workflow_call` (quais `inputs`/`secrets`/`outputs` ele declara) — não assume que herda algo que não foi passado explicitamente. Mantém `permissions:` no menor escopo necessário (um workflow chamado sem bloco próprio herda o do caller). Trata pin de ação de terceiro e instalação de ferramenta via script como superfície de segurança: nunca introduz `curl | bash` sem pin de versão/checksum, e para ações que manipulam credenciais AWS considera pin por SHA em vez de tag mutável — hoje **nenhuma** ação do projeto é pinada por SHA, só por tag major (`@v4`, `@v5`, `@v3`), o que é o principal ponto de atenção de supply-chain deste repositório.

## Fontes de verdade (ler antes de agir)

Esta skill cobre a mecânica YAML (triggers exatos, permissions, contratos de workflow_call, `if:`, encadeamento de outputs, pin de ações) que os documentos abaixo, já bons na narrativa, não detalham:

| O quê | Onde |
|---|---|
| Narrativa completa de cada workflow (o que cada etapa faz, por quê) | `.github/workflow.md` |
| Resumo do fluxo de jobs e tabela de secrets | `estrutura-projeto` |
| Infraestrutura Terraform que `02_terraform.yml`/`04_deploy_lightsail.yml` operam | `especialista-infraestrutura-terraform` |
| Quality gates executados por `01_test.yml` (pytest/ruff/mypy/bandit/safety) | `especialista-testes-app` |

## Inventário dos 6 workflows — gatilho e escopo

| Workflow | `on:` | `permissions:` próprio |
|---|---|---|
| `00_pipeline.yml` | `push` (branches `feature/*`, `develop`, `main`) + `workflow_dispatch` (input `environment`: choice `dev`/`prod`, default `dev`) | `id-token: write`, `contents: read`, `actions: write`, `pull-requests: write` — orquestrador, o único com bloco amplo |
| `01_test.yml` | `workflow_call` (sem inputs/secrets/outputs) | nenhum — herda do caller |
| `02_terraform.yml` | `workflow_call` | nenhum — herda do caller |
| `03_pr_auto.yml` | `workflow_call` (input `branch_name`) | `contents: write`, `pull-requests: write` |
| `04_deploy_lightsail.yml` | `workflow_call` | nenhum — herda do caller |
| `05_backfill.yml` | `workflow_dispatch` isolado (não é chamado por outro workflow); `run-name:` dinâmico (`"Backfill [PROD/DEV]: <table_group> (<start_year>-<end_year|atual>)"`) | `id-token: write`, `contents: read` |

`01_test.yml`, `02_terraform.yml` e `04_deploy_lightsail.yml` só disparam via `uses:` de outro workflow — não têm `push`/`workflow_dispatch` próprio, então não aparecem na aba "Run workflow" do GitHub.

## Contratos `workflow_call` (inputs/secrets/outputs declarados)

| Workflow | `inputs` | `secrets` obrigatórios | `outputs` |
|---|---|---|---|
| `01_test.yml` | — | — | — |
| `02_terraform.yml` | `environment` (string) | `aws-assume-role-arn`, `aws-statefile-s3-bucket`, `aws-lock-dynamodb-table`, `aws-filmbot-secret-arn`, `notification-email`, `infracost-api-key` (6) | `was_destroyed` (= `jobs.terraform.outputs.destroyed_status`) |
| `03_pr_auto.yml` | `branch_name` (string) | — (usa `secrets.GITHUB_TOKEN` implícito, disponível mesmo sem declarar) | — |
| `04_deploy_lightsail.yml` | `environment` (string) | `aws-assume-role-arn`, `aws-statefile-s3-bucket`, `aws-lock-dynamodb-table` (3 — subconjunto de `02_terraform.yml`, sem `aws-filmbot-secret-arn` nem notification/infracost) | — |

Em `00_pipeline.yml`, a seleção de secret por ambiente (`_DEV`/`_PROD`) é uma expressão ternária longa, **repetida verbatim** para cada um dos 3 secrets AWS comuns (`aws-assume-role-arn`, `aws-statefile-s3-bucket`, `aws-lock-dynamodb-table`) nos dois jobs que chamam workflows reutilizáveis (`terraform` e `deploy-lightsail`) — mais `aws-filmbot-secret-arn` só no job `terraform`. Padrão da expressão: `github.event_name == 'workflow_dispatch' && (github.event.inputs.environment == 'dev' && secrets.X_DEV || secrets.X_PROD) || github.ref_name == 'develop' && secrets.X_DEV || secrets.X_PROD`. É duplicação intencional (GitHub Actions não permite montar o nome do secret dinamicamente por interpolação, ex. `secrets['X_' + env]`), não um bug — mas ao adicionar um secret novo com esse mesmo padrão, copiar a expressão inteira, não simplificar.

## `if:` entre jobs — expressões booleanas exatas

- `test`: `startsWith(github.ref_name, 'feature/')`
- `resolve-env` / `terraform`: `github.ref_name == 'develop' || github.ref_name == 'main' || github.event_name == 'workflow_dispatch'`
- `deploy-lightsail`: `(github.ref_name == 'main' || (github.event_name == 'workflow_dispatch' && github.event.inputs.environment == 'prod')) && needs.terraform.result == 'success' && needs.terraform.outputs.was_destroyed != 'true'` — o gate que impede deploy depois de um `terraform destroy`
- `auto-pr-feature`: `startsWith(github.ref_name, 'feature/') && needs.test.result == 'success'`
- `auto-pr-environment`: `github.ref_name == 'develop' && needs.terraform.result == 'success'`
- Dentro de `02_terraform.yml` (mesmo job `terraform`): apply e destroy são mutuamente exclusivos via `if: steps.read-destroy-config.outputs.destroy == 'true'` (Destroy) / `!= 'true'` (Bootstrap IAM, Plan, Apply)
- Dentro de `03_pr_auto.yml`: `Setup Terraform`/`Terraform Validate`/`Terraform Format Check` só rodam com `if: startsWith(inputs.branch_name, 'feature/')` — `develop` pula, pois já passou pelo `02_terraform.yml` completo
- Dentro de `04_deploy_lightsail.yml`: 4 steps encadeados em `if: steps.tf.outputs.lightsail_enabled == 'true' && steps.instance_check.outputs.instance_running == 'true'` (setup SSH, criar `.env`, deploy, health check)

## Encadeamento de outputs entre jobs/steps

- `resolve-env.outputs.environment` (job) → consumido por `terraform`/`deploy-lightsail` via `needs.resolve-env.outputs.environment`, também usado no `with: environment:` de ambos os `uses:`
- `terraform` job (dentro de `02_terraform.yml`) → `outputs.destroyed_status = steps.read-destroy-config.outputs.destroy` → exposto como `was_destroyed` do workflow reutilizável (bloco `on.workflow_call.outputs`) → consumido pelo `if:` de `deploy-lightsail` em `00_pipeline.yml`
- Em `04_deploy_lightsail.yml`, o step `tf` (id `tf`) produz ~10 outputs consumidos por 4 steps seguintes: `public_ip`, `lightsail_enabled`, `instance_name`, `key_file`, `access_key_id` (mascarado via `::add-mask::`), `secret_access_key` (mascarado), `cw_log_group`, `filmbot_secret_arn` (mascarado), `athena_s3_output`, `glue_database`, `spec_table`
- Em `05_backfill.yml`, o step `env` (id `env`) produz `name` (dev/prod, resolvido do branch) e o step `project` produz `project_prefix` (lido de `infra/config/project.json` via `jq`) — ambos interpolados em ~20 variáveis de ambiente do step "Run backfill" (nomes de job Glue, databases, buckets, tabelas)

## Segurança de supply-chain — o achado mais importante

- **Nenhuma ação de terceiro é pinada por SHA** — todas por tag major mutável: `actions/checkout@v4` (`01_test.yml`, `02_terraform.yml`, `03_pr_auto.yml`, `04_deploy_lightsail.yml`, `05_backfill.yml` — todo workflow que faz checkout), `actions/setup-python@v5` (`01_test.yml`, `05_backfill.yml`), `hashicorp/setup-terraform@v3` (`02_terraform.yml`, `03_pr_auto.yml`, `04_deploy_lightsail.yml`), `aws-actions/configure-aws-credentials@v4` (`02_terraform.yml`, `04_deploy_lightsail.yml`, `05_backfill.yml`). Uma tag `@v4` re-apontada por um ataque de supply-chain entregaria código malicioso já de posse de credenciais AWS via OIDC — `configure-aws-credentials` é a ação mais sensível do conjunto.
- `02_terraform.yml`, step "Setup and Run TFLint": `curl -s https://raw.githubusercontent.com/terraform-linters/tflint/master/install_linux.sh | bash` — aponta para a branch `master` (não uma tag/release), sem checksum. Risco de supply-chain independente do pin de actions, fácil de não notar por estar dentro de um `run:`, não de um `uses:`.
- Ao adicionar/atualizar uma action: preferir pin por SHA para as que tocam credenciais; nunca introduzir novo `curl | bash` sem fixar ao menos uma tag/release, idealmente com checksum.

## Outras mecânicas e inconsistências a conhecer

- **`concurrency:`** só existe em `02_terraform.yml`, a nível de job: `group: terraform-${{ inputs.environment }}`, `cancel-in-progress: false` — serializa applies do mesmo ambiente (evita corrida TOCTOU no import idempotente da role de CI/CD). Nenhum outro workflow usa `concurrency:`, nem `00_pipeline.yml`. Isso não cobre cancelamento manual de um run em andamento — cancelar mata o processo do terraform sem ele liberar o lock do DynamoDB, mesmo sem nenhuma execução concorrente real.
- **Force-unlock automático em cancelamento**: último step de `02_terraform.yml` (`if: cancelled()`, depois do Apply) — consulta o item de lock direto na tabela DynamoDB, extrai o `ID` de dentro do atributo `Info` e roda `terraform force-unlock -force <ID>` (nunca ID hardcoded); vira no-op se não houver lock (job cancelado antes de qualquer terraform rodar). Único step do repositório que reage a `cancelled()` em vez do padrão implícito `success()`.
- **`defaults.run.shell: bash`** só declarado em `02_terraform.yml` e `04_deploy_lightsail.yml` — ativa `pipefail`. É por isso que `02_terraform.yml` usa `terraform state show <addr>` em vez de `terraform state list | grep`: sob `pipefail`, se o `grep` fecha o pipe antes do `terraform` terminar de imprimir o state inteiro, o `terraform` recebe `EPIPE` e o `if` cai no `else` mesmo com o `grep` tendo funcionado — ver comentário no próprio step "Import existing CI/CD role". Os outros 3 workflows não declaram `defaults.run.shell`, então não têm `pipefail` ativo por padrão.
- **Cache**: só `01_test.yml` usa (`actions/setup-python@v5` com `cache: "pip"` e `cache-dependency-path` apontando para `app/**/requirements.txt` + `test/**/requirements_tests.txt`). `05_backfill.yml` chama `actions/setup-python@v5` **sem** `cache:` — inconsistência a observar em review, não necessariamente um problema (backfill roda raramente).
- **Relatórios não persistidos**: `bandit-report.json`, `safety-report.json` (`01_test.yml`) e `checkov-report.json` (`02_terraform.yml`) são gerados no workspace mas nunca enviados via `actions/upload-artifact` — descartados ao fim do job. `actions/upload-artifact`/`download-artifact` não é usado em lugar nenhum do repositório.
- **Sem `matrix:`/`strategy:`** em nenhum dos 6 workflows — tudo roda single-job `ubuntu-latest`.
- **`timeout-minutes`** só declarado em 2 jobs: `01_test.yml` (`15`) e `05_backfill.yml` (`360`, deliberadamente alinhado ao `max_tentativas=6` do loop de retry a ~1h por sessão AWS — se um mudar, o outro precisa mudar junto, ver comentário no step "Run backfill").
- **Sem composite actions** (`.github/actions/` não existe) — todo reuso entre os 6 arquivos é via `uses: ./.github/workflows/X.yml` (reusable *workflows*, não composite *actions*). Lógica duplicada e não fatorada: leitura de `infra/config/project.json` via `jq` (`02_terraform.yml`, `04_deploy_lightsail.yml`, parcialmente `05_backfill.yml`), setup do `hashicorp/setup-terraform` com `terraform_wrapper: false` (`02_terraform.yml`, `04_deploy_lightsail.yml`), a ternária de seleção de secret por ambiente (seção acima).
- **Ausentes no repositório**: `CODEOWNERS`, `dependabot.yml` (nada atualiza automaticamente os pins de tag das actions), templates de issue/PR.
- **`05_backfill.yml`** tem 6 `table_group` (`discover`, `referencias`, `detalhes_e_providers`, `data_quality`, `traducao`, `rename_colunas`) mapeados 1:1 para scripts em `scripts/backfill_*.py`; a lógica de retomada por `ExpiredTokenException` (código de saída `75`) reassume a role via `aws sts assume-role-with-web-identity` inline usando o token OIDC do próprio job (`ACTIONS_ID_TOKEN_REQUEST_TOKEN`/`ACTIONS_ID_TOKEN_REQUEST_URL`) — mecanismo já bem narrado em `.github/workflow.md`, citado aqui só como referência de onde encontrar a implementação exata (`set +e`/`set -e` ao redor do `executar_script` é necessário porque os steps `run:` do Actions rodam com `set -e` implícito, que abortaria antes do `codigo=$?` ser capturado).

## Regras ao criar/alterar um workflow

- Workflow novo reutilizável: declarar `on: workflow_call` com `inputs`/`secrets`/`outputs` explícitos, seguindo o padrão de `02_terraform.yml`
- `permissions:` no menor escopo necessário; só declarar bloco próprio quando o workflow precisar de algo que o caller não concede
- Job novo que dependa de outro: usar `needs.<job>.outputs.<x>` para passar dados — não reconstruir estado via arquivo solto sem `upload-artifact`
- Ação de terceiro nova: preferir tag de release estável; para ações que manipulam credenciais AWS, considerar pin por SHA
- Nunca introduzir `curl | bash` sem pin de versão/checksum — para instalar uma CLI nova, preferir uma action oficial (padrão `hashicorp/setup-terraform`) ao padrão do TFLint (script solto na branch `master`)
- Secret novo com variação dev/prod: seguir o padrão de expressão ternária já usado em `00_pipeline.yml`, não introduzir um mecanismo diferente
