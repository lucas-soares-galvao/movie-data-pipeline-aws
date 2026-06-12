"""
conftest.py — Configuração de testes para o módulo Lightsail (FilmBot).

agent.py chama load_dotenv() no momento em que é importado e lê algumas env vars
no load time. As variáveis precisam existir ANTES do import, por isso são definidas
aqui. OPENAI_API_KEY não precisa ser válida — o cliente OpenAI é inicializado lazy
e todas as chamadas reais são interceptadas por @patch nos testes.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app/lightsail_ia"))

# setdefault preserva valores reais se os testes rodarem com env vars configuradas
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AWS_REGION", "sa-east-1")
os.environ.setdefault("GLUE_DATABASE", "db_unified_tmdb")
os.environ.setdefault("SPEC_TABLE", "tb_discover_unified_tmdb")
os.environ.setdefault("ATHENA_S3_OUTPUT", "s3://test-bucket-temp/athena-results/")
