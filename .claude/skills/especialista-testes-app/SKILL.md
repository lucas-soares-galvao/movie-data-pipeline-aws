---
name: especialista-testes-app
description: Especialista em testes de test/, organizado por serviço AWS (Lambda, Glue PythonShell/awswrangler, Glue Spark/PySpark, Lightsail, pacote compartilhado). Use ao escrever ou revisar testes em test/<modulo>/test_*.py ou conftest.py, ao mockar boto3/awswrangler/Athena/PySpark, ao adicionar testes para um módulo novo, ou ao investigar o mecanismo de isolamento de sys.modules em test/conftest.py. Projeto usa pytest como runner, classes unittest.TestCase e unittest.mock (sem moto).
---

# Especialista em Testes — `test/` por Serviço AWS

## Papel

Você é o especialista responsável pelos testes em `test/`, que espelha `app/` módulo a módulo. A stack de teste do projeto, sempre presente e nunca a trocar: **`pytest` como executor** (via `pytest.ini`), casos escritos como **classes `unittest.TestCase`** com métodos `test_*` (por isso cada `<modulo>_tests.md` organiza os casos em seções "TestClassName"), e todo mock/stub feito com **`unittest.mock`** (`MagicMock`, `patch`, `patch.object`) — nunca `moto`, `pytest-mock`/`mocker` nem `botocore.stub.Stubber`, que não aparecem em lugar nenhum do projeto. Métodos de teste têm nome descritivo em português (`test_<comportamento>`, conforme `CLAUDE.md`); nem toda a base segue isso à risca (alguns testes em `glue_agg`/`glue_data_quality` têm nomes em inglês) — mantenha português em testes novos, sem reescrever os existentes só por consistência. Antes de mockar um colaborador AWS, verifique o padrão já em uso no mesmo serviço — Lambda, Glue awswrangler, Glue PySpark e Lightsail têm padrões de mock bem diferentes entre si (ver abaixo).

## Fontes de verdade (ler antes de agir)

| O quê | Onde |
|---|---|
| Árvore de `test/`, config geral do `pytest.ini` | `estrutura-projeto` |
| Checklist pós-mudança, mapeamento `app/<modulo>/src/utils.py → test/<modulo>/test_utils.py`, comandos de validação | `revisao-pos-mudanca-codigo` |
| Quality gate: cobertura de testes **>= 95%** (bloqueante no CI, `--cov-fail-under=95` em `.github/workflows/01_test.yml`) — `scripts/` e `app/lightsail_ia/{app,forms,recommendation,cards}.py` ficam fora desse gate via `omit=` no `.coveragerc` | `CLAUDE.md`, `revisao-pos-mudanca-codigo` |

## Débito de cobertura para chegar a 95% — ordem de prioridade

Com `app.py`/`forms.py`/`recommendation.py`/`cards.py` excluídos do gate (telas Streamlit, sem
framework de teste automatizado no projeto), a cobertura de `app/` fica em ~95,25% — margem mínima
(poucas linhas). Ao fechar essa lacuna, seguir esta ordem (do mais barato ao mais caro):

1. **`app/lightsail_ia/src/components.py`** — funções wrapper finas em torno de
   `st.markdown`/`components.html` (`_inject_css`, `load_base_css`, `load_forms_css`, `load_app_css`,
   `load_recommendation_css`, `load_cards_css`, `load_preference_counter_script`,
   `load_audio_cancel_script`, `render_footer`, `render_form_footer`). Reaproveitar o mock de
   `streamlit` que já cobre `render_card`/`render_grid` no mesmo arquivo. (Contagem de linhas
   faltando não recalculada nesta edição — mudou com o split de `app.py` em `forms.py`/
   `recommendation.py`/`cards.py`/`infrastructure.py`; ver `pytest --cov` para o número atual.)
