"""
utils.py — Funções auxiliares da Lambda.

Aqui ficam todas as funções que fazem tarefas específicas:
  - buscar a chave de API no Secrets Manager
  - chamar a API do TMDB
  - salvar arquivos no S3
  - acionar o job Glue ETL

Separar essas funções do main.py torna o código mais fácil de ler,
testar e reutilizar.
"""

import json
import logging

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_PAGES = 100  # Máximo de páginas por ano (TMDB suporta até 500)


# ---------------------------------------------------------------------------
# Secrets Manager
# ---------------------------------------------------------------------------


def get_tmdb_api_key(secret_arn: str) -> str:
    """
    Busca a chave de API do TMDB armazenada no AWS Secrets Manager.

    O segredo deve estar no formato JSON: {"api_key": "sua-chave-aqui"}

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
# TMDB API
# ---------------------------------------------------------------------------



def fetch_tmdb_data(api_key: str, content_type: str, year: int, page: int) -> dict:
    """
    Busca uma página de dados de filmes ou séries na API do TMDB.

    Endpoints utilizados:
      - Filmes: https://api.themoviedb.org/3/discover/movie
      - Séries:  https://api.themoviedb.org/3/discover/tv

    Parâmetros fixos em todas as chamadas:
      - language    : pt-BR  (resultados em português)
      - sort_by     : popularity.desc (mais populares primeiro)
      - page        : número da página solicitada

    Args:
        api_key:      Chave de API do TMDB.
        content_type: "movie" para filmes ou "tv" para séries.
        year:         Ano de lançamento/estreia do conteúdo.
        page:         Número da página (1 a 500 — limite do TMDB).

    Returns:
        Dicionário com os dados retornados pela API, incluindo:
          - page          : página atual
          - results       : lista de filmes/séries
          - total_pages   : total de páginas disponíveis
          - total_results : total de registros disponíveis
    """
    if content_type == "movie":
        url = "https://api.themoviedb.org/3/discover/movie"
    else:
        url = "https://api.themoviedb.org/3/discover/tv"

    params = {
        "api_key": api_key,
        "language": "pt-BR",
        "sort_by": "popularity.desc",
        "page": page,
    }

    # Adiciona o filtro de ano com o nome correto para cada tipo de conteúdo
    if content_type == "movie":
        params["primary_release_year"] = year
    else:
        params["first_air_date_year"] = year

    response = requests.get(url, params=params, timeout=30)
    # Lança uma exceção automática se a API retornar erro (4xx, 5xx)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------


def save_to_s3(s3_client, bucket: str, data: dict, s3_key: str) -> None:
    """
    Salva um dicionário Python como arquivo JSON no S3.

    Args:
        s3_client: Cliente boto3 já instanciado para o S3.
        bucket:    Nome do bucket de destino.
        data:      Dados a serem salvos (dicionário Python).
        s3_key:    Caminho do arquivo dentro do bucket.
                   Exemplo: "filmes/ano=2023/mes=05/pagina_001.json"
    """
    # ensure_ascii=False mantém acentos e caracteres especiais do pt-BR
    body = json.dumps(data, ensure_ascii=False)

    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(f"Arquivo salvo: s3://{bucket}/{s3_key}")


# ---------------------------------------------------------------------------
# Glue ETL
# ---------------------------------------------------------------------------


def trigger_glue_job(
    glue_client,
    job_name: str,
    glue_catalog_args: dict,
    table_type: str,
    table_name: str,
    year: int = None,
    tmdb_secret_arn: str = None,
) -> str:
    """
    Inicia o job Glue ETL para processar dados do TMDB.

    Pode ser chamado de três formas:
      - table_type="genre":         processa apenas as tabelas de gênero.
      - table_type="configuration": processa apenas as tabelas de configuração.
      - table_type="discover"+year: processa os dados de discover de um ano específico.

    Args:
        glue_client:       Cliente boto3 já instanciado para o Glue.
        job_name:          Nome do job Glue cadastrado na AWS.
        glue_catalog_args: Dicionário com argumentos base (MEDIA_TYPE, DATABASE).
        table_type:        Tipo de tabela a processar: "genre", "configuration" ou "discover".
        table_name:        Nome da tabela no Glue Catalog a ser processada nesta chamada.
        year:              Ano dos dados a processar. Usado apenas para discover.

    Returns:
        O ID de execução do job (JobRunId), útil para acompanhamento.
    """
    # Constrói os argumentos do Glue: o prefixo "--" é obrigatório
    arguments = {
        "--TABLE_TYPE": table_type,
        "--TABLE_NAME": table_name,
    }

    # O ano e o ARN do secret só são informados quando o job processa tabelas de discover
    if year is not None:
        arguments["--YEAR"] = str(year)
        if tmdb_secret_arn:
            arguments["--TMDB_SECRET_ARN"] = tmdb_secret_arn

    for key, value in glue_catalog_args.items():
        arguments[f"--{key.upper()}"] = str(value)

    response = glue_client.start_job_run(
        JobName=job_name,
        Arguments=arguments,
    )
    run_id = response["JobRunId"]
    if year is not None:
        logger.info(
            f"Job Glue '{job_name}' iniciado para '{table_type}' do ano {year}. RunId: {run_id}"
        )
    else:
        logger.info(
            f"Job Glue '{job_name}' iniciado para '{table_type}'. RunId: {run_id}"
        )
    return run_id


# ---------------------------------------------------------------------------
# TMDB API — dados de referência (sem paginação)
# ---------------------------------------------------------------------------


def fetch_tmdb_reference(api_key: str, endpoint: str, params: dict = None) -> dict:
    """
    Busca dados de referência do TMDB — endpoints que retornam uma lista
    simples, sem paginação (países, idiomas, gêneros, etc.).

    Args:
        api_key:  Chave de API do TMDB.
        endpoint: Caminho do endpoint a partir da base, ex.: "/configuration/countries".
        params:   Parâmetros extras opcionais, ex.: {"language": "pt-BR"}.

    Returns:
        Dicionário com os dados retornados pela API.
    """
    base_url = "https://api.themoviedb.org/3"
    url = f"{base_url}{endpoint}"

    query = {"api_key": api_key}
    if params:  # adiciona parâmetros extras apenas se forem informados
        query.update(params)

    response = requests.get(url, params=query, timeout=30)
    response.raise_for_status()
    return response.json()


def collect_genre_data(api_key: str, s3_client, bucket: str, content_type: str) -> None:
    """
    Coleta a lista de gêneros do TMDB para o tipo de conteúdo recebido e salva no S3.

      content_type="movie" → /genre/movie/list → tmdb/genre/movie/generos_filmes.json
      content_type="tv"    → /genre/tv/list    → tmdb/genre/tv/generos_series.json

    Args:
        api_key:      Chave de API do TMDB.
        s3_client:    Cliente boto3 do S3.
        bucket:       Nome do bucket S3 de destino.
        content_type: "movie" ou "tv".
    """
    if content_type == "movie":
        logger.info("Coletando referência: /genre/movie/list")
        data = fetch_tmdb_reference(api_key, "/genre/movie/list", {"language": "pt-BR"})
        save_to_s3(
            s3_client, bucket, data["genres"], "tmdb/genre/movie/generos_filmes.json"
        )
    else:
        logger.info("Coletando referência: /genre/tv/list")
        data = fetch_tmdb_reference(api_key, "/genre/tv/list", {"language": "pt-BR"})
        save_to_s3(
            s3_client, bucket, data["genres"], "tmdb/genre/tv/generos_series.json"
        )


def collect_configuration_data(
    api_key: str, s3_client, bucket: str, content_type: str
) -> None:
    """
    Coleta os dados de configuração do TMDB para o tipo de conteúdo recebido e salva no S3.

      content_type="movie" → /configuration/languages           → tmdb/configuration/languages/idiomas.json
      content_type="tv"    → /configuration/countries?language=pt-BR → tmdb/configuration/countries/paises.json

    Args:
        api_key:      Chave de API do TMDB.
        s3_client:    Cliente boto3 do S3.
        bucket:       Nome do bucket S3 de destino.
        content_type: "movie" ou "tv".
    """
    if content_type == "movie":
        logger.info("Coletando referência: /configuration/languages")
        data = fetch_tmdb_reference(api_key, "/configuration/languages")
        save_to_s3(s3_client, bucket, data, "tmdb/configuration/languages/idiomas.json")
    else:
        logger.info("Coletando referência: /configuration/countries")
        data = fetch_tmdb_reference(
            api_key, "/configuration/countries", {"language": "pt-BR"}
        )
        save_to_s3(s3_client, bucket, data, "tmdb/configuration/countries/paises.json")


# ---------------------------------------------------------------------------
# Coleta e salvamento por ano
# ---------------------------------------------------------------------------



def collect_discover_data(
    api_key: str, s3_client, bucket: str, content_type: str, folder: str, year: int
) -> None:
    """
    Busca todas as páginas disponíveis (até MAX_PAGES) de um tipo de conteúdo
    para um dado ano e salva cada página como um arquivo JSON separado no S3.

    A função para automaticamente se o TMDB informar que não há mais páginas,
    evitando chamadas desnecessárias à API.

    O enriquecimento com runtime/episódios é feito posteriormente pelo Glue ETL.

    Args:
        api_key:      Chave de API do TMDB.
        s3_client:    Cliente boto3 do S3.
        bucket:       Nome do bucket S3 de destino.
        content_type: "movie" (filmes) ou "tv" (séries) — parâmetro da API do TMDB.
        folder:       Nome da pasta no S3: "filmes" ou "series".
        year:         Ano de lançamento/estreia do conteúdo.
    """
    logger.info(f"Coletando {folder} do ano {year}...")

    for page in range(1, MAX_PAGES + 1):
        data = fetch_tmdb_data(api_key, content_type, year, page)

        # O TMDB informa o total de páginas disponíveis na resposta.
        # Se já passamos do limite real, não há mais dados para buscar.
        total_pages = data.get("total_pages", 0)
        if page > total_pages:
            logger.info(
                f"{folder}/{year}: {total_pages} página(s) disponível(is). Encerrando na página {page - 1}."
            )
            break

        results = data["results"]

        # Salva apenas a lista de filmes/séries, sem os metadados de paginação
        # Exemplo de caminho gerado: tmdb/discover/movie/ano=2023/pagina_001.json
        s3_key = f"{folder}/ano={year}/pagina_{page:03d}.json"
        save_to_s3(s3_client, bucket, results, s3_key)
