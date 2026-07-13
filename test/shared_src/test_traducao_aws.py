from unittest.mock import MagicMock, patch

from shared_utils.traducao_aws import translate_text_aws


class TestTranslateTextAws:
    def test_traduz_com_sucesso(self):
        mock_client = MagicMock()
        mock_client.translate_text.return_value = {"TranslatedText": "Olá"}
        with patch("shared_utils.traducao_aws.boto3.client", return_value=mock_client) as mock_boto:
            result = translate_text_aws("Hello", region="sa-east-1")
        assert result == "Olá"
        mock_boto.assert_called_once_with("translate", region_name="sa-east-1")
        mock_client.translate_text.assert_called_once_with(
            Text="Hello", SourceLanguageCode="auto", TargetLanguageCode="pt",
        )

    def test_retorna_original_em_caso_de_excecao(self):
        with patch("shared_utils.traducao_aws.boto3.client", side_effect=Exception("boom")):
            result = translate_text_aws("Hello", region="sa-east-1")
        assert result == "Hello"

    def test_retorna_original_quando_resposta_vazia(self):
        mock_client = MagicMock()
        mock_client.translate_text.return_value = {"TranslatedText": ""}
        with patch("shared_utils.traducao_aws.boto3.client", return_value=mock_client):
            result = translate_text_aws("Hello", region="sa-east-1")
        assert result == "Hello"

    def test_usa_region_default_us_east_1(self):
        """AWS Translate não está disponível em sa-east-1 (região principal do
        pipeline) — o default us-east-1 evita esquecer de informar a região."""
        mock_client = MagicMock()
        mock_client.translate_text.return_value = {"TranslatedText": "Olá"}
        with patch("shared_utils.traducao_aws.boto3.client", return_value=mock_client) as mock_boto:
            translate_text_aws("Hello")
        mock_boto.assert_called_once_with("translate", region_name="us-east-1")