2. **`app/lambda_api/src/utils.py`** (12 linhas faltando) — branches de erro em
   `collect_now_playing_data`/`collect_discover_data`: `except HTTPError` (retry/continue) e
   `if saved_pages == 0: raise RuntimeError`. Reaproveitar o mock de `tmdb_get`/`fetch_tmdb_data`
   levantando `HTTPError` já usado em outros testes do arquivo.
3. **`app/glue_details/src/utils.py`** (27 linhas faltando, maior bloco isolado) — parsing de
   `sys.argv` para `--FORCE_REFETCH`/`--TRANSLATE_PROVIDER`, a função `_fetch_collections_pt_br`
   inteira (busca paralela de coleções em pt-BR, ainda sem nenhum teste) e o branch de merge com
   dados existentes via `wr.s3.read_parquet` no fluxo de watch providers.
4. **`app/lightsail_ia/src/agent.py`** (12 linhas) e **`app/lightsail_ia/src/formatting.py`** (6 linhas) —
   branches de erro/edge case do agente de recomendação (LLM) e de formatação de data/duração;
   deixar por último por menor volume e maior complexidade de mock (LLM).
| Enumeração caso a caso de testes e fixtures de cada módulo | `test/<modulo>/<modulo>_tests.md` |
| Código Python/SQL/PySpark/awswrangler exercitado pelos testes | `especialista-engenharia-dados-app` |

## Mecanismo central: `test/conftest.py` (raiz) — isolamento entre suítes Glue

Problema: `glue_etl`, `glue_details`, `glue_agg`, `glue_data_quality`, `lambda_api` e `lightsail_ia` importam seus próprios módulos internamente via `src.X` (`src.utils` nos 5 primeiros, `src.agent`/`src.components`/`src.infrastructure`/`src.cards`/`src.forms`/`src.formatting`/`src.recommendation` em `lightsail_ia`) — mesmo nome de pacote raiz (`src`) em suítes diferentes, o que causaria uma suíte importar o módulo em cache de outra ao rodarem juntas na mesma sessão pytest.

Solução, em `test/conftest.py`:
- `import app` roda no topo do módulo, **antes** de qualquer `_set_suite_path`, cacheando o pacote real `app/` em `sys.modules["app"]`. Necessário porque `app/lightsail_ia/` tem um `app.py` próprio (entrypoint do Streamlit) — se a suíte `lightsail_ia` for a primeira do processo a rodar `_set_suite_path`, esse `app.py` ficaria à frente da raiz do repo no `sys.path` e sombrearia o pacote `app` de verdade (`import app` resolveria pro arquivo, não pro pacote), quebrando o import fully-qualified de **todas as outras suítes** pelo resto da sessão.
- `_SUITE_TO_APP` (nome da suíte → `Path` de `app/<modulo>`) e `_SUITE_TO_SRC_MODULE` (nome da suíte → módulo fully-qualified usado como âncora, ex. `app.glue_etl.src.utils`) registram as 6 suítes que colidem em `src`. Suítes sem entrada aqui (`shared_src`, `scripts`) não recebem alias — estrutura diferente, sem colisão de nome. Para `lightsail_ia`, que não tem `utils.py`, a âncora é `app.lightsail_ia.src.recommendation` (importa `agent`/`components`/`infrastructure` internamente, pré-populando a maioria dos aliases; `cards`/`login`/`formatting` resolvem sob demanda via `__path__` do pacote `src` já aliasado — mesmo mecanismo de resolução de subpacote que já cobre `src.rulesets_dq` em `glue_data_quality`).
- `pytest_collect_file` (hook chamado antes de cada arquivo de teste ser importado): identifica a suíte pelo primeiro segmento do path (`test/glue_etl/... → "glue_etl"`), limpa do `sys.modules` as chaves `src`, `main`, `utils`, `shared_utils` (e submódulos `src.*`/`shared_utils.*`), reconstrói `sys.path` via `_set_suite_path` (coloca `src/`, `app_dir` e `shared_src` da suíte atual na frente, removendo os das demais suítes), importa o módulo fully-qualified âncora da suíte e registra como `sys.modules["src.utils"]` (alias sem uso real em `lightsail_ia`, que não tem `utils.py` — inofensivo) — mais os aliases de cada submódulo de `src` já carregado sob o pacote fully-qualified (ex. `src.rulesets_dq` no `glue_data_quality`).
- `pytest_runtest_setup` (hook chamado antes de **cada teste individual**, via `_apply_suite_aliases`): reaplica os mesmos aliases — necessário porque a execução pode intercalar suítes diferentes — e restaura `sys.modules["main"]` para o módulo `main` correto da suíte, pois `patch("main.xxx")` resolve pela string em tempo de execução e ficaria apontando para a suíte errada.

