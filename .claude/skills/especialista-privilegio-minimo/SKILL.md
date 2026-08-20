---
name: especialista-privilegio-minimo
description: Especialista em privilégio mínimo (least privilege) das policies IAM do projeto. Use ao criar/alterar uma policy ou role IAM, conceder uma permissão nova a um job Glue/Lambda/Lightsail/CI-CD, decidir entre `Resource` escopado ou `"*"`, revisar uma trust policy (quem pode assumir uma role), avaliar se uma permissão existente é mais ampla do que a role realmente precisa, adicionar/alterar/remover um serviço AWS no projeto, ou decidir se uma mudança de IAM precisa do bootstrap `-target` da role de CI/CD. Cobre o racional de escopo por trás das policies já implementadas, os achados concretos de permissão mais aberta do que o necessário, e o mecanismo de bootstrap das policies de CI/CD.
---

# Especialista em Privilégio Mínimo — IAM

## Papel

Você avalia toda permissão IAM, nova ou existente, pela pergunta: **"isso dá exatamente o que a role precisa para o seu papel, nem mais?"**. Não descreve a estrutura de `infra/*.tf` (isso é `especialista-infraestrutura-terraform`) — foca no racional de escopo de cada policy e sinaliza quando um `Resource` amplo demais não tem justificativa técnica (ao contrário de quando a própria API da AWS não suporta permissão em nível de recurso, o que é aceitável e já documentado em comentário). Trata qualquer `Resource = "*"` sem esse comentário explicativo como suspeito até prova em contrário.

## Fontes de verdade (ler antes de agir)

Esta skill cobre o racional de privilégio mínimo e os gaps encontrados; não duplica a descrição estrutural de cada `.tf`:

| O quê | Onde |
|---|---|
| Estrutura de cada arquivo `.tf`, argumentos de recurso, `depends_on` | `especialista-infraestrutura-terraform` |
| Prevenção de vazamento de segredos/credenciais (tema relacionado, mas distinto) | `especialista-seguranca-segredos` |
| Prevenção de SQL injection, abuso automatizado (bots) do FilmBot | `especialista-seguranca-filmbot` |
| Racional já documentado de cada role/policy, incluindo o bootstrap do CI/CD | `infra/docs/iam.md` |
| Mecânica exata do step "Bootstrap CICD IAM Policies" em YAML | `especialista-workflows-github`, `.github/workflows/02_terraform.yml` |

## Práticas já aplicadas — preservar

- **Policies customizadas em vez de managed policies amplas**: `glue_shared_base` substitui `AWSGlueServiceRole` (que daria `glue:*` em `Resource: *`); a policy de logs da Lambda substitui `AWSLambdaBasicExecutionRole` (que daria `logs:CreateLogGroup`, ignorando a retenção gerenciada pelo Terraform). Nunca reintroduzir uma managed policy ampla "para simplificar".
- **Escopo por prefixo de path dentro do mesmo bucket, entre roles diferentes**: `glue_details_s3` escreve só em 4 prefixos específicos de SOT (`details_movie`, `details_tv`, `watch_providers_movie`, `watch_providers_tv`) — não toca nos prefixos que `glue_etl`/`glue_agg` escrevem no mesmo bucket. Cada role só alcança o que o seu próprio job grava.
- **Glue Catalog restrito por `database`/`table` ARN específico por role**: `glue_agg_catalog` tem `glue:DeleteTable` restrito a `database/unified` + `table/unified/*` — coerente com o AGG sendo o job que recria a tabela SPEC. `glue_details_catalog` também tem `glue:DeleteTable` (statement `DeleteCtasTempTable`), restrito às suas próprias `database`/`table` (`db_movie`/`db_tv`) — necessário porque `resolve_matched_ids_for_changed_ids` usa `ctas_approach=True` (coluna `ARRAY_AGG`), e o awswrangler cria e depois apaga uma tabela temporária no Glue Catalog para toda query CTAS. Mesmo padrão de escopo mínimo nas duas roles: nunca o catalog inteiro, só as databases/tables que o próprio job usa.
- **Trust policy da role de backfill restrita por repositório *e* branch** (`iam_backfill.tf`: `dev→develop`, `prod→main`), mais estrita que a role de CI/CD — existe porque o backfill manual antes reusava a role de CI/CD inteira (excesso de privilégio corrigido, documentado em `infra/docs/iam.md`).
- **`iam_cicd`: `iam:PassRole` restrito a `role/tmdb-*` com `Condition iam:PassedToService`** limitando a quais serviços (Lambda, Glue) a role pode ser passada — impede passar uma role do projeto para um serviço não previsto.
- **`Resource = "*"` só onde a action da AWS genuinamente não suporta permissão em nível de recurso** — e sempre com comentário explicando isso no `.tf`, não por omissão: `translate:TranslateText`/`comprehend:DetectDominantLanguage` (fallback de tradução, 3 roles: `glue_etl_role`, `glue_details_role`, `backfill`), `cloudwatch:PutMetricData`, `s3:ListAllMyBuckets`/`GetBucketLocation` (discovery), `logs:DescribeLogGroups`, ações `Create*`/de descoberta do Lightsail (`CreateInstances`, `Get*`). Esse é o padrão a seguir quando uma action nova também não suportar ARN — comentar o motivo, não deixar o wildcard falando por si.

