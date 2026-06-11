# Testes — lightsail_ia

## O que é testado

Testa a função `recomendar()` e as funções do agente de IA em `app/lightsail_ia/agent.py`. Verifica as três etapas do pipeline de recomendação: extração de filtros via GPT-4o, consulta ao Athena e formatação das recomendações. A interface Streamlit (`app.py`) não é testada diretamente — é validada via execução manual. Todas as chamadas externas (OpenAI, Athena) são mockadas.

## Estrutura

```
test/lightsail/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
└── test_agent.py             # Testes do agente de recomendação
```

## Fixtures (`conftest.py`)

| Fixture | Tipo | Descrição |
|---|---|---|
| `mock_openai_client` | `MagicMock` | Substitui chamadas à API OpenAI (etapas 1 e 3) |
| `mock_athena_query` | `MagicMock` | Substitui `awswrangler.athena.read_sql_query` |
| `sample_filters` | `dict` | Filtros simulados retornados pelo GPT na etapa 1 |
| `sample_athena_results` | `pd.DataFrame` | DataFrame simulado retornado pela query Athena |
| `sample_recommendations` | `list[dict]` | Lista de recomendações simuladas retornadas pelo GPT na etapa 3 |

## Casos de teste — `test_agent.py`

### Extração de filtros (Etapa 1)

| Teste | O que verifica |
|---|---|
| `test_extracts_genre_from_user_input` | GPT extrai `genero` do texto livre do usuário |
| `test_extracts_media_type_movie` | `tipo="movie"` extraído quando usuário menciona filmes |
| `test_extracts_media_type_tv` | `tipo="tv"` extraído quando usuário menciona séries |
| `test_extracts_minimum_rating` | `nota_minima` extraída corretamente |
| `test_uses_function_calling_format` | Chamada ao OpenAI usa `tools` (Function Calling), não texto livre |

### Consulta ao Athena (Etapa 2)

| Teste | O que verifica |
|---|---|
| `test_queries_spec_table` | Query busca na tabela `tb_discover_unified_tmdb` |
| `test_filters_by_vote_count` | Query inclui `vote_count >= 50` |
| `test_filters_by_media_type_when_specified` | WHERE inclui `media_type = 'movie'` quando extraído |
| `test_filters_by_genre_when_specified` | WHERE inclui `genre_names LIKE '%Terror%'` quando gênero extraído |
| `test_returns_empty_list_when_no_results` | Retorna lista vazia sem erro quando Athena não encontra resultados |

### Formatação de recomendações (Etapa 3)

| Teste | O que verifica |
|---|---|
| `test_formats_result_as_list_of_dicts` | Resultado final é uma lista de dicionários |
| `test_includes_required_fields` | Cada item tem `titulo`, `tipo`, `ano`, `sinopse`, `nota`, `streaming_providers` |
| `test_includes_motivo_field` | Cada item inclui `motivo` (justificativa da recomendação) |
| `test_passes_athena_results_to_gpt` | Dados reais do Athena são passados para o GPT na etapa 3 |

### Fluxo completo

| Teste | O que verifica |
|---|---|
| `test_recomendar_returns_recommendations` | `recomendar()` retorna lista não vazia para input válido |
| `test_recomendar_runs_three_steps_in_order` | GPT é chamado 2 vezes (etapa 1 e etapa 3), Athena 1 vez (etapa 2) |
| `test_recomendar_handles_openai_error` | Erro na API OpenAI é tratado sem levantar exceção não capturada |

## Como executar

```bash
# Apenas os testes do lightsail
pytest test/lightsail/ -v

# Com cobertura
pytest test/lightsail/ --cov=app/lightsail_ia --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto.

## Observação sobre testes de interface

A interface Streamlit (`app.py`) não é coberta por testes automatizados nesta suite. Para validar o app visualmente, execute localmente:

```bash
cd app/lightsail_ia
streamlit run app.py
```
