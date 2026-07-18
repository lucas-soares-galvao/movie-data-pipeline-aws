from unittest.mock import MagicMock, patch

from shared_utils.idioma_aws import detect_language_aws


class TestDetectLanguageAws:
    def test_detecta_com_sucesso_idioma_de_maior_score(self):
        mock_client = MagicMock()
        mock_client.detect_dominant_language.return_value = {
            "Languages": [
                {"LanguageCode": "es", "Score": 0.4},
                {"LanguageCode": "pt", "Score": 0.9},
            ]
        }
        with patch("shared_utils.idioma_aws.boto3.client", return_value=mock_client) as mock_boto:
            result = detect_language_aws("Olá mundo", region="sa-east-1")
        assert result == "pt"
        mock_boto.assert_called_once_with("comprehend", region_name="sa-east-1")
        mock_client.detect_dominant_language.assert_called_once_with(Text="Olá mundo")

    def test_usa_region_default_us_east_1(self):
        """Comprehend não está disponível em sa-east-1 (região principal do pipeline) —
        o default us-east-1 evita esquecer de informar a região."""
        mock_client = MagicMock()
        mock_client.detect_dominant_language.return_value = {
            "Languages": [{"LanguageCode": "en", "Score": 0.99}]
        }
        with patch("shared_utils.idioma_aws.boto3.client", return_value=mock_client) as mock_boto:
            detect_language_aws("Hello")
        mock_boto.assert_called_once_with("comprehend", region_name="us-east-1")

    def test_lista_de_idiomas_vazia_devolve_none(self):
        mock_client = MagicMock()
        mock_client.detect_dominant_language.return_value = {"Languages": []}
        with patch("shared_utils.idioma_aws.boto3.client", return_value=mock_client):
            result = detect_language_aws("texto qualquer")
        assert result is None

    def test_excecao_capturada_devolve_none(self):
        with patch("shared_utils.idioma_aws.boto3.client", side_effect=Exception("boom")):
            result = detect_language_aws("Hello")
        assert result is None

    def test_texto_vazio_devolve_none_sem_chamar_boto3(self):
        with patch("shared_utils.idioma_aws.boto3.client") as mock_boto:
            result = detect_language_aws("")
        assert result is None
        mock_boto.assert_not_called()

    def test_texto_so_espaco_devolve_none(self):
        with patch("shared_utils.idioma_aws.boto3.client") as mock_boto:
            result = detect_language_aws("   ")
        assert result is None
        mock_boto.assert_not_called()
