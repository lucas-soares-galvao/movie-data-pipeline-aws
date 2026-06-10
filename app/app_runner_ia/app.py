import re

import streamlit as st

from utils.agente import executar_agente

st.set_page_config(page_title="FilmBot", page_icon="🎬", layout="wide")

st.markdown("""
<style>
  .grid-filmes {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
  }
  .card {
    background: #111;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.06);
    display: flex;
    flex-direction: column;
  }
  .card-body {
    padding: 12px;
    display: flex;
    flex-direction: column;
    flex: 1;
  }
  .genero {
    background: rgba(249,115,22,0.13);
    color: #fb923c;
    border-radius: 99px;
    padding: 2px 8px;
    font-size: 11px;
    display: inline-block;
    margin: 2px;
    border: 1px solid rgba(249,115,22,0.2);
  }
  .meta-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 2px 0;
  }
  .meta-icon {
    font-size: 16px;
    line-height: 1;
    flex-shrink: 0;
    width: 20px;
    text-align: center;
  }
  .nota { color: #f97316; font-weight: bold; font-size: 16px; }
  .duracao { color: #a3a3a3; font-size: 14px; }
  .sinopse { color: #d4d4d4; font-size: 12px; margin-top: 6px; line-height: 1.5; flex: 1; }
  .motivo {
    color: #a3a3a3;
    font-size: 11px;
    font-style: italic;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(255,255,255,0.05);
  }
  .provider {
    background: rgba(34,197,94,0.12);
    color: #4ade80;
    border-radius: 99px;
    padding: 2px 8px;
    font-size: 11px;
    display: inline-block;
    margin: 2px;
    vertical-align: middle;
  }
  .providers-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
    margin: 2px 0;
  }
  .providers-label {
    color: #737373;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 6px 0 2px 0;
  }
</style>
""", unsafe_allow_html=True)

st.title("🎬 FilmBot — Recomendações do seu data lake")
st.caption("Os dados vêm da tabela SPEC do pipeline AWS (TMDB)")

preferencia = st.text_input(
    "O que você quer assistir?",
    placeholder="Ex: filmes de terror dos anos 2010, séries parecidas com O Senhor dos Anéis...",
)


def _gerar_html_card(titulo: dict) -> str:
    """Gera o HTML de um card de título a partir de um dict de recomendação."""
    poster = titulo.get("backdrop_url") or titulo.get("poster_url") or ""
    nota = titulo.get("nota")
    sinopse = titulo.get("sinopse") or ""
    generos = titulo.get("generos") or []
    motivo = titulo.get("motivo") or ""
    duracao = (titulo.get("duracao") or "").replace("~null", "").strip(" ·")
    duracao = " · ".join(part.strip() for part in duracao.split(" · ") if part.strip())
    streaming_providers = titulo.get("streaming_providers") or ""

    img_html = (
        f'<img src="{poster}" style="width:100%;height:200px;object-fit:cover;display:block;" />'
        if poster else ""
    )
    generos_html = "".join(f'<span class="genero">{g.strip()}</span>' for g in generos)
    providers_html = ""
    if streaming_providers:
        badges = "".join(
            f'<span class="provider">{p.strip()}</span>'
            for p in streaming_providers.split(",")
            if p.strip()
        )
        providers_html = (
            f'<div class="meta-row providers-row">'
            f'<span class="meta-icon">📺</span>{badges}</div>'
        )

    return f"""
    <div class="card">
      {img_html}
      <div class="card-body">
        <strong>{titulo.get('titulo', '')}</strong>
        <span style="color:#737373; font-size:12px">
          &nbsp;({titulo.get('ano', '')}) — {titulo.get('tipo', '')}
        </span>
        <div style="margin: 6px 0">{generos_html}</div>
        {f'<div class="meta-row"><span class="meta-icon">★</span><span class="nota">{nota}</span></div>' if nota else ''}
        {f'<div class="meta-row"><span class="meta-icon">⏱</span><span class="duracao">{duracao}</span></div>' if duracao else ''}
        {providers_html}
        <p class="sinopse">{sinopse}</p>
        <p class="motivo">💡 {motivo}</p>
      </div>
    </div>
    """


def _gerar_html_grid(titulos: list[dict]) -> str:
    """Envolve os cards em um grid HTML e colapsa espaços extras."""
    cards = "".join(_gerar_html_card(t) for t in titulos)
    grid = f'<div class="grid-filmes">{cards}</div>'
    # Colapsa espaços/quebras de linha para evitar bugs no parser do Streamlit
    return re.sub(r"\s+", " ", grid)


if st.button("Recomendar", type="primary") and preferencia:
    with st.spinner("Consultando o data lake e gerando recomendações..."):
        titulos = executar_agente(preferencia)

    if not titulos:
        st.warning("Nenhum título encontrado para essa busca. Tente outra descrição.")
    else:
        st.markdown(f"**{len(titulos)} título(s) encontrado(s)**")
        st.markdown(_gerar_html_grid(titulos), unsafe_allow_html=True)
