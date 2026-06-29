"""formatacao.py — Formatação determinística de registros do Athena para cards do FilmBot."""

_MESES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def _formatar_tipo(media_type: str) -> str:
    """Converte media_type da API ('movie'/'tv') para português ('filme'/'série')."""
    return "filme" if media_type == "movie" else "série" if media_type == "tv" else media_type


def _formatar_generos(genre_names: str | None) -> list[str]:
    """Converte string de gêneros separados por vírgula em lista."""
    if not genre_names:
        return []
    return [g.strip() for g in genre_names.split(",") if g.strip()]


def _formatar_duracao_titulo(registro: dict) -> str | None:
    """Formata duração: '2h 15min' para filmes, '3 temporadas · 24 eps' para séries."""
    if registro.get("media_type") == "movie":
        raw = registro.get("runtime_minutes")
        if not raw:
            return None
        minutos = int(raw)
        horas, resto = divmod(minutos, 60)
        return f"{horas}h {resto}min" if horas else f"{resto}min"

    partes = []
    seasons = registro.get("number_of_seasons")
    episodes = registro.get("number_of_episodes")
    ep_runtime = registro.get("episode_runtime_minutes")
    if seasons:
        n = int(seasons)
        partes.append(f"{n} temporada{'s' if n != 1 else ''}")
    if episodes:
        partes.append(f"{int(episodes)} eps")
    if ep_runtime:
        partes.append(f"~{int(ep_runtime)} min/ep")
    return " · ".join(partes) if partes else None


def _formatar_data_lancamento(air_date: str | None) -> str | None:
    """Converte data ISO 'YYYY-MM-DD' para 'Mês de Ano' em português."""
    if not air_date or len(air_date) < 7:
        return None
    try:
        partes = air_date.split("-")
        ano = int(partes[0])
        mes = int(partes[1])
        return f"{_MESES[mes]} de {ano}"
    except (ValueError, KeyError, IndexError):
        return None


def _formatar_theater_end_date(theater_end_date: str | None, in_theaters: bool) -> str | None:
    """Converte data ISO para 'DD/MM/AAAA' se o título estiver em cartaz."""
    if not in_theaters or not theater_end_date:
        return None
    try:
        ano, mes, dia = theater_end_date.split("-")
        return f"{dia}/{mes}/{ano}"
    except ValueError:
        return None


def _formatar_nota(vote_average: object) -> float | None:
    """Converte nota (str, int ou float) para float, retornando None se inválida."""
    if vote_average is None or vote_average == "":
        return None
    try:
        return float(vote_average)
    except (ValueError, TypeError):
        return None


def formatar_registro(registro: dict) -> dict:
    """Transforma um registro cru do Athena em dict formatado para o card do app."""
    in_theaters = str(registro.get("in_theaters", "")).lower() == "true"
    return {
        "titulo": registro.get("title", ""),
        "tipo": _formatar_tipo(registro.get("media_type", "")),
        "ano": int(registro["year"]) if registro.get("year") else None,
        "generos": _formatar_generos(registro.get("genre_names")),
        "sinopse": registro.get("overview") or "",
        "nota": _formatar_nota(registro.get("vote_average")),
        "poster_url": registro.get("poster_url") or None,
        "backdrop_url": registro.get("backdrop_url") or None,
        "duracao": _formatar_duracao_titulo(registro),
        "data_lancamento": _formatar_data_lancamento(registro.get("air_date")),
        "streaming_providers": registro.get("streaming_providers") or None,
        "in_theaters": in_theaters,
        "theater_end_date": _formatar_theater_end_date(
            registro.get("theater_end_date"), in_theaters
        ),
        "tagline": registro.get("tagline") or None,
        "elenco": registro.get("actor_names") or None,
        "diretor": registro.get("director") or None,
        "roteiristas": registro.get("screenplay") or None,
        "compositor": registro.get("music_composer") or None,
        "keywords": registro.get("keywords_pt") or None,
        "certificacao": registro.get("certification") or None,
        "trailer_url": registro.get("trailer_url") or None,
        "colecao": registro.get("collection_name") or None,
        "produtoras": registro.get("production_companies") or None,
        "paises_producao": registro.get("production_countries") or None,
        "produtor": registro.get("producer") or None,
        "cinematografo": registro.get("cinematographer") or None,
        "montador": registro.get("editor") or None,
        "redes_tv": registro.get("networks") or None,
        "criadores": registro.get("created_by") or None,
        "aluguel_compra": registro.get("rent_buy_providers") or None,
        "recomendados": registro.get("recommended_titles") or None,
        "similares": registro.get("similar_titles") or None,
        "titulos_alternativos": registro.get("alternative_titles") or None,
    }
