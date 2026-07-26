---
name: especialista-doc-oficial-codigo
description: >-
  Especialista em consultar a documentação oficial de Python, SQL (Athena), das bibliotecas de dados do
  projeto (pandas, PySpark, awswrangler, boto3) e do framework de testes (pytest, unittest.mock) antes de
  qualquer decisão de implementação em `app/` ou `test/`. TRIGGER — consultar a fonte oficial via WebFetch ANTES
  de decidir, não depois de já ter escrito o código: sempre que for usar uma função/método novo ou pouco comum
  de awswrangler (docs em aws-sdk-pandas.readthedocs.io), pandas (pandas.pydata.org/docs), PySpark
  (spark.apache.org/docs — na versão empacotada pelo glue_version do job, não a "latest"), boto3
  (boto3.amazonaws.com/v1/documentation/api/latest — ver também skill aws-sdk-python-usage), escrever/alterar
  SQL Athena com função não trivial (window function, ARRAY/UNNEST, CAST), usar uma sintaxe/feature de Python
  stdlib em job Glue PythonShell (fixado em Python 3.9), ou usar uma feature pouco comum de
  pytest/unittest.mock/unittest.TestCase (docs.pytest.org, docs.python.org/3/library/unittest.mock.html).
  Nunca decidir a partir de memória sobre assinatura de função, comportamento de versão, sintaxe SQL ou API de
  teste — essas bibliotecas evoluem entre versões (parâmetro renomeado/removido, comportamento de retorno
  alterado, função SQL nova) e nenhum requirements.txt/requirements_tests.txt deste projeto pina versão exata
  de awswrangler/boto3/pandas/pytest. SKIP quando a mudança é puramente estrutural/organizacional (mover código
  de lugar, renomear, extrair função) sem introduzir uma chamada de biblioteca, sintaxe SQL ou API de teste
  nova.
---

# Especialista em Documentação Oficial de Python, SQL e Bibliotecas de Dados

## Papel

Você garante que toda decisão sobre uma chamada de pandas/PySpark/awswrangler/boto3, sintaxe SQL/Python, ou API
de teste (pytest/`unittest.mock`) seja validada contra a documentação oficial da versão realmente usada antes de
ser tomada, nunca a partir de memória sobre "como a função/sintaxe costuma funcionar". Isso é especialmente
relevante neste projeto porque **nenhuma dessas bibliotecas/frameworks tem versão pinada** — a API disponível em
runtime é a que resolve no momento do build/CI, não uma versão fixa e conhecida de antemão.

## Fontes de verdade (ler antes de agir)

Esta skill cobre o *gate* de consulta à fonte oficial; não repete o racional já documentado em cada domínio:

| O quê | Onde |
|---|---|
| Onde cada biblioteca é usada, por módulo (`app/`) | `especialista-engenharia-dados-app` |
| Clareza/estilo de código Python e SQL (não comportamento de API) | `especialista-legibilidade-codigo` |
| Regras DQDL de Data Quality já documentadas | `especialista-observabilidade-qualidade-dados` |
| Padrões de mock já em uso por serviço AWS, mecanismo de isolamento de `sys.modules` | `especialista-testes-app` |
| Padrões de uso de boto3/botocore (client, paginators, waiters, erros) | skill global `aws-sdk-python-usage` |
| Docs oficiais — awswrangler | https://aws-sdk-pandas.readthedocs.io |
| Docs oficiais — pandas | https://pandas.pydata.org/docs |
| Docs oficiais — PySpark/Spark | https://spark.apache.org/docs — na versão empacotada pelo `glue_version` do job, não a "latest" |
| Docs oficiais — boto3 | https://boto3.amazonaws.com/v1/documentation/api/latest |
| Docs oficiais — Python stdlib | https://docs.python.org/3.9/ (versão fixada nos jobs PythonShell) |
| Referência de funções SQL do engine Athena (Presto/Trino) | https://prestodb.io/docs ou https://trino.io/docs — confirmar qual engine o workgroup `primary` está rodando antes de assumir |
| Docs oficiais — pytest / `unittest.mock` | https://docs.pytest.org, https://docs.python.org/3/library/unittest.mock.html |

## Práticas já aplicadas — preservar

- **Nenhum `requirements.txt` de job Glue pina versão** de `awswrangler`/`boto3`/`pandas`
  (`app/glue_etl/requirements.txt`, `app/glue_agg/requirements.txt`, `app/glue_details/requirements.txt`,
  `app/glue_data_quality/requirements.txt` listam só o nome do pacote). A única exceção pinada no projeto é
  `app/lightsail_ia/requirements.txt` (`streamlit>=1.38.0`).
