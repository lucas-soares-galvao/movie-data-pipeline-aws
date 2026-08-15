"""formatacao.py — Formatação determinística de registros do Athena para cards do FilmBot."""

from datetime import date, datetime, timezone

_MONTHS = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr",
    5: "Mai", 6: "Jun", 7: "Jul", 8: "Ago",
    9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}

# Distância (em dias, pra qualquer lado) até a qual uma data ainda ganha dia exato
# ('DD/MM') em vez de só mês/ano ('Mês de Ano') — ver _format_adaptive_date().
_ADAPTIVE_DATE_THRESHOLD_DAYS = 90


def _format_type(media_type: str) -> str:
    """Converte media_type da API ('movie'/'tv') para português ('Filme'/'Série')."""
    return "Filme" if media_type == "movie" else "Série" if media_type == "tv" else media_type


def _format_genres(genre_names: str | None) -> list[str]:
    """Converte string de gêneros separados por vírgula em lista."""
    if not genre_names:
        return []
    return [g.strip() for g in genre_names.split(",") if g.strip()]


def _format_title_duration(record: dict) -> str | None:
    """Formata duração: '1h 30min (90min)' para filmes com mais de 1h (o total em minutos
    entre parênteses só aparece quando difere do formato h/min — abaixo de 1h seria
    redundante), '45min' para filmes com menos de 1h, e '3 temp · 24 ep · ~45 min/ep' para
    séries (tudo abreviado, sem plural)."""
    if record.get("media_type") == "movie":
        raw = record.get("runtime_minutes")
        if not raw:
            return None
        minutes = int(raw)
        hours, remainder = divmod(minutes, 60)
        if hours:
            return f"{hours}h {remainder}min ({minutes}min)"
        return f"{remainder}min"

    parts = []
    seasons = record.get("number_of_seasons")
    episodes = record.get("number_of_episodes")
    ep_runtime = record.get("episode_runtime_minutes")
    if seasons:
        parts.append(f"{int(seasons)} temp")
    if episodes:
        parts.append(f"{int(episodes)} ep")
    if ep_runtime:
        parts.append(f"~{int(ep_runtime)} min/ep")
    return " · ".join(parts) if parts else None


def _format_release_date(air_date: str | None) -> str | None:
    """Converte data ISO 'YYYY-MM-DD' para 'Mês de Ano' (nome do mês abreviado) em português."""
    if not air_date or len(air_date) < 7:
        return None
    try:
        parts = air_date.split("-")
        year = int(parts[0])
        month = int(parts[1])
        return f"{_MONTHS[month]} de {year}"
    except (ValueError, KeyError, IndexError):
        return None


def _format_adaptive_date(iso_date: str | None, today: date | None = None) -> str | None:
    """Converte 'YYYY-MM-DD' pra 'DD/MM' quando a data está a até
    _ADAPTIVE_DATE_THRESHOLD_DAYS dias de hoje (futuro ou passado), ou 'Mês de Ano' (mesmo
    formato de _format_release_date) quando está mais distante. Dia exato só é
    confiável/relevante perto da data — datas bem mais distantes (ex.: lançamento anunciado
    com muita antecedência, ou próximo episódio de uma pausa longa de temporada) costumam ter
    só mês/ano confirmado no TMDB, com o dia sendo um placeholder que muda depois; usado por
    theater_end_date/next_episode_date/upcoming_date (ver format_record() abaixo e
    render_card() em componentes.py). `today` é injetável pra testes determinísticos; em
    produção usa a data real em UTC."""
    if not iso_date:
        return None
    try:
        year_str, month_str, day_str = iso_date.split("-")
        parsed = date(int(year_str), int(month_str), int(day_str))
    except ValueError:
        return None
    reference = today or datetime.now(tz=timezone.utc).date()
    if abs((parsed - reference).days) <= _ADAPTIVE_DATE_THRESHOLD_DAYS:
        return f"{day_str}/{month_str}"
    return f"{_MONTHS[parsed.month]} de {parsed.year}"


def _is_upcoming(air_date: str | None, today: date | None = None) -> bool:
    """True quando `air_date` é estritamente futuro (título ainda não lançado) — usado só pra
    decidir se o badge "Em breve" aparece (ver render_card() em componentes.py); o texto do
    badge vem de _format_adaptive_date() (mesmo campo `air_date`). `today` é injetável pra
    testes determinísticos; em produção usa a data real em UTC."""
    if not air_date:
        return False
    try:
        year, month, day = air_date.split("-")
        parsed = date(int(year), int(month), int(day))
    except ValueError:
        return False
    return parsed > (today or datetime.now(tz=timezone.utc).date())


def _format_rating(vote_average: object) -> float | None:
    """Converte nota (str, int ou float) para float, retornando None se inválida."""
    if vote_average is None or vote_average == "":
        return None
    try:
        return float(vote_average)
    except (ValueError, TypeError):
        return None


def format_record(record: dict, today: date | None = None) -> dict:
    """Transforma um registro cru do Athena em dict formatado para o card do app.

    `today` é repassado pra `_format_adaptive_date()`/`_is_upcoming()` (datas relativas ao
    "hoje") — injetável pra testes determinísticos; em produção nunca é passado, cada uma
    cai no próprio default (data real em UTC)."""
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
        "upcoming_date": (
            _format_adaptive_date(record.get("air_date"), today=today)
            if _is_upcoming(record.get("air_date"), today=today)
            else None
        ),
        "streaming_providers": record.get("streaming_providers") or None,
        "streaming_provider_logos": record.get("streaming_provider_logos") or None,
        "in_theaters": in_theaters,
        "theater_end_date": (
            _format_adaptive_date(record.get("theater_end_date"), today=today) if in_theaters else None
        ),
        "next_episode_season_number": (
            int(record["next_episode_season_number"]) if record.get("next_episode_season_number") else None
        ),
        "next_episode_number": (
            int(record["next_episode_number"]) if record.get("next_episode_number") else None
        ),
        "next_episode_date": _format_adaptive_date(record.get("next_episode_air_date"), today=today),
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
        "rent_buy_provider_logos": record.get("rent_buy_provider_logos") or None,
        "recommended": record.get("recommended_titles") or None,
        "similar": record.get("similar_titles") or None,
        "alternative_titles": record.get("alternative_titles") or None,
    }
