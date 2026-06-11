"""
utils.py — Funções auxiliares do job Glue Details.

==============================================================================
O QUE ESTE ARQUIVO FAZ?
==============================================================================
Este arquivo contém todas as funções de suporte do job Glue Details.
É organizado em blocos temáticos:

  1. Retry com backoff exponencial (_tmdb_get):
     Garante que erros temporários de rede não derrubem o job inteiro.
     ANALOGIA: Como discar várias vezes se der sinal de ocupado, esperando
     um pouco mais a cada tentativa (1s → 2s → 4s).

  2. Leitura de argumentos do Glue (get_parameters_glue):
     O Glue passa parâmetros via linha de comando; esta função os organiza
     em um dicionário Python.

  3. Secrets Manager (get_tmdb_api_key):
     Busca a chave de API do TMDB guardada com segurança na AWS.

  4. Fetch de IDs via Athena (fetch_ids_from_sot):
     Consulta SQL no data lake para saber quais IDs precisam de detalhes.

  5. Coleta de detalhes (collect_and_write_details):
     Para cada ID, chama a API do TMDB em paralelo (ThreadPool) e grava
     os dados enriquecidos no SOT.

  6. Coleta de watch providers (collect_and_write_watch_providers):
     Para cada ID, descobre quais plataformas de streaming (Netflix, Prime, etc.)
     têm aquele título disponível no Brasil (região BR).

  7. Acionamento downstream (trigger_data_quality, trigger_agg):
     Dispara os próximos jobs do pipeline sem esperar a conclusão deles.

TECNOLOGIAS UTILIZADAS:
  - requests + ThreadPoolExecutor: chamadas HTTP paralelas à API do TMDB
  - AWS Wrangler (wr.s3.to_parquet): grava em Parquet e registra no Glue Catalog
  - wr.athena.read_sql_query: consulta SQL no data lake via Athena
  - Boto3 (secretsmanager + glue): acessa AWS de forma programática

Responsabilidades:
  - Ler argumentos do job
  - Buscar IDs distintos das tabelas de discover no SOT via Athena
  - Chamar o endpoint de detalhes da API TMDB (/movie/{id} ou /tv/{id})
  - Gravar os detalhes diretamente no SOT como Parquet particionado por year
  - Acionar o job Glue AGG ao final

Por que este job existe separado da Lambda API?
  A Lambda já opera no limite máximo de timeout (900 s). Buscar detalhes
  individuais para cada ID descoberto adicionaria milhares de chamadas extras
  à execução. O Glue PythonShell não tem essa restrição de 15 minutos.
"""

import json
import logging
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import awswrangler as wr
import boto3
import pandas as pd
import requests
from awsglue.utils import getResolvedOptions
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
    Executa GET na API do TMDB com retry automático em erros transientes.

    ANALOGIA (backoff exponencial): Como tentar ligar para alguém ocupado.
    Na 1ª tentativa falhou? Espera 1s. Na 2ª? Espera 2s. Na 3ª? Espera 4s.
    O tempo de espera dobra a cada tentativa — isso evita sobrecarregar o servidor
    que já está com problemas. O "+random" é um "jitter" para evitar que múltiplos
    workers acordem ao mesmo tempo e ataquem o servidor simultaneamente.

    Args:
        url:         URL completa do endpoint da API do TMDB.
        params:      Parâmetros de query string (api_key, language, etc.).
        max_retries: Número máximo de tentativas antes de desistir.

    Returns:
        Dicionário Python com a resposta JSON da API.

    Raises:
        HTTPError: Se o servidor responder com erro não-transiente (401, 404, etc.)
                   ou se todas as tentativas de erros transientes falharem.
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
                    # raise_for_status() lança uma exceção HTTPError para qualquer
                    # status 4xx ou 5xx, interrompendo a execução desta função.
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
                continue  # volta ao início do loop para fazer uma nova tentativa
            # Se chegou aqui, o status não é transiente (não está em _TMDB_TRANSIENT_STATUS).
            # raise_for_status() lança exceção se for qualquer outro código de erro (ex: 401, 404).
            # Se o status for 200 OK, não lança nada e retorna a resposta.
            response.raise_for_status()
            return response.json()
        except (ConnectionError, Timeout) as e:
            # Erros de rede (sem conexão, timeout de TCP) — vale tentar novamente
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