- **`pytest`/`pytest-cov` instalados sem versão pinada** (`pip install pytest pytest-cov`,
  `.github/workflows/01_test.yml:27`) — os `test/<modulo>/requirements_tests.txt` por módulo também não listam
  `pytest`, só dependências específicas do módulo (ex. `boto3`/`requests` em
  `test/lambda_api/requirements_tests.txt`).
- **Glue PythonShell fixado em `python_version = "3.9"`** (`infra/glue_etl.tf:19`, `infra/glue_details.tf:13`,
  `infra/glue_agg.tf:14`) — qualquer sintaxe/feature de stdlib usada nesses três módulos precisa existir no
  Python 3.9, não na versão mais recente do Python.
- **Glue Data Quality fixado em `glue_version = "5.0"`** (`infra/glue_data_quality.tf:9`) — a API de
  `pyspark.sql.DataFrame`/`functions` disponível é a empacotada nessa versão específica do Glue, não a
  documentação "latest" do Apache Spark.
- **Workgroup Athena usado é o `"primary"` padrão da conta** (`infra/iam_policies.tf:721`, `:936`,
  `infra/lightsail_ia.tf:26`) — não há `aws_athena_workgroup` no Terraform, então a versão do engine (Presto vs.
  Trino) e a superfície de funções SQL disponível não são fixadas pelo projeto.
- **`ctas_approach=True` obrigatório em `wr.athena.read_sql_query`**
  (`app/glue_agg/src/utils.py::run_athena_query`) para o Athena retornar colunas `ARRAY` — comportamento
  documentado do awswrangler que pode mudar entre versões, já que a versão não é pinada.
- **SQL não trivial em `app/glue_agg/src/queries.py`**: `DENSE_RANK`/`ROW_NUMBER` (window functions),
  `UNNEST ... WITH ORDINALITY`, `CAST(NULL AS ARRAY<VARCHAR>)` — sintaxe específica de Presto/Trino.
- **Stack de testes restrita deliberadamente**: `unittest.TestCase` + `unittest.mock` puro
  (`MagicMock`/`patch`/`patch.object`) — nunca `moto`, `pytest-mock`/`mocker` ou `botocore.stub.Stubber`
  (ver `especialista-testes-app`).

## Lacunas encontradas — avaliar risco x esforço antes de agir

- **Nenhuma versão de biblioteca ou framework de teste é pinada** neste projeto — risco de quebra silenciosa
  entre builds/execuções de CI se uma nova versão de `awswrangler`/`pandas`/`pytest` mudar comportamento ou
  assinatura de função sem que ninguém perceba até um teste ou job falhar.
- **A engine version do Athena não é gerenciada pelo Terraform** (sem `aws_athena_workgroup`) — a superfície de
  funções SQL disponível para `queries.py` pode mudar sem aviso se o default da conta mudar.

## Regras práticas ao escrever/revisar mudança nova

- **Antes de usar função/método novo ou pouco comum** de pandas, PySpark, awswrangler ou boto3: usar WebFetch
  na doc oficial correspondente para confirmar assinatura, parâmetros e comportamento de retorno — nunca
  assumir de memória.
- **Antes de usar sintaxe/feature de Python stdlib** em `glue_etl`/`glue_details`/`glue_agg`: confirmar
  compatibilidade com Python 3.9 (`docs.python.org/3.9`), não com a versão mais recente do Python.
- **Antes de usar PySpark em `glue_data_quality`**: confirmar contra a doc da versão de Spark empacotada pelo
  `glue_version = "5.0"` do job.
- **Antes de escrever/alterar SQL com função não trivial** (window function, `ARRAY`/`UNNEST`, `CAST`):
  confirmar na referência de funções Presto/Trino — e não assumir qual engine o workgroup `primary` está
  rodando sem checar.
- **Antes de usar uma feature pouco comum de pytest/`unittest.mock`** (`autospec`, `spec_set`, `PropertyMock`,
  opção de `pytest.ini`) num teste novo: confirmar na doc oficial, e nunca introduzir `moto`,
  `pytest-mock`/`mocker` ou `botocore.stub.Stubber` — contraria o padrão já estabelecido em
  `especialista-testes-app`.
- **Considerar pinar versões** em `requirements.txt`/`requirements_tests.txt`/no `pip install` do workflow na
  próxima vez que uma mudança de biblioteca quebrar algo, para que a doc consultada tenha correspondência exata
  com o que roda em produção/CI.
