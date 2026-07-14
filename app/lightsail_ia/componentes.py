"""componentes.py — Funções auxiliares de renderização para o FilmBot."""

import html
from datetime import date
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_CERTIFICATION_DESCRIPTIONS = {
    "L": "Livre para todas as idades",
    "10": "Não recomendado para menores de 10 anos",
    "12": "Não recomendado para menores de 12 anos",
    "14": "Não recomendado para menores de 14 anos",
    "16": "Não recomendado para menores de 16 anos",
    "18": "Não recomendado para menores de 18 anos",
}

_YT_IMG = (
    '<img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJyZWQiPjxwYXRoIGQ9Ik0yMy40OTggNi4xODZhMy4wMTYgMy4wMTYgMCAwIDAtMi4xMjItMi4xMzZDMTkuNTA1IDMuNTQ2IDEyIDMuNTQ2IDEyIDMuNTQ2cy03LjUwNSAwLTkuMzc3LjUwNEEzLjAxNyAzLjAxNyAwIDAgMCAuNTAyIDYuMTg2QzAgOC4wNyAwIDEyIDAgMTJzMCAzLjkzLjUwMiA1LjgxNGEzLjAxNiAzLjAxNiAwIDAgMCAyLjEyMiAyLjEzNmMxLjg3MS41MDQgOS4zNzYuNTA0IDkuMzc2LjUwNHM3LjUwNSAwIDkuMzc3LS41MDRhMy4wMTUgMy4wMTUgMCAwIDAgMi4xMjItMi4xMzZDMjQgMTUuOTMgMjQgMTIgMjQgMTJzMC0zLjkzLS41MDItNS44MTR6TTkuNTQ1IDE1LjU2OFY4LjQzMkwxNS44MTggMTJsLTYuMjczIDMuNTY4eiIvPjwvc3ZnPg=="'
    ' width="20" height="20" alt="YouTube" style="display:inline-block;vertical-align:middle;" />'
)


def _inject_css(file_name: str) -> None:
    """Lê um arquivo CSS e injeta na página via st.markdown."""
    path = Path(__file__).parent / "static" / file_name
    css = path.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def load_login_css() -> None:
    """Injeta os estilos da tela de login."""
    _inject_css("login.css")


def load_main_css() -> None:
    """Injeta os estilos da página principal."""
    _inject_css("principal.css")


def load_preference_counter_script(max_chars: int) -> None:
    """Injeta o script do contador dinâmico de caracteres do campo de preferência."""
    path = Path(__file__).parent / "static" / "contador_caracteres.js"
    script = path.read_text(encoding="utf-8").replace("__MAX_CHARS__", str(max_chars))
    components.html(f"<script>{script}</script>", height=0)


def render_card(title: dict) -> str:
    """Monta o HTML de um card de título com escape contra XSS."""
    poster = title.get("backdrop_url") or title.get("poster_url") or ""
    title_name = html.escape(title.get("title", ""))
    year = html.escape(str(title.get("year", "")))
    title_type = html.escape(title.get("type", ""))
    rating = title.get("rating")
    overview = html.escape(title.get("overview") or "")
    genres = title.get("genres") or []
    duration = title.get("duration") or ""
    release_date = html.escape(title.get("release_date") or "")
    streaming_providers = title.get("streaming_providers") or ""
    in_theaters = title.get("in_theaters") or False
    theater_end_date = html.escape(title.get("theater_end_date") or "")
    certification = html.escape(title.get("certification") or "")
    trailer_url = title.get("trailer_url") or ""

    img_html = (
        f'<img src="{poster}" alt="{title_name}"'
        f' class="card-img" loading="lazy" />'
        if poster else ""
    )

    genres_html = "".join(
        f'<span class="genre">{html.escape(g.strip())}</span>' for g in genres
    )

    cinema_html = ""
    if in_theaters:
        label = f"Em cartaz até {theater_end_date}" if theater_end_date else "Em cartaz"
        cinema_html = (
            f'<div class="meta-row"><span class="meta-icon">🎬</span>'
            f'<span class="cinema-badge">{html.escape(label)}</span></div>'
        )

    certification_title = html.escape(_CERTIFICATION_DESCRIPTIONS.get(certification, certification))
    certification_html = (
        f'<span class="certification-badge" data-rating="{certification}"'
        f' title="{certification_title}">'
        f'{certification}</span>'
        if certification else ""
    )

    trailer_html = ""
    if trailer_url:
        safe_url = html.escape(trailer_url)
        trailer_html = (
            f'<div class="meta-row"><span class="meta-icon">{_YT_IMG}</span>'
            f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" class="trailer-link">'
            f'Trailer</a></div>'
        )

    providers_html = ""
    if streaming_providers:
        stream_badges = "".join(
            f'<span class="provider">{html.escape(p.strip())}</span>'
            for p in streaming_providers.split(",")
            if p.strip()
        )
        providers_html = (
            f'<div class="meta-row providers-row">'
            f'<span class="meta-icon">📺</span>{stream_badges}</div>'
        )

    rating_html = (
        f'<div class="meta-row"><span class="meta-icon">★</span>'
        f'<span class="rating">{html.escape(str(rating))}</span></div>'
        if rating is not None else ""
    )
    duration_html = (
        f'<div class="meta-row"><span class="meta-icon">⏱</span>'
        f'<span class="duration">{html.escape(duration)}</span></div>'
        if duration else ""
    )
    release_date_html = (
        f'<div class="meta-row"><span class="meta-icon">📅</span>'
        f'<span class="release-date">{release_date}</span></div>'
        if release_date else ""
    )

    return f"""
    <article class="card">
      {img_html}
      <div class="card-body">
        <strong>{title_name}</strong>
        <span class="card-subtitle">
          &nbsp;({year}) — {title_type} {certification_html}
        </span>
        <div class="genres-container">{genres_html}</div>
        {rating_html}
        {duration_html}
        {release_date_html}
        {cinema_html}
        {providers_html}
        {trailer_html}
        <p class="overview">{overview}</p>
      </div>
    </article>
    """


def render_grid(titles: list[dict]) -> str:
    """Monta o HTML completo do grid de cards."""
    cards = [render_card(t) for t in titles]
    return '<div class="grid-titles">' + "".join(cards) + "</div>"


def render_footer() -> None:
    """Renderiza o rodapé da página principal com crédito TMDB."""
    year = date.today().year
    st.markdown(
        f'<div class="footer">'
        f"© {year} FilmBot · Dados fornecidos por "
        f'<a href="https://www.themoviedb.org/?language=pt-BR"'
        f' target="_blank" rel="noopener noreferrer">TMDB</a>'
        f" · Todos os direitos reservados"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_login_footer() -> None:
    """Renderiza o rodapé simplificado da tela de login."""
    year = date.today().year
    st.markdown(
        f'<div class="footer-login">'
        f"© {year} FilmBot · Todos os direitos reservados"
        f"</div>",
        unsafe_allow_html=True,
    )
