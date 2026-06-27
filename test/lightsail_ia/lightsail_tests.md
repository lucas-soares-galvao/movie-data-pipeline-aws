# Testes — lightsail_ia

## O que é testado

Testa as funções de `app/lightsail_ia/agent.py`: `recomendar()`, `buscar_titulos_spec()`, funções de formatação (`_formatar_registro`, `_formatar_tipo`, `_formatar_generos`, `_formatar_duracao_titulo`, `_formatar_data_lancamento`, `_formatar_theater_end_date`, `_formatar_nota`) e `limpar_duracao()`. Os testes usam estilo **pytest** (classes simples, `assert` nativo, `with patch(...)` como context manager). Verifica as etapas do pipeline de recomendação: extração de filtros via LLM, consulta ao Athena, formatação determinística via Python e geração de motivo pelo LLM. A interface Streamlit (`app.py`) não é testada diretamente — é validada via execução manual. Todas as chamadas externas (LLM e Athena) são substituídas por **mocks** via `unittest.mock` — objetos falsos que simulam respostas do LLM e do banco de dados sem fazer chamadas reais, evitando custos de API e tornando os testes determinísticos.

## Estrutura

```
test/lightsail_ia/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
└── test_agent.py             # Testes do agente de recomendação
```

## Setup (`conftest.py`)

O `conftest.py` configura variáveis de ambiente obrigatórias antes do import de `agent.py` e define uma fixture `autouse` que limpa o cache de WHERE clauses entre testes:

| Variável | Valor de teste |
|---|---|
| `LLM_API_KEY` | `"test-llm-key"` (fallback — `FILMBOT_SECRET_ARN` não é definida em testes) |
| `AWS_REGION` | `"sa-east-1"` |
| `GLUE_DATABASE` | `"db_tmdb_unified_prod"` |
| `SPEC_TABLE` | `"tb_tmdb_discover_unified_prod"` |
| `ATHENA_S3_OUTPUT` | `"s3://test-bucket-temp/athena-results/"` |

| Fixture | Escopo | Descrição |
|---|---|---|
| `_limpar_cache_where` | `autouse` | Limpa `agent._CACHE_WHERE` antes de cada teste para garantir isolamento entre testes |

## Funções auxiliares de mock (`test_agent.py`)

| Função | Descrição |
|---|---|
| `_setup_athena_mock(mock_boto3, rows_data)` | Configura o mock do `boto3` para simular as 3 etapas da API nativa do Athena: `start_query_execution` → `get_query_execution` (polling) → `get_paginator().paginate()`. `rows_data` define as linhas de resultado; `None` retorna apenas o header (resultado vazio). |
| `_mock_litellm(tool_args, resposta_final)` | Retorna lista de 2 respostas para `side_effect` de `litellm.completion`: a 1ª simula a resposta da Etapa 1 (Function Calling com `tool_args`), a 2ª simula a Etapa 3 (JSON com `id` e `motivo` por título). Ambas incluem mock de `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`) para compatibilidade com `_logar_uso_tokens()`. |

## Casos de teste — `test_agent.py`

### `TestValidarWhere` — Validação de segurança da cláusula WHERE

| Teste | O que verifica |
|---|---|
| `test_aceita_clausula_valida` | Aceita e retorna cláusula WHERE válida sem alterações |
| `test_rejeita_ponto_e_virgula` | Rejeita cláusulas com `;` (prevenção de statement injection) |
| `test_rejeita_drop` | Rejeita cláusulas com `DROP` |
| `test_rejeita_delete` | Rejeita cláusulas com `DELETE` |
| `test_rejeita_insert` | Rejeita cláusulas com `INSERT` |
| `test_rejeita_subquery_select` | Rejeita cláusulas com `SELECT` (prevenção de subquery) |
| `test_remove_espacos_nas_pontas` | Remove espaços em branco nas extremidades da cláusula |

### `TestBuscarTitulosSpec` — Consulta ao Athena (Etapa 2)