# ---------------------------------------------------------------------------
# Utilitários gerais
# ---------------------------------------------------------------------------


def get_resolved_option(args: list) -> Dict[str, Any]:
    """
    Converte a lista de argumentos do Glue em um dicionário.

    Args:
        args: Lista de nomes de argumentos a resolver (sem o prefixo "--").

    Returns:
        Dicionário mapeando nome do argumento para seu valor.
    """
    return getResolvedOptions(sys.argv, args)


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos obrigatórios do job Glue Details.

    Argumentos obrigatórios:
      S3_BUCKET_SOT                — bucket onde as tabelas de detalhe serão gravadas
      S3_BUCKET_TEMP               — bucket temporário para os resultados do Athena
      DATABASE                     — nome do banco no Glue Catalog
      TABLE_DISCOVER_MOVIE         — nome da tabela de discover de filmes no Catalog
      TABLE_DISCOVER_TV            — nome da tabela de discover de séries no Catalog
      TABLE_DETAILS_MOVIE          — nome da tabela de detalhes de filmes (destino)
      TABLE_DETAILS_TV             — nome da tabela de detalhes de séries (destino)
      TABLE_WATCH_PROVIDERS_MOVIE  — nome da tabela de watch providers de filmes (destino)
      TABLE_WATCH_PROVIDERS_TV     — nome da tabela de watch providers de séries (destino)
      TMDB_SECRET_ARN              — ARN do segredo com a API key do TMDB
      GLUE_AGG_JOB_NAME            — nome do job Glue AGG a ser acionado ao final
      MEDIA_TYPE                   — "movie" ou "tv"
      YEAR                         — ano de discover a processar
      END_YEAR                     — último ano do ciclo (usado para decidir se aciona AGG)

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


# ---------------------------------------------------------------------------
# Secrets Manager
# ---------------------------------------------------------------------------


def get_tmdb_api_key(secret_arn: str) -> str:
    """
    Busca a chave de API do TMDB armazenada no AWS Secrets Manager.

    O segredo deve estar no formato JSON: {"tmdb_api_key": "sua-chave-aqui"}

    Args:
        secret_arn: ARN do segredo cadastrado no Secrets Manager.

    Returns:
        A chave de API do TMDB como string.
    """
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])
    return secret["tmdb_api_key"]


# ---------------------------------------------------------------------------
# Leitura dos IDs do SOT via Athena
# ---------------------------------------------------------------------------


def fetch_ids_from_sot(
    database: str,
    table_discover: str,
    s3_bucket_temp: str,
    year: str,
) -> List[int]:
    """
    Busca os IDs distintos da tabela de discover no SOT via Athena,
    filtrados pelo ano exato recebido.

    POR QUE USAR O SOT E NÃO O SOR?
      - SOR (Bronze): dados brutos, pode ter duplicatas (vários arquivos JSON por página)
      - SOT (Silver): dados já processados pelo Glue ETL, deduplicados e validados
      Buscar do SOT garante que vamos enriquecer apenas IDs únicos e válidos.

    COMO FUNCIONA O ATHENA?
      O Athena é um serviço que executa queries SQL diretamente nos arquivos Parquet
      do S3, sem precisar carregar tudo em memória. O s3_output é onde os resultados
      temporários da query ficam antes de serem lidos pelo Wrangler.

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

    # Converte a coluna "id" do DataFrame para uma lista de inteiros Python
    ids = df["id"].astype(int).tolist()
    logger.info(f"IDs encontrados: {len(ids)}.")
    return ids


# ---------------------------------------------------------------------------
# TMDB API — detalhes individuais
# ---------------------------------------------------------------------------


def fetch_tmdb_details(api_key: str, content_type: str, item_id: int) -> dict:
    """
    Busca os detalhes de um filme ou série pelo ID na API do TMDB.

    Endpoints utilizados:
      - Filme: https://api.themoviedb.org/3/movie/{id}
      - Série:  https://api.themoviedb.org/3/tv/{id}

    Para filmes, o campo relevante é:
      - runtime (int): duração em minutos

    Para séries, os campos relevantes são:
      - number_of_seasons  (int): total de temporadas
      - number_of_episodes (int): total de episódios
      - episode_run_time   (list[int]): lista com duração(ões) típica(s) por episódio

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


