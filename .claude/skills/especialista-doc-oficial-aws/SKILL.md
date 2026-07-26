---
name: especialista-doc-oficial-aws
description: >-
  Especialista em consultar a fonte oficial correta da AWS e do Terraform antes de qualquer decisão de
  implementação. TRIGGER — consultar a fonte oficial via WebFetch ANTES de decidir, não depois de já ter escrito
  o código: sempre que for escolher um serviço AWS novo (docs.aws.amazon.com/<serviço>), adicionar/alterar um
  argumento de recurso do provider `aws` (registry.terraform.io/providers/hashicorp/aws/latest/docs, respeitando
  a versão pinada em infra/provider.tf), conceder ou revisar uma permissão IAM
  (docs.aws.amazon.com/service-authorization/latest/reference), avaliar limite/quota/preço de um recurso
  (páginas de pricing/limits do próprio serviço), ou alterar Terraform core — `required_version`, o bloco
  `backend "s3"` (incluindo as chaves passadas via `-backend-config`), ou o provider `archive`
  (developer.hashicorp.com/terraform/language, registry.terraform.io/providers/hashicorp/archive). Nunca decidir
  a partir de memória ou suposição sobre argumento de recurso, action IAM, quota, sintaxe de backend ou
  comportamento de serviço — tanto a AWS quanto o Terraform mudam com frequência (novos argumentos, actions IAM
  novas, quotas revisadas, breaking changes de major version, novas opções de locking de backend) e valores
  hardcoded no projeto (DPU mínima do Glue, timeout máximo de Lambda, retenção máxima de SQS, região fixa do
  Lightsail, `dynamodb_table` no backend S3) refletem o que era verdade quando foram escritos. SKIP quando a
  mudança é lógica de negócio pura em app/ sem tocar infraestrutura/serviço/permissão AWS ou configuração
  Terraform.
---

# Especialista em Documentação Oficial da AWS e do Terraform

## Papel

Você garante que toda decisão de infraestrutura, serviço ou permissão AWS — argumento de recurso do provider
`aws` ou `archive`, configuração de Terraform core (`required_version`, backend `s3`), serviço escolhido para
uma necessidade nova, permissão IAM concedida, limite/quota/preço avaliado — seja validada contra a **fonte
oficial correta** antes de ser tomada, nunca a partir de memória ou suposição sobre como a AWS ou o Terraform
"costumam" funcionar. Ambos mudam com frequência (argumentos de recurso novos, actions IAM novas, quotas
revisadas, breaking changes entre major versions, novas opções de locking de backend), e todo valor hardcoded
neste projeto (DPU mínima do Glue, timeout máximo de Lambda, retenção máxima de SQS, região fixa do Lightsail,
`dynamodb_table` no backend S3) reflete o que era verdade quando foi escrito — não necessariamente o que é
verdade hoje.

## Fontes de verdade (ler antes de agir)

Esta skill cobre o *gate* de consulta à fonte oficial; não repete o racional já documentado em cada domínio:

| O quê | Onde |
|---|---|
| Qual serviço AWS escolher para uma necessidade nova (racional de custo x benefício já decidido) | `especialista-arquitetura-aws` |
| Argumentos de recurso Terraform, `depends_on`, convenções de nomeação já em uso | `especialista-infraestrutura-terraform` |
| Privilégio mínimo IAM, racional de escopo já aplicado | `especialista-privilegio-minimo` |
| Custo x benefício dos recursos já escolhidos | `especialista-finops-aws` |
| Registro oficial do provider Terraform `aws` (argumentos/atributos por versão) | https://registry.terraform.io/providers/hashicorp/aws/latest/docs — sempre checar contra a versão pinada em `infra/provider.tf:35` (`~> 6.0`), não a doc "latest" se ela já estiver numa major version maior |
| IAM Service Authorization Reference (actions, resource types, condition keys por serviço) | https://docs.aws.amazon.com/service-authorization/latest/reference/ |
| Documentação de serviço AWS (comportamento, limites, quotas) | https://docs.aws.amazon.com/ (doc do serviço específico) |
| Preços atuais por serviço | página de pricing do próprio serviço em https://aws.amazon.com/pricing/ |
| Documentação core do Terraform (linguagem HCL, `required_version`, backend `s3`) | https://developer.hashicorp.com/terraform/language — em especial `.../language/backend/s3` para as chaves de `-backend-config` |
| Registro oficial do provider `archive` (argumentos por versão) | https://registry.terraform.io/providers/hashicorp/archive/latest/docs — checar contra a versão pinada em `infra/provider.tf:40` (`~> 2.0`) |

## Práticas já aplicadas — preservar

- **Provider AWS Terraform pinado em `~> 6.0`** (`infra/provider.tf:35`) — qualquer argumento de recurso
  sugerido precisa bater com o registry nessa major version, não com a doc genérica "mais recente".
- **Glue PythonShell no piso de `0.0625` DPU** (`local.pythonshell_min_capacity`, usado em `glue_etl.tf`,
  `glue_agg.tf`, `glue_details.tf`) — é o mínimo permitido pela doc oficial de capacidade de Glue Jobs, não uma
  escolha arbitrária de economia.
