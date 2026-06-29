"""app.py — Interface web do FilmBot (aplicativo Streamlit)."""

import json
import logging
import math
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import boto3
import streamlit as st
import streamlit.components.v1 as components
import watchtower
from agent import recomendar
from componentes import (
    carregar_css_login,
    carregar_css_principal,
    renderizar_grid,
    renderizar_rodape,
    renderizar_rodape_login,
)


def _carregar_filmbot_password() -> None:
    """Busca filmbot_password do Secrets Manager e escreve em secrets.toml."""
    secret_arn = os.getenv("FILMBOT_SECRET_ARN")
    if not secret_arn:
        return
    secrets_dir = Path(__file__).parent / ".streamlit"
    secrets_file = secrets_dir / "secrets.toml"
    if secrets_file.exists():
        return
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "sa-east-1"))
    response = client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])
    secrets_dir.mkdir(exist_ok=True)
    secrets_file.write_text(
        f'[auth]\npassword = "{secret["filmbot_password"]}"\n',
        encoding="utf-8",
    )
    secrets_file.chmod(0o600)


_carregar_filmbot_password()

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
_MAX_CONSULTAS_POR_HORA = 20


@st.cache_resource
def _criar_historico_por_ip() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de consultas por IP."""
    return {}


_historico_por_ip = _criar_historico_por_ip()


def _obter_ip_cliente() -> str:
    """Extrai o IP do cliente a partir do header X-Forwarded-For repassado pelo Caddy."""
    forwarded = st.context.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else "local"


def _consultas_na_ultima_hora(ip: str) -> int:
    """Conta consultas na última hora para o IP e limpa registros expirados."""
    agora = time.time()
    historico = [t for t in _historico_por_ip.get(ip, []) if t > agora - 3600]
    _historico_por_ip[ip] = historico
    return len(historico)


def _segundos_para_liberar(ip: str) -> int:
    """Calcula quantos segundos faltam até a consulta mais antiga do IP expirar."""
    historico = _historico_por_ip.get(ip, [])
    if not historico:
        return 0
    return max(0, math.ceil(historico[0] + 3600 - time.time()))


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

_ip_cliente = _obter_ip_cliente()
_consultas_feitas = _consultas_na_ultima_hora(_ip_cliente)
_restantes = _MAX_CONSULTAS_POR_HORA - _consultas_feitas

if _restantes <= 0:
    _segundos = _segundos_para_liberar(_ip_cliente)
    components.html(f"""
    <style>
      body {{ margin: 0; padding: 0; background: transparent; font-family: 'Source Sans Pro', sans-serif; }}
      .msg-aviso {{
        background: rgba(250,204,21,0.1);
        border: 1px solid rgba(250,204,21,0.3);
        border-radius: 10px;
        padding: 12px 16px;
        color: #fbbf24;
        font-size: 14px;
        max-width: 50%;
      }}
      .tempo-countdown {{ font-weight: 600; }}
    </style>
    <div class="msg-aviso">
      ⚠️ Limite de consultas atingido. Disponível novamente em
      <span class="tempo-countdown" id="countdown"></span>.
    </div>
    <script>
      let restante = {_segundos};
      const el = document.getElementById('countdown');
      function atualizar() {{
        if (restante <= 0) {{
          el.textContent = '00:00';
          window.parent.location.reload();
          return;
        }}
        const m = Math.floor(restante / 60);
        const s = restante % 60;
        el.textContent = String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
        restante--;
      }}
      atualizar();
      setInterval(atualizar, 1000);
    </script>
    """, height=55)
else:
    st.caption(f"Consultas restantes: {_restantes}/{_MAX_CONSULTAS_POR_HORA} por hora")

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
        if st.button("Recomendar", type="primary", disabled=_restantes <= 0) and preferencia:
            _historico_por_ip.setdefault(_ip_cliente, []).append(time.time())
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
    st.markdown(renderizar_grid(titulos), unsafe_allow_html=True)

renderizar_rodape()
