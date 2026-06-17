# Testes — lightsail_ia

## O que é testado

Testa a função `recomendar()` e as funções do agente de IA em `app/lightsail_ia/agent.py`. Verifica as três etapas do pipeline de recomendação: extração de filtros via GPT-4o, consulta ao Athena e formatação das recomendações. A interface Streamlit (`app.py`) não é testada diretamente — é validada via execução manual. Todas as chamadas externas (OpenAI/LLM e Athena) são substituídas por **mocks** — objetos falsos que simulam respostas do LLM e do banco de dados sem fazer chamadas reais, evitando custos de API e tornando os testes determinísticos.

## Estrutura

```
test/lightsail/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
└── test_agent.py             # Testes do agente de recomendação
```

## Setup (`conftest.py`)

O `conftest.py` não define fixtures pytest — apenas configura variáveis de ambiente obrigatórias antes do import de `agent.py`:

| Variável | Valor de teste |
|---|---|
| `LLM_API_KEY` | `"test-llm-key"` |
| `AWS_REGION` | `"sa-east-1"` |
| `GLUE_DATABASE` | `"db_tmdb_unified_prod"` |
| `SPEC_TABLE` | `"tb_tmdb_discover_unified_prod"` |
| `ATHENA_S3_OUTPUT` | `"s3://test-bucket-temp/athena-results/"` |

## Funções auxiliares de mock (`test_agent.py`)

| Função | Descrição |
|---|---|
| `_setup_athena_mock(mock_boto3, rows_data)` | Configura o mock do `boto3` para simular as 3 etapas da API nativa do Athena: `start_query_execution` → `get_query_execution` (polling) → `get_paginator().paginate()`. `rows_data` define as linhas de resultado; `None` retorna apenas o header (resultado vazio). |
| `_mock_litellm(tool_args, resposta_final)` | Retorna lista de 2 respostas para `side_effect` de `litellm.completion`: a 1ª simula a resposta da Etapa 1 (Function Calling com `tool_args`), a 2ª simula a Etapa 3 (texto JSON com recomendações). |

## Casos de teste — `test_agent.py`

### `TestBuscarTitulosSpec` — Consulta ao Athena (Etapa 2)

| Teste | O que verifica |
|---|---|
| `test_retorna_lista_vazia_sem_resultados` | Retorna `[]` quando Athena não encontra resultados |
| `test_retorna_registros_como_lista_de_dicts` | Converte corretamente rows do Athena em lista de dicts |
| `test_filtro_tipo_incluido_na_query` | WHERE inclui `media_type = 'movie'` quando `tipo` é passado |
| `test_filtro_ano_incluido_na_query` | WHERE inclui `year = '1990'` quando `ano` é passado |
| `test_filtro_genero_incluido_na_query` | WHERE inclui `genre_names LIKE '%Terror%'` quando `genero` é passado |
| `test_limite_aplicado_na_query` | LIMIT na query reflete o parâmetro `limite` |
| `test_limite_e_limitado_ao_maximo_de_30` | Limita a `LIMIT 30` mesmo se `limite=100` for passado |
| `test_limite_minimo_e_1` | Usa `LIMIT 1` quando `limite=0` for passado |

### `TestRecomendar` — Fluxo completo de recomendação

| Teste | O que verifica |
|---|---|
| `test_retorna_lista_vazia_se_athena_sem_resultados` | Retorna `[]` quando Athena não encontra resultados |
| `test_chama_llm_duas_vezes` | `litellm.completion` é chamado exatamente 2 vezes (etapas 1 e 3) |
| `test_retorna_lista_de_titulos` | Resultado final é lista de dicts com campos corretos |
| `test_remove_markdown_code_block_do_json` | Remove ` ```json ... ``` ` antes de parsear a resposta do LLM |
| `test_retorna_lista_vazia_se_llm_retorna_string_vazia` | Retorna `[]` sem erro quando o LLM retorna string vazia na etapa 3 |
| `test_passa_filtros_extraidos_pelo_llm_para_athena` | Filtros extraídos na etapa 1 são passados corretamente para `buscar_titulos_spec()` |
| `test_retorna_lista_vazia_se_llm_nao_chama_tool` | Retorna `[]` sem chamar Athena quando o LLM não retorna `tool_calls` (ex: modelo incompatível com `tool_choice="required"`) |
| `test_retorna_data_lancamento_formatada` | Campo `data_lancamento` está presente na resposta final |

## Como executar

```bash
# Apenas os testes do lightsail
pytest test/lightsail/ -v

# Com cobertura
pytest test/lightsail/ --cov=app/lightsail_ia --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).

## Observação sobre testes de interface

A interface Streamlit (`app.py`) não é coberta por testes automatizados nesta suite. Para validar o app visualmente, execute localmente:

```bash
cd app/lightsail_ia
streamlit run app.py
```

## Lacuna de cobertura — `in_theaters` e `theater_end_date`

O SELECT real em `agent.py` inclui `in_theaters` e `theater_end_date` nas colunas consultadas ao Athena. No entanto, o fixture `COLUMNS` em `test_agent.py` **não inclui** essas duas colunas, e o dicionário `TITULO_FAKE` e o JSON `RESPOSTA_LLM_FAKE` também não as contêm.

Consequência: os testes exercitam o fluxo completo mas **não verificam** que `in_theaters` e `theater_end_date` são corretamente retornados pela query e processados pelo agente. Para cobrir esse comportamento seria necessário adicionar as colunas ao `COLUMNS`, incluir os campos em `TITULO_FAKE` e adicionar testes específicos (análogos ao `test_retorna_data_lancamento_formatada`).
