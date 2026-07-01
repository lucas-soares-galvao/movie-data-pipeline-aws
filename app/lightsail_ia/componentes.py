"""componentes.py — Funções auxiliares de renderização para o FilmBot."""

import html
from datetime import date
from pathlib import Path

import streamlit as st

_DESCRICAO_CLASSIFICACAO = {
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


def _injetar_css(arquivo: str) -> None:
    """Lê um arquivo CSS e injeta na página via st.markdown."""
    caminho = Path(__file__).parent / "static" / arquivo
    css = caminho.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def carregar_css_login() -> None:
    """Injeta os estilos da tela de login."""
    _injetar_css("login.css")


def carregar_css_principal() -> None:
    """Injeta os estilos da página principal."""
    _injetar_css("principal.css")


def renderizar_card(t: dict) -> str:
    """Monta o HTML de um card de título com escape contra XSS."""
    poster = t.get("backdrop_url") or t.get("poster_url") or ""
    titulo = html.escape(t.get("titulo", ""))
    ano = html.escape(str(t.get("ano", "")))
    tipo = html.escape(t.get("tipo", ""))
    nota = t.get("nota")
    sinopse = html.escape(t.get("sinopse") or "")
    generos = t.get("generos") or []
    duracao = t.get("duracao") or ""
    data_lancamento = html.escape(t.get("data_lancamento") or "")
    streaming_providers = t.get("streaming_providers") or ""
    in_theaters = t.get("in_theaters") or False
    theater_end_date = html.escape(t.get("theater_end_date") or "")
    certificacao = html.escape(t.get("certificacao") or "")
    trailer_url = t.get("trailer_url") or ""

    img_html = (
        f'<img src="{poster}" alt="{titulo}"'
        f' class="card-img" loading="lazy" />'
        if poster else ""
    )

    generos_html = "".join(
        f'<span class="genero">{html.escape(g.strip())}</span>' for g in generos
    )

    cinema_html = ""
    if in_theaters:
        label = f"Em cartaz até {theater_end_date}" if theater_end_date else "Em cartaz"
        cinema_html = (
            f'<div class="meta-row"><span class="meta-icon">🎬</span>'
            f'<span class="cinema-badge">{html.escape(label)}</span></div>'
        )

    certificacao_titulo = html.escape(_DESCRICAO_CLASSIFICACAO.get(certificacao, certificacao))
    certificacao_html = (
        f'<span class="certificacao-badge" data-rating="{certificacao}"'
        f' title="{certificacao_titulo}">'
        f'{certificacao}</span>'
        if certificacao else ""
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

    nota_html = (
        f'<div class="meta-row"><span class="meta-icon">★</span>'
        f'<span class="nota">{html.escape(str(nota))}</span></div>'
        if nota is not None else ""
    )
    duracao_html = (
        f'<div class="meta-row"><span class="meta-icon">⏱</span>'
        f'<span class="duracao">{html.escape(duracao)}</span></div>'
        if duracao else ""
    )
    data_html = (
        f'<div class="meta-row"><span class="meta-icon">📅</span>'
        f'<span class="data-lancamento">{data_lancamento}</span></div>'
        if data_lancamento else ""
    )

    return f"""
    <article class="card">
      {img_html}
      <div class="card-body">
        <strong>{titulo}</strong>
        <span class="card-subtitle">
          &nbsp;({ano}) — {tipo} {certificacao_html}
        </span>
        <div class="generos-container">{generos_html}</div>
        {nota_html}
        {duracao_html}
        {data_html}
        {cinema_html}
        {providers_html}
        {trailer_html}
        <p class="sinopse">{sinopse}</p>
      </div>
    </article>
    """


def renderizar_grid(titulos: list[dict]) -> str:
    """Monta o HTML completo do grid de cards."""
    cards = [renderizar_card(t) for t in titulos]
    return '<div class="grid-filmes">' + "".join(cards) + "</div>"


def renderizar_rodape() -> None:
    """Renderiza o rodapé da página principal com crédito TMDB."""
    ano = date.today().year
    st.markdown(
        f'<div class="rodape">'
        f"© {ano} FilmBot · Dados fornecidos por "
        f'<a href="https://www.themoviedb.org/?language=pt-BR"'
        f' target="_blank" rel="noopener noreferrer">TMDB</a>'
        f" · Todos os direitos reservados"
        f"</div>",
        unsafe_allow_html=True,
    )


def renderizar_rodape_login() -> None:
    """Renderiza o rodapé simplificado da tela de login."""
    ano = date.today().year
    st.markdown(
        f'<div class="rodape-login">'
        f"© {ano} FilmBot · Todos os direitos reservados"
        f"</div>",
        unsafe_allow_html=True,
    )
