---
name: revisao-pos-mudanca-codigo
description: Checklist obrigatório pós-mudança de código neste projeto — testes, arquivos .md por módulo, docstrings, type hints e permissão IAM quando a mudança chama um serviço AWS novo/diferente — com ponte para as skills de qualidade/teste/documentação/IAM que devem guiar a mudança ao longo do caminho (especialista-engenharia-dados-app, especialista-legibilidade-codigo, especialista-testes-app, especialista-documentacao, especialista-privilegio-minimo). Use sempre ao terminar uma alteração em app/, test/ ou scripts/, antes de reportar a tarefa como concluída. Cobre o que verificar e onde, mapeando cada camada de código à sua documentação/teste espelhado.
---

# Skill: Revisão Pós-Mudança de Código

Após **toda alteração de código** neste projeto, execute este checklist antes de considerar a tarefa concluída.

---

## 0. Antes do Checklist

Este checklist é a conferência final — não é o único momento em que qualidade de código entra em jogo. Ao
escrever ou alterar a lógica de negócio em si, estas duas skills já deveriam ter guiado o código antes de chegar
aqui:

- **`especialista-engenharia-dados-app`** — padrão `main.py`/`src/utils.py`, reaproveitamento de `shared_src`,
  type hints e docstrings completos por serviço AWS.
- **`especialista-legibilidade-codigo`** — nomes descritivos, extração de função/CTE, comentários que explicam o
  "porquê".

Se o código ainda não seguiu essas skills, corrija antes de rodar os checklists abaixo — eles verificam o
resultado, não substituem o processo de escrever bem.

Se a mudança faz o código chamar um serviço/action AWS novo ou diferente do que já chamava, o checklist da Seção 1
tem um item específico para isso, com ponte para `especialista-privilegio-minimo`.

---

## 1. Testes

### Checklist

- [ ] **Funções novas ou modificadas em `app/<modulo>/src/utils.py` ou `main.py`** possuem testes correspondentes em `test/<modulo>/test_utils.py` ou `test_main.py`?
- [ ] **Novos branches de lógica** (if/else, try/except, loops com condição) estão cobertos por cenários de teste (caso feliz + caso de erro)?
- [ ] **Parâmetros novos ou removidos** de funções existentes foram refletidos nos mocks e chamadas dos testes?
- [ ] **Fixtures em `conftest.py`** foram atualizadas se a assinatura de dependências mudou?
- [ ] **Cobertura >= 80%** — rode `pytest --cov=app --cov-report=term-missing --cov-fail-under=80` e confirme que o gate passa
- [ ] **A mudança faz uma chamada nova/diferente a um serviço AWS?** (novo bucket/prefixo S3, nova tabela do Glue Catalog, novo client/action boto3 ou awswrangler, módulo passa a rodar sob outra role) — se sim, confirmar que a policy IAM da role correspondente em `infra/*.tf` já cobre essa permissão antes de reportar a tarefa como concluída; ver `especialista-privilegio-minimo` (racional de escopo mínimo) e `especialista-infraestrutura-terraform` (sintaxe do recurso). Se a policy não cobrir, é mudança de infra que precisa acompanhar o PR — sinalizar ao usuário, não apenas ao código de `app/`. Skip se a mudança não introduz nenhuma chamada nova/diferente a um serviço AWS (refactor puro, transformação de dado já lido, ajuste de teste).

> Para *como* escrever/mockar cada teste corretamente (padrão de mock por serviço AWS — Lambda, Glue
> awswrangler, Glue PySpark, Lightsail), ver `especialista-testes-app`.

### Onde criar testes

```
app/<modulo>/src/utils.py  →  test/<modulo>/test_utils.py
app/<modulo>/main.py       →  test/<modulo>/test_main.py
app/shared_src/shared_utils/api_client.py    →  test/shared_src/test_api_client.py
app/shared_src/shared_utils/triggers.py      →  test/shared_src/test_triggers.py
app/shared_src/shared_utils/glue_helpers.py  →  test/shared_src/test_glue_helpers.py
app/shared_src/shared_utils/traducao.py      →  test/shared_src/test_traducao.py
app/lightsail_ia/agent.py  →  test/lightsail_ia/test_agent.py
```

Se o módulo de teste ainda não existe, crie seguindo a estrutura espelhada com `__init__.py`, `conftest.py` e `requirements_tests.txt`.

---

## 2. Documentação — Arquivos `.md`

### Checklist

- [ ] **Módulo alterado** — o arquivo `app/<modulo>/<modulo>.md` reflete as mudanças? (novas funções, parâmetros, fluxos, dependências)
- [ ] **Testes alterados** — o arquivo `test/<modulo>/<modulo>_tests.md` reflete os novos cenários, fixtures ou dependências de teste?
- [ ] **Infraestrutura alterada** — os docs em `infra/docs/` (`overview.md`, `recursos.md`, `pipeline.md`, `iam.md`) estão atualizados?
- [ ] **Skills** — se a mudança afeta arquitetura, estrutura de pastas, convenções ou fluxos do pipeline, atualize as skills em `.claude/skills/` (`projeto-filmes-aws`, `estrutura-projeto`); se afeta um domínio coberto por uma skill especialista (IAM, Terraform, testes, observabilidade/DQ, segurança, FinOps, etc.), atualize também essa skill — não só as duas gerais
- [ ] **CLAUDE.md** — se a mudança introduz novo comando útil, nova convenção ou novo módulo, atualize o `CLAUDE.md` raiz

> Para os templates e o formato esperado de cada `.md` (por módulo, por teste, por skill), ver
> `especialista-documentacao`.

---

## 3. Documentação — Docstrings

### Checklist

- [ ] **Toda função pública** (não prefixada com `_`) tem docstring descrevendo o que faz
- [ ] **Parâmetros** estão documentados na docstring com nome e descrição
- [ ] **Retorno** está documentado na docstring
- [ ] **Exceções lançadas** (raises) estão documentadas quando relevantes
- [ ] Docstrings existentes em funções modificadas foram **atualizadas** para refletir as mudanças

### Formato esperado

```python
def minha_funcao(param1: str, param2: int) -> dict:
    """Descrição curta do que a função faz.

    Args:
        param1: Descrição do parâmetro 1.
        param2: Descrição do parâmetro 2.

    Returns:
        Descrição do retorno.

    Raises:
        ValueError: Quando param2 é negativo.
    """
```

---

## 4. Documentação — Type Hints

### Checklist

- [ ] **Toda função** (pública e privada) tem type hints em todos os parâmetros e no retorno
- [ ] **Tipos complexos** usam `dict`, `list`, `tuple`, `Optional`, `Union` do módulo `typing` quando necessário
- [ ] **Variáveis com tipo ambíguo** (ex.: retorno de API, JSON parseado) possuem anotação explícita
- [ ] **Type hints existentes** em funções modificadas foram atualizados se a assinatura mudou
- [ ] Rode `mypy app/` e confirme que não há erros novos

---

## Como Aplicar

Ao finalizar qualquer alteração de código:

1. Identifique todos os arquivos modificados
2. Para cada arquivo, percorra os 4 checklists acima
3. Faça as correções necessárias antes de reportar a tarefa como concluída
4. Rode os comandos de validação:
   ```bash
   pytest --cov=app --cov-report=term-missing --cov-fail-under=80
   ruff check app/ test/
   mypy app/
   ```

**A tarefa só está concluída quando todos os itens aplicáveis estiverem verificados.**
