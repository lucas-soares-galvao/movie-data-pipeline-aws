# 0. Pipeline CI/CD — Documentação do Fluxo

## Visão Geral

O pipeline automatiza as seguintes etapas a cada push no repositório:

1. **Qualidade**: lint, type check, segurança e cobertura de testes
2. **Infraestrutura**: provisiona ou destrói recursos AWS via Terraform
3. **Deploy**: publica a aplicação FilmBot no Lightsail
4. **Promoção**: cria PRs automáticos entre branches (`feature → develop → main`)

Além do fluxo automático acima, dois workflows são independentes do `00_pipeline.yml`:

- `05_lightsail_scheduler.yml` — liga/desliga (destroy/create real, não só stop/start) a instância Lightsail de prod para economizar custo (FilmBot não existe em dev). Roda por `schedule` (cron): liga e desliga automaticamente. Também aceita `workflow_dispatch` manual.
- `06_backfill.yml` — disparado manualmente (`workflow_dispatch`), para reprocessar dados históricos sob demanda. O ambiente (dev/prod) é resolvido automaticamente pelo branch selecionado ao disparar o workflow.

---

## Diagrama de Fluxo

```mermaid
flowchart TD
    PUSH["Push / workflow_dispatch"]

    PUSH -->|feature/*| TEST["01_test.yml\nQuality gates"]
    PUSH -->|develop ou main| TF["02_terraform.yml\nTerraform apply/destroy"]

    TEST --> PR_FEAT["03_pr_auto.yml\nPR: feature → develop"]
    TF -->|develop branch| PR_ENV["03_pr_auto.yml\nPR: develop → main"]
    TF -->|main branch| DEPLOY["04_deploy_lightsail.yml\nDeploy app"]

    CRON["schedule (cron: liga/desliga prod)"] --> SCHED["05_lightsail_scheduler.yml\nLiga/desliga Lightsail (destroy/create)"]
    MANUAL2["workflow_dispatch manual (prod)"] --> SCHED
    SCHED -->|action=start| DEPLOY2["04_deploy_lightsail.yml\nReidrata a instância"]

    MANUAL["workflow_dispatch manual"] --> BACKFILL["06_backfill.yml\nBackfill sob demanda (ambiente por branch)"]
```

---

## Triggers

| Evento | Branch | Workflows executados |
|---|---|---|
| `push` | `feature/*` | test → PR feature→develop |
| `push` | `develop` | terraform (dev) → PR develop→main (FilmBot não existe em dev — deploy-lightsail sempre "skipped") |
| `push` | `main` | terraform (prod) → deploy (prod, se a instância estiver ligada) |
| `workflow_dispatch` | — | terraform (dev **ou** prod) → deploy só se ambiente resolvido for prod |
| `schedule` (`05_lightsail_scheduler.yml`) | — | liga/desliga a instância Lightsail de prod (cron BRT) — independente do `00_pipeline.yml` |
| `workflow_dispatch` (`05_lightsail_scheduler.yml`) | — | liga/desliga manual de prod (`action=start`/`stop`) |
| `workflow_dispatch` (`06_backfill.yml`) | — | backfill sob demanda, ambiente resolvido pelo branch selecionado (`main`→prod, `develop`→dev) — independente do `00_pipeline.yml` |

---

## Workflows

### `00_pipeline.yml` — Orquestrador

Ponto de entrada do pipeline. Chama os outros workflows na ordem certa usando `needs:` e condicionais de branch. Um job `resolve-env` resolve o ambiente uma única vez (evitando repetir a mesma lógica nos jobs `terraform` e `deploy-lightsail`); a seleção de secrets `_DEV`/`_PROD` continua feita em cada job, pois secrets não devem transitar por outputs de job.

**Lógica de ambiente (job `resolve-env`):**

| Branch | Ambiente |
|---|---|
| `develop` | `dev` |
| `main` | `prod` |
| `workflow_dispatch` | escolha manual |

---

### `01_test.yml` — Quality Gates

Valida a qualidade do código antes de qualquer deploy. Executa **apenas em branches `feature/*`**.

| Etapa | Ferramenta | Comportamento |
|---|---|---|
| Lint | Ruff | **Bloqueia** se falhar |
| Cobertura de testes | pytest-cov | **Bloqueia** se < 95% |
| Type check | mypy | Aviso (não bloqueia) |
| Segurança do código | Bandit | Aviso (não bloqueia) |
| Vulnerabilidades em deps | Safety | Aviso (não bloqueia) |

