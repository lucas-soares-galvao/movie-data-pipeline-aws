"""utils.py — Funções auxiliares da Lambda API."""

import json
import logging
from typing import Any, Optional

# noqa: F401 = diz ao linter para ignorar "import não usado" — esses imports são
# re-exportados para que main.py os importe diretamente de src.utils.
from shared_utils.api_client import get_api_secret, api_get as tmdb_get  # noqa: F401
from shared_utils.triggers import trigger_glue_job  # noqa: F401

S3Client = Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Máximo de páginas coletadas por ano da API TMDB.
# O TMDB suporta até 500 páginas, mas 100 (= 2.000 títulos) é suficiente
# para cobrir os lançamentos mais relevantes por ano sem exceder o timeout da Lambda.
MAX_PAGES = 100


def fetch_tmdb_data(api_key: str, content_type: str, year: int, page: int) -> dict:
    """
    Busca uma página do endpoint /discover do TMDB, filtrada por ano e ordenada por popularidade.

    Args:
        api_key:      Chave de autenticação da API TMDB
        content_type: "movie" para filmes, "tv" para séries
        year:         Ano de lançamento para filtrar
        page:         Página a buscar (1 a 500 — limite do TMDB)

    Returns:
        Dicionário com: page, results (lista de 20 títulos), total_pages, total_results
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

    if content_type == "movie":
        params["primary_release_year"] = year
    else:
        params["first_air_date_year"] = year

    return tmdb_get(url, params)


def save_to_s3(s3_client: S3Client, bucket: str, data: dict, s3_key: str) -> None:
    """
    Serializa um dicionário Python para JSON e salva no S3.

    Args:
        s3_client: Cliente boto3 já instanciado
        bucket:    Nome do bucket S3 destino
        data:      Dados Python a serializar (dict ou list)
        s3_key:    Caminho do arquivo no bucket
    """
    # ensure_ascii=False preserva caracteres UTF-8 como acentos (ã, é, ç)
    # sem isso, "Ação" seria salvo como "ção" — ilegível para humanos
    body = json.dumps(data, ensure_ascii=False)

    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(f"Arquivo salvo: s3://{bucket}/{s3_key}")


def fetch_tmdb_reference(api_key: str, endpoint: str, params: Optional[dict] = None) -> dict:
    """
    Busca um endpoint de referência do TMDB (retorna lista completa, sem paginação).

    Args:
        api_key:  Chave de API TMDB
        endpoint: Caminho a partir da base URL (ex: "/genre/movie/list")
        params:   Parâmetros opcionais (ex: {"language": "pt-BR"})

    Returns:
        Dicionário com o corpo da resposta JSON
    """
    base_url = "https://api.themoviedb.org/3"
    url = f"{base_url}{endpoint}"

    query = {"api_key": api_key}
    if params:
        query.update(params)

    return tmdb_get(url, query)


def collect_genre_data(api_key: str, s3_client: S3Client, bucket: str, content_type: str) -> None:
    """Coleta gêneros do TMDB e salva no S3 SOR."""
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
    api_key: str, s3_client: S3Client, bucket: str, content_type: str
) -> None:
    """Coleta idiomas (movie) ou países (tv) do TMDB e salva no S3 SOR."""
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


def collect_watch_providers_ref(
    api_key: str, s3_client: S3Client, bucket: str, content_type: str
) -> None:
    """Coleta plataformas de streaming disponíveis no Brasil e salva no S3 SOR."""
    logger.info(f"Coletando referência: /watch/providers/{content_type}")
    data = fetch_tmdb_reference(
        api_key,
        f"/watch/providers/{content_type}",
        {"watch_region": "BR"},  # Filtra apenas plataformas disponíveis no Brasil
    )

    providers = [
        {
            "provider_id":         p["provider_id"],
            "provider_name":       p["provider_name"],
            "display_priority_br": p.get("display_priorities", {}).get("BR"),
        }
        for p in data.get("results", [])
    ]

    s3_key = f"tmdb/watch_providers_ref/{content_type}/watch_providers_ref.json"
    save_to_s3(s3_client, bucket, providers, s3_key)


def collect_now_playing_data(api_key: str, s3_client: S3Client, bucket: str) -> None:
    """Coleta filmes atualmente em cartaz nos cinemas e salva no S3 SOR."""
    logger.info("Coletando filmes em cartaz: /movie/now_playing")
    url = "https://api.themoviedb.org/3/movie/now_playing"

    for page in range(1, MAX_PAGES + 1):
        data = tmdb_get(url, {"api_key": api_key, "language": "pt-BR", "region": "BR", "page": page})

        total_pages = data.get("total_pages", 0)
        if page > total_pages:
            logger.info(
                f"now_playing: {total_pages} página(s) disponível(is). Encerrando na página {page - 1}."
            )
            break

        # Embute as datas da janela teatral em cada registro para o ETL ler normalmente.
        dates = data.get("dates", {})
        for result in data["results"]:
            result["theater_start_date"] = dates.get("minimum")
            result["theater_end_date"] = dates.get("maximum")

        save_to_s3(s3_client, bucket, data["results"], f"tmdb/now_playing/movie/pagina_{page:03d}.json")


def collect_discover_data(
    api_key: str, s3_client: S3Client, bucket: str, content_type: str, folder: str, year: int
) -> None:
    """
    Coleta todas as páginas do discover para um ano, salvando um JSON por página no S3.

    Para até MAX_PAGES (100) ou total_pages, o que for menor.

    Args:
        api_key:       Chave de API TMDB
        s3_client:     Cliente boto3 S3
        bucket:        Nome do bucket SOR
        content_type:  "movie" ou "tv"
        folder:        Pasta base no S3 (ex: "tmdb/discover/movie")
        year:          Ano de lançamento/estreia para filtrar
    """
    logger.info(f"Coletando {folder} do ano {year}...")

    for page in range(1, MAX_PAGES + 1):
        data = fetch_tmdb_data(api_key, content_type, year, page)

        total_pages = data.get("total_pages", 0)
        if page > total_pages:
            logger.info(
                f"{folder}/{year}: {total_pages} página(s) disponível(is). Encerrando na página {page - 1}."
            )
            break

        s3_key = f"{folder}/ano={year}/pagina_{page:03d}.json"
        save_to_s3(s3_client, bucket, data["results"], s3_key)
