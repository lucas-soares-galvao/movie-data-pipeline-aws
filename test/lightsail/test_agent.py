"""
test_agent.py — Testes unitários do agente de recomendação de filmes.

==============================================================================
O QUE ESTE ARQUIVO TESTA?
==============================================================================
Testa as duas funções públicas de agent.py:

  buscar_titulos_spec()  → monta o SQL com os filtros recebidos e consulta
                           o Athena via boto3 nativo, retornando lista de
                           dicionários com os títulos encontrados na camada
                           SPEC (Gold layer)

  recomendar()           → orquestra os 3 passos do agente de IA:
    PASSO 1: GPT-4o lê o texto do usuário e devolve filtros como JSON
    PASSO 2: Athena é consultado com esses filtros
    PASSO 3: GPT-4o formata os resultados como recomendações

Todas as dependências externas (OpenAI, boto3/Athena) são substituídas por
Mocks para que os testes rodem sem credenciais ou rede.

==============================================================================
HELPER _setup_athena_mock()
==============================================================================
O agent.py usa a API nativa do boto3 Athena em três etapas:
  1. start_query_execution() → dispara a query e retorna QueryExecutionId
  2. get_query_execution()   → verifica o estado (polling até SUCCEEDED)
  3. get_paginator().paginate() → lê os resultados paginados

_setup_athena_mock() configura um MagicMock que simula essas três etapas,
opcionalmente incluindo linhas de dados (rows_data) no resultado.

==============================================================================
HELPER _mock_openai_client()
==============================================================================
O GPT-4o é chamado DUAS VEZES em recomendar():
  1ª chamada → retorna uma "tool_call" com os filtros SQL como JSON
  2ª chamada → retorna o JSON final com as recomendações formatadas

Para simular isso, _mock_openai_client() configura o mock com side_effect
como uma lista [resposta_passo1, resposta_passo3] — o mock devolve o
primeiro item na 1ª chamada e o segundo na 2ª chamada automaticamente.

==============================================================================
FIXTURES TITULOS_FAKE e RESPOSTA_OPENAI_FAKE
==============================================================================
TITULO_FAKE simula uma linha da tabela SPEC retornada pelo Athena.
RESPOSTA_OPENAI_FAKE simula o JSON que o GPT-4o retorna no Passo 3,
com a lista "titulos" contendo os dados formatados para o app Streamlit.

==============================================================================
CLASSES DE TESTE
==============================================================================
  TestBuscarTitulosSpec → testa a construção do SQL (filtros opcionais)
    - sem resultados → retorna lista vazia
    - com resultados → retorna lista de dicionários
    - filtro tipo (movie/tv) → aparece no SQL como media_type = '...'
    - filtro ano → aparece no SQL como year = '...'
    - filtro gênero → aparece no SQL com o nome do gênero
    - limite → aparece no SQL como LIMIT N

  TestRecomendar → testa o fluxo completo dos 3 passos
    - Athena sem resultados → retorna lista vazia (pula o Passo 3)
    - OpenAI é chamado exatamente 2 vezes por requisição
    - retorno é lista de dicionários com a estrutura de recomendações
    - remove markdown code fences (```json...```) antes do json.loads
    - OpenAI retornando string vazia → retorna lista vazia
    - filtros extraídos no Passo 1 são passados para buscar_titulos_spec()
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import agent


# ── Fixtures ─────────────────────────────────────────────────────────────────

TITULO_FAKE = {
    "title": "O Iluminado",
    "media_type": "movie",
    "year": "1980",
    "genre_names": "Terror, Drama",
    "overview": "Um escritor enlouquece num hotel isolado.",
    "vote_average": 8.4,
    "poster_url": "https://example.com/poster.jpg",
    "backdrop_url": None,
    "runtime_minutes": 146,
    "number_of_seasons": None,
    "number_of_episodes": None,
    "episode_runtime_minutes": None,
    "streaming_providers": "Netflix",
}

RESPOSTA_OPENAI_FAKE = json.dumps(
    {
        "titulos": [
            {
                "titulo": "O Iluminado",
                "tipo": "filme",
                "ano": 1980,
                "generos": ["Terror", "Drama"],
                "sinopse": "Um escritor enlouquece num hotel isolado.",
                "nota": 8.4,
                "poster_url": "https://example.com/poster.jpg",
                "backdrop_url": None,
                "motivo": "Clássico do terror psicológico.",
                "duracao": "2h 26min",
                "streaming_providers": "Netflix",
            }
        ]
    }
)

# Colunas retornadas pelo SELECT em buscar_titulos_spec() — usadas para
# montar o header row que o Athena sempre inclui na primeira página de resultados.
COLUMNS = [
    "title", "media_type", "year", "genre_names", "overview",
    "vote_average", "poster_url", "backdrop_url",
    "runtime_minutes", "number_of_seasons",
    "number_of_episodes", "episode_runtime_minutes",
    "streaming_providers",
]


def _setup_athena_mock(mock_boto3, rows_data=None):
    """Configura o mock do boto3 para simular as três etapas da API do Athena.

    A API nativa do Athena usada por buscar_titulos_spec() requer:
      1. start_query_execution() → inicia a query, retorna QueryExecutionId
      2. get_query_execution()   → polling até o estado ser SUCCEEDED
      3. get_paginator().paginate() → lê os resultados paginados

    Args:
        mock_boto3:  Mock do módulo boto3 injetado via @patch("agent.boto3").
        rows_data:   Lista de dicts com os dados de cada linha a retornar.
                     None ou lista vazia → retorna apenas o header (resultado vazio).

    Returns:
        mock_athena: Mock do client Athena (boto3.client("athena", ...)).
    """
    mock_athena = MagicMock()
    mock_boto3.client.return_value = mock_athena

    mock_athena.start_query_execution.return_value = {"QueryExecutionId": "test-exec-id"}
    mock_athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
    }

    # O Athena sempre inclui uma linha de header (nomes das colunas) na primeira página.
    # Para resultados vazios, retornamos apenas o header; para resultados com dados,
    # adicionamos as linhas de dados após o header.
    header = {"Data": [{"VarCharValue": col} for col in COLUMNS]}
    if rows_data:
        data_rows = [
            {"Data": [{"VarCharValue": str(row.get(col) or "")} for col in COLUMNS]}
            for row in rows_data
        ]
        page = {"ResultSet": {"Rows": [header] + data_rows}}
    else:
        page = {"ResultSet": {"Rows": [header]}}

    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [page]
    mock_athena.get_paginator.return_value = mock_paginator

    return mock_athena


def _mock_openai_client(tool_args: dict, resposta_final: str):
    """Cria um client OpenAI mockado para os dois estágios da pipeline."""
    mock_client = MagicMock()

    # PASSO 1: resposta com tool_call (extração de filtros)
    tool_call = MagicMock()
    tool_call.id = "call_test_123"
    tool_call.function.arguments = json.dumps(tool_args)
    msg_passo1 = MagicMock()
    msg_passo1.tool_calls = [tool_call]
    choice_passo1 = MagicMock()
    choice_passo1.message = msg_passo1
    resposta_passo1 = MagicMock()
    resposta_passo1.choices = [choice_passo1]

    # PASSO 3: resposta final com JSON de recomendações
    msg_passo3 = MagicMock()
    msg_passo3.content = resposta_final
    choice_passo3 = MagicMock()
    choice_passo3.message = msg_passo3
    resposta_passo3 = MagicMock()
    resposta_passo3.choices = [choice_passo3]

    mock_client.chat.completions.create.side_effect = [resposta_passo1, resposta_passo3]
    return mock_client


# ── Testes de buscar_titulos_spec ─────────────────────────────────────────────


class TestBuscarTitulosSpec(unittest.TestCase):

    @patch("agent.boto3")
    def test_retorna_lista_vazia_sem_resultados(self, mock_boto3):
        _setup_athena_mock(mock_boto3)

        resultado = agent.buscar_titulos_spec()

        self.assertEqual(resultado, [])

    @patch("agent.boto3")
    def test_retorna_registros_como_lista_de_dicts(self, mock_boto3):
        _setup_athena_mock(mock_boto3, rows_data=[TITULO_FAKE])

        resultado = agent.buscar_titulos_spec()

        self.assertIsInstance(resultado, list)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["title"], "O Iluminado")

    @patch("agent.boto3")
    def test_filtro_tipo_incluido_na_query(self, mock_boto3):
        mock_athena = _setup_athena_mock(mock_boto3)

        agent.buscar_titulos_spec(tipo="movie")

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        self.assertIn("media_type = 'movie'", sql_executado)

    @patch("agent.boto3")
    def test_filtro_ano_incluido_na_query(self, mock_boto3):
        mock_athena = _setup_athena_mock(mock_boto3)

        agent.buscar_titulos_spec(ano=1990)

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        self.assertIn("year = '1990'", sql_executado)

    @patch("agent.boto3")
    def test_filtro_genero_incluido_na_query(self, mock_boto3):
        mock_athena = _setup_athena_mock(mock_boto3)

        agent.buscar_titulos_spec(genero="Terror")

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        self.assertIn("Terror", sql_executado)

    @patch("agent.boto3")
    def test_limite_aplicado_na_query(self, mock_boto3):
        mock_athena = _setup_athena_mock(mock_boto3)

        agent.buscar_titulos_spec(limite=10)

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        self.assertIn("LIMIT 10", sql_executado)

    @patch("agent.boto3")
    def test_limite_e_limitado_ao_maximo_de_30(self, mock_boto3):
        mock_athena = _setup_athena_mock(mock_boto3)

        agent.buscar_titulos_spec(limite=100)

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        self.assertIn("LIMIT 30", sql_executado)
        self.assertNotIn("LIMIT 100", sql_executado)

    @patch("agent.boto3")
    def test_limite_minimo_e_1(self, mock_boto3):
        mock_athena = _setup_athena_mock(mock_boto3)

        agent.buscar_titulos_spec(limite=0)

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        self.assertIn("LIMIT 1", sql_executado)


# ── Testes de recomendar ───────────────────────────────────────────────────────


class TestRecomendar(unittest.TestCase):

    @patch("agent._get_openai_client")
    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_vazia_se_athena_sem_resultados(self, mock_buscar, mock_get_client):
        mock_buscar.return_value = []
        mock_get_client.return_value = _mock_openai_client({"tipo": "movie"}, "")

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(resultado, [])

    @patch("agent._get_openai_client")
    @patch("agent.buscar_titulos_spec")
    def test_chama_openai_duas_vezes(self, mock_buscar, mock_get_client):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_client = _mock_openai_client({"tipo": "movie"}, RESPOSTA_OPENAI_FAKE)
        mock_get_client.return_value = mock_client

        agent.recomendar("filmes de terror")

        self.assertEqual(mock_client.chat.completions.create.call_count, 2)

    @patch("agent._get_openai_client")
    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_de_titulos(self, mock_buscar, mock_get_client):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_get_client.return_value = _mock_openai_client({"tipo": "movie"}, RESPOSTA_OPENAI_FAKE)

        resultado = agent.recomendar("filmes de terror")

        self.assertIsInstance(resultado, list)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["titulo"], "O Iluminado")

    @patch("agent._get_openai_client")
    @patch("agent.buscar_titulos_spec")
    def test_remove_markdown_code_block_do_json(self, mock_buscar, mock_get_client):
        mock_buscar.return_value = [TITULO_FAKE]
        resposta_com_markdown = f"```json\n{RESPOSTA_OPENAI_FAKE}\n```"
        mock_get_client.return_value = _mock_openai_client({"tipo": "movie"}, resposta_com_markdown)

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(len(resultado), 1)

    @patch("agent._get_openai_client")
    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_vazia_se_openai_retorna_string_vazia(self, mock_buscar, mock_get_client):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_get_client.return_value = _mock_openai_client({"tipo": "movie"}, "")

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(resultado, [])

    @patch("agent._get_openai_client")
    @patch("agent.buscar_titulos_spec")
    def test_passa_filtros_extraidos_pelo_openai_para_athena(self, mock_buscar, mock_get_client):
        mock_buscar.return_value = [TITULO_FAKE]
        filtros = {"tipo": "movie", "genero": "Terror", "ano": 1980, "nota_minima": 7.0, "limite": 5}
        mock_get_client.return_value = _mock_openai_client(filtros, RESPOSTA_OPENAI_FAKE)

        agent.recomendar("filmes de terror dos anos 80")

        mock_buscar.assert_called_once_with(**filtros)


if __name__ == "__main__":
    unittest.main()