---

### `02_terraform.yml` — Infraestrutura

Provisiona ou destrói a infraestrutura AWS.

**Entrada:** `environment` (`dev` ou `prod`)  
**Saída:** `was_destroyed` — indica se a infra foi destruída (impede o deploy)

**`infra/config/destroy_config.json`**

Controla se o workflow deve destruir (`terraform destroy`) ou provisionar (`terraform apply`) cada ambiente:

```json
{ "dev": false, "prod": false }
```

Mudar um valor para `true` faz com que o próximo push naquele ambiente execute `terraform destroy` em vez de `terraform apply`. Após a destruição, o valor **não é revertido automaticamente** — é necessário mudar de volta para `false` e fazer novo push para reaplicar a infraestrutura.

**Etapas principais:**

1. Lê `infra/config/project.json` via `jq` — nome do wheel compartilhado, nome/prefixo da role e policies de CI/CD, key do state file (fonte única de identidade do projeto, também lida diretamente pelo Terraform)
2. Build do pacote Lambda (`infra/scripts/build_lambda_package.py`), do wheel Shared e dos wheels dos módulos Glue Python Shell listados em `glue_wheel_modules` (`infra/config/project.json`, hoje: ETL, Agg, Details) — verifica se os artefatos foram gerados; adicionar um novo módulo Glue Python Shell é só incluí-lo nesse array
3. Lê `infra/config/destroy_config.json` para decidir se destrói ou aplica — valida que o valor é `true` ou `false`
4. `terraform init` com backend S3 + DynamoDB
5. **Import da role de CI/CD** — a role `lsg-github-actions-{env}` existe fora do Terraform desde antes de virar `resource` em `iam_cicd.tf`; este step adota ela no state via `terraform import` (checa `terraform state show` antes — no-op após a primeira adoção; usa `state show` de um resource específico em vez de `state list | grep` para não depender de um pipe entre dois comandos, que sob `pipefail` podia gerar falso negativo por broken pipe e reimportar uma role já adotada). Sem isso o Terraform tentaria `CreateRole` nela, que a própria role não tem permissão de fazer contra si mesma
6. `terraform validate` e `terraform fmt -check` (**bloqueantes**) + TFLint e Checkov (não-bloqueantes — apenas avisos)
7. Injeta o e-mail de notificação no `.tfvars` (não é commitado no repo)
8. **Bootstrap das IAM policies** — aplica com `-target` as 6 policies do CI/CD antes do plan principal, resolvendo o problema de bootstrap (a role precisa das policies para gerenciar os recursos, mas as policies são criadas pelo mesmo Terraform). Idempotente — se as policies já existem, é um no-op. Verifica via polling (a cada 5s, timeout 60s) com `aws iam list-attached-role-policies` se as 6 policies estão de fato attachadas à role — falha o pipeline se alguma estiver ausente
9. `terraform destroy` **ou** `terraform plan` + Infracost + `terraform apply`
10. **Force-unlock automático em caso de cancelamento** (`if: cancelled()`) — cancelar o run manualmente (ex.: via GitHub UI) enquanto um step de terraform está rodando mata o processo sem ele liberar o lock do DynamoDB, travando o próximo run com "Error acquiring the state lock" mesmo sem execução concorrente real. Este step só roda quando o job foi cancelado: consulta o item de lock direto na tabela, extrai o `ID` de dentro do atributo `Info` e chama `terraform force-unlock -force <ID>` — nunca com ID hardcoded. Se não houver lock na tabela (job cancelado antes de qualquer terraform rodar), é um no-op

**Autenticação AWS:** OIDC — assume a role `lsg-github-actions-{env}` (nome configurável via `infra/config/project.json`) com políticas de privilégio mínimo gerenciadas pelo Terraform (`iam_cicd.tf`). As variáveis `cicd_statefile_s3_bucket` e `cicd_lock_dynamodb_table` são passadas via `-var` a partir dos secrets `aws-statefile-s3-bucket` e `aws-lock-dynamodb-table`.

**Concorrência:** o job `terraform` usa `concurrency: group: terraform-{environment}` (`cancel-in-progress: false`) — runs do mesmo ambiente (ex.: dois pushes seguidos em `develop`) são enfileirados em vez de rodar em paralelo contra o mesmo state; dev e prod têm grupos separados e não se bloqueiam entre si. Evita uma corrida entre o step de import (item 5) e o lock do DynamoDB quando dois runs do mesmo ambiente coincidem. Isso não cobre cancelamento manual de um run em andamento (mata o processo do terraform de qualquer forma) — para esse caso existe o step 10, força o unlock em vez de só evitar a corrida.