- **Lambda `timeout = 900` segundos** (`infra/lambda_api.tf:43`) — é o teto máximo documentado pela AWS para
  Lambda, não uma margem de segurança escolhida pelo projeto.
- **SQS DLQ `message_retention_seconds = 1209600`** — 14 dias (`infra/sqs.tf:11`) — é o teto máximo documentado
  pela AWS para retenção de mensagem em fila SQS.
- **Provider `aws.lightsail` fixado em `us-east-1`** (`infra/provider.tf:53`, comentário "Lightsail requer
  us-east-1") — afirmação sobre comportamento da API que já foi confirmada, mas que deveria ser reconfirmada na
  doc oficial se algum dia parecer não bater (ex.: AWS expandir a API para outras regiões).
- **IAM `Resource = "*"` só em actions que a doc oficial confirma não suportar escopo por recurso**
  (`translate:TranslateText`/`comprehend:DetectDominantLanguage`, `infra/iam_policies.tf:284` e `:972`) — aceito
  porque o IAM Service Authorization Reference confirma a ausência de suporte a ARN nessas actions, não por
  conveniência (ver `especialista-privilegio-minimo`).
- **`required_version = ">= 1.5.0"`** (`infra/provider.tf:28`) — piso mínimo de versão do Terraform core exigido
  pelo projeto; qualquer sintaxe/feature nova usada em `.tf` precisa ser suportada a partir dessa versão, não
  apenas na versão que o autor da mudança tem instalada localmente.
- **Provider `archive` pinado em `~> 2.0`** (`infra/provider.tf:40`) — usado via `data.archive_file` para os 3
  pacotes `.zip` do projeto (Lambda API, Lightsail scheduler, job Spark de Data Quality); mesmo princípio do
  provider `aws`: argumento novo precisa bater com essa major version.

## Lacunas encontradas — avaliar risco x esforço antes de agir

- **Nenhum dos fatos acima tem reconfirmação periódica contra a fonte oficial.** Foram fixados quando o código
  foi escrito; se a AWS revisar um limite (ex.: teto de timeout de Lambda, retenção máxima de SQS) ou o provider
  Terraform lançar uma major version com breaking changes, nada no projeto sinaliza a divergência.
- **O provider está pinado em `~> 6.0`, mas a doc "latest" do registry mostra sempre a versão mais recente
  publicada** (hoje pode já ser v7+) — consultar a doc sem filtrar pela versão pinada pode sugerir um argumento
  que não existe (ou tem nome diferente) na v6.x realmente usada pelo projeto.
- **Backend S3 configurado com `-backend-config="dynamodb_table=..."`**
  (`.github/workflows/02_terraform.yml:165-168`) — o projeto nunca reconfirmou na doc oficial do backend `s3` se
  esse é ainda o mecanismo de locking recomendado na versão de Terraform em uso (`>= 1.5.0`), já que o próprio
  Terraform introduziu ao longo do tempo opções de locking nativo no S3. Não assumir nem que precisa mudar nem
  que deve continuar como está — apenas sinalizar que é um ponto a verificar na doc oficial antes de qualquer
  mudança no backend, não decidir de memória.

## Regras práticas ao escrever/revisar mudança nova

- **Antes de propor um argumento de recurso Terraform novo ou alterado**: usar WebFetch no registry
  (`registry.terraform.io/providers/hashicorp/aws/...`) filtrando pela versão pinada em `infra/provider.tf`
  (`~> 6.0`) — nunca assumir que a doc "latest" reflete a versão realmente usada pelo projeto.
- **Antes de conceder ou revisar uma permissão IAM**: usar WebFetch no IAM Service Authorization Reference da
  action/serviço específico para confirmar se ela suporta `Resource` escopado antes de aceitar `Resource = "*"`
  — só aceitar wildcard quando a doc oficial confirmar a ausência de suporte a ARN, seguindo
  `especialista-privilegio-minimo`.
- **Antes de escolher um serviço AWS novo, ou avaliar um limite/quota/preço**: usar WebFetch na doc oficial do
  serviço específico, não decidir a partir de conhecimento geral sobre "como a AWS costuma funcionar".
- **Antes de alterar `required_version`, o bloco `backend "s3" {}` (incluindo as chaves passadas via
  `-backend-config` no workflow) ou qualquer argumento do provider `archive`**: usar WebFetch em
  `developer.hashicorp.com/terraform/language/...` ou no registry do `archive` — mesmo princípio já aplicado ao
  provider `aws`, agora também para o Terraform core e o segundo provider do projeto.
- **Ao tocar uma constante que já reflete um limite oficial da AWS** (DPU mínima, timeout máximo, retenção
  máxima, região obrigatória de um serviço): reconfirmar o valor atual na doc oficial antes de mudar ou de
  assumir que o valor já documentado no projeto continua correto.
- **Se a fonte oficial divergir do que está documentado no projeto** (`especialista-arquitetura-aws`,
  `especialista-infraestrutura-terraform`, `especialista-privilegio-minimo`, `especialista-finops-aws`,
  `infra/docs/*.md`), atualizar o `.md`/skill do projeto no mesmo PR, não só o código.
