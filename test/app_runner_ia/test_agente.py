import json
from unittest.mock import MagicMock, patch

import pandas as pd

import utils.agente as m


# ── Helpers ───────────────────────────────────────────────────────────────────

def _df_titulo():
    return pd.DataFrame([{
        "title": "Filme Teste",
        "media_type": "movie",
        "year": "2023",
        "genre_names": "Ação",
        "overview": "Sinopse teste",
        "vote_average": 7.5,
        "poster_url": "https://img.example.com/poster.jpg",
        "backdrop_url": None,
        "runtime_minutes": 120,
        "number_of_seasons": None,
        "number_of_episodes": None,
        "episode_runtime_minutes": None,
        "streaming_providers": "Netflix",
    }])


def _mock_client_com_titulos():
    """Cria um mock de OpenAI client que simula o pipeline completo de 3 passos."""
    mock_client = MagicMock()

    tool_call = MagicMock()
    tool_call.function.arguments = '{"tipo": "movie", "limite": 10}'
    tool_call.id = "call_test123"

    msg_passo1 = MagicMock()
    msg_passo1.tool_calls = [tool_call]

    resp_passo1 = MagicMock()
    resp_passo1.choices = [MagicMock(message=msg_passo1)]

    resp_passo3 = MagicMock()
    resp_passo3.choices = [MagicMock()]
    resp_passo3.choices[0].message.content = '{"titulos": [{"titulo": "Filme Teste"}]}'

    mock_client.chat.completions.create.side_effect = [resp_passo1, resp_passo3]
    return mock_client


# ── TestBuscarOpenaiKey ────────────────────────────────────────────────────────

class TestBuscarOpenaiKey:
    def test_busca_segredo_no_secrets_manager(self, monkeypatch):
        monkeypatch.setenv("OPENAI_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123:secret:openai")
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value.get_secret_value.return_value = {
            "SecretString": json.dumps({"OPENAI_API_KEY": "sk-test"})
        }
        with patch.object(m, "boto3", mock_boto3):
            result = m._buscar_openai_key()
        assert result == "sk-test"

    def test_usa_arn_do_env(self, monkeypatch):
        arn = "arn:aws:secretsmanager:sa-east-1:999:secret:minha-chave"
        monkeypatch.setenv("OPENAI_SECRET_ARN", arn)
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value.get_secret_value.return_value = {
            "SecretString": json.dumps({"OPENAI_API_KEY": "sk-xyz"})
        }
        with patch.object(m, "boto3", mock_boto3):
            m._buscar_openai_key()
        mock_boto3.client.return_value.get_secret_value.assert_called_once_with(SecretId=arn)


# ── TestBuscarTitulosSpec ──────────────────────────────────────────────────────

