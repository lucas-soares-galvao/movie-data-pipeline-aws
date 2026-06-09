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

from src.utils import (
    collect_configuration_data,
    collect_discover_data,
    collect_genre_data,
    collect_watch_providers_ref,
    get_tmdb_api_key,
    trigger_glue_job,
)

# ---------------------------------------------------------------------------
# Configuração de log (os registros aparecem no CloudWatch automaticamente)
# ---------------------------------------------------------------------------
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Variáveis de ambiente — definidas no Terraform (infra/lambda_api.tf)
# ---------------------------------------------------------------------------
TMDB_SECRET_ARN = os.environ["TMDB_SECRET_ARN"]  # ARN do segredo com a API key do TMDB
GLUE_ETL_JOB_NAME = os.environ["GLUE_ETL_JOB_NAME"]  # Nome do job Glue ETL
S3_BUCKET_SOR = os.environ[
    "S3_BUCKET_SOR"
]  # Bucket SOR onde os dados brutos são salvos

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

    # Argumentos comuns a todas as chamadas do Glue ETL
    glue_base_args = {
        "MEDIA_TYPE": content_type,
        "DATABASE": event["database"],
        "DATABASE_UNIFIED": event["database_unified"],
    }

    # Configurações (países/idiomas) são referências globais compartilhadas entre filmes e séries.
    # Por isso usam DATABASE_UNIFIED: o banco que centraliza tabelas que não pertencem a
    # apenas um tipo de mídia (ao contrário de discover/gêneros, que são separados por movie/tv).
    glue_unified_args = {
        "MEDIA_TYPE": content_type,
        "DATABASE": event["database_unified"],
        "DATABASE_UNIFIED": event["database_unified"],
    }

    # Nomes das tabelas específicas para o tipo recebido
    if content_type == "movie":
        table_genre = event["table_genre_movie"]
        table_configuration = event["table_configuration_languages"]
        table_discover = event["table_discover_movie"]
        table_watch_providers_ref = event["table_watch_providers_ref_movie"]
    else:
        table_genre = event["table_genre_tv"]
        table_configuration = event["table_configuration_countries"]
        table_discover = event["table_discover_tv"]
        table_watch_providers_ref = event["table_watch_providers_ref_tv"]

    only_discover = event.get("only_discover", False)
    skip_discover = event.get("skip_discover", False)

    # Busca a chave de API uma única vez para não chamar o Secrets Manager repetidamente
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_tmdb_api_key(TMDB_SECRET_ARN)

    current_year = datetime.now().year
    start_year   = int(event.get("start_year", current_year - 1))
    end_year     = int(event.get("end_year",   current_year))

    if not only_discover:
        # Coleta gêneros e aciona o Glue passando apenas a tabela de gêneros
        logger.info(f"Coletando gêneros do TMDB para '{content_type}'...")
        collect_genre_data(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de gêneros...")
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_base_args,
            table_type="genre",
            table_name=table_genre,
        )

        # Coleta configurações e aciona o Glue passando apenas a tabela de configuração
        logger.info(f"Coletando configurações do TMDB para '{content_type}'...")
        collect_configuration_data(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de configuração...")
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_unified_args,
            table_type="configuration",
            table_name=table_configuration,
        )

        # Coleta referência de provedores de streaming e aciona o Glue ETL
        # para popular as tabelas tb_watch_providers_ref_{movie|tv}_tmdb.
        logger.info(f"Coletando referência de watch providers do TMDB para '{content_type}'...")
        collect_watch_providers_ref(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de watch providers de referência...")
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_base_args,
            table_type="watch_providers_ref",
            table_name=table_watch_providers_ref,
        )
    else:
        logger.info("only_discover=True: pulando coleta de genre, configuration e watch_providers_ref.")

    if skip_discover:
        logger.info("skip_discover=True: pulando coleta de discover.")
        return {
            "statusCode": 200,
            "body": f"Coleta de referência de '{content_type}' finalizada com sucesso.",
        }

    logger.info(
        f"Iniciando coleta do TMDB ({content_type}) de {start_year} até {end_year}..."
    )

    for year in range(start_year, end_year + 1):
        logger.info(f"=== Ano: {year} | Tipo: {content_type} ===")

        # Coleta o tipo recebido no evento para o ano atual
        collect_discover_data(
            api_key=api_key,
            s3_client=s3_client,
            bucket=S3_BUCKET_SOR,
            content_type=content_type,
            folder=f"tmdb/discover/{content_type}",
            year=year,
        )

        # Aciona o Glue ETL passando a tabela de discover, o ano e o tipo.
        # end_year é repassado para que o glue_details filtre apenas os IDs dos anos atualizados neste ciclo.
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_base_args,
            table_type="discover",
            table_name=table_discover,
            year=year,
            end_year=end_year,
        )

    logger.info(f"Coleta de '{content_type}' finalizada com sucesso!")
    return {
        "statusCode": 200,
        "body": f"Dados de '{content_type}' coletados de {start_year} a {end_year} com sucesso.",
    }