---

### `03_pr_auto.yml` — PR Automático

Cria ou atualiza um Pull Request para promover código entre branches.

**Entrada:** `branch_name` (branch de origem)

| Branch de origem | Branch de destino |
|---|---|
| `feature/*` | `develop` |
| `develop` | `main` |

Antes de criar o PR, executa `terraform validate -backend=false` e `terraform fmt -check` — apenas em branches `feature/*`. Em `develop`, esses checks são pulados porque o `02_terraform.yml` já os executou antes do auto-pr ser chamado.

---

### `04_deploy_lightsail.yml` — Deploy da Aplicação

Publica a aplicação Streamlit (FilmBot) na instância Lightsail via SSH. No `00_pipeline.yml`, o job `deploy-lightsail` executa só quando o ambiente resolvido é `prod` — FilmBot não existe em dev (ver `infra/lightsail_ia.tf`), então um push em `develop` sempre resolve esse job como "skipped". Se a instância de prod estiver destruída no momento do push (fora da janela agendada), o step "Check instance state" pula o deploy com warning, sem falhar o pipeline. Também é chamado por `05_lightsail_scheduler.yml` (job `deploy-app`), sempre que a ação foi `start` — reidrata a instância recém-criada do zero após cada ciclo de liga (agendado ou manual).

**Entrada:** `environment` (mantido na interface do `workflow_call` por estabilidade, mas na prática só é chamado com `prod`)

**Etapas principais:**

1. Lê `infra/config/project.json` via `jq` — `app_name`, `app_display_name`, `app_folder`, `statefile_key` (por padrão `filmbot`/`FilmBot`/`lightsail_ia`)
2. Lê outputs do Terraform (IP, chave SSH, credenciais AWS do agente, nome da instância, log group do CloudWatch, ARN do Secrets Manager, `ATHENA_S3_OUTPUT`/`GLUE_DATABASE`/`SPEC_TABLE`) — valida que nenhum output crítico está vazio
3. Verifica o estado da instância via `aws lightsail get-instance` — se não estiver `running` (ex: destruída pelo scheduler, fora da janela agendada), **pula os steps de deploy** com warning (mas ainda exibe a URL do app no final)
4. Configura SSH com retry (até 30 tentativas, intervalo de 10s) — falha o pipeline se SSH não ficar disponível em 5 minutos
5. Cria `.env` na instância com variáveis de ambiente da aplicação (credenciais AWS, ARN do Secrets Manager, Athena, Glue, CloudWatch) — todas lidas dos outputs do Terraform, nenhuma hardcoded no workflow — verifica via SSH se o arquivo foi criado
6. Cria `.env.caddy` na instância com `FILMBOT_DOMAIN=filmbot.lsgalvao.com.br` (domínio fixo — este workflow só é chamado para prod). O `Caddyfile` lê essa variável via `{$FILMBOT_DOMAIN}` (`EnvironmentFile=.env.caddy` no `caddy.service`) — sem esse arquivo o Caddy não sobe
7. Deploy por SSH (`app_name`/`app_folder` passados como variáveis de ambiente da sessão SSH, branch fixa `main`):
   - Cria um swap de 1GB (`fallocate`/`mkswap`/`swapon`, idempotente) antes de instalar dependências — necessário no bundle `micro_3_0` para o `pip install`/app não sofrerem OOM kill; aplicado em qualquer bundle
   - Instala o Caddy como proxy reverso HTTPS (se ainda não instalado)
   - **Primeiro deploy**: clone do repo (URL derivada de `${{ github.repository }}`), venv, systemd services (`<app_name>` + `caddy`)
   - **Updates**: git pull, pip install, restart de ambos os services
   - Verifica se os serviços `<app_name>` e `caddy` estão ativos (`systemctl is-active`) — falha o pipeline se algum estiver inativo
8. Health check — aguarda 30s e faz `curl` no IP público para confirmar que o app está respondendo
9. Exibe a URL do app (`app_display_name`) no log e no Job Summary (clicável)

---

### `05_lightsail_scheduler.yml` — Liga/Desliga o Lightsail (custo)

Workflow independente do `00_pipeline.yml`, exclusivo de prod (FilmBot não existe em dev). Substitui o antigo Lambda + EventBridge (`lightsail_scheduler.tf`, removido) — o Lightsail cobra a mesma tarifa do bundle tanto em `running` quanto em `stopped` (confirmado via fatura AWS real), então só parar a instância não economizava nada. Este workflow **destrói e recria** a instância via `terraform apply`/`destroy -target`, o que de fato zera a cobrança fora da janela de uso.

