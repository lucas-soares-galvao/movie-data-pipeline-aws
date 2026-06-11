"""
main.py — Ponto de entrada do job Glue Details.

==============================================================================
O QUE É O GLUE DETAILS?
==============================================================================
Este job é o "enriquecedor" do pipeline: ele pega os IDs dos filmes e séries
descobertos pelo job ETL (que veio da Lambda), e busca informações extras
para cada ID diretamente na API do TMDB.

PROBLEMA QUE RESOLVE:
  A Lambda API tem um limite rígido de 900 segundos (15 minutos) de execução.
  Com milhares de filmes/séries descobertos, fazer uma chamada para cada ID
  consumiria muito mais tempo. O Glue PythonShell não tem esse limite de tempo,
  então é o lugar certo para esse trabalho de longa duração.

ANALOGIA: Imagine que a Lambda fez uma lista de nomes de filmes, mas sem detalhes.
  O Glue Details pega essa lista e, para cada nome, vai buscar as informações
  completas: duração, número de temporadas, onde assistir no streaming BR, etc.
  É como pegar um catálogo resumido e transformá-lo em um catálogo detalhado.

FLUXO COMPLETO:
  1. Lê os argumentos do job (qual ano, qual tipo — filme ou série)
  2. Busca a chave de API do TMDB (salva com segurança no Secrets Manager)
  3. Consulta o Athena: "Quais IDs existem na tabela de discover para esse ano?"
  4. Para cada ID: chama /movie/{id} ou /tv/{id} e guarda duração/temporadas
  5. Para cada ID: chama /movie/{id}/watch/providers e guarda plataformas BR
  6. Salva os detalhes como Parquet no bucket SOT
  7. Dispara o Glue Data Quality (em paralelo) para validar os dados
  8. Se for o último run do ciclo (tv + ano mais recente), dispara o Glue AGG

POR QUE SÓ ACIONAR O AGG NO ÚLTIMO RUN?
  O pipeline processa filmes E séries, e para cada um processa múltiplos anos.
  O Glue AGG faz um JOIN entre todos esses dados. Se ele rodasse cedo demais,
  o JOIN ficaria incompleto. Por isso esperamos o último run: tv + end_year.
  Nesse ponto, todos os detalhes (filmes e séries, todos os anos) já estão no SOT.

  Ordem dos runs (exemplo com anos 2022–2024):
    movie/2022 → movie/2023 → movie/2024
    tv/2022    → tv/2023    → tv/2024  ← neste, dispara o AGG
"""

import logging
import sys

from src.utils import (
    collect_and_write_details,
    collect_and_write_watch_providers,
    fetch_ids_from_sot,
    get_parameters_glue,
    get_tmdb_api_key,
    trigger_agg,
    trigger_data_quality,
)

# Configuração de logging: redireciona para stdout para que o Glue capture nos logs do job
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger()