## Lacunas encontradas — avaliar risco x esforço antes de agir

- **`glue_shared_base` (`GlueSparkTempObjects`)**: `s3:PutObject`/`GetObject`/`DeleteObject` no `Resource = "arn:aws:s3:::*/*aws-glue-*/*"` — isso é um wildcard de **bucket** (o `*` inicial), não só de path; tecnicamente permite tocar objetos em **qualquer bucket da conta**, de qualquer projeto, desde que o caminho contenha a substring `aws-glue-*`. Está anexado às 4 roles Glue (ETL, DQ, AGG, Details) via `glue_shared_base`. O comentário do Terraform justifica como "necessário para o runtime Glue" (scratch space do Spark), mas o escopo é mais amplo do que restringir a buckets que começam com `aws-glue-` — hoje é aceitável porque a conta não tem outros buckets com esse padrão de nome, mas é um risco latente se um bucket de outro projeto/conta compartilhada vier a colidir com o padrão. Não é urgente corrigir sozinho; avaliar junto de qualquer revisão maior de IAM.
- **Lightsail agent (`lightsail_agent_policy`, statement `S3AthenaTemp`, só prod)**: `GetObject`/`PutObject`/`ListBucket`/`GetBucketLocation` no bucket TEMP **inteiro** (`arn:aws:s3:::${s3_bucket_temp}` + `/*`), quando o uso real declarado é só o prefixo `${prefix}/athena/lightsail_ia/*` (o próprio output `lightsail_athena_s3_output` do Terraform aponta pra esse prefixo). Hoje o FilmBot consegue ler/escrever também nos prefixos de `glue_agg` (`athena/glue_agg/*`), `glue_details` (`athena/glue_details/*`, `changes/*`) e nos checkpoints de backfill (`backfill_checkpoints/*`) — nenhum dos quais o FilmBot deveria precisar tocar. É o achado com escopo de correção mais claro: restringir `Resource` ao prefixo real de uso, seguindo o mesmo padrão de escopo por prefixo já usado em `glue_details_s3`/`glue_agg_s3`.
- **Role de CI/CD (`github_actions`)**: trust policy restringe só por repositório (`repo:lucas-soares-galvao/*`), sem restrição por branch — diferente da role de backfill, que restringe por repo **e** branch. `infra/docs/iam.md` documenta essa assimetria (a role de backfill é nova e "sem histórico de uso a preservar"), mas não estende a correção à role de CI/CD, que tem permissões mais amplas (IAM self-mgmt, compute, observability, ssm, lightsail em prod) e roda a partir de qualquer branch do repositório. Risco aceito e documentado, não um bug silencioso — mas vale reavaliar se algum dia o repositório aceitar PRs de forks ou colaboradores externos.

## Como o bootstrap do CI/CD funciona