**Triggers:**

| Trigger | Ação |
|---|---|
| `schedule`: `cron(0 3 * * *)` | desligar (00:00 BRT diário) |
| `schedule`: `cron(0 21 * * 1-5)` | ligar (18:00 BRT seg-sex) |
| `schedule`: `cron(0 11 * * 0,6)` | ligar (08:00 BRT sáb-dom, `0`=domingo) |
| `workflow_dispatch` (`action`: start\|stop) | manual, disparado a partir de `main` |

**Etapas principais:**

1. Checkout + step `resolve` decide `environment`/`action`: sempre resolve `prod` (falha se disparado de outro branch), `action` vem do input em `workflow_dispatch` ou é decidido comparando `github.event.schedule` contra a string exata do cron de desligar
2. Lê `infra/config/project.json` via `jq` — `statefile_key`
3. Autenticação AWS via OIDC (secrets `_PROD`) + `terraform init`
4. `terraform destroy -target` (ação `stop`) **ou** `terraform apply -target` (ação `start`), sempre sobre `aws_lightsail_instance.filmbot`, `aws_lightsail_instance_public_ports.filmbot`, `aws_lightsail_static_ip_attachment.filmbot` (+ `aws_lightsail_key_pair.filmbot` no apply) — **nunca** `aws_lightsail_static_ip.filmbot`, que fica de fora do `-target` em ambas as direções
5. Force-unlock automático em caso de cancelamento (`if: cancelled()`) — mesmo padrão do `02_terraform.yml`
6. Job `deploy-app`: chama `04_deploy_lightsail.yml` via `uses:`, só quando a ação foi `start` e o job anterior teve sucesso — reidrata a instância recém-criada do zero (bootstrap completo, não snapshot)

**Por que destroy/create e não stop/start:** o Lightsail conta o bundle como usado (`BundleUsage` na fatura) tanto parado quanto rodando — a fatura de um mês inteiro com o scheduler antigo (stop/start) mostrou a mesma quantidade de horas cobradas de um mês sem nenhum desligamento. Destruir a instância de fato remove essas horas da fatura.

**Por que o IP estático nunca é destruído:** `aws_lightsail_static_ip.filmbot` (`infra/lightsail_ia.tf`, `local.lightsail_prod_enabled`) é um recurso independente da instância no Lightsail — desanexar não o deleta, só marca como "unattached" (pequena taxa de idle se ficar assim por mais de 1h). Ao nunca incluí-lo no `-target`, o mesmo IP é sempre reanexado à instância nova, e o domínio `filmbot.lsgalvao.com.br` no registro.br é cadastrado uma única vez.

**Concorrência:** `concurrency: group: terraform-prod` — mesmo group usado pelo job `terraform` de `02_terraform.yml` para prod, serializando com qualquer apply/destroy completo disparado por push em `main`.

**Comportamento a saber:** `lightsail_instance_enabled` permanece `true` por padrão (o liga/desliga é feito via `-target`, não por essa variável) — um `terraform apply` completo disparado por um push normal em `main` recria a instância se ela estiver destruída no momento. Ou seja, um deploy de código pode religar o servidor fora da janela agendada; não é uma falha do cron.

---

### `06_backfill.yml` — Backfill Manual

Workflow independente do `00_pipeline.yml`, disparado apenas manualmente (`workflow_dispatch`) para reprocessar dados históricos sob demanda. O ambiente é resolvido **automaticamente pelo branch** selecionado em "Use workflow from": `main` → prod, `develop` → dev, qualquer outro branch falha o workflow antes de configurar credenciais AWS.

**Entradas:**

| Input | Obrigatório | Default | Descrição |
|---|---|---|---|
| `table_group` | sim | — | Grupo de tabelas a atualizar (choice) |
| `start_year` | sim | `2000` | Ano inicial (ignorado para `referencias`) |
| `end_year` | não | vazio (= ano atual) | Ano final (ignorado para `referencias`) |

**Grupos de tabelas (`table_group`) e script executado:**

