# _setup_athena_mock() simula as 3 etapas do boto3 Athena:
#   start_query_execution → get_query_execution (polling) → get_paginator().paginate()
# O mock precisa dessas 3 chamadas encadeadas porque agent.py as chama em sequência.
#
# _mock_litellm() usa side_effect=[passo1, passo3] porque recomendar() chama
# o LLM duas vezes: 1ª para extrair filtros como JSON, 2ª para formatar respostas.

import json
import unittest
from unittest.mock import MagicMock, patch

import agent


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
    "air_date": "1980-05-23",
}

RESPOSTA_LLM_FAKE = json.dumps(
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
                "data_lancamento": "maio de 1980",
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
    "streaming_providers", "air_date",
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


def _mock_litellm(tool_args: dict, resposta_final: str):
    """Retorna lista de 2 respostas para o side_effect de litellm.completion."""
    tool_call = MagicMock()
    tool_call.id = "call_test_123"
    tool_call.function.name = "buscar_titulos_spec"
    tool_call.function.arguments = json.dumps(tool_args)

    msg_passo1 = MagicMock()
    msg_passo1.content = None
    msg_passo1.tool_calls = [tool_call]

    msg_passo3 = MagicMock()
    msg_passo3.content = resposta_final

    passo1 = MagicMock()
    passo1.choices = [MagicMock(message=msg_passo1)]

    passo3 = MagicMock()
    passo3.choices = [MagicMock(message=msg_passo3)]

    return [passo1, passo3]


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


class TestRecomendar(unittest.TestCase):

    @patch("agent.litellm.completion")
    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_vazia_se_athena_sem_resultados(self, mock_buscar, mock_completion):
        mock_buscar.return_value = []
        mock_completion.side_effect = _mock_litellm({"tipo": "movie"}, "")

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(resultado, [])

    @patch("agent.litellm.completion")
    @patch("agent.buscar_titulos_spec")
    def test_chama_llm_duas_vezes(self, mock_buscar, mock_completion):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_completion.side_effect = _mock_litellm({"tipo": "movie"}, RESPOSTA_LLM_FAKE)

        agent.recomendar("filmes de terror")

        self.assertEqual(mock_completion.call_count, 2)

    @patch("agent.litellm.completion")
    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_de_titulos(self, mock_buscar, mock_completion):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_completion.side_effect = _mock_litellm({"tipo": "movie"}, RESPOSTA_LLM_FAKE)

        resultado = agent.recomendar("filmes de terror")

        self.assertIsInstance(resultado, list)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["titulo"], "O Iluminado")

    @patch("agent.litellm.completion")
    @patch("agent.buscar_titulos_spec")
    def test_remove_markdown_code_block_do_json(self, mock_buscar, mock_completion):
        mock_buscar.return_value = [TITULO_FAKE]
        resposta_com_markdown = f"```json\n{RESPOSTA_LLM_FAKE}\n```"
        mock_completion.side_effect = _mock_litellm({"tipo": "movie"}, resposta_com_markdown)

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(len(resultado), 1)

    @patch("agent.litellm.completion")
    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_vazia_se_llm_retorna_string_vazia(self, mock_buscar, mock_completion):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_completion.side_effect = _mock_litellm({"tipo": "movie"}, "")

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(resultado, [])

    @patch("agent.litellm.completion")
    @patch("agent.buscar_titulos_spec")
    def test_passa_filtros_extraidos_pelo_llm_para_athena(self, mock_buscar, mock_completion):
        mock_buscar.return_value = [TITULO_FAKE]
        filtros = {"tipo": "movie", "genero": "Terror", "ano": 1980, "nota_minima": 7.0, "limite": 5}
        mock_completion.side_effect = _mock_litellm(filtros, RESPOSTA_LLM_FAKE)

        agent.recomendar("filmes de terror dos anos 80")

        mock_buscar.assert_called_once_with(**filtros)

    @patch("agent.litellm.completion")
    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_vazia_se_llm_nao_chama_tool(self, mock_buscar, mock_completion):
        msg_sem_tool = MagicMock()
        msg_sem_tool.content = None
        msg_sem_tool.tool_calls = None

        passo1_sem_tool = MagicMock()
        passo1_sem_tool.choices = [MagicMock(message=msg_sem_tool)]
        mock_completion.return_value = passo1_sem_tool

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(resultado, [])
        mock_buscar.assert_not_called()

    @patch("agent.litellm.completion")
    @patch("agent.buscar_titulos_spec")
    def test_retorna_data_lancamento_formatada(self, mock_buscar, mock_completion):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_completion.side_effect = _mock_litellm({"tipo": "movie"}, RESPOSTA_LLM_FAKE)

        resultado = agent.recomendar("filmes de terror")

        self.assertIn("data_lancamento", resultado[0])
        self.assertEqual(resultado[0]["data_lancamento"], "maio de 1980")


if __name__ == "__main__":
    unittest.main()
