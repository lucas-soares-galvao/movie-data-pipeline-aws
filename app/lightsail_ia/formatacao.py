"""formatacao.py — Formatação determinística de registros do Athena para cards do FilmBot."""

_MONTHS = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def _format_type(media_type: str) -> str:
    """Converte media_type da API ('movie'/'tv') para português ('filme'/'série')."""
    return "filme" if media_type == "movie" else "série" if media_type == "tv" else media_type


def _format_genres(genre_names: str | None) -> list[str]:
    """Converte string de gêneros separados por vírgula em lista."""
    if not genre_names:
        return []
    return [g.strip() for g in genre_names.split(",") if g.strip()]


def _format_title_duration(record: dict) -> str | None:
    """Formata duração: '2h 15min' para filmes, '3 temporadas · 24 eps' para séries."""
    if record.get("media_type") == "movie":
        raw = record.get("runtime_minutes")
        if not raw:
            return None
        minutes = int(raw)
        hours, remainder = divmod(minutes, 60)
        return f"{hours}h {remainder}min" if hours else f"{remainder}min"

    parts = []
    seasons = record.get("number_of_seasons")
    episodes = record.get("number_of_episodes")
    ep_runtime = record.get("episode_runtime_minutes")
    if seasons:
        n = int(seasons)
        parts.append(f"{n} temporada{'s' if n != 1 else ''}")
    if episodes:
        parts.append(f"{int(episodes)} eps")
    if ep_runtime:
        parts.append(f"~{int(ep_runtime)} min/ep")
    return " · ".join(parts) if parts else None


def _format_release_date(air_date: str | None) -> str | None:
    """Converte data ISO 'YYYY-MM-DD' para 'Mês de Ano' em português."""
    if not air_date or len(air_date) < 7:
        return None
    try:
        parts = air_date.split("-")
        year = int(parts[0])
        month = int(parts[1])
        return f"{_MONTHS[month]} de {year}"
    except (ValueError, KeyError, IndexError):
        return None


def _format_theater_end_date(theater_end_date: str | None, in_theaters: bool) -> str | None:
    """Converte data ISO para 'DD/MM/AAAA' se o título estiver em cartaz."""
    if not in_theaters or not theater_end_date:
        return None
    try:
        year, month, day = theater_end_date.split("-")
        return f"{day}/{month}/{year}"
    except ValueError:
        return None


def _format_rating(vote_average: object) -> float | None:
    """Converte nota (str, int ou float) para float, retornando None se inválida."""
    if vote_average is None or vote_average == "":
        return None
    try:
        return float(vote_average)
    except (ValueError, TypeError):
        return None


def format_record(record: dict) -> dict:
    """Transforma um registro cru do Athena em dict formatado para o card do app."""
    in_theaters = str(record.get("in_theaters", "")).lower() == "true"
    return {
        "title": record.get("title", ""),
        "type": _format_type(record.get("media_type", "")),
        "year": int(record["year"]) if record.get("year") else None,
        "genres": _format_genres(record.get("genre_names")),
        "overview": record.get("overview") or "",
        "rating": _format_rating(record.get("vote_average")),
        "poster_url": record.get("poster_url") or None,
        "backdrop_url": record.get("backdrop_url") or None,
        "duration": _format_title_duration(record),
        "release_date": _format_release_date(record.get("air_date")),
        "streaming_providers": record.get("streaming_providers") or None,
        "in_theaters": in_theaters,
        "theater_end_date": _format_theater_end_date(
            record.get("theater_end_date"), in_theaters
        ),
        "tagline": record.get("tagline") or None,
        "cast": record.get("actor_names") or None,
        "director": record.get("director") or None,
        "writers": record.get("screenplay") or None,
        "composer": record.get("music_composer") or None,
        "keywords": record.get("keywords_pt") or None,
        "certification": record.get("certification") or None,
        "trailer_url": record.get("trailer_url") or None,
        "collection": record.get("collection_name") or None,
        "production_companies": record.get("production_companies") or None,
        "production_countries": record.get("production_countries") or None,
        "producer": record.get("producer") or None,
        "cinematographer": record.get("cinematographer") or None,
        "editor": record.get("editor") or None,
        "networks": record.get("networks") or None,
        "creators": record.get("created_by") or None,
        "rent_buy_providers": record.get("rent_buy_providers") or None,
        "recommended": record.get("recommended_titles") or None,
        "similar": record.get("similar_titles") or None,
        "alternative_titles": record.get("alternative_titles") or None,
    }
