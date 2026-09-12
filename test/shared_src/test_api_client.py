import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from shared_utils.api_client import api_get, get_api_secret

# ---------------------------------------------------------------------------
# api_get
# ---------------------------------------------------------------------------


def _make_response(status_code=200, json_data=None, headers=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    r.headers = headers or {}
    r.raise_for_status.return_value = None
    return r


class TestApiGet:
    @patch("shared_utils.api_client.time.sleep")
    @patch("shared_utils.api_client.requests.get")
    def test_retorna_json_em_sucesso(self, mock_get, mock_sleep):
        mock_get.return_value = _make_response(200, {"ok": True})
        resultado = api_get("https://api.example.com/test", {"api_key": "k"})
        assert resultado == {"ok": True}
        mock_sleep.assert_not_called()

    @patch("shared_utils.api_client.time.sleep")
    @patch("shared_utils.api_client.requests.get")
    def test_retry_em_status_transiente_e_retorna_em_sucesso(self, mock_get, mock_sleep):
        mock_get.side_effect = [_make_response(500), _make_response(200, {"ok": True})]
        resultado = api_get("https://api.example.com/test", {"api_key": "k"})
        assert resultado == {"ok": True}
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("shared_utils.api_client.time.sleep")
    @patch("shared_utils.api_client.requests.get")
    def test_retry_em_429_usa_retry_after(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            _make_response(429, headers={"Retry-After": "5"}),
            _make_response(200, {}),
        ]
        api_get("https://api.example.com/test", {"api_key": "k"})
        wait = mock_sleep.call_args[0][0]
        assert wait >= 5

    @patch("shared_utils.api_client.time.sleep")
    @patch("shared_utils.api_client.requests.get")
    def test_retry_em_connection_error_e_retorna_em_sucesso(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("timeout"),
            _make_response(200, {"ok": True}),
        ]
        resultado = api_get("https://api.example.com/test", {"api_key": "k"})
        assert resultado == {"ok": True}
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("shared_utils.api_client.time.sleep")
    @patch("shared_utils.api_client.requests.get")
    def test_levanta_apos_esgotar_tentativas_http(self, mock_get, mock_sleep):
        r500 = _make_response(500)
        r500.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        mock_get.return_value = r500
        with pytest.raises(requests.exceptions.HTTPError):
            api_get("https://api.example.com/test", {"api_key": "k"})
        assert mock_get.call_count == 5

    @patch("shared_utils.api_client.time.sleep")
    @patch("shared_utils.api_client.requests.get")
    def test_levanta_apos_esgotar_tentativas_connection(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.exceptions.ConnectionError("fail")
        with pytest.raises(requests.exceptions.ConnectionError):
            api_get("https://api.example.com/test", {"api_key": "k"})
        assert mock_get.call_count == 5


# ---------------------------------------------------------------------------
# get_api_secret
# ---------------------------------------------------------------------------


class TestGetApiSecret:
    # Patch em "boto3.client" (objeto boto3 global), não em "shared_utils.api_client.boto3":
    # o conftest de test/ apaga shared_utils.* de sys.modules ao coletar cada suite de
    # _SUITE_TO_APP, então quando a suíte inteira roda de uma vez o get_api_secret chamado
    # aqui pode ser a referência importada do módulo ANTIGO, enquanto o patch por string
    # resolveria o módulo NOVO — deixando boto3 real vazar e a função tentar credenciais
    # AWS de verdade. O objeto "boto3" é o mesmo nos dois casos, então patchar ali cobre
    # ambos e mantém tudo mockado (sem tocar AWS de verdade).
    @patch("boto3.client")
    def test_retorna_chave_do_secrets_manager(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"tmdb_api_key": "chave-teste-123"})
        }

        resultado = get_api_secret("arn:aws:secretsmanager:us-east-1:123:secret:tmdb", "tmdb_api_key")

        assert resultado == "chave-teste-123"
        # config= passado por timeout explícito (S7618): assert por kwarg, não item a item,
        # porque o valor é a constante BotoConfig do módulo.
        mock_client_factory.assert_called_once()
        assert mock_client_factory.call_args[0] == ("secretsmanager",)
        assert "config" in mock_client_factory.call_args.kwargs
        mock_client.get_secret_value.assert_called_once_with(
            SecretId="arn:aws:secretsmanager:us-east-1:123:secret:tmdb"
        )
