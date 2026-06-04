"""
main.py — Ponto de entrada da Lambda de recomendação.

Fluxo:
  1. Recebe preferências do usuário via POST (API Gateway / Lambda Function URL).
  2. Extrai filtros simples do texto (gêneros, décadas, idioma).
  3. Busca candidatos em tb_discover_unified_tmdb via Athena.
  4. Passa candidatos + preferências ao Claude para selecionar e justificar.
  5. Retorna JSON com as recomendações.

Variáveis de ambiente (definidas no Terraform):
  - ATHENA_DATABASE      : banco no Glue Catalog (ex.: "db_tmdb")
  - S3_BUCKET_TEMP       : bucket para resultados temporários do Athena
  - OPENAI_SECRET_ARN : ARN do secret com a chave OPENAI
"""

import json
import logging
import re

from src.agent import recommend
from src.athena import search_catalog

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Content-Type": "application/json",
}

# Mapa simples de palavras-chave em português → gêneros em inglês usados na tabela
_GENRE_MAP = {
    "ação": "Action",
    "aventura": "Adventure",
    "animação": "Animation",
    "comédia": "Comedy",
    "crime": "Crime",
    "documentário": "Documentary",
    "drama": "Drama",
    "família": "Family",
    "fantasia": "Fantasy",
    "terror": "Horror",
    "horror": "Horror",
    "musical": "Music",
    "mistério": "Mystery",
    "romance": "Romance",
    "romântico": "Romance",
    "ficção científica": "Science Fiction",
    "ficção": "Science Fiction",
    "sci-fi": "Science Fiction",
    "suspense": "Thriller",
    "thriller": "Thriller",
    "guerra": "War",
    "faroeste": "Western",
    "história": "History",
}


def _extract_filters(preferences: str) -> dict:
    text = preferences.lower()

    genres = [eng for pt, eng in _GENRE_MAP.items() if pt in text]
    genres = list(dict.fromkeys(genres))  # remove duplicatas mantendo ordem

    years = re.findall(r"\b(19\d{2}|20\d{2})\b", text)
    decades = re.findall(r"\b(19\d0|20[012]\d0)s?\b", text)

    year_min = year_max = None
    if years:
        year_min = year_max = int(years[0])
    elif decades:
        decade = int(decades[0])
        year_min, year_max = decade, decade + 9

    # Décadas por nome (ex.: "anos 90")
    decade_name = re.search(r"anos?\s+(19\d{2}|20\d{2}|\d{2})", text)
    if decade_name and not years:
        d = int(decade_name.group(1))
        if d < 100:
            d += 1900
        year_min, year_max = d, d + 9

    language = None
    if "japonês" in text or "anime" in text:
        language = "ja"
    elif "coreano" in text or "k-drama" in text:
        language = "ko"
    elif "francês" in text:
        language = "fr"
    elif "espanhol" in text:
        language = "es"
    elif "português" in text:
        language = "pt"

    return {
        "genres": genres or None,
        "year_min": year_min,
        "year_max": year_max,
        "language": language,
    }


def lambda_handler(event, context):
    # Preflight CORS
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    try:
        body = json.loads(event.get("body") or "{}")
        preferences = body.get("preferences", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return _error(400, "Body JSON inválido.")

    if len(preferences) < 10:
        return _error(400, "Descreva suas preferências com pelo menos 10 caracteres.")

    if len(preferences) > 500:
        return _error(400, "Preferências muito longas. Máximo: 500 caracteres.")

    logger.info(f"Preferências recebidas: {preferences!r}")
    filters = _extract_filters(preferences)
    logger.info(f"Filtros extraídos: {filters}")

    movies = search_catalog(
        genres=filters["genres"],
        year_min=filters["year_min"],
        year_max=filters["year_max"],
        language=filters["language"],
    )

    if not movies:
        return _error(404, "Nenhum filme encontrado com esses filtros. Tente ser mais genérico.")

    recommendations = recommend(preferences, movies)

    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps(
            {"movies": recommendations, "total": len(recommendations)},
            ensure_ascii=False,
        ),
    }


def _error(status: int, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps({"error": message}, ensure_ascii=False),
    }
