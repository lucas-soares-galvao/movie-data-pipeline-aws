---
name: revisao-de-pr
description: Checklist de revisão de um Pull Request completo (diff de outra sessão/pessoa, via `git diff <base>...HEAD` ou `gh pr diff <numero>`) antes do merge — cobre as mesmas camadas de revisao-pos-mudanca-codigo (testes, docs, docstrings, type hints, IAM) mais infra/Terraform, workflows GitHub, Streamlit/FilmBot e segurança, e sinaliza explicitamente o que o CI de 01_test.yml não bloqueia (mypy/bandit/safety são apenas informativos) e o que ele não verifica (sincronia de .md, testes de scripts/). Use ao revisar um PR pronto antes de aprovar/mergear — não ao terminar sua própria mudança na sessão atual (nesse caso, revisao-pos-mudanca-codigo).
---

# Skill: Revisão de PR

Use este checklist ao revisar um **Pull Request pronto**, antes de aprovar ou mergear — o diff pode vir de outra
sessão, de outra pessoa, ou simplesmente não ser o trabalho que você acabou de escrever agora.

---

## 0. Relação com revisao-pos-mudanca-codigo

- Se você é quem acabou de fazer a mudança **nesta mesma sessão**, use `revisao-pos-mudanca-codigo` — ela já
  cobre o checklist de testes/docs/docstrings/type hints/IAM logo depois de escrever o código.
- Use **esta** skill ao revisar um PR já aberto, de outra sessão ou pessoa, antes do merge. Os 4 checklists de
  base são os mesmos das duas skills — aqui eles são aplicados sobre o **diff completo**, arquivo por arquivo, não
  sobre a mudança que você mesmo acabou de fazer.

---

## 1. Obter e classificar o diff

```bash
git diff origin/main...HEAD    # ou a branch base correta
gh pr diff <numero>            # se revisando via número do PR
```

Classifique os arquivos alterados por camada — cada uma tem um gate e uma skill de ponte diferentes:

- `app/<modulo>/`
- `test/<modulo>/`
- `scripts/`
- `infra/*.tf`
- `.github/workflows/*.yml`
- `app/lightsail_ia/` (UI/agente do FilmBot)
- `.claude/skills/**` e `.md` de raiz (`CLAUDE.md`, `README.md`)

---

## 2. Checklist por camada

| Camada alterada | O que checar | Skill de ponte |
|---|---|---|
| `app/<modulo>/src/utils.py` ou `main.py` | Testes correspondentes existem (`revisao-pos-mudanca-codigo` seção 1), docstrings completas, type hints em toda função, e — se a mudança chama um serviço/action AWS novo/diferente — a policy IAM da role já cobre isso em `infra/*.tf` | `especialista-engenharia-dados-app`, `especialista-legibilidade-codigo`, `especialista-privilegio-minimo` |
| Particionamento, `mode` de escrita (`overwrite`/`overwrite_partitions`/merge manual) em job Glue | Idempotência preservada — rodar o job duas vezes não duplica dados | `especialista-design-dados` |
| Chamada a `api.themoviedb.org` nova ou com parâmetro alterado | Comportamento confirmado contra a doc oficial do TMDB, não por memória | `especialista-api-tmdb` |
| `test/<modulo>/test_*.py`, `conftest.py` | Cobertura do diff não caiu abaixo de 95% em `app/`; mocks de boto3/awswrangler/Athena/PySpark corretos | `especialista-testes-app` |
| `scripts/*.py` | Teste espelhado em `test/scripts/test_<script>.py` existe e passa — **não aparece no gate de 95%** (`scripts/` fica fora de `--cov=app`), então o CI não avisa se faltar | — |
| `infra/*.tf` | Argumentos do recurso corretos, `depends_on` coerente, privilégio mínimo na policy IAM (nunca `Resource: "*"` sem justificativa), custo do recurso novo/alterado | `especialista-infraestrutura-terraform`, `especialista-privilegio-minimo`, `especialista-finops-aws` |
| `.github/workflows/*.yml` | Contrato de `workflow_call` (inputs/secrets/outputs) respeitado, `permissions:` no menor escopo, pin de ação de terceiro sem regressão de supply-chain | `especialista-workflows-github` |
| `app/lightsail_ia/` (Streamlit, `agent.py`, `static/*.css\|js`) | Design system "Luminous" preservado, responsividade desktop/mobile; se mexeu no system prompt/tools/modelo do LLM, custo de tokens avaliado; se mexeu em input do usuário, sem abertura para SQL injection ou abuso automatizado | `especialista-streamlit-filmbot`, `especialista-custo-llm-agente`, `especialista-seguranca-filmbot` |
| Qualquer `.md` novo, removido ou renomeado | Sincronia com docs agregadoras (`estrutura-projeto`, `projeto-filmes-aws`) e com o índice em `CLAUDE.md`/`skills_doc.md` — nada no CI verifica isso automaticamente | `especialista-documentacao` |

---

## 3. Lacunas que o CI não cobre

`01_test.yml` já bloqueia `ruff check` e `pytest --cov=app --cov-fail-under=95` — não repita esse trabalho. O
valor desta skill está no que passa despercebido:

- **`mypy app/ --ignore-missing-imports`, `bandit -r app/ -ll` e `safety check` rodam no CI mas são apenas
  informativos** — nada os torna bloqueantes. Antes de aprovar, olhar o resultado desses três steps e decidir se
  algum achado ali é bloqueante de fato para este PR específico.
- **Sincronia de documentação não é verificada por nada automatizado.** Se um módulo, tabela, variável de
  ambiente, regra EventBridge ou modo de execução mudou, confirmar que o `.md` do módulo, o `.md` de teste, a
  skill de domínio relevante, `skills_doc.md` e o índice do `CLAUDE.md` foram todos atualizados juntos.
- **`scripts/` fica fora do gate de 95%** (`--cov=app` não inclui `scripts/`) — os testes espelhados em
  `test/scripts/` ainda precisam existir e passar; o CI não falha se faltarem.

---

## 4. Formato do relatório

Achados ordenados por severidade (mais grave primeiro), citando `arquivo:linha`, separados em dois grupos:

- **Bloqueia o merge** — equivalente ao que o CI já trata como gate: teste quebrado, cobertura de `app/` abaixo
  de 95%, violação de `ruff`, permissão IAM insuficiente para uma chamada AWS nova, DQDL faltando para tabela
  nova.
- **Recomendação, não bloqueia** — achados de `mypy`/`bandit`/`safety` (informativos no CI), gap de
  documentação, legibilidade, oportunidade de reaproveitar utilitário existente.

---

## Como Aplicar

1. Obtenha o diff completo do PR (seção 1) e classifique os arquivos por camada.
2. Para cada arquivo, percorra a linha correspondente do checklist da seção 2, consultando a skill de ponte
   quando a mudança exigir profundidade de domínio.
3. Aplique a seção 3 — confirme explicitamente os três pontos que o CI não bloqueia/não verifica.
4. Monte o relatório final no formato da seção 4 antes de aprovar ou pedir mudanças.