# ---------------------------------------------------------------------------
# Coleta + gravação no SOT
# ---------------------------------------------------------------------------


_TMDB_MAX_WORKERS = 20  # ~20 req/s concorrentes — bem abaixo do limite de 40 req/s do TMDB
# Por que 20 e não mais? A API do TMDB tem um rate limit (~40 req/s).
# Com ThreadPoolExecutor(20) e timeout=30s, nunca ultrapassamos esse limite,
# evitando respostas 429 (Too Many Requests) que atrasariam o processamento.


def _parse_detail(detalhe: dict, content_type: str) -> Optional[dict]:
    """
    Extrai apenas os campos relevantes da resposta da API de detalhes.

    A API retorna dezenas de campos por título. Extraímos apenas os que
    serão usados no Glue AGG e no app Streamlit.

    Para FILMES extrai:
      - runtime: duração em minutos (ex: 162 → "2h 42min" no app)
      - title_en, overview_en: título e sinopse em inglês (para fallback e tradução)
      - poster_path_en, backdrop_path_en: caminhos de imagem (sem URL base)
      - year: extraído dos primeiros 4 chars de release_date ("2022-12-16" → "2022")

    Para SÉRIES extrai:
      - number_of_seasons, number_of_episodes: total de temporadas e episódios
      - episode_run_time: lista com duração(ões) típica(s) de episódio em minutos
      - title_en, overview_en, poster_path_en, backdrop_path_en: mesmos que filmes
      - year: extraído de first_air_date (data de estreia da série)
    """
    if content_type == "movie":
        release_date = detalhe.get("release_date") or ""
        # Extrai o ano dos primeiros 4 caracteres da data no formato "YYYY-MM-DD"
        year = release_date[:4] if release_date else None
        return {
            "id":               detalhe.get("id"),
            "runtime":          detalhe.get("runtime"),       # duração total em minutos
            "title_en":         detalhe.get("title"),         # título original em inglês
            "overview_en":      detalhe.get("overview"),      # sinopse em inglês
            "poster_path_en":   detalhe.get("poster_path"),   # "/abc123.jpg" (sem URL base)
            "backdrop_path_en": detalhe.get("backdrop_path"), # imagem de fundo
            "year":             year,                          # usado como partição no S3
        }
    else:  # tv
        first_air_date = detalhe.get("first_air_date") or ""
        year = first_air_date[:4] if first_air_date else None
        return {
            "id":                 detalhe.get("id"),
            "number_of_seasons":  detalhe.get("number_of_seasons"),  # total de temporadas
            "number_of_episodes": detalhe.get("number_of_episodes"),  # total de episódios
            # episode_run_time é uma lista (pode ter mais de um valor para séries com
            # episódios de duração variável). Tipicamente tem um único elemento.
            "episode_run_time":   detalhe.get("episode_run_time", []),
            "title_en":           detalhe.get("name"),         # séries usam "name", não "title"
            "overview_en":        detalhe.get("overview"),
            "poster_path_en":     detalhe.get("poster_path"),
            "backdrop_path_en":   detalhe.get("backdrop_path"),
            "year":               year,
        }


