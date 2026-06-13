"""utils.py — Funções auxiliares do job Glue Details."""

import json
import logging
import random
import sys
import threading
import time
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import awswrangler as wr
import boto3
import pandas as pd
import requests
from awsglue.utils import getResolvedOptions
from deep_translator import GoogleTranslator
from requests.exceptions import ConnectionError, Timeout

logger = logging.getLogger()

TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Códigos HTTP que indicam problema temporário no servidor — vale tentar de novo.
# 429 = Too Many Requests (enviamos rápido demais — a TMDB pede para esperar)
# 500 = Internal Server Error (problema no servidor da TMDB — pode ser passageiro)
# 502 = Bad Gateway (servidor intermediário com problema temporário)
# 503 = Service Unavailable (TMDB temporariamente fora do ar)
# 504 = Gateway Timeout (servidor demorou demais para responder)
# Para esses erros vale tentar novamente. Para outros (401 Unauthorized, 404 Not Found)
# não adianta tentar de novo — é um erro permanente.
_TMDB_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _tmdb_get(url: str, params: dict, max_retries: int = 3) -> dict:
    """
    GET na API do TMDB com retry e backoff exponencial em erros transientes.

    Args:
        url:         URL completa do endpoint da API do TMDB.
        params:      Parâmetros de query string.
        max_retries: Número máximo de tentativas antes de desistir.

    Returns:
        Dicionário Python com a resposta JSON da API.

    Raises:
        HTTPError: Se o servidor responder com erro não-transiente ou tentativas esgotadas.
        ConnectionError / Timeout: Se não conseguir conectar após max_retries tentativas.
    """
    for attempt in range(max_retries):
        is_last_attempt = attempt == max_retries - 1
        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code in _TMDB_TRANSIENT_STATUS:
                if is_last_attempt:
                    logger.error(
                        f"HTTP {response.status_code} após {max_retries} tentativas. "
                        f"Todas as tentativas esgotadas para {url}."
                    )
                    response.raise_for_status()
                # Para 429, o TMDB informa no header "Retry-After" quanto tempo esperar.
                # Para os demais erros transientes, usa backoff exponencial (1s → 2s → 4s).
                # random.uniform(0, 1) adiciona um "jitter" (variação aleatória) de até 1s
                # para evitar que múltiplos workers acordem exatamente ao mesmo tempo.
                if response.status_code == 429 and "Retry-After" in response.headers:
                    wait = int(response.headers["Retry-After"]) + random.uniform(0, 1)
                else:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    f"HTTP {response.status_code} (tentativa {attempt + 1}/{max_retries}). "
                    f"Aguardando {wait:.1f}s..."
                )
                time.sleep(wait)
                continue
            # Se chegou aqui, o status não é transiente — raise_for_status() lança exceção
            # para qualquer outro erro 4xx/5xx (ex: 401, 404). Para 200 OK retorna normalmente.
            response.raise_for_status()
            return response.json()
        except (ConnectionError, Timeout) as e:
            if is_last_attempt:
                logger.error(
                    f"Erro de conexão após {max_retries} tentativas: {e}. "
                    f"Todas as tentativas esgotadas para {url}."
                )
                raise
            wait = (2 ** attempt) + random.uniform(0, 1)  # backoff exponencial com jitter
            logger.warning(
                f"Erro de conexão (tentativa {attempt + 1}/{max_retries}): {e}. "
                f"Aguardando {wait:.1f}s..."
            )
            time.sleep(wait)


