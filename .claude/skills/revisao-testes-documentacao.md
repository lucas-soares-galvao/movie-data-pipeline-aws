# Skill: Revisão de Testes e Documentação Pós-Mudança

Após **toda alteração de código** neste projeto, execute este checklist antes de considerar a tarefa concluída.

---

## 1. Testes

### Checklist

- [ ] **Funções novas ou modificadas em `app/<modulo>/src/utils.py` ou `main.py`** possuem testes correspondentes em `test/<modulo>/test_utils.py` ou `test_main.py`?
- [ ] **Novos branches de lógica** (if/else, try/except, loops com condição) estão cobertos por cenários de teste (caso feliz + caso de erro)?
- [ ] **Parâmetros novos ou removidos** de funções existentes foram refletidos nos mocks e chamadas dos testes?
- [ ] **Fixtures em `conftest.py`** foram atualizadas se a assinatura de dependências mudou?
- [ ] **Cobertura >= 80%** — rode `pytest --cov=app --cov-report=term-missing --cov-fail-under=80` e confirme que o gate passa

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
- [ ] **Skills** — se a mudança afeta arquitetura, estrutura de pastas, convenções ou fluxos do pipeline, atualize as skills em `.claude/skills/` (`projeto-filmes-aws.md`, `estrutura-projeto.md`)
- [ ] **CLAUDE.md** — se a mudança introduz novo comando útil, nova convenção ou novo módulo, atualize o `CLAUDE.md` raiz

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
