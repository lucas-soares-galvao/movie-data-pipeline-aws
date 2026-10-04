import json
from unittest.mock import MagicMock, patch

from shared_utils.llm_client import load_llm_api_key


class TestLoadLlmApiKey:
    """Chave lida do Secrets Manager (produção, via FILMBOT_SECRET_ARN) ou do ambiente
    (desenvolvimento) — compartilhada entre o agente de recomendação (lightsail_ia) e a
    tradução via LLM (traducao_llm.py/idioma_llm.py)."""

    _ARN = "arn:aws:secretsmanager:sa-east-1:123456789012:secret:filmbot"

    def _mock_secret(self, mock_boto3, secret: dict) -> MagicMock:
        client = MagicMock()
        client.get_secret_value.return_value = {"SecretString": json.dumps(secret)}
        mock_boto3.client.return_value = client
        return client

    def test_campo_obrigatorio_vem_do_secrets_manager_quando_arn_configurado(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", self._ARN)
        with patch("shared_utils.llm_client.boto3") as mock_boto3:
            client = self._mock_secret(mock_boto3, {"llm_api_key": "chave-llm"})
            assert load_llm_api_key("llm_api_key", "LLM_API_KEY") == "chave-llm"

        client.get_secret_value.assert_called_once_with(SecretId=self._ARN)
        mock_boto3.client.assert_called_once_with("secretsmanager", region_name="sa-east-1")

    def test_campo_obrigatorio_vem_do_ambiente_sem_arn(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("LLM_API_KEY", "chave-env")
        with patch("shared_utils.llm_client.boto3") as mock_boto3:
            assert load_llm_api_key("llm_api_key", "LLM_API_KEY") == "chave-env"

        mock_boto3.client.assert_not_called()

    def test_campo_opcional_presente_no_secret(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", self._ARN)
        with patch("shared_utils.llm_client.boto3") as mock_boto3:
            self._mock_secret(mock_boto3, {"llm_api_key": "x", "transcription_api_key": "chave-stt"})
            result = load_llm_api_key("transcription_api_key", "TRANSCRIPTION_API_KEY", required=False)
        assert result == "chave-stt"

    def test_campo_opcional_ausente_no_secret_retorna_none_sem_derrubar_o_chamador(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", self._ARN)
        with patch("shared_utils.llm_client.boto3") as mock_boto3:
            self._mock_secret(mock_boto3, {"llm_api_key": "x"})
            assert load_llm_api_key("transcription_api_key", "TRANSCRIPTION_API_KEY", required=False) is None

    def test_campo_opcional_vem_do_ambiente_sem_arn(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("TRANSCRIPTION_API_KEY", "stt-env")
        assert load_llm_api_key("transcription_api_key", "TRANSCRIPTION_API_KEY", required=False) == "stt-env"

    def test_campo_obrigatorio_ausente_no_secret_levanta_key_error(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", self._ARN)
        with patch("shared_utils.llm_client.boto3") as mock_boto3:
            self._mock_secret(mock_boto3, {"outro_campo": "x"})
            try:
                load_llm_api_key("llm_api_key", "LLM_API_KEY")
            except KeyError:
                return
        raise AssertionError("esperava KeyError para campo obrigatório ausente")

    def test_nenhuma_fonte_configurada_devolve_none(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        assert load_llm_api_key("llm_api_key", "LLM_API_KEY") is None

    def test_regiao_customizada_repassada_ao_client(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", self._ARN)
        with patch("shared_utils.llm_client.boto3") as mock_boto3:
            self._mock_secret(mock_boto3, {"llm_api_key": "x"})
            load_llm_api_key("llm_api_key", "LLM_API_KEY", region="us-east-1")
        mock_boto3.client.assert_called_once_with("secretsmanager", region_name="us-east-1")