def collect_and_write_details(
    api_key: str,
    ids: List[int],
    content_type: str,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
) -> None:
    """
    Chama a API de detalhes para cada ID em paralelo e grava o resultado no SOT como Parquet.

    Para filmes extrai: id, runtime, year (ano de lançamento).
    Para séries extrai: id, number_of_seasons, number_of_episodes,
                        episode_run_time (array<int>), year (ano de estreia).

    O campo year é extraído da data de lançamento/estreia e usado como
    coluna de partição, mantendo o mesmo padrão das tabelas de discover.
    Quando um ID não retornar os dados esperados, o registro é ignorado
    sem interromper o processamento dos demais.

    As chamadas à API são feitas em paralelo com ThreadPoolExecutor limitado
    a _TMDB_MAX_WORKERS workers para respeitar o rate limit do TMDB (~40 req/s).

    Args:
        api_key:       Chave de API do TMDB.
        ids:           Lista de IDs a consultar.
        content_type:  "movie" ou "tv".
        s3_bucket_sot: Nome do bucket SOT de destino.
        table_name:    Nome da tabela no Glue Catalog (e prefixo no S3).
        database:      Nome do banco de dados no Glue Catalog.
    """
    # Lista compartilhada entre threads — acumulará todos os registros coletados
    registros = []
    # threading.Lock() garante acesso exclusivo à lista quando múltiplas threads
    # tentam adicionar registros ao mesmo tempo (evita corrupção de dados por
    # condição de corrida — "race condition")
    lock = threading.Lock()

    def fetch_and_parse(item_id: int) -> None:
        """Função chamada por cada thread: busca detalhes de um ID e adiciona ao resultado."""
        try:
            detalhe = fetch_tmdb_details(api_key, content_type, item_id)
            registro = _parse_detail(detalhe, content_type)
            with lock:
                # "with lock" garante que apenas uma thread por vez adiciona à lista
                registros.append(registro)
        except requests.RequestException as exc:
            # Se um ID falhar (ex: ID deletado da TMDB), apenas registra o aviso
            # e continua para os próximos IDs sem interromper o job inteiro
            logger.warning(f"Erro ao buscar detalhes do ID {item_id}: {exc}")

    logger.info(f"Buscando detalhes de {len(ids)} IDs ({content_type}) com {_TMDB_MAX_WORKERS} workers...")
    # ThreadPoolExecutor gerencia um pool de threads:
    # - Envia todas as tarefas de uma vez (submit)
    # - Executa até 20 simultaneamente
    # - as_completed() aguarda cada uma terminar e captura erros inesperados
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

    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"
    logger.info(
        f"Gravando {len(df)} registros de detalhes em {s3_path} | "
        f"particao=[year] | mode=overwrite_partitions"
    )
    # overwrite_partitions: substitui apenas as partições (anos) presentes neste DataFrame.
    # Isso permite rodar o job para o ano 2024 sem apagar os dados de 2022 e 2023.
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,             # registra/atualiza a tabela no Glue Catalog automaticamente
        partition_cols=["year"],  # cria subpastas year=2022/, year=2023/, etc.
        mode="overwrite_partitions",
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' gravada com sucesso no SOT.")


# ---------------------------------------------------------------------------
# TMDB API — watch providers por região (BR)
# ---------------------------------------------------------------------------


def fetch_tmdb_watch_providers(api_key: str, content_type: str, item_id: int) -> dict:
    """
    Busca os provedores de streaming para um filme ou série na região BR.

    Endpoints:
      - Filme: https://api.themoviedb.org/3/movie/{id}/watch/providers
      - Série:  https://api.themoviedb.org/3/tv/{id}/watch/providers

    Retorna o dicionário da região "BR" (pode ser vazio se não houver dados).

    Args:
        api_key:      Chave de API do TMDB.
        content_type: "movie" ou "tv".
        item_id:      ID do filme ou série no TMDB.

    Returns:
        Dicionário com as chaves "flatrate", "rent", "buy" (cada uma é lista de providers),
        ou dicionário vazio se BR não estiver disponível.
    """
    endpoint = "movie" if content_type == "movie" else "tv"
    url = f"{TMDB_BASE_URL}/{endpoint}/{item_id}/watch/providers"
    params = {"api_key": api_key}

    results = _tmdb_get(url, params).get("results", {})
    return results.get("BR", {})