def get_resolved_option(args: list) -> Dict[str, Any]:
    """Wrapper de getResolvedOptions — converte lista de nomes em dicionário nome→valor."""
    return getResolvedOptions(sys.argv, args)


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos obrigatórios do job Glue Details.

    Returns:
        Dicionário com todos os argumentos resolvidos.
    """
    required_args = [
        "S3_BUCKET_SOT",
        "S3_BUCKET_TEMP",
        "DATABASE",
        "TABLE_DISCOVER_MOVIE",
        "TABLE_DISCOVER_TV",
        "TABLE_DETAILS_MOVIE",
        "TABLE_DETAILS_TV",
        "TABLE_WATCH_PROVIDERS_MOVIE",
        "TABLE_WATCH_PROVIDERS_TV",
        "TMDB_SECRET_ARN",
        "GLUE_AGG_JOB_NAME",
        "GLUE_DATA_QUALITY_JOB_NAME",
        "MEDIA_TYPE",
        "YEAR",
        "END_YEAR",
    ]
    return get_resolved_option(required_args)


def get_tmdb_api_key(secret_arn: str) -> str:
    """
    Busca a chave de API do TMDB no Secrets Manager.

    Formato do segredo: {"tmdb_api_key": "sua-chave-aqui"}

    Args:
        secret_arn: ARN do segredo cadastrado no Secrets Manager.

    Returns:
        A chave de API do TMDB como string.
    """
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])
    return secret["tmdb_api_key"]


def fetch_ids_from_sot(
    database: str,
    table_discover: str,
    s3_bucket_temp: str,
    year: str,
) -> List[int]:
    """
    Busca IDs distintos da tabela de discover no SOT via Athena, filtrados pelo ano.

    Usa o SOT (não o SOR) porque os IDs já foram deduplicados pelo Glue ETL.

    Args:
        database:       Nome do banco de dados no Glue Catalog.
        table_discover: Nome da tabela de discover (movie ou tv).
        s3_bucket_temp: Bucket S3 para os resultados temporários do Athena.
        year:           Ano a processar (string, ex: "2025").

    Returns:
        Lista de IDs inteiros únicos.
    """
    s3_output = f"s3://{s3_bucket_temp}/athena/glue_details/"
    # DISTINCT evita buscar detalhes do mesmo ID mais de uma vez
    # WHERE year filtra apenas a partição do ano atual (não processa anos passados novamente)
    query = f"SELECT DISTINCT id FROM {database}.{table_discover} WHERE year = '{year}'"

    logger.info(f"Buscando IDs em '{table_discover}' para year={year}...")
    df = wr.athena.read_sql_query(
        sql=query,
        database=database,
        s3_output=s3_output,
        ctas_approach=False,  # False = query direta (mais simples, sem criar tabela temporária no S3)
    )

    ids = df["id"].astype(int).tolist()
    logger.info(f"IDs encontrados: {len(ids)}.")
    return ids


def fetch_existing_ids_from_details(
    database: str,
    table_details: str,
    s3_bucket_temp: str,
    year: str,
) -> List[int]:
    """
    Retorna IDs já presentes na tabela de detalhes para o ano informado.

    Usado para calcular o delta: apenas IDs ausentes precisam ser buscados na API.
    Retorna lista vazia se a tabela não existir ainda (primeira execução).

    Args:
        database:       Nome do banco de dados no Glue Catalog.
        table_details:  Nome da tabela de detalhes (movie ou tv).
        s3_bucket_temp: Bucket S3 para resultados temporários do Athena.
        year:           Ano a verificar.

    Returns:
        Lista de IDs inteiros já processados.
    """
    s3_output = f"s3://{s3_bucket_temp}/athena/glue_details/"
    # Só considera "existente" quem foi processado no mês atual.
    # IDs de meses anteriores (ou sem data) são stale e voltam para re-fetch no dia 1.
    query = (
        f"SELECT DISTINCT id FROM {database}.{table_details} "
        f"WHERE year = '{year}' "
        f"AND dt_processamento >= date_trunc('month', current_date)"
    )

    logger.info(f"Verificando IDs já processados em '{table_details}' para year={year}...")
    try:
        df = wr.athena.read_sql_query(
            sql=query,
            database=database,
            s3_output=s3_output,
            ctas_approach=False,
        )
        ids = df["id"].astype(int).tolist()
        logger.info(f"IDs já em details (mês atual): {len(ids)}.")
        return ids
    except Exception as exc:
        logger.warning(
            f"Não foi possível consultar '{table_details}' "
            f"(tabela pode não existir ainda): {exc}"
        )
        return []


def fetch_ids_stale_watch_providers(
    database: str,
    table_discover: str,
    table_watch_providers: str,
    s3_bucket_temp: str,
    year: str,
) -> List[int]:
    """
    Retorna IDs do discover que precisam de atualização de watch providers.

    Inclui: sem registro, com dt_atualizacao nulo (migração) ou desatualizado antes do mês atual.

    Args:
        database:              Nome do banco de dados no Glue Catalog.
        table_discover:        Nome da tabela de discover.
        table_watch_providers: Nome da tabela de watch providers.
        s3_bucket_temp:        Bucket S3 para resultados temporários do Athena.
        year:                  Ano a verificar.

    Returns:
        Lista de IDs inteiros a atualizar.
    """
    s3_output = f"s3://{s3_bucket_temp}/athena/glue_details/"
    query = f"""
        SELECT DISTINCT d.id
        FROM {database}.{table_discover} d
        LEFT JOIN {database}.{table_watch_providers} wp
            ON d.id = wp.id AND wp.year = '{year}'
        WHERE d.year = '{year}'
          AND (
              wp.id IS NULL
              OR wp.dt_atualizacao IS NULL
              OR wp.dt_atualizacao < date_trunc('month', current_date)
          )
    """

    logger.info(
        f"Identificando IDs com watch providers ausentes/desatualizados "
        f"em '{table_watch_providers}' para year={year}..."
    )
    try:
        df = wr.athena.read_sql_query(
            sql=query,
            database=database,
            s3_output=s3_output,
            ctas_approach=False,
        )
        ids = df["id"].astype(int).tolist()
        logger.info(f"IDs para atualizar watch providers: {len(ids)}.")
        return ids
    except Exception as exc:
        logger.warning(f"Erro ao consultar watch providers desatualizados: {exc}")
        return []


def fetch_tmdb_details(api_key: str, content_type: str, item_id: int) -> dict:
    """
    Busca os detalhes de um filme ou série pelo ID na API do TMDB.

    Args:
        api_key:      Chave de API do TMDB.
        content_type: "movie" ou "tv".
        item_id:      ID do filme ou série no TMDB.

    Returns:
        Dicionário com os campos retornados pela API.
    """
    endpoint = "movie" if content_type == "movie" else "tv"
    url = f"{TMDB_BASE_URL}/{endpoint}/{item_id}"
    params = {"api_key": api_key, "language": "en-US"}

    return _tmdb_get(url, params)


_TMDB_MAX_WORKERS = 20      # ~20 req/s concorrentes — bem abaixo do rate limit de ~40 req/s do TMDB
_TRANSLATE_MAX_WORKERS = 10  # traduções EN→PT paralelas via Google Translate


def _parse_detail(detalhe: dict, content_type: str) -> Optional[dict]:
    """Extrai os campos relevantes da resposta de /movie/{id} ou /tv/{id}."""
    if content_type == "movie":
        release_date = detalhe.get("release_date") or ""
        # Extrai o ano dos primeiros 4 caracteres da data no formato "YYYY-MM-DD"
        year = release_date[:4] if release_date else None
        return {
            "id":                detalhe.get("id"),
            "runtime":           detalhe.get("runtime"),
            "title_en":          detalhe.get("title"),
            "overview_en":       detalhe.get("overview"),
            "poster_path_en":    detalhe.get("poster_path"),   # "/abc123.jpg" (sem URL base)
            "backdrop_path_en":  detalhe.get("backdrop_path"),
            "original_language": detalhe.get("original_language"),  # usado para filtrar tradução
            "dt_processamento":  date.today(),
            "year":              year,                               # usado como partição no S3
        }
    else:  # tv
        first_air_date = detalhe.get("first_air_date") or ""
        year = first_air_date[:4] if first_air_date else None
        return {
            "id":                 detalhe.get("id"),
            "number_of_seasons":  detalhe.get("number_of_seasons"),
            "number_of_episodes": detalhe.get("number_of_episodes"),
            # episode_run_time é uma lista (pode ter mais de um valor para séries com
            # episódios de duração variável). Tipicamente tem um único elemento.
            "episode_run_time":   detalhe.get("episode_run_time", []),
            "title_en":           detalhe.get("name"),  # séries usam "name", não "title"
            "overview_en":        detalhe.get("overview"),
            "poster_path_en":     detalhe.get("poster_path"),
            "backdrop_path_en":   detalhe.get("backdrop_path"),
            "original_language":  detalhe.get("original_language"),
            "dt_processamento":   date.today(),
            "year":               year,
        }


def _adicionar_traducoes_pt(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adiciona colunas title_pt e overview_pt ao DataFrame de detalhes.

    Traduz apenas registros com original_language='en' (EN→PT via Google Translate).
    Para outros idiomas, title_pt e overview_pt ficam nulos — o glue_agg usará o título
    original do discover nesses casos.
    """
    df["title_pt"] = None
    df["overview_pt"] = None

    mask = df["original_language"] == "en"
    if not mask.any():
        return df

    def _translate(texto: str) -> str:
        if not texto:
            return ""
        try:
            return GoogleTranslator(source="en", target="pt").translate(texto)
        except Exception as exc:
            logger.warning(f"Falha ao traduzir: {exc}. Mantendo original.")
            return texto

    total = mask.sum()
    logger.info(f"Traduzindo {total} registros com original_language='en' ({_TRANSLATE_MAX_WORKERS} workers).")

    for col_en, col_pt in (("title_en", "title_pt"), ("overview_en", "overview_pt")):
        valores = df.loc[mask, col_en].fillna("").tolist()
        with ThreadPoolExecutor(max_workers=_TRANSLATE_MAX_WORKERS) as executor:
            traduzidos = list(executor.map(_translate, valores))
        df.loc[mask, col_pt] = traduzidos

    return df