**Regra prática**: ao criar um job Glue novo com `src/utils.py` (ou outro módulo que colida em `src.X`), registrar as chaves correspondentes em `_SUITE_TO_APP` e `_SUITE_TO_SRC_MODULE` em `test/conftest.py` — sem isso, os testes do módulo novo podem silenciosamente importar o módulo em cache de outro job. Se o novo módulo tiver um arquivo literalmente chamado `app.py` no próprio diretório (só `lightsail_ia` hoje), confirmar que o `import app` no topo do conftest continua rodando antes de qualquer `_set_suite_path` — é o que impede esse `app.py` de sombrear o pacote `app` real.

## `pytest.ini`

```ini
[pytest]
testpaths = test
pythonpath = . app/lambda_api scripts
python_files = test_*.py
```
`pythonpath` cobre só a raiz, `app/lambda_api` e `scripts` — o restante do path-wiring por suíte é dinâmico via `conftest.py` (seção acima), não estático aqui.

## Organização por serviço AWS

### AWS Lambda — `lambda_api`

Sem stub de `sys.modules`: `boto3`/`requests` são dependências reais instaláveis, nada a fingir. Mock no ponto de chamada — `patch("src.utils.<colaborador>", ...)` para funções do próprio módulo, ou um `MagicMock()` passado como argumento (ex. `s3_client`) — assertando via `mock.call_args`/`assert_called_once_with(...)`. `test/lambda_api/conftest.py` é essencialmente vazio (só documenta a ausência de `sys.path` global).

### AWS Glue — jobs PythonShell/awswrangler — `glue_etl`, `glue_details`, `glue_agg`

`conftest.py` de cada um só stuba `awsglue`/`awsglue.utils` (`getResolvedOptions = MagicMock()`, `GlueArgumentError = Exception`) via `sys.modules.setdefault` — sem tocar em PySpark, porque estes jobs usam `awswrangler`/pandas, não Spark.

- Consultas Athena testadas com `patch("...wr.athena.read_sql_query", return_value=<DataFrame>)`, verificando o **texto do SQL gerado** (`mock_read.call_args.kwargs["sql"]`, `assert "..." in sql`) — nunca execução real contra Athena.
- Gravação testada mockando `wr.s3.to_parquet` e assertando os kwargs (`path`, `partition_cols`, `mode`, `database`, `table`).

### AWS Glue — job Spark/PySpark — `glue_data_quality`

O único módulo com stub pesado, porque `awsglue`, `awsgluedq` e `pyspark` não existem fora do runtime do Glue. Em `test/glue_data_quality/conftest.py`, um helper `_make_module(name, **attrs)` cria módulos falsos registrados via `sys.modules.setdefault` (nunca sobrescreve um pacote real, caso os testes rodem dentro do ambiente Glue):

- `awsglue`, `awsglue.utils` (`getResolvedOptions=None` — trocado por `MagicMock()` em cada teste que precisa), `awsglue.context` (`GlueContext=None`), `awsglue.dynamicframe` (`DynamicFrame=None`)
- `awsgluedq`, `awsgluedq.transforms` (`EvaluateDataQuality=None`)
- `pyspark`, `pyspark.context` (`SparkContext=None`), `pyspark.sql` (`DataFrame=MagicMock`), `pyspark.sql.functions` (`col=MagicMock()`, `when=MagicMock()` — **precisam** ser `MagicMock`, não `None`, porque o código de produção as chama e encadeia diretamente, ex. `col("year") == year`, `when(...).when(...)`; já `coalesce`, `from_utc_timestamp`, `lit`, `current_timestamp` ficam `None` no conftest e são sobrescritas via `patch` nos testes individuais que as exercitam), `pyspark.sql.types` (`StringType=MagicMock()`, pois é instanciada)

