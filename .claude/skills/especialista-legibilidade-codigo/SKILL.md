---
name: especialista-legibilidade-codigo
description: Especialista em legibilidade e clareza de código Python e SQL em app/ e test/. Use ao escrever ou revisar uma função nova, ao escrever ou revisar SQL Athena novo, ao nomear variável/função/coluna, ao decidir se extrai uma função ou uma CTE, ao escrever um comentário, ou ao avaliar se um trecho de código está fácil de entender para quem não o escreveu. Reforça o padrão de clareza já em vigor no projeto — não introduz convenção nova.
---

# Especialista em Legibilidade — Python e SQL, `app/` e `test/`

## Papel

Você é o guardião da legibilidade do código deste projeto, em Python (`app/`, `test/`, `scripts/`) e em SQL Athena (`app/glue_agg/src/queries.py` e SQL embutido em outros módulos). O critério é simples: **uma pessoa lendo o trecho pela primeira vez, sem contexto prévio, entende o que ele faz e por que ele existe, sem precisar perguntar a quem escreveu**. Você não inventa uma convenção nova de estilo — o projeto já opera num padrão de clareza alto (nomes descritivos, docstrings completas, comentários que explicam o "porquê", SQL comentado CTE a CTE); seu trabalho é reconhecer esse padrão, replicá-lo em código novo e sinalizar quando um trecho foge dele.

## Fontes de verdade (ler antes de agir)

Esta skill trata de legibilidade/clareza; não repete o que já está bem coberto em outro lugar:

| O quê | Onde |
|---|---|
| Checklist obrigatório de docstrings, type hints e testes pós-mudança | `revisao-testes-documentacao` |
| Organização do código por serviço AWS, onde vive cada função/query | `especialista-engenharia-dados-app` |
| Padrões de nomeação e estrutura de testes (`test_<comportamento>`, mocks) | `especialista-testes-app` |
| Idioma (identificadores em inglês, prosa/comentários em português) | `CLAUDE.md` (raiz) |

## Padrões de legibilidade em Python já em vigor — preservar

- **Nomes autoexplicativos em inglês**: o nome da função já diz o que ela faz sem abrir o corpo (`fetch_tmdb_data`, `collect_now_playing_data`, `derive_canonical_name`, `write_parquet_to_sot`). Verbo + objeto, sem abreviação obscura. Ao nomear algo novo, pergunte: "dá pra adivinhar o que isso retorna só pelo nome?"
- **`main.py` delega, `src/utils.py` concentra lógica** em funções pequenas, cada uma com uma responsabilidade (buscar dado, transformar, gravar) — nunca uma função que faz as três coisas sem necessidade. Isso é o que torna cada função testável isoladamente.
- **Comentário explica o "porquê", nunca o "o quê"** — o código já diz o quê. Exemplos reais a seguir como referência: `_CANONICAL_SUFFIXES` em `app/glue_etl/src/utils.py` explica por que a ordem da lista importa (sufixos mais específicos antes dos genéricos) e dá um exemplo concreto do bug que ocorreria na ordem errada; `MAX_PAGES` em `app/lambda_api/src/utils.py` explica o trade-off (limite real da API vs. timeout da Lambda) por trás do número 100, em vez de só dizer "número máximo de páginas".
- **Padrão de paginação replicado, não reinventado**: `collect_now_playing_data`, `collect_discover_data` e `fetch_changed_ids` (todos em `app/lambda_api/src/utils.py`) usam a mesma estrutura — loop com contadores nomeados (`saved_pages`/`failed_pages`), captura de `HTTPError` por página sem abortar a coleta inteira, `raise RuntimeError` só quando todas as páginas falham. Ao escrever uma função de paginação nova, siga essa estrutura em vez de criar uma variação.
- **Extrair helper privado quando a lógica se repete**, sem criar abstração além do necessário: `_add_translation` (`app/glue_etl/src/utils.py`) concentra a lógica comum de `_add_name_pt_countries`/`_add_name_pt_languages`, que viram wrappers de uma linha. Não crie uma camada de abstração genérica para um caso de uso único — três linhas parecidas em dois lugares não justificam um helper.
- **Docstring `Args`/`Returns`/`Raises` completa + type hints em toda função nova ou alterada** — sem exceção, é o padrão em 100% dos módulos (checklist detalhado em `revisao-testes-documentacao`). Uma docstring que só repete o nome da função (`"""Busca dados."""` numa função chamada `fetch_data`) não conta — ela precisa agregar informação que o nome não carrega (formato do retorno, efeitos colaterais, por que um parâmetro é opcional).
- **Evitar comprehension ou lambda aninhado que exija reler duas vezes** para entender. Uma list comprehension com um `if` simples é clara (`collect_watch_providers_ref` em `lambda_api/src/utils.py`); uma comprehension com múltiplos `for`/`if` aninhados ou lambda dentro de lambda não é — nesse caso, prefira um loop explícito, mesmo que fique mais longo.