def collect_and_write_details(
    api_key: str,
    ids: List[int],
    content_type: str,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
) -> None:
    """
    Busca detalhes de cada ID em paralelo e grava no SOT como Parquet particionado por year.

    IDs que falharem na API são descartados silenciosamente.

    Args:
        api_key:       Chave de API do TMDB.
        ids:           Lista de IDs a consultar.
        content_type:  "movie" ou "tv".
        s3_bucket_sot: Nome do bucket SOT de destino.
        table_name:    Nome da tabela no Glue Catalog.
        database:      Nome do banco de dados no Glue Catalog.
    """
    registros = []
    lock = threading.Lock()  # evita race condition ao acumular registros entre threads

    def fetch_and_parse(item_id: int) -> None:
        try:
            detalhe = fetch_tmdb_details(api_key, content_type, item_id)
            registro = _parse_detail(detalhe, content_type)
            with lock:
                registros.append(registro)
        except requests.RequestException as exc:
            # Se um ID falhar (ex: ID deletado da TMDB), apenas registra o aviso
            # e continua para os próximos IDs sem interromper o job inteiro
            logger.warning(f"Erro ao buscar detalhes do ID {item_id}: {exc}")

    logger.info(f"Buscando detalhes de {len(ids)} IDs ({content_type}) com {_TMDB_MAX_WORKERS} workers...")
    with ThreadPoolExecutor(max_workers=_TMDB_MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_parse, item_id): item_id for item_id in ids}
        for future in as_completed(futures):
            future.result()  # propaga exceções inesperadas (além de RequestException)

    if not registros:
        logger.warning(f"Nenhum detalhe coletado para '{content_type}'. Nada gravado.")
        return

    df = pd.DataFrame(registros)
    # Remove linhas sem year — registros sem data de lançamento não podem ser particionados
    # e causariam erro ao tentar criar a pasta "year=None/" no S3
    df = df.dropna(subset=["year"])

    df = _adicionar_traducoes_pt(df)
    # original_language foi usado apenas para filtrar a tradução; já existe em tb_discover
    df = df.drop(columns=["original_language"])

    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"

    # Merge: lê registros existentes de cada partição year, remove os IDs que serão
    # re-escritos e concatena com os novos dados — evita duplicatas ao usar overwrite_partitions.
    df_existing = pd.DataFrame()
    for yr in df["year"].dropna().unique().tolist():
        try:
            df_read = wr.s3.read_parquet(
                path=s3_path,
                dataset=True,
                partition_filter=lambda x: x["year"] == str(yr),
            )
            if not df_read.empty:
                df_existing = pd.concat(
                    [df_existing, df_read[~df_read["id"].isin(df["id"])]],
                    ignore_index=True,
                )
                logger.info(f"Mantendo {len(df_read[~df_read['id'].isin(df['id'])])} registros existentes para year={yr}.")
        except Exception as exc:
            logger.info(f"Sem dados existentes para year={yr} em '{table_name}': {exc}")

    if not df_existing.empty:
        df = pd.concat([df_existing, df], ignore_index=True)

    logger.info(
        f"Gravando {len(df)} registros de detalhes em {s3_path} | "
        f"particao=[year] | mode=overwrite_partitions"
    )
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' gravada com sucesso no SOT.")


