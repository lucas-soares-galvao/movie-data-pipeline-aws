"""
conftest.py — Configuração de testes para o módulo Lightsail (FilmBot).

==============================================================================
POR QUE PRECISAMOS DESTE conftest.py?
==============================================================================
O código do app Lightsail (agent.py) chama load_dotenv() no momento em que
é importado. Algumas variáveis de ambiente são lidas dentro das funções
(ex: buscar_titulos_spec lê ATHENA_S3_OUTPUT em cada chamada). Para evitar
erros por variáveis ausentes durante os testes, definimos valores fictícios
aqui antes de qualquer import.

O cliente OpenAI é inicializado sob demanda via _get_openai_client(), então
OPENAI_API_KEY não precisa ser válida — as chamadas reais são interceptadas
por @patch nos testes.

SOLUÇÃO: Definir as variáveis de ambiente ANTES de qualquer import.
O conftest.py do pytest roda antes de qualquer arquivo de teste, então
este é o lugar correto para definir os valores padrão.

OS VALORES SÃO FICTÍCIOS:
  Todas as variáveis usam valores de teste (ex: "test-openai-key").
  Nos testes, as chamadas reais à API OpenAI e ao Athena são interceptadas
  por @patch ou unittest.mock.MagicMock, então os valores reais não importam.

CAMINHOS DE IMPORTAÇÃO:
  O código do Lightsail está em app/lightsail_ia/ (não em app/lightsail_ia/src/).
  sys.path.insert() permite que os testes importem agent.py diretamente.

Raciocinio: configura variáveis de ambiente antes dos imports para evitar
erros de inicialização nos módulos que leem env vars no load time.
"""

import os
import sys

# Adiciona o diretório do app Lightsail ao sys.path.
# Sem isso, "import agent" no arquivo de teste falharia com ModuleNotFoundError.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app/lightsail_ia"))

# Define variáveis de ambiente padrão para os testes.
# os.environ.setdefault() só define se a variável ainda não existe,
# preservando valores reais se o teste rodar com variáveis reais configuradas.
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")           # chave falsa para OpenAI
os.environ.setdefault("AWS_REGION", "sa-east-1")                     # região padrão do projeto
os.environ.setdefault("GLUE_DATABASE", "db_unified_tmdb")            # banco no Glue Catalog
os.environ.setdefault("SPEC_TABLE", "tb_discover_unified_tmdb")      # tabela SPEC consultada
os.environ.setdefault("ATHENA_S3_OUTPUT", "s3://test-bucket-temp/athena-results/")  # bucket fictício
