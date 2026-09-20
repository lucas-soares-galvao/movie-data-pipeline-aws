"""
conftest.py — Configuração de testes para o módulo Lightsail (FilmBot).

agent.py chama load_dotenv() no momento em que é importado e lê algumas env vars
no load time. As variáveis precisam existir ANTES do import, por isso são definidas
aqui. LLM_API_KEY não precisa ser válida — o cliente LLM é inicializado lazy
e todas as chamadas reais são interceptadas por @patch nos testes.

Módulos de produção são importados via `from src.X import Y` (mesmo padrão de
lambda_api/glue_*). O `src` solto é realiasado para `app.lightsail_ia.src` pelo
conftest.py global (`test/conftest.py`, `_SUITE_TO_APP`/`_SUITE_TO_SRC_MODULE`) a cada
arquivo/teste, evitando colisão com o `src` de outras suites quando a suíte completa
roda no mesmo processo pytest.
"""

import os

import pytest

# Isolamento do .env local: load_dotenv() (agent.py) NÃO sobrescreve variável já definida, nem
# vazia. Um app/lightsail_ia/.env de desenvolvimento com estas duas preenchidas faria o
# AppTest (test_app.py) rodar setup_cloudwatch_logging()/load_filmbot_password() de verdade:
# handler real do CloudWatch, chamada real ao Secrets Manager e root logger derrubado para
# ERROR pelo resto da sessão pytest — o que quebrava os testes de log (caplog) de
# test/scripts e test/shared_src só na máquina do desenvolvedor, nunca no CI (sem .env).
os.environ["FILMBOT_SECRET_ARN"] = ""
os.environ["CLOUDWATCH_LOG_GROUP"] = ""

# Mesma razão para as credenciais AWS: o .env de desenvolvimento traz chaves reais, e uma chamada
# boto3 esquecida sem mock usaria essas chaves. Valores falsos (convenção do moto) fazem a
# chamada falhar por credencial inválida — e o bloqueio de rede de test/conftest.py já barra a
# conexão antes disso. AWS_PROFILE sai para o boto3 não procurar um perfil real em ~/.aws.
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ.pop("AWS_PROFILE", None)

# setdefault preserva valores reais se os testes rodarem com env vars configuradas
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ.setdefault("TRANSCRIPTION_API_KEY", "test-transcription-key")
os.environ.setdefault("AWS_REGION", "sa-east-1")
os.environ.setdefault("GLUE_DATABASE", "db_tmdb_unified_prod")
os.environ.setdefault("SPEC_TABLE", "tb_tmdb_discover_unified_prod")
os.environ.setdefault("ATHENA_S3_OUTPUT", "s3://test-bucket-temp/athena-results/")
os.environ.setdefault("COGNITO_USER_POOL_ID", "sa-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client-id")
os.environ.setdefault("SNS_NEW_SIGNUP_TOPIC_ARN", "arn:aws:sns:sa-east-1:123456789012:test-new-signup-topic")


@pytest.fixture(autouse=True)
def _limpar_cache_where():
    from src import agent
    agent._WHERE_CACHE.clear()