## Padrões de legibilidade em SQL (Athena) já em vigor — preservar

Referência canônica: `app/glue_agg/src/queries.py` — a query mais complexa do projeto, e também a mais bem documentada.

- **CTEs nomeadas, uma responsabilidade por CTE**: cada bloco `WITH nome AS (...)` faz uma única coisa (deduplicar, unir, resolver um relacionamento) e o nome já entrega essa responsabilidade (`movies_ranked`, `genre_names`, `production_countries_resolved`). Evite uma CTE que faz duas coisas não relacionadas só para economizar um bloco.
- **Comentário de cabeçalho "leia de cima para baixo"**: no topo da query, uma lista numerada resume a sequência de CTEs antes de qualquer SQL — quem abre o arquivo entende o fluxo geral antes de mergulhar em cada bloco.
- **Alinhamento de `AS` em colunas renomeadas**: quando várias colunas são renomeadas na mesma `SELECT`, os `AS` ficam alinhados verticalmente — facilita escanear a lista e ver de relance o que cada coluna virou.
- **Comentário explica o "porquê" de uma técnica não óbvia, não a sintaxe**: por que `DENSE_RANK` e não `ROW_NUMBER` em `movie_wp_recent` (preservar todos os provedores do ano mais recente, não só um); por que `WITH ORDINALITY` em `production_countries_resolved` (preservar a ordem original do array ao reagrupar); por que `CAST(NULL AS ARRAY<VARCHAR>)` em `UNION ALL` (Athena exige tipo explícito nos dois lados). Um comentário que só parafraseia a cláusula SQL não agrega nada.
- **SQL como string fixa com placeholders (`.format()`), nunca concatenação dinâmica de fragmentos** — é o padrão em todo o projeto. A única exceção controlada é `app/lightsail_ia/agent.py`, onde uma cláusula `WHERE` gerada por LLM passa por `_validate_where` antes de ser interpolada (mecanismo em `especialista-engenharia-dados-app`, racional de segurança/SQL injection em `especialista-seguranca-aplicacao`); replicar esse padrão de validação para qualquer SQL novo montado a partir de input externo.

## Legibilidade em testes

- Nome de método `test_<comportamento>` descritivo em português (conforme `CLAUDE.md`) — o nome do teste funciona como especificação: alguém lendo só a lista de nomes de uma classe de teste entende o que o código sob teste faz.
- Um comportamento por teste — evite um `test_*` que testa três cenários com múltiplos blocos de assert desconectados; prefira dividir em métodos separados, cada um com um cenário e uma asserção central.
- Mocks e fixtures nomeados de forma que a asserção seja legível sem abrir a implementação (`mock_read_sql_query`, não `m1`/`mock2`); ver padrões já estabelecidos por serviço em `especialista-testes-app`.

## Checklist prático ao escrever ou revisar código novo

- [ ] O nome da função/variável/coluna entrega o que ela é/faz, sem precisar abrir o corpo?
- [ ] Toda função nova tem type hints completos e docstring `Args`/`Returns`/`Raises`?
- [ ] Cada comentário explica uma decisão não óbvia (o "porquê"), não repete o que a linha já diz?
- [ ] A função faz uma coisa só, ou está misturando busca de dado + transformação + gravação sem necessidade?
- [ ] Existe uma comprehension/lambda/CTE que exigiria reler duas vezes para entender? Se sim, vale simplificar.
- [ ] SQL novo: cada CTE tem nome e responsabilidade únicos, e qualquer técnica não óbvia (`DENSE_RANK`, `ORDINALITY`, `CAST(NULL AS ...)`) está comentada?
- [ ] Teste novo: o nome do método já descreve o comportamento verificado, em português?

## Anti-padrões a evitar

- Nome genérico (`data`, `tmp`, `df2`, `result`) fora de um escopo local trivial de 2–3 linhas.
- Docstring que só parafraseia o nome da função, sem agregar informação sobre formato de retorno, efeito colateral ou motivo de um parâmetro opcional.
- Função que mistura I/O, transformação e regra de negócio numa única sequência sem necessidade — dificulta testar cada parte isoladamente.
- Magic number sem constante nomeada e sem comentário do porquê daquele valor (compare com `MAX_PAGES = 100`, que tem os dois).
- CTE ou bloco de SQL complexo (window function, `UNNEST`, `CASE` longo) sem nenhum comentário explicando a intenção.
- Abstração genérica criada para um único caso de uso — prefira repetir três linhas simples a introduzir um helper configurável demais.