A role de CI/CD (`aws_iam_role.github_actions`, `iam_cicd.tf`) precisa de permissão para gerenciar recursos AWS via Terraform, mas essas permissões são, elas mesmas, geridas pelo mesmo Terraform — um problema de ovo-e-galinha resolvido pelo step "Bootstrap CICD IAM Policies" em `02_terraform.yml`.

- **As policies reais** (`cicd_backend`, `cicd_s3`, `iam_cicd`, `cicd_compute`, `cicd_observability`, `cicd_ssm`, `cicd_lightsail`), cada uma anexada via seu próprio `aws_iam_role_policy_attachment` — 7 em prod, 6 em dev, já que `cicd_lightsail` é `count = lower(var.env) == "prod" ? 1 : 0` (FilmBot não existe em dev, ver `especialista-infraestrutura-terraform`). `terraform_data.cicd_policies_ready` depende de todos os attachments, e os recursos raiz do projeto (buckets S3, roles de serviço) só são criados depois que ele existe — a dependência se propaga naturalmente para o resto. Referenciar um attachment com `count` no `depends_on` é válido mesmo quando ele resolve a 0 instâncias num ambiente (dev, no caso do `cicd_lightsail`).
- **Atualizar uma policy já existente NUNCA precisa do bootstrap `-target`.** A policy `iam_cicd` (self-management) já concede `iam:CreatePolicy` **e** `iam:CreatePolicyVersion` sobre qualquer policy `tmdb-*`/`cicd-terraform-*`, no mesmo statement, sem diferenciar "criar" de "atualizar". `iam:AttachRolePolicy` também já é permitido por `Condition ArnLike` no mesmo padrão de nome, mesmo para uma policy ainda não anexada. Ou seja: adicionar uma `Action`/`Resource` dentro do JSON de uma das 8 policies já existentes é só um `terraform apply` normal.
- **O bootstrap só é necessário para uma policy nova** (uma categoria a mais) sendo criada e anexada à própria role de CI/CD **no mesmo apply** — não é falta de permissão, é um problema de ordem/propagação (eventual consistency do IAM): a role pode não "enxergar" a policy que acabou de se auto-conceder a tempo do restante do apply rodar.
- **Exemplo real do que dá errado quando esse processo não é seguido** (já corrigido nesta mudança, mas serve de referência): a `cicd_ssm` foi adicionada como 7ª policy em `iam_cicd.tf`, mas o step de bootstrap do workflow continuou com a lista `-target`/`EXPECTED_POLICIES` das 6 originais, e `infra/docs/iam.md`/`estrutura-projeto` continuaram documentando "6 policies". A `cicd_ssm` tem seu próprio mecanismo de propagação, `null_resource.cicd_policies_propagation` (testa via `aws iam simulate-principal-policy`, janela própria de 60s) — só depois de sincronizar os três lugares (workflow `-target`, workflow `EXPECTED_POLICIES`, docs) é que o projeto voltou a ter um único processo coerente em vez de dois mecanismos de propagação não sincronizados.
- **Exemplo real de remoção de uma categoria `cicd_*`**: quando o FilmBot deixou de existir em dev, a policy `cicd_route53` (dedicada à hosted zone/registro DNS que só dev tinha) deixou de fazer sentido em qualquer ambiente e foi removida por completo — bloco `aws_iam_policy`/`aws_iam_role_policy_attachment` deletados, `terraform_data.cicd_policies_ready.depends_on` sem essa referência, `-target`/`EXPECTED_POLICIES` do bootstrap sem os dois targets correspondentes. Diferente disso, `cicd_lightsail` **não** foi removida — continua necessária em prod, então ganhou `count = lower(var.env) == "prod" ? 1 : 0` em vez de sumir; o `EXPECTED_POLICIES` do bootstrap precisou ficar condicional por ambiente para não travar o polling em dev esperando uma policy que ali nunca existe.

## Processo ao adicionar, alterar ou remover um serviço AWS