| Teste | O que verifica |
|---|---|
| `test_retorna_lista_vazia_sem_resultados` | Retorna `[]` quando Athena não encontra resultados |
| `test_retorna_registros_como_lista_de_dicts` | Converte corretamente rows do Athena em lista de dicts |
| `test_filtro_where_incluido_na_query` | WHERE inclui a cláusula gerada pelo LLM na query |
| `test_vote_count_fixo_sempre_presente` | Filtro fixo `vote_count >= 50` está sempre presente na query |
| `test_filtro_idioma_na_query` | WHERE inclui `original_language = 'ko'` para filtro de idioma |
| `test_filtro_duracao_na_query` | WHERE inclui `runtime_minutes <= 90` para filtro de duração |
| `test_filtro_temporadas_na_query` | WHERE inclui `number_of_seasons = 1` para filtro de temporadas |
| `test_filtro_em_cartaz_na_query` | WHERE inclui `in_theaters = true` para filtro de cinema |
| `test_filtro_plataforma_na_query` | WHERE inclui `lower(streaming_providers) LIKE '%netflix%'` para filtro de streaming |
| `test_filtro_faixa_de_ano_na_query` | WHERE inclui `year BETWEEN '2000' AND '2010'` para faixa de ano |
| `test_limite_aplicado_na_query` | LIMIT na query reflete o parâmetro `limite` |
| `test_limite_e_limitado_ao_maximo_de_10` | Limita a `LIMIT 10` mesmo se `limite=100` for passado |
| `test_limite_minimo_e_1` | Usa `LIMIT 1` quando `limite=0` for passado |
| `test_rejeita_where_com_sql_perigoso` | Levanta `ValueError` quando a cláusula WHERE contém SQL perigoso |

### `TestRecomendar` — Fluxo completo de recomendação

| Teste | O que verifica |
|---|---|
| `test_retorna_lista_vazia_se_athena_sem_resultados` | Retorna `[]` quando Athena não encontra resultados |
| `test_chama_llm_duas_vezes` | `litellm.completion` é chamado exatamente 2 vezes (etapas 1 e 3) |
| `test_retorna_lista_de_titulos` | Resultado final é lista de dicts com campos corretos |
| `test_remove_markdown_code_block_do_json` | Remove ` ```json ... ``` ` antes de parsear a resposta do LLM |
| `test_retorna_registros_sem_motivo_se_llm_retorna_string_vazia` | Retorna registros formatados com `motivo=""` quando o LLM retorna string vazia na etapa 3 |
| `test_retorna_registros_sem_motivo_se_llm_retorna_json_invalido` | Retorna registros com `motivo=""` quando o LLM retorna texto que não é JSON |
| `test_motivo_funciona_com_id_string` | Motivo é mesclado corretamente quando o LLM retorna `id` como string (`"0"` em vez de `0`) |
| `test_motivo_funciona_com_lista_direta` | Motivo é mesclado corretamente quando o LLM retorna lista `[...]` em vez de `{"titulos": [...]}` |
| `test_passa_filtros_extraidos_pelo_llm_para_athena` | `filtro_where` e `limite` extraídos na etapa 1 são passados corretamente para `buscar_titulos_spec()` |
| `test_retorna_lista_vazia_se_llm_nao_chama_tool` | Retorna `[]` sem chamar Athena quando o LLM não retorna `tool_calls` (ex: modelo não escolhe usar a tool) |
| `test_retorna_data_lancamento_formatada` | Campo `data_lancamento` formatado pelo Python (ex: `"Maio de 1980"`) |
| `test_campos_formatados_pelo_python` | Valida que todos os campos determinísticos são formatados corretamente pelo Python (`tipo`, `ano`, `generos`, `sinopse`, `nota`, `duracao`, `streaming_providers`, `in_theaters`, `motivo`) |

### `TestCacheWhere` — Cache de cláusulas WHERE

| Teste | O que verifica |
|---|---|
| `test_chave_cache_normaliza_entrada` | Chave do cache é idêntica para entradas com diferença de caixa/espaços |
| `test_salvar_e_buscar_cache` | Salvar e buscar retorna os mesmos argumentos |
| `test_cache_miss_retorna_none` | Retorna `None` para preferência não cacheada |
| `test_cache_expirado_retorna_none` | Retorna `None` e remove entrada quando TTL expira |
| `test_cache_evita_chamada_llm_passo_1` | Com cache preenchido, `litellm.completion` é chamado apenas 1 vez (etapa 3) em vez de 2 |

### `TestLogarUsoTokens` — Logging de uso de tokens

| Teste | O que verifica |
|---|---|
| `test_loga_tokens_com_usage` | `logger.info` é chamado com `prompt_tokens`, `completion_tokens` e `etapa` no `extra` |
| `test_nao_loga_sem_usage` | `logger.info` não é chamado quando a resposta não possui atributo `usage` |

### `TestLimparDuracao` — Limpeza de strings de duração (legado)

