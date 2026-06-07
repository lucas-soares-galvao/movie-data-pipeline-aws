import streamlit as st
from agent import recomendar

st.set_page_config(page_title="FilmBot", page_icon="🎬", layout="wide")

st.markdown("""
<style>
  .card {
    background: #111;
    border-radius: 12px;
    padding: 12px;
    border: 1px solid rgba(255,255,255,0.06);
    height: 100%;
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
  .sinopse { color: #d4d4d4; font-size: 12px; margin-top: 6px; line-height: 1.5; }
  .motivo {
    color: #a3a3a3;
    font-size: 11px;
    font-style: italic;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(255,255,255,0.05);
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
        cols = st.columns(4)

        for i, t in enumerate(titulos):
            with cols[i % 4]:
                poster = t.get("poster_url") or ""
                nota = t.get("nota")
                sinopse = t.get("sinopse") or ""
                generos = t.get("generos") or []
                motivo = t.get("motivo") or ""
                duracao = t.get("duracao") or ""

                if poster:
                    st.image(poster, use_container_width=True)

                generos_html = "".join(
                    f'<span class="genero">{g.strip()}</span>' for g in generos
                )

                st.markdown(f"""
                <div class="card">
                  <strong>{t.get('titulo', '')}</strong>
                  <span style="color:#737373; font-size:12px">
                    &nbsp;({t.get('ano', '')}) — {t.get('tipo', '')}
                  </span>
                  <div style="margin: 6px 0">{generos_html}</div>
                  {f'<p class="nota">★ {nota}</p>' if nota else ''}
                  {f'<p class="duracao">⏱ {duracao}</p>' if duracao else ''}
                  <p class="sinopse">{sinopse}</p>
                  <p class="motivo">💡 {motivo}</p>
                </div>
                """, unsafe_allow_html=True)
