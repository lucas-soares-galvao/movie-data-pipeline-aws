# CLAUDE.md — Contexto do Projeto

Pipeline de engenharia de dados serverless na AWS que coleta, transforma, valida e unifica dados de filmes e séries da API do TMDB. O resultado alimenta o FilmBot, uma interface web com IA que recomenda títulos em linguagem natural.

## Idioma

Projeto inteiramente em **português**: código, comentários, commits, documentação e nomes de variáveis descritivas.

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

Para entender o projeto em profundidade, consulte as skills em `.claude/skills/`:

- **projeto-filmes-aws.md** — Arquitetura do pipeline, camadas de dados, tabelas, variáveis de ambiente, convenções
- **estrutura-projeto.md** — Árvore de diretórios, workflows CI/CD, estrutura Terraform, organização de testes
- **revisao-testes-documentacao.md** — Checklist obrigatório pós-mudança: testes, arquivos `.md`, docstrings e type hints
