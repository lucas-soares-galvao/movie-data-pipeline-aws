"""
main.py — Ponto de entrada da Lambda.

Este arquivo contém apenas a lógica principal do fluxo de dados:
  1. Lê o tipo de conteúdo ("movie" ou "tv") e os nomes das tabelas do
     Glue Catalog enviados pelo EventBridge no campo "event".
  2. Busca a chave de API do TMDB no Secrets Manager.
  3. Coleta os dados de referência relativos ao tipo (gêneros + países/idiomas)
     e salva no S3.
  4. Para cada ano de 2000 até o ano atual:
     a. Coleta até 100 páginas do tipo recebido e salva no S3 (bucket SOR).
     b. Aciona o job Glue ETL passando o ano e os nomes das tabelas do Catalog.

A Lambda é executada duas vezes por dia pelo EventBridge:
  01:05 UTC — event {"type": "movie", "database": "...", "table_discover_movie": "...", ...}
  01:20 UTC — event {"type": "tv",    "database": "...", "table_discover_tv": "...",    ...}

Estrutura de pastas gerada no S3:
  tmdb/configuration/countries/paises.json       (execução tv)
  tmdb/configuration/languages/idiomas.json      (execução movie)
  tmdb/genre/movie/generos_filmes.json           (execução movie)
  tmdb/genre/tv/generos_series.json             (execução tv)
  tmdb/discover/movie/ano=AAAA/pagina_NNN.json  (execução movie)
  tmdb/discover/tv/ano=AAAA/pagina_NNN.json     (execução tv)
"""

import logging
import os
from datetime import datetime

import boto3

from src.utils import collect_and_save, collect_reference_data, get_tmdb_api_key, trigger_glue_job

# ---------------------------------------------------------------------------
# Configuração de log (os registros aparecem no CloudWatch automaticamente)
# ---------------------------------------------------------------------------
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Variáveis de ambiente — definidas no Terraform (infra/lambda_api.tf)
# ---------------------------------------------------------------------------
TMDB_SECRET_ARN = os.environ["TMDB_SECRET_ARN"]      # ARN do segredo com a API key do TMDB
GLUE_ETL_JOB_NAME = os.environ["GLUE_ETL_JOB_NAME"]  # Nome do job Glue ETL
S3_BUCKET_SOR = os.environ["S3_BUCKET_SOR"]          # Bucket SOR onde os dados brutos são salvos

# ---------------------------------------------------------------------------
# Constantes de negócio
# ---------------------------------------------------------------------------
START_YEAR = 2000  # Primeiro ano a ser coletado


# ---------------------------------------------------------------------------
# Handler principal — chamado pela AWS ao invocar a Lambda
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    """
    Função principal da Lambda. A AWS a chama automaticamente ao disparar a função.

    O EventBridge envia no evento:
      - "type"   : "movie" ou "tv" — define o que será coletado nesta execução.
      - "database" e os nomes das tabelas do Glue Catalog, repassados ao Glue ETL.

    Exemplo de evento (movie):
      {
        "type": "movie",
        "database": "tmdb_db",
        "table_discover_movie": "discover_movie",
        "table_genre_movie": "genre_movie",
        "table_configuration_languages": "configuration_languages"
      }

    Args:
        event:   Dicionário enviado pelo EventBridge com o tipo e nomes de tabelas.
        context: Informações de execução fornecidas pela AWS.

    Returns:
        Dicionário com statusCode 200 e uma mensagem de confirmação.
    """
    # Clientes AWS criados uma única vez e reutilizados em todo o loop
    s3_client = boto3.client("s3")
    glue_client = boto3.client("glue")

    # "type" define se esta execução é para filmes ou séries
    content_type = event["type"]  # "movie" ou "tv"

    # Monta os argumentos padronizados para o Glue ETL.
    # Independente do tipo, o Glue sempre recebe os mesmos nomes de argumento,
    # apenas os valores mudam entre a execução de movie e tv.
    if content_type == "movie":
        glue_catalog_args = {
            "MEDIA_TYPE":          content_type,
            "DATABASE":            event["database"],
            "DISCOVER_TABLE":      event["table_discover_movie"],
            "GENRE_TABLE":         event["table_genre_movie"],
            "CONFIGURATION_TABLE": event["table_configuration_languages"],
        }
    else:
        glue_catalog_args = {
            "MEDIA_TYPE":          content_type,
            "DATABASE":            event["database"],
            "DISCOVER_TABLE":      event["table_discover_tv"],
            "GENRE_TABLE":         event["table_genre_tv"],
            "CONFIGURATION_TABLE": event["table_configuration_countries"],
        }

    # Busca a chave de API uma única vez para não chamar o Secrets Manager repetidamente
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_tmdb_api_key(TMDB_SECRET_ARN)

    current_year = datetime.now().year

    # Coleta apenas as referências relevantes para o tipo recebido:
    #   movie → genre/movie + configuration/languages
    #   tv    → genre/tv    + configuration/countries
    logger.info("Coletando dados de referência do TMDB para '%s'...", content_type)
    collect_reference_data(api_key, s3_client, S3_BUCKET_SOR, content_type)

    # Aciona o Glue ETL para processar as tabelas de referência (gêneros e configurações)
    # Não passa year aqui pois os dados de referência não são particionados por ano
    logger.info("Acionando Glue ETL para tabelas de referência...")
    trigger_glue_job(glue_client, GLUE_ETL_JOB_NAME, glue_catalog_args)

    logger.info("Iniciando coleta do TMDB (%s) de %d até %d...", content_type, START_YEAR, current_year)

    for year in range(START_YEAR, current_year + 1):
        logger.info("=== Ano: %d | Tipo: %s ===", year, content_type)

        # Coleta o tipo recebido no evento para o ano atual
        collect_and_save(
            api_key=api_key,
            s3_client=s3_client,
            bucket=S3_BUCKET_SOR,
            content_type=content_type,
            folder=f"tmdb/discover/{content_type}",
            year=year,
        )

        # Aciona o Glue ETL passando o ano e os nomes das tabelas do Glue Catalog
        trigger_glue_job(glue_client, GLUE_ETL_JOB_NAME, glue_catalog_args, year)

    logger.info("Coleta de '%s' finalizada com sucesso!", content_type)
    return {
        "statusCode": 200,
        "body": f"Dados de '{content_type}' coletados de {START_YEAR} a {current_year} com sucesso.",
    }