| `table_group` | Script | Serviço AWS |
|---|---|---|
| `discover` | `scripts/backfill_discover.py` | Lambda |
| `referencias` | `scripts/backfill_referencias.py` | Lambda |
| `detalhes_e_providers` | `scripts/backfill_enriquecimento.py` | Glue Details |
| `data_quality` | `scripts/backfill_data_quality.py` | Glue Data Quality |
| `traducao` | `scripts/backfill_traducao.py` | S3 (direto) |
| `rename_colunas` | `scripts/backfill_rename_colunas.py` | S3 (direto) |

**Etapas principais:**

1. Checkout + resolve o ambiente a partir do branch (`main`→prod, `develop`→dev, outro branch → falha)
2. Lê `infra/config/project.json` via `jq` — `project_prefix`
3. Autenticação AWS via OIDC — assume `AWS_ASSUME_ROLE_ARN_BACKFILL_DEV` ou `AWS_ASSUME_ROLE_ARN_BACKFILL_PROD` conforme o ambiente resolvido (role dedicada e de privilégio mínimo, separada da role de CI/CD usada pelo `00_pipeline.yml` — ver `infra/docs/iam.md`)
4. Setup Python 3.12, instala `boto3` (e `scripts/requirements_backfill.txt` apenas se `table_group == traducao`)
5. Executa o script correspondente ao `table_group` escolhido, com todas as variáveis de ambiente dos recursos AWS montadas dinamicamente como `<project_prefix>-...-<ambiente>` / `<project_prefix>_..._<ambiente>` (ex.: `tmdb-glue-details-dev`, `db_tmdb_movie_prod`) — prefixo lido de `infra/config/project.json`, ambiente resolvido pelo branch

`timeout-minutes: 360` — backfills históricos podem levar horas dependendo do volume de dados.

**Retomada automática após expiração de credencial:**

A sessão AWS assumida via OIDC dura 1h (padrão da action `configure-aws-credentials`), mas backfills como `detalhes_e_providers` podem levar várias horas. Em vez de esticar a duração da sessão, o step "Run backfill" trata isso com dois mecanismos complementares:

- **Retry em bash**: os scripts que iteram por ano (`backfill_discover.py`, `backfill_enriquecimento.py`, `backfill_data_quality.py`, `backfill_traducao.py`, `backfill_rename_colunas.py`) detectam `ExpiredTokenException` e saem com `exit code 75` (`scripts/backfill_shared.py`). Um laço `while` no step captura esse código, renova a credencial inline via OIDC (`assume-role-with-web-identity`, nova sessão de 1h) e roda o script de novo — até `max_tentativas=6`, alinhado ao `timeout-minutes: 360` (~6 sessões de 1h). Qualquer outro código de saída propaga a falha imediatamente, sem retry. (`backfill_referencias.py` não itera por ano e nunca sai com 75 — para ele o laço roda uma única vez.)
- **Checkpoint em S3**: cada reinício acima é um processo Python novo, sem memória do progresso anterior. Para não refazer trabalho já concluído, esses mesmos scripts persistem as unidades (`tipo:ano`) já processadas com sucesso em `s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{table_group}.json` a cada unidade concluída, e leem esse checkpoint no início para pular direto para as pendentes. O checkpoint é apagado ao final de um backfill sem falhas pendentes. `backfill_traducao.py` usa adicionalmente `S3_BUCKET_SOT` para ler/escrever os parquets reais — separado do checkpoint.

Se o `table_group` escolhido falhar por outro motivo (não expiração de credencial) ou esgotar as 6 tentativas, é preciso disparar o workflow manualmente de novo — ele também vai retomar do checkpoint salvo, agora numa nova execução.

---

## Promoção de Branches

```
feature/minha-feature
        ↓  (PR automático após testes passarem)
      develop
        ↓  (PR automático após terraform dev bem-sucedido)
        main
```

Cada promoção é feita via PR automático criado pelo `03_pr_auto.yml`. O merge ainda requer aprovação manual.

---

## Secrets e Variáveis

| Secret | Ambiente | Uso |
|---|---|---|
| `AWS_ASSUME_ROLE_ARN_DEV` / `_PROD` | dev / prod | OIDC — autenticação AWS (role de CI/CD, `00_pipeline.yml`) |
| `AWS_ASSUME_ROLE_ARN_BACKFILL_DEV` / `_PROD` | dev / prod | OIDC — autenticação AWS (role de backfill manual, `06_backfill.yml`) |
| `AWS_STATEFILE_S3_BUCKET_DEV` / `_PROD` | dev / prod | Backend Terraform (estado) |
| `AWS_LOCK_DYNAMODB_TABLE_DEV` / `_PROD` | dev / prod | Lock do estado Terraform |
| `AWS_FILMBOT_SECRET_ARN_DEV` / `_PROD` | dev / prod | ARN do segredo unificado no Secrets Manager (tmdb_api_key, llm_api_key, filmbot_password) |
| `NOTIFICATION_EMAIL` | ambos | E-mails de alerta da infra |
| `INFRACOST_API_KEY` | ambos | Estimativa de custo no PR |

