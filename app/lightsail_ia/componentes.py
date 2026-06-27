"""componentes.py — Funções auxiliares de renderização para o FilmBot."""

import html
import re
from datetime import date
from pathlib import Path
from typing import Callable

import streamlit as st


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


def renderizar_card(t: dict, limpar_duracao_fn: Callable[[str], str]) -> str:
    """Monta o HTML de um card de título com escape contra XSS."""
    poster = t.get("backdrop_url") or t.get("poster_url") or ""
    titulo = html.escape(t.get("titulo", ""))
    ano = html.escape(str(t.get("ano", "")))
    tipo = html.escape(t.get("tipo", ""))
    nota = t.get("nota")
    sinopse = html.escape(t.get("sinopse") or "")
    generos = t.get("generos") or []
    duracao = limpar_duracao_fn(t.get("duracao") or "")
    data_lancamento = html.escape(t.get("data_lancamento") or "")
    streaming_providers = t.get("streaming_providers") or ""
    in_theaters = t.get("in_theaters") or False
    theater_end_date = html.escape(t.get("theater_end_date") or "")

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
          &nbsp;({ano}) — {tipo}
        </span>
        <div class="generos-container">{generos_html}</div>
        {nota_html}
        {duracao_html}
        {data_html}
        {cinema_html}
        {providers_html}
        <p class="sinopse">{sinopse}</p>
      </div>
    </article>
    """


def renderizar_grid(titulos: list[dict], limpar_duracao_fn: Callable[[str], str]) -> str:
    """Monta o HTML completo do grid de cards."""
    cards = [renderizar_card(t, limpar_duracao_fn) for t in titulos]
    grid_html = '<div class="grid-filmes">' + "".join(cards) + "</div>"
    return re.sub(r"\s+", " ", grid_html)


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