class TestBuscarTitulosSpec:
    def test_retorna_lista_de_dicts(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET_TEMP", "bucket-temp-dev")
        with patch.object(m, "wr") as mock_wr:
            mock_wr.athena.read_sql_query.return_value = _df_titulo()
            result = m.buscar_titulos_spec(tipo="movie", limite=5)
        assert isinstance(result, list)
        assert result[0]["title"] == "Filme Teste"

    def test_aplica_filtro_de_tipo_na_sql(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET_TEMP", "bucket-temp-dev")
        with patch.object(m, "wr") as mock_wr:
            mock_wr.athena.read_sql_query.return_value = _df_titulo()
            m.buscar_titulos_spec(tipo="movie")
            sql = mock_wr.athena.read_sql_query.call_args[1]["sql"]
        assert "media_type = 'movie'" in sql

    def test_aplica_filtro_de_genero_na_sql(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET_TEMP", "bucket-temp-dev")
        with patch.object(m, "wr") as mock_wr:
            mock_wr.athena.read_sql_query.return_value = _df_titulo()
            m.buscar_titulos_spec(genero="Terror")
            sql = mock_wr.athena.read_sql_query.call_args[1]["sql"]
        assert "Terror" in sql

    def test_aplica_filtro_de_ano_na_sql(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET_TEMP", "bucket-temp-dev")
        with patch.object(m, "wr") as mock_wr:
            mock_wr.athena.read_sql_query.return_value = _df_titulo()
            m.buscar_titulos_spec(ano=2022)
            sql = mock_wr.athena.read_sql_query.call_args[1]["sql"]
        assert "year = '2022'" in sql

    def test_usa_database_do_env(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET_TEMP", "bucket-temp-dev")
        monkeypatch.setenv("ATHENA_DATABASE", "db_custom")
        with patch.object(m, "wr") as mock_wr:
            mock_wr.athena.read_sql_query.return_value = _df_titulo()
            m.buscar_titulos_spec()
            database = mock_wr.athena.read_sql_query.call_args[1]["database"]
        assert database == "db_custom"

    def test_usa_tabela_do_env_na_sql(self, monkeypatch):
        monkeypatch.setenv("S3_BUCKET_TEMP", "bucket-temp-dev")
        monkeypatch.setenv("ATHENA_TABLE", "tb_custom_spec")
        with patch.object(m, "wr") as mock_wr:
            mock_wr.athena.read_sql_query.return_value = _df_titulo()
            m.buscar_titulos_spec()
            sql = mock_wr.athena.read_sql_query.call_args[1]["sql"]
        assert "tb_custom_spec" in sql


# ── TestExecutarAgente ─────────────────────────────────────────────────────────

class TestExecutarAgente:
    def setup_method(self):
        m._openai_client = None

    def test_pipeline_completo_retorna_lista(self):
        with (
            patch.object(m, "_get_client", return_value=_mock_client_com_titulos()),
            patch.object(m, "buscar_titulos_spec", return_value=[{"title": "Filme"}]),
        ):
            result = m.executar_agente("filmes de ação")
        assert isinstance(result, list)
        assert result[0]["titulo"] == "Filme Teste"

    def test_retorna_lista_vazia_sem_titulos_no_athena(self):
        with (
            patch.object(m, "_get_client", return_value=_mock_client_com_titulos()),
            patch.object(m, "buscar_titulos_spec", return_value=[]),
        ):
            result = m.executar_agente("algo muito específico")
        assert result == []

    def test_chama_openai_duas_vezes_quando_ha_titulos(self):
        mock_client = _mock_client_com_titulos()
        with (
            patch.object(m, "_get_client", return_value=mock_client),
            patch.object(m, "buscar_titulos_spec", return_value=[{"title": "X"}]),
        ):
            m.executar_agente("filmes de drama")
        assert mock_client.chat.completions.create.call_count == 2

    def test_chama_openai_uma_vez_quando_sem_titulos(self):
        mock_client = _mock_client_com_titulos()
        with (
            patch.object(m, "_get_client", return_value=mock_client),
            patch.object(m, "buscar_titulos_spec", return_value=[]),
        ):
            m.executar_agente("algo incomum")
        assert mock_client.chat.completions.create.call_count == 1

    def test_retorna_lista_vazia_se_openai_retorna_json_vazio(self):
        mock_client = _mock_client_com_titulos()
        mock_client.chat.completions.create.side_effect[1].choices[0].message.content = (
            '{"titulos": []}'
        )
        with (
            patch.object(m, "_get_client", return_value=mock_client),
            patch.object(m, "buscar_titulos_spec", return_value=[{"title": "X"}]),
        ):
            result = m.executar_agente("alguma preferência")
        assert result == []

    def test_remove_bloco_markdown_do_json(self):
        mock_client = _mock_client_com_titulos()
        mock_client.chat.completions.create.side_effect[1].choices[0].message.content = (
            '```json\n{"titulos": [{"titulo": "Wrapped"}]}\n```'
        )
        with (
            patch.object(m, "_get_client", return_value=mock_client),
            patch.object(m, "buscar_titulos_spec", return_value=[{"title": "X"}]),
        ):
            result = m.executar_agente("qualquer coisa")
        assert result[0]["titulo"] == "Wrapped"
