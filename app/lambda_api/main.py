"""
main.py — Ponto de Entrada da Função Lambda

==============================================================================
O QUE ESTE ARQUIVO FAZ?
==============================================================================
Este é o arquivo principal da função Lambda — o ponto de entrada que a AWS
chama quando o EventBridge dispara o agendamento.

FLUXO COMPLETO:
  1. O EventBridge envia um evento JSON dizendo o que coletar ("movie" ou "tv")
  2. Este arquivo lê o evento e busca a chave da API TMDB no Secrets Manager
  3. Coleta dados de referência (gêneros, idiomas/países, plataformas) da API
  4. Coleta dados de discover (lista de filmes/séries populares) ano a ano
  5. Para cada conjunto de dados coletado, dispara o Glue ETL para processar

ORGANIZAÇÃO DO CÓDIGO:
  - main.py    → Fluxo principal (o "maestro" — coordena, não detalha)
  - src/utils.py → Funções detalhadas (o "músico" — executa cada tarefa)

Separar assim facilita testes: cada função de utils.py pode ser testada
independentemente, sem precisar simular o EventBridge inteiro.

EXEMPLO DE EVENTO RECEBIDO (payload do EventBridge):
  {
    "type": "movie",                          ← tipo de mídia a coletar
    "only_discover": true,                    ← pular gêneros/configurações
    "database": "db_movie_tmdb",              ← banco no Glue Catalog
    "database_unified": "db_unified_tmdb",
    "table_discover_movie": "tb_discover_movie_tmdb",
    "table_genre_movie": "tb_genre_movie_tmdb",
    ...
  }

ESTRUTURA DE PASTAS GERADA NO S3 (bucket SOR):
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

# ==============================================================================
# CONFIGURAÇÃO DE LOG
# ==============================================================================
# O AWS Lambda captura automaticamente tudo que for logado e envia ao CloudWatch.
# Nível INFO = exibe mensagens informativas normais (não apenas erros).
# Usar logger.info() em vez de print() é a boa prática para ambientes de produção.
# ==============================================================================
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ==============================================================================
# VARIÁVEIS DE AMBIENTE
# ==============================================================================
# Configurações injetadas pelo Terraform quando a Lambda é criada (lambda_api.tf).
# Usar variáveis de ambiente em vez de hardcodar valores permite que o mesmo
# código funcione em dev e prod sem modificação.
#
# os.environ["NOME"] levanta KeyError se a variável não existir — comportamento
# intencional, pois a Lambda não deve rodar sem essas configurações.
# ==============================================================================
TMDB_SECRET_ARN = os.environ["TMDB_SECRET_ARN"]    # ARN do segredo da API TMDB
GLUE_ETL_JOB_NAME = os.environ["GLUE_ETL_JOB_NAME"]  # Nome do job Glue a disparar
S3_BUCKET_SOR = os.environ["S3_BUCKET_SOR"]        # Bucket para salvar dados brutos


def lambda_handler(event, context):
    """
    Função principal da Lambda — chamada pela AWS quando o EventBridge dispara.

    PARÂMETROS DA AWS:
    - event:   Dicionário JSON enviado pelo EventBridge (definido em eventbridge_lambda_api.tf)
    - context: Objeto com informações da execução atual (tempo restante, memória, etc.)
               Não usamos o context neste projeto, mas ele é obrigatório pela assinatura.

    RETORNO:
    - Dicionário com statusCode 200 (sucesso) e body com mensagem descritiva.
    - Se houver exceção, a AWS captura e marca a execução como "Failed".
    """
    # Cria os clientes AWS uma única vez — mais eficiente que criar dentro do loop.
    # boto3.client() abre uma conexão com o serviço; reutilizar evita overhead.
    s3_client = boto3.client("s3")
    glue_client = boto3.client("glue")

    # "movie" ou "tv" — determina quais endpoints TMDB e quais tabelas serão usadas
    content_type = event["type"]

    # Argumentos base repassados para TODOS os jobs Glue disparados nesta execução.
    # Cada job Glue precisa saber: qual tipo de mídia processar e em qual banco registrar.
    glue_base_args = {
        "MEDIA_TYPE": content_type,
        "DATABASE": event["database"],
        "DATABASE_UNIFIED": event["database_unified"],
    }

    # Os nomes das tabelas no Glue Catalog são diferentes para movie e tv.
    # Este bloco mapeia o tipo para os nomes corretos das tabelas.
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

    # FLAGS DE CONTROLE:
    # only_discover=True → Coleta APENAS o discover (pula gêneros/config/watch_providers)
    #                      Usado na execução DIÁRIA (dados de referência não mudam todo dia)
    # skip_discover=True → Coleta APENAS referências (pula o discover)
    #                      Usado na execução SEMANAL (atualiza apenas referências)
    only_discover = event.get("only_discover", False)
    skip_discover = event.get("skip_discover", False)

    # Busca a API key UMA vez antes do loop — evita múltiplas chamadas ao Secrets Manager.
    # O Secrets Manager tem custo por chamada, e a chave não muda durante a execução.
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_tmdb_api_key(TMDB_SECRET_ARN)

    # Anos de coleta: padrão é (ano_atual - 1) até (ano_atual).
    # O EventBridge pode enviar start_year/end_year para backfill histórico.
    current_year = datetime.now().year
    start_year   = int(event.get("start_year", current_year - 1))
    end_year     = int(event.get("end_year",   current_year))

    # ===========================================================================
    # COLETA DE DADOS DE REFERÊNCIA (Gêneros, Configurações, Watch Providers)
    # ===========================================================================
    # Estes dados são relativamente estáticos (gêneros raramente mudam).
    # São coletados semanalmente (only_discover=False) ou pulados na coleta diária.
    if not only_discover:
        # Gêneros: lista de gêneros (Ação=28, Comédia=35, etc.)
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

        # Configurações: idiomas (para filmes) ou países (para séries)
        logger.info(f"Coletando configurações do TMDB para '{content_type}'...")
        collect_configuration_data(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de configuração...")
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_base_args,
            table_type="configuration",
            table_name=table_configuration,
        )

        # Watch Providers: lista de plataformas de streaming disponíveis no Brasil
        # (Netflix=8, Prime Video=119, Disney+=337, etc.)
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

    # Se skip_discover=True, para aqui (execução semanal de referências)
    if skip_discover:
        logger.info("skip_discover=True: pulando coleta de discover.")
        return {
            "statusCode": 200,
            "body": f"Coleta de referência de '{content_type}' finalizada com sucesso.",
        }

    # ===========================================================================
    # COLETA DE DISCOVER (Lista de Filmes/Séries Populares, ano a ano)
    # ===========================================================================
    # O TMDB pagina os resultados (máx. 20 por página, até 500 páginas).
    # Para cada ano, coletamos até 100 páginas = até 2.000 títulos por ano.
    # Cada página é salva como um arquivo JSON separado no S3 SOR.
    # Após salvar, disparamos o Glue ETL para processar aquele ano.
    logger.info(
        f"Iniciando coleta do TMDB ({content_type}) de {start_year} até {end_year}..."
    )

    for year in range(start_year, end_year + 1):
        logger.info(f"=== Ano: {year} | Tipo: {content_type} ===")

        # Coleta todas as páginas disponíveis do TMDB para este ano
        collect_discover_data(
            api_key=api_key,
            s3_client=s3_client,
            bucket=S3_BUCKET_SOR,
            content_type=content_type,
            folder=f"tmdb/discover/{content_type}",
            year=year,
        )

        # Dispara o Glue ETL para processar os dados do ano recém-coletado.
        # "end_year" é repassado para que o Glue Details saiba quando é a
        # última iteração (tv + end_year = hora de disparar o Glue AGG).
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