def fetch_tmdb_watch_providers(api_key: str, content_type: str, item_id: int) -> dict:
    """
    Busca provedores de streaming para um título na região BR.

    Args:
        api_key:      Chave de API do TMDB.
        content_type: "movie" ou "tv".
        item_id:      ID do filme ou série no TMDB.

    Returns:
        Dicionário com chaves "flatrate", "rent", "buy", ou vazio se BR não disponível.
    """
    endpoint = "movie" if content_type == "movie" else "tv"
    url = f"{TMDB_BASE_URL}/{endpoint}/{item_id}/watch/providers"
    params = {"api_key": api_key}

    results = _tmdb_get(url, params).get("results", {})
    return results.get("BR", {})


def _parse_watch_providers(br_data: dict, item_id: int, year: Optional[str]) -> List[dict]:
    """
    Converte a seção BR de watch/providers em registros normalizados (um por provedor × tipo).

    Tipos: flatrate (assinatura), rent (aluguel), buy (compra).

    Args:
        br_data: Seção "BR" da resposta da API (pode ser vazio se BR não disponível).
        item_id: ID do título no TMDB.
        year:    Ano de partição.

    Returns:
        Lista de registros com: id, provider_type, provider_id, provider_name, logo_path, year.
    """
    records = []
    for provider_type in ("flatrate", "rent", "buy"):
        for p in br_data.get(provider_type, []):
            name = p.get("provider_name")
            if not name:
                continue  # ignora provedores sem nome (dados incompletos da API)
            records.append({
                "id":             item_id,
                "provider_type":  provider_type,
                "provider_id":    p.get("provider_id"),
                "provider_name":  name,
                "logo_path":      p.get("logo_path"),
                "dt_atualizacao": date.today(),
                "year":           year,
            })
    return records