Testa a função `limpar_duracao()` que remove fragmentos `~null` gerados pelo LLM quando campos de duração são nulos. Função mantida por compatibilidade com `app.py`, mas novas durações são formatadas por `_formatar_duracao_titulo()`. Não usa mocks — são testes puramente unitários sobre manipulação de strings.

| Teste | O que verifica |
|---|---|
| `test_retorna_vazio_para_string_vazia` | String vazia retorna vazia |
| `test_remove_null_isolado` | `"~null"` retorna `""` |
| `test_remove_null_no_fim` | `"3 temporadas · ~null"` → `"3 temporadas"` |
| `test_remove_null_no_inicio` | `"~null · 36 eps"` → `"36 eps"` |
| `test_remove_multiplos_nulls` | `"~null · 36 eps · ~null"` → `"36 eps"` |
| `test_preserva_duracao_normal` | `"2h 26min"` preservado intacto |
| `test_preserva_duracao_composta` | `"3 temporadas · 36 eps · 45min"` preservado intacto |
| `test_remove_separadores_vazios` | `" · 36 eps · "` → `"36 eps"` |

### `TestFormatarTipo` — Conversão de `media_type`

| Teste | O que verifica |
|---|---|
| `test_movie_para_filme` | `"movie"` → `"filme"` |
| `test_tv_para_serie` | `"tv"` → `"série"` |
| `test_valor_desconhecido` | Valor desconhecido retornado sem alteração |

### `TestFormatarGeneros` — Separação de gêneros

| Teste | O que verifica |
|---|---|
| `test_separa_por_virgula` | `"Terror, Drama"` → `["Terror", "Drama"]` |
| `test_retorna_lista_vazia_para_none` | `None` → `[]` |
| `test_retorna_lista_vazia_para_string_vazia` | `""` → `[]` |

### `TestFormatarDuracaoTitulo` — Formatação de duração

| Teste | O que verifica |
|---|---|
| `test_filme_com_duracao` | `146` min → `"2h 26min"` |
| `test_filme_sem_duracao` | `runtime_minutes=None` → `None` |
| `test_filme_menos_de_uma_hora` | `45` min → `"45min"` (sem horas) |
| `test_serie_completa` | Seasons + episodes + ep. runtime → `"3 temporadas · 36 eps · ~45 min/ep"` |
| `test_serie_sem_episode_runtime` | Omite parte de runtime → `"2 temporadas · 20 eps"` |
| `test_serie_uma_temporada` | Singular → `"1 temporada · 10 eps"` |
| `test_serie_sem_dados` | Todos os campos `None` → `None` |

### `TestFormatarDataLancamento` — Formatação de data

| Teste | O que verifica |
|---|---|
| `test_data_valida` | `"1980-05-23"` → `"Maio de 1980"` |
| `test_data_none` | `None` → `None` |
| `test_data_vazia` | `""` → `None` |
| `test_data_curta` | `"1980"` (sem mês) → `None` |

### `TestFormatarTheaterEndDate` — Formatação de data de saída do cinema

| Teste | O que verifica |
|---|---|
| `test_em_cartaz_com_data` | `"2025-07-15"` + `in_theaters=True` → `"15/07/2025"` |
| `test_fora_de_cartaz` | `in_theaters=False` → `None` |
| `test_em_cartaz_sem_data` | `theater_end_date=None` → `None` |

### `TestFormatarNota` — Conversão de nota

| Teste | O que verifica |
|---|---|
| `test_float_valido` | `8.4` → `8.4` |
| `test_string_valida` | `"7.5"` → `7.5` |
| `test_none` | `None` → `None` |
| `test_string_vazia` | `""` → `None` |

### `TestFormatarRegistro` — Formatação completa de um registro

| Teste | O que verifica |
|---|---|
| `test_registro_completo_filme` | Registro de filme formatado com todos os campos corretos |
| `test_registro_serie` | Registro de série com `tipo="série"` e duração formatada com temporadas |

## Como executar

```bash
# Apenas os testes do lightsail
pytest test/lightsail_ia/ -v

# Com cobertura
pytest test/lightsail_ia/ --cov=app/lightsail_ia --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).

## Observação sobre testes de interface

A interface Streamlit (`app.py`) não é coberta por testes automatizados nesta suite. Para validar o app visualmente, execute localmente:

```bash
cd app/lightsail_ia
streamlit run app.py
```

A variável `CLOUDWATCH_LOG_GROUP` não é definida no conftest — isso é intencional: sem ela, o handler watchtower não é ativado e os testes rodam sem dependência do CloudWatch.

