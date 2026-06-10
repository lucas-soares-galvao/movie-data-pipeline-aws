# Raciocinio: configura variáveis de ambiente antes dos imports para evitar
# erros de inicialização nos módulos que leem env vars no load time.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app/lightsail_ia"))

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("AWS_REGION", "sa-east-1")
os.environ.setdefault("GLUE_DATABASE", "db_unified_tmdb")
os.environ.setdefault("SPEC_TABLE", "tb_discover_unified_tmdb")
os.environ.setdefault("ATHENA_S3_OUTPUT", "s3://test-bucket-temp/athena-results/")