def main() -> None:
    """Coleta detalhes da API TMDB para um media_type/ano e grava no SOT."""
    args = get_parameters_glue()

    # --- Infraestrutura (buckets, banco, segredo, jobs downstream) ---
    # Onde salvar os dados processados (SOT = Silver layer)
    s3_bucket_sot  = args["S3_BUCKET_SOT"]
    # Bucket temporário para resultados intermediários do Athena
    s3_bucket_temp = args["S3_BUCKET_TEMP"]
    # Banco de dados no Glue Catalog (ex: "db_movie_tmdb" ou "db_tv_tmdb")
    database       = args["DATABASE"]
    # ARN do segredo no Secrets Manager — onde a API key do TMDB está guardada
    secret_arn     = args["TMDB_SECRET_ARN"]
    # Nome do job Glue AGG que será acionado no final do ciclo
    agg_job_name   = args["GLUE_AGG_JOB_NAME"]
    # Nome do job Glue Data Quality para validar os dados após a escrita
    dq_job_name    = args["GLUE_DATA_QUALITY_JOB_NAME"]

    # --- Tabelas do Glue Catalog ---
    # Nomes das tabelas de origem (discover) e destino (details, watch_providers)
    # para filmes e séries separadamente
    table_discover_movie = args["TABLE_DISCOVER_MOVIE"]
    table_discover_tv    = args["TABLE_DISCOVER_TV"]
    table_details_movie  = args["TABLE_DETAILS_MOVIE"]
    table_details_tv     = args["TABLE_DETAILS_TV"]
    table_watch_providers_movie = args["TABLE_WATCH_PROVIDERS_MOVIE"]
    table_watch_providers_tv    = args["TABLE_WATCH_PROVIDERS_TV"]

    # --- Parâmetros de execução do ciclo ---
    media_type = args["MEDIA_TYPE"]   # "movie" ou "tv"
    year       = args["YEAR"]         # ano a processar (ex: "2024")
    end_year   = args["END_YEAR"]     # último ano do ciclo (usado para disparar AGG)

    # Seleciona as tabelas corretas com base no media_type atual
    # (filmes e séries têm tabelas separadas no Glue Catalog)
    table_discover        = table_discover_movie        if media_type == "movie" else table_discover_tv
    table_details         = table_details_movie         if media_type == "movie" else table_details_tv
    table_watch_providers = table_watch_providers_movie if media_type == "movie" else table_watch_providers_tv

    # Busca a chave uma única vez — evita múltiplas chamadas ao Secrets Manager durante o job.
    # A chave é reutilizada em todas as chamadas à API do TMDB neste job.
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_tmdb_api_key(secret_arn)

    # Consulta o Athena para obter os IDs já validados do SOT.
    # Usamos o SOT (e não o SOR) porque os IDs do SOT já foram deduplicados e validados
    # pelo Glue ETL. Isso evita buscar detalhes de IDs incorretos ou duplicados.
    ids = fetch_ids_from_sot(
        database=database,
        table_discover=table_discover,
        s3_bucket_temp=s3_bucket_temp,
        year=year,
    )

    # PASSO 1: Busca detalhes individuais para cada ID (duração de filmes ou temporadas de séries)
    # As chamadas são feitas em paralelo com até 20 workers para respeitar o rate limit da TMDB.
    logger.info(f"Coletando detalhes de {len(ids)} itens ({media_type}, year={year})...")
    collect_and_write_details(
        api_key=api_key,
        ids=ids,
        content_type=media_type,
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_details,
        database=database,
    )

    # PASSO 2: Busca quais serviços de streaming estão disponíveis no Brasil para cada título.
    # Ex: Netflix, Amazon Prime Video, Max, etc. (apenas flatrate — assinatura)
    logger.info(f"Coletando watch providers BR de {len(ids)} itens ({media_type}, year={year})...")
    collect_and_write_watch_providers(
        api_key=api_key,
        ids=ids,
        content_type=media_type,
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_watch_providers,
        database=database,
        year=year,
    )

    # PASSO 3: Dispara validação de qualidade (não-bloqueante) para ambas as tabelas gravadas.
    # O job de DQ roda em paralelo — não esperamos sua conclusão para continuar.
    trigger_data_quality(
        dq_job_name=dq_job_name,
        table_name=table_details,
        database=database,
        year=year,
    )

    trigger_data_quality(
        dq_job_name=dq_job_name,
        table_name=table_watch_providers,
        database=database,
        year=year,
    )

    # PASSO 4: Aciona o AGG somente no último run do ciclo (tv + ano mais recente).
    # Somente neste ponto todos os detalhes de filmes e séries estão disponíveis no SOT,
    # permitindo que o AGG faça os JOINs completos para gerar a camada SPEC.
    if media_type == "tv" and year == end_year:
        logger.info("Último run do ciclo (tv + end_year) — acionando Glue AGG...")
        trigger_agg(agg_job_name=agg_job_name)

    logger.info("Job Glue Details finalizado com sucesso!")


# Ponto de entrada: o Glue executa este arquivo como script Python standalone.
# "__name__ == '__main__'" garante que main() só seja chamado quando executado diretamente.
if __name__ == "__main__":
    main()