def collect_and_write_watch_providers(
    api_key: str,
    ids: List[int],
    content_type: str,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
    year: str,
) -> None:
    """
    Busca provedores de streaming BR para cada ID em paralelo e grava no SOT.

    Args:
        api_key:       Chave de API do TMDB.
        ids:           Lista de IDs a consultar.
        content_type:  "movie" ou "tv".
        s3_bucket_sot: Nome do bucket SOT de destino.
        table_name:    Nome da tabela no Glue Catalog.
        database:      Nome do banco de dados no Glue Catalog.
        year:          Ano de partição.
    """
    registros: List[dict] = []
    lock = threading.Lock()

    def fetch_and_parse(item_id: int) -> None:
        try:
            br_data = fetch_tmdb_watch_providers(api_key, content_type, item_id)
            parsed = _parse_watch_providers(br_data, item_id, year)
            if parsed:
                with lock:
                    registros.extend(parsed)
        except requests.RequestException as exc:
            logger.warning(f"Erro ao buscar watch providers do ID {item_id}: {exc}")

    logger.info(
        f"Buscando watch providers BR de {len(ids)} IDs ({content_type}) "
        f"com {_TMDB_MAX_WORKERS} workers..."
    )
    with ThreadPoolExecutor(max_workers=_TMDB_MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_parse, item_id): item_id for item_id in ids}
        for future in as_completed(futures):
            future.result()

    if not registros:
        logger.warning(f"Nenhum watch provider BR coletado para '{content_type}'. Nada gravado.")
        return

    df = pd.DataFrame(registros)
    df = df.dropna(subset=["year"])

    # Merge: lê registros existentes do ano, remove os IDs que serão atualizados,
    # e concatena com os novos dados para preservar IDs não-stale.
    df_existing = pd.DataFrame()
    try:
        df_read = wr.s3.read_parquet(
            path=f"s3://{s3_bucket_sot}/tmdb/{table_name}/",
            dataset=True,
            partition_filter=lambda x: x["year"] == year,
        )
        if not df_read.empty:
            df_existing = df_read[~df_read["id"].isin(ids)]
            logger.info(f"Mantendo {len(df_existing)} registros não-stale de '{table_name}'.")
    except Exception as exc:
        logger.info(f"Sem dados existentes para year={year} em '{table_name}': {exc}")

    if not df_existing.empty:
        df = pd.concat([df_existing, df], ignore_index=True)

    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"
    logger.info(
        f"Gravando {len(df)} registros de watch providers em {s3_path} | "
        f"particao=[year] | mode=overwrite_partitions"
    )
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' gravada com sucesso no SOT.")


def trigger_data_quality(
    dq_job_name: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
) -> str:
    """
    Dispara o job Glue Data Quality sem aguardar.

    Args:
        dq_job_name: Nome do job Glue Data Quality cadastrado na AWS.
        table_name:  Nome da tabela a validar.
        database:    Nome do banco de dados no Glue Catalog.
        year:        Ano da partição.

    Returns:
        JobRunId da execução.
    """
    arguments = {
        "--TABLE_NAME": table_name,
        "--DATABASE": database,
    }
    if year is not None:
        arguments["--YEAR"] = year

    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(
        JobName=dq_job_name,
        Arguments=arguments,
    )
    run_id = response["JobRunId"]
    logger.info(
        f"Job Data Quality '{dq_job_name}' iniciado para tabela '{table_name}'. RunId: {run_id}"
    )
    return run_id


def trigger_agg(agg_job_name: str) -> str:
    """
    Dispara o job Glue AGG.

    Args:
        agg_job_name: Nome do job Glue AGG cadastrado na AWS.

    Returns:
        JobRunId da execução.
    """
    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(JobName=agg_job_name)
    run_id = response["JobRunId"]
    logger.info(f"Job AGG '{agg_job_name}' iniciado. RunId: {run_id}")
    return run_id
