"""Testa o bloqueio de rede instalado por test/conftest.py (nenhum teste pode chamar serviço real)."""

import socket

import pytest


class TestBloqueioDeRede:
    def test_resolucao_de_dns_externa_e_bloqueada(self):
        with pytest.raises(RuntimeError, match="Teste tentou acessar a rede"):
            socket.getaddrinfo("sts.sa-east-1.amazonaws.com", 443)

    def test_conexao_externa_e_bloqueada(self):
        with pytest.raises(RuntimeError, match="Teste tentou acessar a rede"):
            socket.create_connection(("203.0.113.10", 443), timeout=1)

    def test_connect_ex_externo_e_bloqueado(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock, pytest.raises(RuntimeError):
            sock.connect_ex(("203.0.113.10", 443))

    def test_boto3_sem_mock_nao_chega_na_aws(self):
        import boto3

        client = boto3.client(
            "sts", region_name="sa-east-1", aws_access_key_id="testing", aws_secret_access_key="testing"
        )
        with pytest.raises(Exception, match="Teste tentou acessar a rede"):
            client.get_caller_identity()

    def test_loopback_continua_liberado(self):
        # asyncio/AppTest usam um socketpair local; bind e connect em 127.0.0.1 precisam funcionar.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                pass
