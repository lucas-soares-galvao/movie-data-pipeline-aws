# Testes — lightsail_ia

## O que é testado

Testa as funções do agente de recomendação (`app/lightsail_ia/agent.py`), as funções de formatação (`app/lightsail_ia/formatacao.py`) e os componentes de renderização HTML (`app/lightsail_ia/componentes.py`). O `test_agent.py` cobre `recomendar()`, `buscar_titulos_spec()`, validação SQL, cache e logging de tokens. O `test_formatacao.py` cobre as funções puras de formatação (`formatar_registro`, `_formatar_tipo`, `_formatar_generos`, `_formatar_duracao_titulo`, `_formatar_data_lancamento`, `_formatar_theater_end_date`, `_formatar_nota`). O `test_componentes.py` cobre a renderização de cards e grids (`renderizar_card`, `renderizar_grid`), incluindo escape XSS e verificação de campos exibidos/ignorados. Os testes usam estilo **pytest** (classes simples, `assert` nativo, `with patch(...)` como context manager). A interface Streamlit (`app.py`) não é testada diretamente — é validada via execução manual. Todas as chamadas externas (LLM e Athena) são substituídas por **mocks** via `unittest.mock` — objetos falsos que simulam respostas do LLM e do banco de dados sem fazer chamadas reais, evitando custos de API e tornando os testes determinísticos.

## Estrutura

```
test/lightsail_ia/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_agent.py             # Testes do agente (LLM, Athena, cache, validação)
├── test_componentes.py       # Testes de renderização HTML (cards e grids)
└── test_formatacao.py        # Testes das funções puras de formatação
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
| `_mock_litellm(tool_args)` | Retorna lista com 1 resposta para `side_effect` de `litellm.completion`: simula a resposta da Etapa 1 (Function Calling com `tool_args`). Inclui mock de `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`) para compatibilidade com `_logar_uso_tokens()`. |

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
| `test_chama_llm_uma_vez` | `litellm.completion` é chamado exatamente 1 vez (etapa 1) |
| `test_retorna_lista_de_titulos` | Resultado final é lista de dicts com campos corretos |
| `test_passa_filtros_extraidos_pelo_llm_para_athena` | `filtro_where` e `limite` extraídos na etapa 1 são passados corretamente para `buscar_titulos_spec()` |
| `test_retorna_lista_vazia_se_llm_nao_chama_tool` | Retorna `[]` sem chamar Athena quando o LLM não retorna `tool_calls` (ex: modelo não escolhe usar a tool) |
| `test_retorna_data_lancamento_formatada` | Campo `data_lancamento` formatado pelo Python (ex: `"Maio de 1980"`) |
| `test_campos_formatados_pelo_python` | Valida que todos os campos determinísticos são formatados corretamente pelo Python (`tipo`, `ano`, `generos`, `sinopse`, `nota`, `duracao`, `streaming_providers`, `in_theaters`) |

### `TestCacheWhere` — Cache de cláusulas WHERE

| Teste | O que verifica |
|---|---|
| `test_chave_cache_normaliza_entrada` | Chave do cache é idêntica para entradas com diferença de caixa/espaços |
| `test_salvar_e_buscar_cache` | Salvar e buscar retorna os mesmos argumentos |
| `test_cache_miss_retorna_none` | Retorna `None` para preferência não cacheada |
| `test_cache_expirado_retorna_none` | Retorna `None` e remove entrada quando TTL expira |
| `test_cache_evita_chamada_llm_passo_1` | Com cache preenchido, `litellm.completion` não é chamado (0 vezes) |

### `TestLogarUsoTokens` — Logging de uso de tokens

| Teste | O que verifica |
|---|---|
| `test_loga_tokens_com_usage` | `logger.info` é chamado com `prompt_tokens`, `completion_tokens` e `etapa` no `extra` |
| `test_nao_loga_sem_usage` | `logger.info` não é chamado quando a resposta não possui atributo `usage` |

## Casos de teste — `test_componentes.py`

### `TestRenderizarCard` — Renderização de cards individuais

| Teste | O que verifica |
|---|---|
| `test_card_basico_contem_titulo` | Card renderiza o título do filme |
| `test_card_ignora_tagline` | Card não renderiza tagline mesmo quando fornecida |
| `test_card_com_elenco` | Card exibe nomes do elenco |
| `test_card_com_diretor` | Card exibe "Diretor: {nome}" para filmes |
| `test_card_com_certificacao` | Card exibe badge de classificação indicativa |
| `test_card_com_trailer` | Card exibe link clicável para o trailer |
| `test_card_ignora_colecao` | Card não renderiza coleção/franquia mesmo quando fornecida |
| `test_card_ignora_criadores` | Card não renderiza criadores mesmo quando fornecidos |
| `test_card_ignora_redes_tv` | Card não renderiza redes de TV mesmo quando fornecidas |
| `test_card_sem_campos_opcionais_nao_gera_divs_vazias` | Campos opcionais ausentes não geram HTML vazio |
| `test_card_cinema_em_cartaz` | Card exibe "Em cartaz até DD/MM/YYYY" quando `in_theaters=True` |
| `test_card_nao_exibe_produtor` | Card não renderiza produtor mesmo quando fornecido |
| `test_card_nao_exibe_cinematografo` | Card não renderiza cinematógrafo mesmo quando fornecido |
| `test_card_nao_exibe_montador` | Card não renderiza montador mesmo quando fornecido |
| `test_card_com_rent_buy_providers` | Card exibe plataformas de aluguel/compra (🛒) |
| `test_card_com_streaming_providers` | Card exibe plataformas de streaming |
| `test_card_escapa_xss` | Valores com `<script>` são escapados via `html.escape` |

### `TestRenderizarGrid` — Renderização do grid de cards

| Teste | O que verifica |
|---|---|
| `test_grid_vazio` | Grid vazio renderiza container sem cards |
| `test_grid_com_titulos` | Grid com múltiplos títulos renderiza múltiplos cards |

## Casos de teste — `test_formatacao.py`

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
| `test_novos_campos_filme` | Campos `roteiristas`, `compositor`, `keywords` (pt) formatados corretamente |
| `test_novos_campos_nulos` | Campos `roteiristas` e `compositor` retornam `None` quando ausentes |
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

