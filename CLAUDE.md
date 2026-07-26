# CLAUDE.md — Contexto do Projeto

Pipeline de engenharia de dados serverless na AWS que coleta, transforma, valida e unifica dados de filmes e séries da API do TMDB. O resultado alimenta o FilmBot, uma interface web com IA que recomenda títulos em linguagem natural.

## Idioma

Prosa em **português**: comentários, docstrings, commits e documentação (`.md`).

Identificadores de código — nomes de colunas de tabela/DataFrame, variáveis, funções e parâmetros — ficam em **inglês**. Exceção: nomes de método de teste (`test_*`) continuam descritivos em português, no mesmo estilo de toda a suíte — funcionam como especificação do comportamento testado, não como identificador técnico.

## Convenções de Desenvolvimento

- Lógica de negócio fica em `app/<modulo>/src/utils.py`; `main.py` apenas resolve argumentos e delega
- Testes em `test/` espelham a estrutura de `app/` — cada módulo tem `conftest.py`, `test_main.py`, `test_utils.py`
- Scripts de operação manual em `scripts/` também têm testes espelhados em `test/scripts/` (um `test_<script>.py` por script), mas ficam fora do gate de 80% — `scripts/` não entra em `--cov=app`. Os testes ainda rodam e bloqueiam o CI normalmente
- Cada módulo em `app/` tem um `.md` descrevendo o que faz, e cada módulo em `test/` tem um `*_tests.md`
- Quality gate: cobertura de testes **>= 80%** (bloqueante no CI)
- Infraestrutura gerenciada por **Terraform** em `infra/`
- CI/CD via **GitHub Actions** com OIDC (sem Access Keys fixas)
- Ambientes isolados: `dev` e `prod` em contas AWS separadas

## Comandos Úteis

```bash
# Testes de um módulo específico
pytest test/<modulo>/ -v

# Testes com cobertura completa (gate de 80%)
pytest --cov=app --cov-report=term-missing --cov-fail-under=80

# Lint
ruff check app/ test/

# Type check
mypy app/

# Segurança
bandit -r app/
```

## Skills para Contexto Detalhado

As skills ficam em `.claude/skills/<nome>/SKILL.md` (formato de diretório) e por isso são descobertas
automaticamente pelo Claude Code — carregadas por relevância ou invocadas via `/nome-da-skill`. Esta lista é um
índice de referência rápida para humanos; ao criar, remover ou renomear uma skill, atualizar aqui **e** em
`.claude/skills/skills_doc.md` no mesmo PR. Para o uso e o cenário/gatilho detalhado de cada skill, ver
[`.claude/skills/skills_doc.md`](.claude/skills/skills_doc.md).

Consulte para entender o projeto em profundidade:

- **projeto-filmes-aws** — Arquitetura do pipeline, camadas de dados, tabelas, variáveis de ambiente, convenções
- **estrutura-projeto** — Árvore de diretórios, workflows CI/CD, estrutura Terraform, organização de testes
- **revisao-testes-documentacao** — Checklist obrigatório pós-mudança: testes, arquivos `.md`, docstrings e type hints
- **especialista-doc-oficial-aws** — Gate de consulta à fonte oficial da AWS e do Terraform (docs de serviço, registry dos providers `aws`/`archive`, Terraform core, IAM Service Authorization Reference) antes de decisões de infraestrutura/serviço/permissão
- **especialista-doc-oficial-codigo** — Gate de consulta à documentação oficial de Python/SQL/bibliotecas de dados (pandas, PySpark, awswrangler, boto3) e do framework de testes (pytest, unittest.mock) antes de decisões de implementação em `app/` e `test/`
- **especialista-documentacao** — Templates de docs por módulo/teste/skill, convenção de onde cada coisa mora, e quando criar/atualizar/juntar uma skill
- **especialista-api-tmdb** — Gate de consulta à documentação oficial da API do TMDB antes de decisões de implementação (endpoint novo, parâmetro alterado, paginação, rate limit)
- **especialista-arquitetura-aws** — Qual serviço AWS escolher para uma necessidade nova (custo x benefício x eficiência)
- **especialista-finops-aws** — Custo x benefício dos recursos AWS já escolhidos (lifecycle S3, DPU Glue, bundle Lightsail, retenção de log)
- **especialista-infraestrutura-terraform** — Argumentos exatos de recurso Terraform, `depends_on`, convenções de nomeação por serviço AWS
- **especialista-privilegio-minimo** — Privilégio mínimo das policies IAM, bootstrap de policies do CI/CD
- **especialista-seguranca-aplicacao** — Prevenção de vazamento de segredos/credenciais, de SQL injection e de abuso automatizado (bots) no FilmBot
- **especialista-observabilidade-qualidade-dados** — Alarmes CloudWatch, tópicos SNS, logs, e regras DQDL de Data Quality
- **especialista-workflows-github** — Mecânica YAML dos workflows GitHub Actions (triggers, `workflow_call`, secrets, supply-chain)
- **especialista-scripts-backfill** — Racional de design dos scripts de backfill manual (checkpoint S3, exit code 75, granularidade de unidade, padrões de tratamento de erro)
- **especialista-engenharia-dados-app** — Código Python/SQL/PySpark/awswrangler em `app/`, por serviço AWS
- **especialista-design-dados** — Particionamento, modo de escrita/idempotência (overwrite vs. overwrite_partitions vs. read-merge-write), formato por camada (JSON/Parquet) e processamento incremental/delta nos jobs Glue
- **especialista-testes-app** — Testes em `test/`, por serviço AWS (mocks de boto3/awswrangler/Athena/PySpark)
- **especialista-legibilidade-codigo** — Clareza e legibilidade de código Python e SQL em `app/`/`test/`
- **especialista-custo-llm-agente** — Custo de tokens/LLM do agente de recomendação do FilmBot
- **especialista-streamlit-filmbot** — UI Streamlit do FilmBot (design system "Luminous", responsividade)