---

## Glossário técnico

| Termo | O que é |
|---|---|
| **OIDC** | Método de autenticação sem chaves estáticas. O GitHub Actions prova sua identidade para a AWS via token temporário — mais seguro que guardar `AWS_ACCESS_KEY` em secrets. |
| **Backend Terraform** | Local onde o Terraform guarda o *state file* — arquivo que mapeia o que foi criado na AWS. Aqui é um bucket S3 com lock via DynamoDB para evitar conflito quando duas pessoas rodam o Terraform ao mesmo tempo. |
| **ARN** | Amazon Resource Name — identificador único de qualquer recurso AWS (ex: `arn:aws:secretsmanager:us-east-1:123456:secret:tmdb-key`). |
| **TFLint** | Linter para código Terraform — detecta erros de configuração e boas práticas sem precisar aplicar nada na AWS. |
| **Checkov** | Scanner de segurança para IaC (Terraform, CloudFormation) — detecta configurações inseguras como buckets S3 públicos ou IAM permissivo demais. |
| **Infracost** | Estima o custo mensal da infraestrutura AWS antes de aplicar — exibe o delta de custo no comentário do PR. |
| **PR automático** | Pull Request criado pelo próprio pipeline (`03_pr_auto.yml`) para promover código entre branches. O merge ainda requer aprovação manual, mas a criação do PR é automatizada para não depender de nenhum desenvolvedor. |
| **`terraform destroy`** | Destrói todos os recursos AWS gerenciados pelo Terraform naquele ambiente — o inverso do `apply`. Usado para desligar o ambiente e parar de pagar. Controlado pelo `infra/config/destroy_config.json`. |

---

## Troubleshooting — Problemas comuns

| Problema | Causa provável | Solução |
|---|---|---|
| Terraform apply falha com "Access Denied" ou "permission denied" | A role OIDC (`lsg-github-actions-{env}`) não tem todas as 6 policies do `iam_cicd.tf` attached | Verifique com `aws iam list-attached-role-policies --role-name lsg-github-actions-{env}` e compare com as 6 policies definidas em `iam_cicd.tf` |
| Terraform apply falha com `AccessDenied: ... iam:CreateRole ... lsg-github-actions-{env}` | O step "Import da role de CI/CD" (item 5 de `02_terraform.yml`) não rodou ou falhou antes de adotar a role existente no state | Confirme que o step de import rodou com sucesso no log; se a role realmente não existir ainda na AWS para esse ambiente, crie-a manualmente antes do próximo run (ela não pode se auto-criar) |
| Testes passam no CI mas falham localmente (ImportError) | `sys.path` não está configurado corretamente | Rode `pytest` da raiz do projeto (não de dentro de `test/`). O `test/conftest.py` raiz gerencia os imports automaticamente |
| Testes falham localmente mas passam no CI | Versão do Python diferente ou dependências desatualizadas | Verifique que está usando Python 3.12+ e instale as dependências de cada módulo: `for req in app/*/requirements.txt test/*/requirements_tests.txt; do pip install -r "$req"; done` |
| Deploy Lightsail é pulado com warning no step "Check instance state" | Instância de prod destruída pelo `05_lightsail_scheduler.yml` (fora da janela agendada) | Verifique o estado com `aws lightsail get-instance --instance-name {nome} --region us-east-1`. Dispare `05_lightsail_scheduler.yml` via `workflow_dispatch` (`action=start`) para religar |
| `06_backfill.yml` falha com `AccessDenied` | A role `tmdb-backfill-role-{env}` não tem a permissão específica exercida pelo `table_group` escolhido | Confira o `eventName` negado no CloudTrail e adicione a action/recurso faltante na policy inline correspondente em `infra/iam_backfill.tf` |
| `terraform destroy` rodou sem querer | Flag `true` em `infra/config/destroy_config.json` não foi revertida | Mude o valor de volta para `false` e faça push para reaplicar a infraestrutura |
| Build Lambda falha com "directory is empty" | Erro no script `build_lambda_package.py` (dependências não instaladas) | Verifique se `pip install` no CI está usando a versão correta do Python e se o `requirements.txt` está atualizado |
