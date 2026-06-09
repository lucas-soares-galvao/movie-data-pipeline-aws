import re
import streamlit as st
from agent import recomendar

st.set_page_config(page_title="FilmBot", page_icon="🎬", layout="wide")

# ── Estilos visuais (dark theme + grid de cards) — sem lógica de negócio aqui ──
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
  .nota { color: #f97316; font-weight: bold; font-size: 14px; margin: 4px 0; }
  .duracao { color: #a3a3a3; font-size: 11px; margin: 2px 0 4px 0; }
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
    border: 1px solid rgba(34,197,94,0.2);
    vertical-align: middle;
  }
  .providers-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 2px;
    margin: 2px 0 4px 0;
  }
  .providers-icon {
    font-size: 13px;
    line-height: 1;
    flex-shrink: 0;
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

if st.button("Recomendar", type="primary") and preferencia:
    with st.spinner("Consultando o data lake e gerando recomendações..."):
        titulos = recomendar(preferencia)

    if not titulos:
        st.warning("Nenhum título encontrado para essa busca. Tente outra descrição.")
    else:
        st.markdown(f"**{len(titulos)} título(s) encontrado(s)**")

        # Streamlit não tem componente de grid de cards nativo, então montamos HTML manualmente.
        # st.markdown(..., unsafe_allow_html=True) renderiza HTML bruto dentro da página.
        cards_html = []
        for t in titulos:
            poster = t.get("backdrop_url") or t.get("poster_url") or ""
            nota = t.get("nota")
            sinopse = t.get("sinopse") or ""
            generos = t.get("generos") or []
            motivo = t.get("motivo") or ""
            duracao = (t.get("duracao") or "").replace("~null", "").strip(" ·")
            duracao = " · ".join(part.strip() for part in duracao.split(" · ") if part.strip())
            streaming_providers = t.get("streaming_providers") or ""

            img_html = (
                f'<img src="{poster}" style="width:100%;height:200px;object-fit:cover;display:block;" />'
                if poster else ""
            )
            generos_html = "".join(
                f'<span class="genero">{g.strip()}</span>' for g in generos
            )
            providers_html = ""
            if streaming_providers:
                badges = "".join(
                    f'<span class="provider">{p.strip()}</span>'
                    for p in streaming_providers.split(",")
                    if p.strip()
                )
                providers_html = f'<div class="providers-row"><span class="providers-icon">📺</span>{badges}</div>'

            cards_html.append(f"""
            <div class="card">
              {img_html}
              <div class="card-body">
                <strong>{t.get('titulo', '')}</strong>
                <span style="color:#737373; font-size:12px">
                  &nbsp;({t.get('ano', '')}) — {t.get('tipo', '')}
                </span>
                <div style="margin: 6px 0">{generos_html}</div>
                {f'<p class="nota">★ {nota}</p>' if nota else ''}
                {f'<p class="duracao">⏱ {duracao}</p>' if duracao else ''}
                {providers_html}
                <p class="sinopse">{sinopse}</p>
                <p class="motivo">💡 {motivo}</p>
              </div>
            </div>
            """)

        grid_html = '<div class="grid-filmes">' + "".join(cards_html) + "</div>"
        grid_html = re.sub(r'\s+', ' ', grid_html)  # colapsa espaços/quebras de linha para evitar bugs no parser do Streamlit
        st.markdown(grid_html, unsafe_allow_html=True)
