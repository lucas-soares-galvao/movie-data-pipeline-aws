"""app.py — Interface web do FilmBot (aplicativo Streamlit)."""

import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor

import boto3
import streamlit as st
import watchtower
from agent import limpar_duracao, recomendar
from componentes import (
    carregar_css_login,
    carregar_css_principal,
    renderizar_grid,
    renderizar_rodape,
    renderizar_rodape_login,
)

_log_group = os.getenv("CLOUDWATCH_LOG_GROUP", "")
if _log_group:
    _cw_handler = watchtower.CloudWatchLogHandler(
        log_group_name=_log_group,
        boto3_client=boto3.client("logs", region_name=os.getenv("AWS_REGION", "sa-east-1")),
        create_log_group=False,
    )
    logging.root.addHandler(_cw_handler)
    logging.root.setLevel(logging.ERROR)

_executor = ThreadPoolExecutor(max_workers=2)

st.set_page_config(page_title="FilmBot", page_icon="🎬", layout="wide")

# ==============================================================================
# AUTENTICAÇÃO
# ==============================================================================
if not st.session_state.get("autenticado"):
    carregar_css_login()

    _, col, _ = st.columns([1, 1.1, 1])
    with col:
        st.markdown("""
        <div class="login-card">
          <p class="login-title">🎬 FilmBot</p>
          <p class="login-subtitle">Seu assistente de recomendações de filmes e séries</p>
          <hr class="login-divider">
        </div>
        """, unsafe_allow_html=True)

        senha = st.text_input(
            "", placeholder="Digite a senha de acesso...",
            type="password", label_visibility="collapsed",
        )
        entrar = st.button("Entrar →", use_container_width=True)

        if entrar and senha == st.secrets.get("auth", {}).get("password", ""):
            st.session_state["autenticado"] = True
            st.rerun()
        elif entrar and senha:
            st.markdown(
                '<div class="login-error">❌ Senha incorreta. Tente novamente.</div>',
                unsafe_allow_html=True,
            )

    renderizar_rodape_login()
    st.stop()

# ==============================================================================
# PÁGINA PRINCIPAL
# ==============================================================================
carregar_css_principal()

col_titulo, col_sair = st.columns([9, 1])
with col_titulo:
    st.title("🎬 FilmBot — Seu assistente de filmes e séries")
    st.caption("Descubra o que assistir com ajuda da inteligência artificial")
with col_sair:
    st.write("")
    if st.button("Sair"):
        st.session_state["autenticado"] = False
        st.rerun()

preferencia = st.text_area(
    "O que você quer assistir?",
    placeholder="Ex: filmes de terror dos anos 2010, séries parecidas com O Senhor dos Anéis...",
    height=68,
)

# ==============================================================================
# LÓGICA DO BOTÃO E BUSCA ASSÍNCRONA
# ==============================================================================
buscando = st.session_state.get("buscando", False)

if buscando:
    col_rec, col_canc, _ = st.columns([1, 1, 6], gap="small")
    with col_rec:
        st.button("Recomendar", type="primary", disabled=True)
    with col_canc:
        if st.button("Cancelar", type="primary", key="btn_cancelar"):
            st.session_state["buscando"] = False
            st.session_state["busca_concluida"] = False
            st.session_state["erro_busca"] = False
            st.session_state["titulos"] = []
            st.session_state["future"] = None
            st.rerun()

    future: Future = st.session_state.get("future")
    if future and future.done():
        st.session_state["buscando"] = False
        st.session_state["busca_concluida"] = True
        try:
            st.session_state["titulos"] = future.result()
        except Exception:
            logging.exception("Erro ao buscar recomendações")
            st.session_state["erro_busca"] = True
            st.session_state["titulos"] = []
        st.rerun()
    else:
        st.markdown("""
        <div class="spinner-container">
          <div class="spinner"></div>
          <span class="spinner-text">Buscando as melhores opções para você...</span>
        </div>
        """, unsafe_allow_html=True)
        time.sleep(0.5)
        st.rerun()
else:
    col_rec, _, __ = st.columns([1, 1, 6], gap="small")
    with col_rec:
        if st.button("Recomendar", type="primary") and preferencia:
            st.session_state["future"] = _executor.submit(recomendar, preferencia)
            st.session_state["buscando"] = True
            st.session_state["busca_concluida"] = False
            st.session_state["erro_busca"] = False
            st.session_state["titulos"] = []
            st.rerun()

# ==============================================================================
# EXIBIÇÃO DOS RESULTADOS
# ==============================================================================
titulos = st.session_state.get("titulos", [])

if st.session_state.get("erro_busca"):
    st.markdown("""
    <div class="msg-erro">
      ❌ Algo deu errado ao buscar as recomendações. Tente novamente em instantes.
    </div>
    """, unsafe_allow_html=True)

if st.session_state.get("busca_concluida") and not titulos and not st.session_state.get("erro_busca"):
    st.markdown("""
    <div class="msg-aviso">
      ⚠️ Não encontramos nada com essa descrição. Tente usar outras palavras ou ser mais específico.
    </div>
    """, unsafe_allow_html=True)
elif titulos:
    palavra = "opção" if len(titulos) == 1 else "opções"
    st.markdown(f"**Encontramos {len(titulos)} {palavra} para você!**")
    st.markdown(renderizar_grid(titulos, limpar_duracao), unsafe_allow_html=True)

renderizar_rodape()
