"""Testes de shared_utils.s3_helpers (ExpectedBucketOwner contra bucket squatting)."""

from shared_utils.s3_helpers import expected_bucket_owner_kwargs


class TestExpectedBucketOwnerKwargs:
    def test_retorna_kwarg_quando_aws_account_id_definida(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCOUNT_ID", "123456789012")
        assert expected_bucket_owner_kwargs() == {"ExpectedBucketOwner": "123456789012"}

    def test_retorna_vazio_quando_aws_account_id_ausente(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCOUNT_ID", raising=False)
        assert expected_bucket_owner_kwargs() == {}

    def test_retorna_vazio_quando_aws_account_id_vazia(self, monkeypatch):
        """String vazia é tratada como ausente — evita enviar ExpectedBucketOwner="" ao boto3."""
        monkeypatch.setenv("AWS_ACCOUNT_ID", "")
        assert expected_bucket_owner_kwargs() == {}

    def test_le_valor_a_cada_chamada_nao_no_import(self, monkeypatch):
        """O valor não é cacheado: reflete a variável de ambiente atual a cada chamada,
        pois nos jobs Glue ela é publicada em os.environ só em runtime (get_parameters_glue)."""
        monkeypatch.delenv("AWS_ACCOUNT_ID", raising=False)
        assert expected_bucket_owner_kwargs() == {}
        monkeypatch.setenv("AWS_ACCOUNT_ID", "999999999999")
        assert expected_bucket_owner_kwargs() == {"ExpectedBucketOwner": "999999999999"}
