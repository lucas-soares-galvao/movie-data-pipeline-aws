import json
import logging
import traceback
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


# Valor obviamente falso: nunca reusar uma chave que já apareceu num ambiente real.
_FAKE_KEY = "0123456789abcdef0123456789abcdef"


def _resposta_real(status_code: int) -> requests.Response:
    """Response real do requests: raise_for_status() monta a mensagem com a URL completa — que no
    TMDB carrega a api_key como parâmetro de query."""
    response = requests.Response()
    response.status_code = status_code
    response.reason = "Not Found" if status_code == 404 else "Internal Server Error"
    response.url = f"https://api.themoviedb.org/3/collection/1?api_key={_FAKE_KEY}&language=pt-BR"
    return response


class TestApiGetNaoVazaChaveDeApi:
    """As exceções de api_get saem sem a chave: a mensagem do requests embute a URL com a query, e
    um log de `{exc}` num repositório público a vazou no log do GitHub Actions."""

    @patch("shared_utils.api_client.time.sleep")
    @patch("shared_utils.api_client.requests.get")
    def test_http_nao_transiente_levanta_sem_a_chave(self, mock_get, mock_sleep):
        mock_get.return_value = _resposta_real(404)
        with pytest.raises(requests.exceptions.HTTPError) as info:
            api_get("https://api.themoviedb.org/3/collection/1", {"api_key": _FAKE_KEY})
        assert _FAKE_KEY not in str(info.value)
        assert "api_key=***" in str(info.value)
        assert _FAKE_KEY not in "".join(traceback.format_exception(info.value))

    @patch("shared_utils.api_client.time.sleep")
    @patch("shared_utils.api_client.requests.get")
    def test_http_transiente_com_tentativas_esgotadas_levanta_sem_a_chave(self, mock_get, mock_sleep):
        mock_get.return_value = _resposta_real(500)
        with pytest.raises(requests.exceptions.HTTPError) as info:
            api_get("https://api.themoviedb.org/3/collection/1", {"api_key": _FAKE_KEY})
        assert mock_get.call_count == 5
        assert _FAKE_KEY not in str(info.value)
        assert _FAKE_KEY not in "".join(traceback.format_exception(info.value))

    @patch("shared_utils.api_client.time.sleep")
    @patch("shared_utils.api_client.requests.get")
    def test_connection_error_esgotado_loga_e_levanta_sem_a_chave(self, mock_get, mock_sleep, caplog):
        mock_get.side_effect = requests.exceptions.ConnectionError(
            OSError(f"HTTPSConnectionPool(host='api.themoviedb.org'): Max retries exceeded with url: /3/x?api_key={_FAKE_KEY}")
        )
        with caplog.at_level(logging.INFO), pytest.raises(requests.exceptions.ConnectionError) as info:
            api_get("https://api.themoviedb.org/3/x", {"api_key": _FAKE_KEY})
        assert _FAKE_KEY not in str(info.value)
        assert _FAKE_KEY not in "".join(traceback.format_exception(info.value))
        assert _FAKE_KEY not in caplog.text  # inclui o traceback de logger.exception


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

    @patch("shared_utils.api_client.register_secret")
    @patch("boto3.client")
    def test_registra_o_valor_para_mascaramento_nos_logs(self, mock_client_factory, mock_register):
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.get_secret_value.return_value = {"SecretString": json.dumps({"tmdb_api_key": _FAKE_KEY})}

        get_api_secret("arn:aws:secretsmanager:us-east-1:123:secret:tmdb", "tmdb_api_key")

        mock_register.assert_called_once_with(_FAKE_KEY)
