# Documentação das Skills

Este arquivo detalha **o uso** e **o cenário/gatilho** de cada skill em `.claude/skills/`. É o complemento
detalhado do índice enxuto que vive em `CLAUDE.md` (seção "Skills para Contexto Detalhado") — aquele serve para
roteamento rápido em uma linha; este explica quando exatamente cada skill entra em ação e o que ela cobre.

> Ao criar, remover ou renomear uma skill: atualizar este arquivo **e** o índice em `CLAUDE.md` no mesmo PR (ver
> `especialista-documentacao`).
>
> **Essa sincronização é manual, sem gate automático.** Nada no CI confere se este arquivo, o índice do
> `CLAUDE.md` e as skills em `.claude/skills/` continuam batendo entre si — depende de quem fizer a mudança
> lembrar de atualizar os três no mesmo PR. Mesma lacuna já registrada em `especialista-documentacao` ("Nada no
> CI verifica se um `.md` ainda bate com o código").

## Tabela-resumo

| Skill | Resumo |
|---|---|
| [projeto-filmes-aws](#projeto-filmes-aws) | Arquitetura funcional do pipeline ponta-a-ponta (TMDB → S3 → Glue → FilmBot) |
| [estrutura-projeto](#estrutura-projeto) | Árvore de diretórios, workflows CI/CD e estrutura Terraform |
| [especialista-doc-oficial-aws](#especialista-doc-oficial-aws) | Gate: consultar doc oficial AWS/Terraform antes de decidir infra/serviço/permissão |
| [especialista-doc-oficial-codigo](#especialista-doc-oficial-codigo) | Gate: consultar doc oficial de Python/SQL/bibliotecas de dados antes de implementar |
| [especialista-api-tmdb](#especialista-api-tmdb) | Gate: consultar doc oficial da API do TMDB antes de mudar endpoint/parâmetro |
| [especialista-documentacao](#especialista-documentacao) | Templates de docs por módulo/teste/skill e ciclo de vida das skills |
| [revisao-testes-documentacao](#revisao-testes-documentacao) | Checklist obrigatório pós-mudança: testes, `.md`, docstrings, type hints |
| [especialista-arquitetura-aws](#especialista-arquitetura-aws) | Qual serviço AWS escolher para uma necessidade nova |
| [especialista-finops-aws](#especialista-finops-aws) | Custo x benefício dos recursos AWS já escolhidos |
| [especialista-infraestrutura-terraform](#especialista-infraestrutura-terraform) | Argumentos exatos de recurso Terraform por serviço AWS |
| [especialista-privilegio-minimo](#especialista-privilegio-minimo) | Privilégio mínimo das policies IAM |
| [especialista-engenharia-dados-app](#especialista-engenharia-dados-app) | Código Python/SQL/PySpark/awswrangler em `app/`, por serviço AWS |
| [especialista-design-dados](#especialista-design-dados) | Particionamento, modo de escrita/idempotência e formato por camada nos jobs Glue |
| [especialista-observabilidade-qualidade-dados](#especialista-observabilidade-qualidade-dados) | Alarmes CloudWatch, tópicos SNS, logs e regras DQDL |
| [especialista-scripts-backfill](#especialista-scripts-backfill) | Racional dos scripts de backfill manual (checkpoint S3, exit code 75) |
| [especialista-testes-app](#especialista-testes-app) | Testes em `test/`, por serviço AWS |
| [especialista-legibilidade-codigo](#especialista-legibilidade-codigo) | Clareza e legibilidade de código Python/SQL |
| [especialista-workflows-github](#especialista-workflows-github) | Mecânica YAML dos workflows GitHub Actions |
| [especialista-seguranca-aplicacao](#especialista-seguranca-aplicacao) | Vazamento de segredos, SQL injection e abuso automatizado no FilmBot |
| [especialista-streamlit-filmbot](#especialista-streamlit-filmbot) | UI Streamlit do FilmBot (design system "Luminous") |
| [especialista-custo-llm-agente](#especialista-custo-llm-agente) | Custo de tokens/LLM do agente de recomendação do FilmBot |

---

## Visão geral do projeto

Skills para entender o projeto como um todo antes de mexer numa parte específica.

### projeto-filmes-aws

**O que é:** descreve a arquitetura funcional do pipeline — o fluxo TMDB → S3 → Glue → FilmBot, as camadas de
dados (SOR/SOT/SPEC/DQ), as tabelas do Glue Catalog e as variáveis de ambiente de cada módulo.

**Quando usar:**
- Para entender o pipeline como um todo antes de mexer numa parte específica.
- Ao introduzir uma tabela ou camada de dados nova.
- Ao explicar o projeto a alguém que não o conhece.

### estrutura-projeto

**O que é:** a árvore de diretórios completa do projeto, o encadeamento dos workflows GitHub Actions
(`00_pipeline` a `05_backfill`), a estrutura de `infra/` (Terraform) e a organização de `test/` (que espelha
`app/`).

**Quando usar:**
- Ao localizar onde um arquivo/módulo/script deveria morar.
- Ao entender como os workflows de CI/CD se encadeiam.
- Ao navegar a estrutura de `infra/` pela primeira vez.
- Ao decidir onde documentar algo novo.

---

## Gates de consulta a fonte oficial

Estas três skills compartilham o mesmo padrão: **consultar a documentação oficial via WebFetch ANTES de decidir,
nunca depois de já ter escrito o código.** Nunca decidir a partir de memória ou suposição — essas fontes mudam
com frequência e valores hardcoded no projeto podem refletir o que era verdade só quando foram escritos.

### especialista-doc-oficial-aws

**O que é:** gate de consulta à fonte oficial da AWS (docs.aws.amazon.com/\<serviço\>), do registry do provider
Terraform `aws`/`archive` (respeitando a versão pinada em `infra/provider.tf`), do IAM Service Authorization
Reference, e do Terraform core (`required_version`, backend `s3`).

**Quando usar:**
- Ao escolher um serviço AWS novo.
- Ao adicionar/alterar um argumento de recurso do provider `aws`.
- Ao conceder ou revisar uma permissão IAM.
- Ao avaliar limite/quota/preço de um recurso.
- Ao alterar Terraform core, o bloco `backend "s3"` ou o provider `archive`.

**Quando pular:** a mudança é lógica de negócio pura em `app/`, sem tocar infraestrutura, serviço ou permissão
AWS/Terraform.

### especialista-doc-oficial-codigo

**O que é:** gate de consulta à documentação oficial de Python, SQL (Athena), das bibliotecas de dados do
projeto (pandas, PySpark, awswrangler, boto3) e do framework de testes (pytest, `unittest.mock`).

**Quando usar:**
- Ao usar uma função/método novo ou pouco comum de awswrangler, pandas, PySpark (na versão do `glue_version` do
  job, não a "latest") ou boto3.
- Ao escrever/alterar SQL Athena com função não trivial (window function, `ARRAY`/`UNNEST`, `CAST`).
- Ao usar sintaxe de Python stdlib em job Glue PythonShell (fixado em Python 3.9).
- Ao usar uma feature pouco comum de pytest/`unittest.mock`/`unittest.TestCase`.

**Quando pular:** a mudança é puramente estrutural/organizacional (mover código de lugar, renomear, extrair
função) sem introduzir chamada de biblioteca, sintaxe SQL ou API de teste nova.

### especialista-api-tmdb

**O que é:** gate de consulta à documentação oficial da API do TMDB (developer.themoviedb.org/reference).

**Quando usar:**
- Ao adicionar um endpoint novo.
- Ao alterar parâmetros de uma chamada já existente (idioma, região, paginação, `append_to_response`, janela de
  datas do Changes API).
- Ao mudar tratamento de rate limit/retry.
- Ao implementar/revisar qualquer função que chame `api.themoviedb.org` (`lambda_api`, `glue_details`,
  `shared_utils/api_client`).

**Quando pular:** a mudança não envolve nenhuma chamada HTTP nova ou alterada ao TMDB (ex.: transformação pura de
dados já coletados).

---

## Documentação e processo pós-mudança

### especialista-documentacao

**O que é:** especialista nos templates de documentação do projeto — docs por módulo
(`app/<modulo>/<modulo>.md`, `test/<modulo>/<modulo>_tests.md`), skills agregadoras (`estrutura-projeto`,
`projeto-filmes-aws`) e skills de domínio (`especialista-*`).

**Quando usar:**
- Ao criar um módulo novo (`app/` ou `scripts/`).
- Ao adicionar/remover uma tabela, script, variável de ambiente, regra EventBridge ou modo de execução.
- Ao escrever um `.md` novo em qualquer camada.
- Ao avaliar se uma skill/doc existente ainda bate com o código atual.
- Ao decidir se uma necessidade nova justifica criar uma skill, atualizar uma existente, ou mantê-la combinada
  com outra.

### revisao-testes-documentacao

**O que é:** o checklist mecânico obrigatório de "o que verificar" depois de qualquer mudança de código —
testes, `.md` por módulo, docstrings e type hints.

**Quando usar:**
- Sempre ao terminar uma alteração em `app/`, `test/` ou `scripts/`, **antes** de reportar a tarefa como
  concluída.

---

## Arquitetura e decisões de serviço AWS

### especialista-arquitetura-aws

**O que é:** especialista em qual serviço AWS usar para uma necessidade nova — custo x benefício x eficiência x
otimização.

**Quando usar:**
- Ao decidir qual serviço AWS atende uma necessidade nova (processamento, orquestração, armazenamento, compute
  do FilmBot).
- Ao avaliar trocar Lambda por Glue (ou o contrário), Athena por um data warehouse, Lightsail por
  Fargate/EC2, EventBridge direto por Step Functions, ou SSM Parameter Store por DynamoDB.

### especialista-finops-aws

**O que é:** especialista em FinOps para os serviços AWS do projeto (S3, Lambda, Glue, Lightsail, CloudWatch,
EventBridge, Athena, Secrets Manager).

**Quando usar:**
- Ao avaliar custo x benefício de um recurso novo ou existente.
- Ao revisar lifecycle de S3, capacidade de Glue Job/Lambda, bundle do Lightsail, retenção de logs.
- Ao decidir se vale adicionar Budgets/anomaly detection.

### especialista-infraestrutura-terraform

**O que é:** especialista em infraestrutura Terraform de `infra/`, organizado por serviço AWS (S3, Lambda, Glue,
Lightsail, IAM, EventBridge, SNS, SQS, CloudWatch, SSM).

**Quando usar:**
- Ao criar/alterar recursos `.tf`.
- Ao revisar argumentos de Glue Job/Lambda/Lightsail.
- Ao ajustar políticas IAM ou entender `depends_on` entre recursos.
- Ao seguir o padrão de nomeação via `locals.envs`/`project.json`.

### especialista-privilegio-minimo

**O que é:** especialista em privilégio mínimo (least privilege) das policies IAM do projeto.

**Quando usar:**
- Ao criar/alterar uma policy ou role IAM.
- Ao conceder uma permissão nova a um job Glue/Lambda/Lightsail/CI-CD.
- Ao decidir entre `Resource` escopado ou `"*"`.
- Ao revisar uma trust policy (quem pode assumir uma role).
- Ao adicionar/alterar/remover um serviço AWS no projeto, ou avaliar se uma mudança de IAM precisa do bootstrap
  `-target` da role de CI/CD.

---

## Engenharia de dados (app/)

### especialista-engenharia-dados-app

**O que é:** especialista em engenharia de dados focado no código de `app/` (Python, SQL, PySpark, awswrangler),
organizado por serviço AWS (Lambda, Glue, Lightsail).

**Quando usar:**
- Ao escrever, revisar ou estender lógica de negócio em `app/<modulo>/src/utils.py` ou `main.py`.
- Ao lidar com queries Athena/SQL embutidas em Python.
- Ao trabalhar com transformações PySpark (`glue_data_quality`) ou awswrangler (`glue_etl`/`glue_details`/`glue_agg`).
- Ao adicionar/alterar regras DQDL, ou decidir onde reaproveitar utilitários de `app/shared_src`.

### especialista-design-dados

**O que é:** especialista em decisões de design de dados que atravessam os jobs Glue (`glue_etl`, `glue_details`,
`glue_agg`, `glue_data_quality`) — particionamento, modo de escrita/idempotência (`overwrite` vs.
`overwrite_partitions` vs. read-merge-write manual), formato de arquivo por camada e processamento
incremental/delta.

**Quando usar:**
- Ao escolher `partition_cols`/`mode` para uma tabela nova ou alterada.
- Ao decidir se uma escrita precisa de merge manual antes do `wr.s3.to_parquet`.
- Ao investigar por que rodar um job duas vezes não duplica dados.
- Ao desenhar a lógica que define "o que já foi processado" (delta), ou ao avaliar o impacto de uma mudança de
  schema numa tabela existente.

### especialista-observabilidade-qualidade-dados

**O que é:** especialista em observabilidade (alarmes CloudWatch, tópicos SNS, logs) e qualidade de dados (Glue
Data Quality/DQDL) do pipeline.

**Quando usar:**
- Ao criar/alterar um alarme ou notificação.
- Ao adicionar uma tabela nova ao Glue Catalog (precisa de ruleset DQDL).
- Ao decidir se um evento novo deve notificar por e-mail, revisar `rulesets_dq.py`, avaliar se uma falha
  silenciosa pode passar despercebida, ou decidir onde/como logar algo novo.

### especialista-scripts-backfill

**O que é:** especialista no mecanismo de backfill manual em `scripts/` (checkpoint em S3, exit code 75,
retomada automática) e no racional de design dos 6 scripts + `backfill_shared.py`.

**Quando usar:**
- Ao criar um script de backfill novo.
- Ao alterar checkpoint/retry.
- Ao decidir se um script deve abortar no primeiro erro ou continuar (fire-and-forget vs. soft-fail).
- Ao revisar o guard de custo do `TRANSLATE_PROVIDER`, ou entender o contrato entre um script e
  `.github/workflows/05_backfill.yml`.

---

## Qualidade e testes

### especialista-testes-app

**O que é:** especialista em testes de `test/`, organizado por serviço AWS (Lambda, Glue PythonShell/awswrangler,
Glue Spark/PySpark, Lightsail, pacote compartilhado). Projeto usa pytest como runner, classes
`unittest.TestCase` e `unittest.mock` (sem moto).

**Quando usar:**
- Ao escrever ou revisar testes em `test/<modulo>/test_*.py` ou `conftest.py`.
- Ao mockar boto3/awswrangler/Athena/PySpark.
- Ao adicionar testes para um módulo novo, ou investigar o mecanismo de isolamento de `sys.modules` em
  `test/conftest.py`.

### especialista-legibilidade-codigo

**O que é:** especialista em legibilidade e clareza de código Python e SQL em `app/` e `test/`. Reforça o padrão
de clareza já em vigor no projeto — não introduz convenção nova.

**Quando usar:**
- Ao escrever ou revisar uma função nova, ou SQL Athena novo.
- Ao nomear variável/função/coluna.
- Ao decidir se extrai uma função ou uma CTE.
- Ao escrever um comentário, ou avaliar se um trecho de código está fácil de entender para quem não o escreveu.

---

## CI/CD

### especialista-workflows-github

**O que é:** especialista nos workflows GitHub Actions de `.github/workflows/` (`00_pipeline`, `01_test`,
`02_terraform`, `03_pr_auto`, `04_deploy_lightsail`, `05_backfill`) — a mecânica YAML que a documentação
narrativa (`estrutura-projeto`, `.github/workflow.md`) não detalha.

**Quando usar:**
- Ao criar/editar arquivos `.yml` de workflow.
- Ao revisar triggers/permissions/concurrency, contratos de `workflow_call` (inputs/secrets/outputs), ou
  condicionais `if:` entre jobs.
- Ao fazer pinning de actions de terceiros, ou avaliar risco de supply-chain em CI/CD.

---

## Segurança

### especialista-seguranca-aplicacao

**O que é:** especialista em segurança de aplicação em três eixos — (1) vazamento de segredos/credenciais no
repositório, CI/CD e ambiente local; (2) prevenção de SQL injection via input externo (usuário ou LLM); (3)
proteção contra abuso automatizado (bots/scripts) do FilmBot.

**Quando usar:**
- Ao criar arquivos `.example`, ou configurar steps de workflow que manipulam credenciais.
- Ao decidir o que entra em `.gitignore`, ou revisar `terraform.tfvars`.
- Ao avaliar exposição de rede (SSH/CIDR), revisar SQL montado a partir de input externo.
- Ao avaliar login/rate limit/limites de tamanho do FilmBot.

---

## FilmBot (Lightsail/Streamlit/LLM)

### especialista-streamlit-filmbot

**O que é:** especialista em construir/estilizar telas Streamlit do FilmBot seguindo o design system "Luminous"
já definido (cores, tipografia, componentes, motion), com foco em responsividade desktop/mobile.

**Quando usar:**
- Ao criar novas telas/seções do `app/lightsail_ia`.
- Ao redesenhar componentes existentes (cards, login, grid).
- Ao ajustar CSS/JS em `static/*.css|js`.
- Ao receber um pedido (texto ou imagem/mockup) para aplicar/replicar visualmente no Streamlit.

### especialista-custo-llm-agente

**O que é:** especialista em custo x benefício de tokens/LLM no agente de recomendação do FilmBot
(`app/lightsail_ia/agent.py`).

**Quando usar:**
- Ao alterar o system prompt.
- Ao adicionar uma tool/function calling nova.
- Ao mudar o modelo (`LLM_MODEL`/`TRANSCRIPTION_MODEL`).
- Ao ajustar cache de respostas, rate limiting, ou avaliar prompt caching.
