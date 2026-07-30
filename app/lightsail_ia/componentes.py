"""componentes.py — Funções auxiliares de renderização para o FilmBot."""

import html
from datetime import datetime, timezone
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

_OVERVIEW_TRUNCATE_CHARS = 200
_MAX_VISIBLE_GENRES = 6
_MAX_VISIBLE_PROVIDERS = 6

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


def load_audio_cancel_script() -> None:
    """Injeta o script do ícone de descarte durante a gravação de áudio."""
    path = Path(__file__).parent / "static" / "audio_cancel_recording.js"
    script = path.read_text(encoding="utf-8")
    components.html(f"<script>{script}</script>", height=0)


def _prioritize(items: list[str], terms: list[str]) -> list[str]:
    """Reordena items colocando primeiro os que contêm algum termo destacado (case-insensitive),
    preservando a ordem relativa dentro de cada grupo. Usado para que um gênero/provedor
    mencionado explicitamente pelo usuário nunca fique escondido no badge "+N"."""
    if not terms:
        return items
    lowered = [t.lower() for t in terms if t]

    def _matches(item: str) -> bool:
        item_lower = item.lower()
        return any(t in item_lower for t in lowered)

    matched = [i for i in items if _matches(i)]
    unmatched = [i for i in items if not _matches(i)]
    return matched + unmatched


def render_card(title: dict, idx: int = 0) -> str:
    """Monta o HTML de um card de título com escape contra XSS."""
    poster = title.get("backdrop_url") or title.get("poster_url") or ""
    title_name = html.escape(title.get("title", ""))
    year = html.escape(str(title.get("year", "")))
    title_type = html.escape(title.get("type", ""))
    rating = title.get("rating")
    overview_raw = title.get("overview") or ""
    reason = html.escape(title.get("reason") or "")
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

    genres_raw = _prioritize(
        [g.strip() for g in genres if g.strip()], title.get("highlighted_genres") or []
    )
    genres_clean = [html.escape(g) for g in genres_raw]
    visible_genres = genres_clean[:_MAX_VISIBLE_GENRES]
    genres_html = "".join(f'<span class="genre">{g}</span>' for g in visible_genres)

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

    trailer_vital_html = ""
    if trailer_url:
        safe_url = html.escape(trailer_url)
        trailer_vital_html = (
            f'<span class="vital vital-trailer">{_YT_IMG}'
            f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" class="trailer-link">'
            f'Trailer</a></span>'
        )

    providers_html = ""
    if streaming_providers:
        provs = [p.strip() for p in streaming_providers.split(",") if p.strip()]
        provs = _prioritize(provs, title.get("highlighted_providers") or [])
        visible_provs = provs[:_MAX_VISIBLE_PROVIDERS]
        stream_badges = "".join(
            f'<span class="provider">{html.escape(p)}</span>' for p in visible_provs
        )
        providers_html = (
            f'<div class="providers-block">'
            f'<span class="providers-label">📺 Onde assistir</span>'
            f'<div class="meta-row providers-row">{stream_badges}</div></div>'
        )

    if len(overview_raw) > _OVERVIEW_TRUNCATE_CHARS:
        overview_short = html.escape(overview_raw[:_OVERVIEW_TRUNCATE_CHARS].rstrip() + "…")
        overview_full = html.escape(overview_raw)
        toggle_id = f"overview-toggle-{idx}"
        overview_html = (
            f'<input type="checkbox" id="{toggle_id}" class="overview-toggle" hidden>'
            f'<p class="overview overview-short">{overview_short}</p>'
            f'<p class="overview overview-full">{overview_full}</p>'
            f'<label for="{toggle_id}" class="overview-more-label">Ver mais</label>'
            f'<label for="{toggle_id}" class="overview-less-label">Ver menos</label>'
        )
    else:
        overview_html = f'<p class="overview">{html.escape(overview_raw)}</p>'

    vitals_parts = []
    if rating is not None:
        vitals_parts.append(
            f'<span class="vital vital-rating">★ {html.escape(str(rating))}</span>'
        )
    if release_date:
        vitals_parts.append(f'<span class="vital vital-release">📅 {release_date}</span>')
    if trailer_vital_html:
        vitals_parts.append(trailer_vital_html)
    vitals_html = (
        '<div class="meta-row vitals-row">'
        + '<span class="vital-sep">·</span>'.join(vitals_parts)
        + '</div>'
        if vitals_parts else ""
    )

    duration_html = (
        f'<div class="meta-row vitals-row"><span class="vital vital-duration">⏱ {html.escape(duration)}</span></div>'
        if duration else ""
    )

    return f"""
    <article class="card">
      {img_html}
      <div class="card-body">
        <strong class="card-title">{title_name}</strong>
        <span class="card-subtitle">
          &nbsp;({year}) — {title_type} {certification_html}
        </span>
        <div class="genres-container">{genres_html}</div>
        {providers_html}
        {cinema_html}
        {vitals_html}
        {duration_html}
        {overview_html}
        <p class="reason">💡 {reason}</p>
      </div>
    </article>
    """


def render_grid(titles: list[dict]) -> str:
    """Monta o HTML completo do grid de cards."""
    cards = [render_card(t, idx) for idx, t in enumerate(titles)]
    return '<div class="grid-titles">' + "".join(cards) + "</div>"


def render_footer() -> None:
    """Renderiza o rodapé da página principal com crédito TMDB."""
    year = datetime.now(tz=timezone.utc).year
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
    year = datetime.now(tz=timezone.utc).year
    st.markdown(
        f'<div class="footer-login">'
        f"© {year} FilmBot · Todos os direitos reservados"
        f"</div>",
        unsafe_allow_html=True,
    )