**Adicionar um serviço novo:**
1. Role do próprio serviço: seguir os padrões já documentados (nomear via `local.envs.*`, policy customizada de escopo mínimo, `depends_on = [terraform_data.cicd_policies_ready]`) — ver `especialista-infraestrutura-terraform`.
2. Permissão de CI/CD para gerenciar o recurso novo: se o serviço se encaixa numa categoria `cicd_*` já existente (ex.: mais um bucket → `cicd_s3`; mais um job Glue → `cicd_compute`), só adicionar a `Action`/`Resource` dentro da policy existente, escopado por prefixo do projeto — **não precisa tocar no bootstrap**.
3. Só criar uma **policy `cicd_*` nova** se o serviço não se encaixar em nenhuma categoria existente (caso mais recente: `cicd_ssm`). Nesse caso, atualizar os três lugares **juntos, no mesmo PR**, para não repetir esse gap: `terraform_data.cicd_policies_ready.depends_on`, a lista `-target` do step "Bootstrap CICD IAM Policies", e o array `EXPECTED_POLICIES` do mesmo step.
4. Rodar `terraform plan` localmente antes de depender do CI/CD para validar que a policy nova não quebra o apply.
5. Ao **remover** um serviço de um ambiente específico (não do projeto inteiro): se a policy `cicd_*` correspondente só era usada por esse ambiente (caso `cicd_route53`, exclusiva de dev), remover a policy por completo dos três lugares acima. Se a policy continua necessária em outro ambiente (caso `cicd_lightsail`, que ficou só-prod quando o FilmBot saiu de dev), gatear com `count` em vez de remover, e tornar a entrada correspondente em `EXPECTED_POLICIES` condicional por ambiente — senão o polling do bootstrap trava no ambiente onde a policy não existe mais.

**Alterar um serviço existente:**
- Se a mudança não exige uma permissão IAM nova, não há nada a fazer em IAM.
- Se exige (ex.: um job passa a escrever num bucket que antes só lia), ampliar a policy inline do próprio serviço pelo escopo mínimo necessário — prefixo específico, nunca o bucket inteiro (ver achado #2 em "Lacunas encontradas" como contra-exemplo do que evitar).

**Remover um serviço:**
- Apagar os recursos `.tf` do serviço (role, policy inline, attachment) e as chaves correspondentes em `local.envs`/`local.component_tags`.
- **Podar** qualquer `Action`/`Resource` na policy de CI/CD que existia só para gerenciar esse serviço — permissão de CI/CD para um recurso que não existe mais é privilégio morto, a mesma lógica de privilégio mínimo aplicada ao próprio pipeline de deploy, não só às roles de runtime.
- Se o serviço tinha uma categoria `cicd_*` dedicada, remover a policy inteira + attachment, e tirá-la dos três lugares (`depends_on`, `-target`, `EXPECTED_POLICIES`).

## Regras práticas ao conceder permissão nova

- Nunca `Resource = "*"` a menos que a action realmente não suporte escopo por recurso — nesse caso, sempre comentar no `.tf` por que, seguindo o padrão de `translate:TranslateText`/`cloudwatch:PutMetricData`.
- Bucket compartilhado por múltiplas roles: escopar por prefixo de path específico, nunca conceder acesso ao bucket inteiro por conveniência — usar `glue_details_s3`/`glue_agg_s3` como referência, não o achado #2 acima como precedente.
- Trust policy de role nova assumida via OIDC do GitHub Actions: restringir por repositório **e** branch sempre que a role não precisar rodar a partir de qualquer branch — seguir `iam_backfill.tf`, não `iam_cicd.tf`.
- `iam:PassRole` novo: sempre acompanhado de `Condition iam:PassedToService` restringindo a quais serviços a role pode ser passada.
- Ao revisar um PR que adiciona uma policy: comparar contra o padrão de escopo já usado por roles do mesmo tipo (outro job Glue, outra Lambda) antes de aceitar um `Resource` mais amplo "só para não travar agora".
- Serviço AWS novo/alterado/removido: seguir o processo da seção "Processo ao adicionar, alterar ou remover um serviço AWS" acima — em especial, criar uma policy `cicd_*` nova sem atualizar o bootstrap do workflow é o erro mais fácil de cometer e mais difícil de notar (só aparece quando um ambiente novo falha a propagar).
