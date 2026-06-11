"""
test_agent.py — Testes unitários do agente de recomendação de filmes.

==============================================================================
O QUE ESTE ARQUIVO TESTA?
==============================================================================
Testa as duas funções públicas de agent.py:

  buscar_titulos_spec()  → monta o SQL com os filtros recebidos e consulta
                           o Athena, retornando lista de dicionários com
                           os títulos encontrados na camada SPEC (Gold layer)

  recomendar()           → orquestra os 3 passos do agente de IA:
    PASSO 1: GPT-4o lê o texto do usuário e devolve filtros como JSON
    PASSO 2: Athena é consultado com esses filtros
    PASSO 3: GPT-4o formata os resultados como recomendações

Todas as dependências externas (OpenAI, Athena/awswrangler, boto3) são
substituídas por Mocks para que os testes rodem sem credenciais ou rede.

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

import pandas as pd

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

    @patch("agent.wr")
    @patch("agent.boto3")
    def test_retorna_lista_vazia_sem_resultados(self, mock_boto3, mock_wr):
        mock_wr.athena.read_sql_query.return_value = pd.DataFrame()

        resultado = agent.buscar_titulos_spec()

        self.assertEqual(resultado, [])

    @patch("agent.wr")
    @patch("agent.boto3")
    def test_retorna_registros_como_lista_de_dicts(self, mock_boto3, mock_wr):
        mock_wr.athena.read_sql_query.return_value = pd.DataFrame([TITULO_FAKE])

        resultado = agent.buscar_titulos_spec()

        self.assertIsInstance(resultado, list)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["title"], "O Iluminado")

    @patch("agent.wr")
    @patch("agent.boto3")
    def test_filtro_tipo_incluido_na_query(self, mock_boto3, mock_wr):
        mock_wr.athena.read_sql_query.return_value = pd.DataFrame()

        agent.buscar_titulos_spec(tipo="movie")

        sql_executado = mock_wr.athena.read_sql_query.call_args[1]["sql"]
        self.assertIn("media_type = 'movie'", sql_executado)

    @patch("agent.wr")
    @patch("agent.boto3")
    def test_filtro_ano_incluido_na_query(self, mock_boto3, mock_wr):
        mock_wr.athena.read_sql_query.return_value = pd.DataFrame()

        agent.buscar_titulos_spec(ano=1990)

        sql_executado = mock_wr.athena.read_sql_query.call_args[1]["sql"]
        self.assertIn("year = '1990'", sql_executado)

    @patch("agent.wr")
    @patch("agent.boto3")
    def test_filtro_genero_incluido_na_query(self, mock_boto3, mock_wr):
        mock_wr.athena.read_sql_query.return_value = pd.DataFrame()

        agent.buscar_titulos_spec(genero="Terror")

        sql_executado = mock_wr.athena.read_sql_query.call_args[1]["sql"]
        self.assertIn("Terror", sql_executado)

    @patch("agent.wr")
    @patch("agent.boto3")
    def test_limite_aplicado_na_query(self, mock_boto3, mock_wr):
        mock_wr.athena.read_sql_query.return_value = pd.DataFrame()

        agent.buscar_titulos_spec(limite=10)

        sql_executado = mock_wr.athena.read_sql_query.call_args[1]["sql"]
        self.assertIn("LIMIT 10", sql_executado)


# ── Testes de recomendar ───────────────────────────────────────────────────────


class TestRecomendar(unittest.TestCase):

    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_vazia_se_athena_sem_resultados(self, mock_buscar):
        mock_buscar.return_value = []
        mock_client = _mock_openai_client({"tipo": "movie"}, "")
        agent.client = mock_client

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(resultado, [])

    @patch("agent.buscar_titulos_spec")
    def test_chama_openai_duas_vezes(self, mock_buscar):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_client = _mock_openai_client({"tipo": "movie"}, RESPOSTA_OPENAI_FAKE)
        agent.client = mock_client

        agent.recomendar("filmes de terror")

        self.assertEqual(mock_client.chat.completions.create.call_count, 2)

    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_de_titulos(self, mock_buscar):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_client = _mock_openai_client({"tipo": "movie"}, RESPOSTA_OPENAI_FAKE)
        agent.client = mock_client

        resultado = agent.recomendar("filmes de terror")

        self.assertIsInstance(resultado, list)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["titulo"], "O Iluminado")

    @patch("agent.buscar_titulos_spec")
    def test_remove_markdown_code_block_do_json(self, mock_buscar):
        mock_buscar.return_value = [TITULO_FAKE]
        resposta_com_markdown = f"```json\n{RESPOSTA_OPENAI_FAKE}\n```"
        mock_client = _mock_openai_client({"tipo": "movie"}, resposta_com_markdown)
        agent.client = mock_client

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(len(resultado), 1)

    @patch("agent.buscar_titulos_spec")
    def test_retorna_lista_vazia_se_openai_retorna_string_vazia(self, mock_buscar):
        mock_buscar.return_value = [TITULO_FAKE]
        mock_client = _mock_openai_client({"tipo": "movie"}, "")
        agent.client = mock_client

        resultado = agent.recomendar("filmes de terror")

        self.assertEqual(resultado, [])

    @patch("agent.buscar_titulos_spec")
    def test_passa_filtros_extraidos_pelo_openai_para_athena(self, mock_buscar):
        mock_buscar.return_value = [TITULO_FAKE]
        filtros = {"tipo": "movie", "genero": "Terror", "ano": 1980, "nota_minima": 7.0, "limite": 5}
        mock_client = _mock_openai_client(filtros, RESPOSTA_OPENAI_FAKE)
        agent.client = mock_client

        agent.recomendar("filmes de terror dos anos 80")

        mock_buscar.assert_called_once_with(**filtros)


if __name__ == "__main__":
    unittest.main()