def _parse_watch_providers(br_data: dict, item_id: int, year: Optional[str]) -> List[dict]:
    """
    Converte a seção BR da resposta de watch/providers em registros normalizados.

    A API retorna provedores agrupados por categoria:
      - flatrate: assinatura (ex: Netflix, Prime Video — você paga mensalmente)
      - rent:     aluguel (ex: paga por título por tempo limitado)
      - buy:      compra definitiva (ex: compra digital no Google Play)

    Cada provedor de cada categoria gera um registro separado na tabela,
    permitindo filtrar por tipo no Athena e no app.

    Exemplo de br_data:
      {
        "flatrate": [
          {"provider_id": 8, "provider_name": "Netflix", "logo_path": "/logo.png"}
        ],
        "rent": [
          {"provider_id": 3, "provider_name": "Google Play Movies", "logo_path": "/..."}
        ]
      }

    Args:
        br_data: Seção "BR" da resposta da API (pode ser vazio se título não disponível no BR).
        item_id: ID do título no TMDB.
        year:    Ano de partição (string).

    Returns:
        Lista de dicionários com os campos: id, provider_type, provider_id,
        provider_name, logo_path, year. Lista vazia se não há provedores no BR.
    """
    records = []
    for provider_type in ("flatrate", "rent", "buy"):
        for p in br_data.get(provider_type, []):
            name = p.get("provider_name")
            if not name:
                continue  # ignora provedores sem nome (dados incompletos da API)
            records.append({
                "id":            item_id,
                "provider_type": provider_type,  # "flatrate", "rent" ou "buy"
                "provider_id":   p.get("provider_id"),   # ID numérico da plataforma
                "provider_name": name,                    # ex: "Netflix"
                "logo_path":     p.get("logo_path"),      # caminho da logo (sem URL base)
                "year":          year,                    # partição no S3
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
    Busca os provedores de streaming BR para cada ID em paralelo e grava no SOT.

    Cada título pode gerar múltiplos registros (um por provedor × categoria).
    Títulos sem provedores BR são silenciosamente ignorados.

    Args:
        api_key:       Chave de API do TMDB.
        ids:           Lista de IDs a consultar.
        content_type:  "movie" ou "tv".
        s3_bucket_sot: Nome do bucket SOT de destino.
        table_name:    Nome da tabela no Glue Catalog.
        database:      Nome do banco de dados no Glue Catalog.
        year:          Ano de partição (string).
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


# ---------------------------------------------------------------------------
# Acionamento do Glue Data Quality
# ---------------------------------------------------------------------------


def trigger_data_quality(
    dq_job_name: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
) -> str:
    """
    Aciona o job Glue Data Quality para validar uma tabela no SOT.

    Args:
        dq_job_name: Nome do job Glue Data Quality cadastrado na AWS.
        table_name:  Nome da tabela a validar (usado para buscar o ruleset).
        database:    Nome do banco de dados no Glue Catalog.
        year:        Ano da partição.

    Returns:
        O ID de execução do job (JobRunId).
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


# ---------------------------------------------------------------------------
# Acionamento do Glue AGG
# ---------------------------------------------------------------------------


def trigger_agg(agg_job_name: str) -> str:
    """
    Aciona o job Glue AGG para unificar os dados de discover com os detalhes no SPEC.

    Chamado ao final do glue_details, quando os detalhes de filmes e séries
    já estão disponíveis no SOT e o AGG pode fazer os JOINs com segurança.

    Args:
        agg_job_name: Nome do job Glue AGG cadastrado na AWS.

    Returns:
        O ID de execução do job (JobRunId).
    """
    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(JobName=agg_job_name)
    run_id = response["JobRunId"]
    logger.info(f"Job AGG '{agg_job_name}' iniciado. RunId: {run_id}")
    return run_id