**Nunca instalar/importar PySpark real nem criar `SparkSession`** — todo o fluxo opera sobre `MagicMock()`. DataFrames são mocks encadeáveis: configure `.withColumnRenamed.return_value = df_mock` (e equivalentes) para que a cadeia de chamadas do código de produção continue retornando o mesmo mock. Asserções tipicamente checam `.assert_any_call(...)` nos métodos do DataFrame mock e nas funções PySpark mockadas. `write_results_to_s3` (que converte para pandas com `.toPandas()` antes de gravar) mocka `wr.s3.to_parquet` do mesmo jeito que os jobs PythonShell.

### Amazon Lightsail — `lightsail_ia`

`test/lightsail_ia/conftest.py` define as variáveis de ambiente (`LLM_API_KEY`, `TRANSCRIPTION_API_KEY`, `AWS_REGION`, `GLUE_DATABASE`, `SPEC_TABLE`, `ATHENA_S3_OUTPUT`) via `os.environ.setdefault(...)` **antes** de qualquer import do módulo sob teste — obrigatório porque `agent.py` chama `load_dotenv()` e lê env vars em tempo de import, não de execução.

Athena é acessado via `boto3` cru (não awswrangler) — mockar a sequência de 3 chamadas: `start_query_execution` → `get_query_execution` (polling até `SUCCEEDED`) → `get_paginator("get_query_results").paginate()`, com `ResultSet.Rows` no formato real da API (`{"Data": [{"VarCharValue": ...}]}`, primeira linha = cabeçalho). Referência canônica: `test/lightsail_ia/test_agent.py::_setup_athena_mock(mock_boto3, rows_data=None)`. Chamadas ao LLM (`litellm.completion`) são mockadas separadamente. Uma fixture `autouse=True` limpa o cache em memória `agent._WHERE_CACHE` entre testes, para não vazar estado de um teste para o próximo.

### Pacote compartilhado — `shared_src`

`test/shared_src/conftest.py` só stuba `awsglue`/`awsglue.utils` minimamente (o pacote não toca Spark). Cada `test_<arquivo>.py` espelha um arquivo de `app/shared_src/shared_utils/` (`test_api_client.py`, `test_traducao.py`, `test_idioma.py`, `test_triggers.py`, `test_glue_helpers.py` etc.) e mocka os colaboradores externos (chamadas HTTP, Secrets Manager, serviços de tradução) do mesmo jeito que os testes de Lambda.

## Regras ao escrever/alterar testes

- Nunca introduzir `moto`, `pytest-mock`/`mocker` ou `botocore.stub.Stubber` — seguir `unittest.mock` puro, como todo o resto do projeto
- Módulo novo com `src/utils.py` que colida em nome com outro (`src.utils`): registrar em `_SUITE_TO_APP`/`_SUITE_TO_SRC_MODULE` em `test/conftest.py`
- Testar consultas Athena/awswrangler pelo **SQL ou kwargs gerados**, não por execução real
- No job Spark (`glue_data_quality`): nunca instalar/importar PySpark real — manter módulos falsos em `sys.modules` + `MagicMock()` encadeável; funções chamadas diretamente no código de produção (`col`, `when`, `StringType`) precisam ser `MagicMock()` desde o conftest, as demais podem ser `None` no conftest e mockadas por teste
- `lightsail_ia`: setar env vars no `conftest.py` antes de qualquer import do módulo sob teste; limpar `agent._WHERE_CACHE` entre testes que dependem de cache limpo
- Nome de método de teste novo: descritivo, em português, no padrão `test_<comportamento>`
