"""app.py — Interface web do FilmBot (aplicativo Streamlit)."""

import hashlib
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
from agent import AudioMuitoLongoError, _MAX_AUDIO_SECONDS, recommend, transcribe_preference
from componentes import (
    load_login_css,
    load_main_css,
    load_preference_counter_script,
    render_grid,
    render_footer,
    render_login_footer,
)


def _load_filmbot_password() -> None:
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


_load_filmbot_password()

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
_MAX_QUERIES_PER_HOUR = 20
_MAX_TRANSCRIPTIONS_PER_HOUR = 30  # Whisper é bem mais barato que o fluxo LLM+Athena
_MAX_PREFERENCE_CHARS = 300


@st.cache_resource
def _create_ip_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de consultas por IP."""
    return {}


_ip_history = _create_ip_history()


@st.cache_resource
def _create_audio_ip_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de transcrições de áudio por IP."""
    return {}


_audio_ip_history = _create_audio_ip_history()


def _get_client_ip() -> str:
    """Extrai o IP do cliente a partir do header X-Forwarded-For repassado pelo Caddy."""
    forwarded = st.context.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else "local"


def _queries_in_last_hour(history: dict[str, list[float]], ip: str) -> int:
    """Conta consultas na última hora para o IP no histórico informado e limpa registros expirados."""
    now = time.time()
    filtered = [t for t in history.get(ip, []) if t > now - 3600]
    history[ip] = filtered
    return len(filtered)


def _seconds_until_available(history: dict[str, list[float]], ip: str) -> int:
    """Calcula quantos segundos faltam até a consulta mais antiga do IP expirar."""
    entries = history.get(ip, [])
    if not entries:
        return 0
    return max(0, math.ceil(entries[0] + 3600 - time.time()))


st.set_page_config(page_title="FilmBot", page_icon="🎬", layout="wide")

# ==============================================================================
# AUTENTICAÇÃO
# ==============================================================================
if not st.session_state.get("authenticated"):
    load_login_css()

    _, col, _ = st.columns([1, 1.1, 1])
    with col:
        st.markdown("""
        <div class="login-card">
          <p class="login-title">🎬 FilmBot</p>
          <p class="login-subtitle">Seu assistente de recomendações de filmes e séries</p>
          <hr class="login-divider">
        </div>
        """, unsafe_allow_html=True)

        password = st.text_input(
            "", placeholder="Digite a senha de acesso...",
            type="password", label_visibility="collapsed",
        )
        submit = st.button("Entrar →", use_container_width=True)

        if submit and password == st.secrets.get("auth", {}).get("password", ""):
            st.session_state["authenticated"] = True
            st.rerun()
        elif submit and password:
            st.markdown(
                '<div class="login-error">❌ Senha incorreta. Tente novamente.</div>',
                unsafe_allow_html=True,
            )

    render_login_footer()
    st.stop()

# ==============================================================================
# PÁGINA PRINCIPAL
# ==============================================================================
load_main_css()

title_col, logout_col = st.columns([9, 1])
with title_col:
    st.title("🎬 FilmBot — Seu assistente de filmes e séries")
    st.caption("Descubra o que assistir com ajuda da inteligência artificial")
with logout_col:
    st.write("")
    if st.button("Sair"):
        st.session_state["authenticated"] = False
        st.rerun()

_client_ip = _get_client_ip()

# ------------------------------------------------------------------
# COMPOSER: pill único (estilo chat moderno) com o botão de áudio embutido no
# canto do text_area via CSS position:absolute (ver ".st-key-composer" em
# static/principal.css). Placeholders reservam a posição visual (texto
# primeiro, status da transcrição depois) sem depender da ordem de execução
# em Python: o áudio precisa ser processado ANTES do text_area, pois o
# Streamlit proíbe setar session_state["preference_text"] depois que o
# widget com essa key já rodou no mesmo script run — só o destino de
# renderização muda. O st.audio_input em si não precisa de placeholder: como
# fica posicionado via CSS absoluto, sua posição no DOM é irrelevante.
# ------------------------------------------------------------------
with st.container(key="composer"):
    text_area_slot = st.empty()
    status_slot = st.empty()

    audio_value = st.audio_input(
        f"Gravar preferência em áudio (máx. {_MAX_AUDIO_SECONDS}s)",
        label_visibility="collapsed",
        key="audio_input",
    )

    _audio_queries_made = _queries_in_last_hour(_audio_ip_history, _client_ip)
    _audio_remaining = _MAX_TRANSCRIPTIONS_PER_HOUR - _audio_queries_made

    if audio_value is not None and not st.session_state.get("transcribing"):
        audio_bytes = audio_value.getvalue()
        audio_hash = hashlib.md5(audio_bytes).hexdigest()
        if audio_hash != st.session_state.get("audio_last_hash"):
            st.session_state["audio_last_hash"] = audio_hash
            st.session_state["transcription_error"] = False
            st.session_state["transcription_empty"] = False
            st.session_state["transcription_too_long"] = False
            st.session_state["transcription_rate_limited"] = False
            st.session_state["transcription_truncated"] = False
            if _audio_remaining <= 0:
                st.session_state["transcription_rate_limited"] = True
            else:
                _audio_ip_history.setdefault(_client_ip, []).append(time.time())
                st.session_state["transcribing"] = True
                st.session_state["transcription_future"] = _executor.submit(
                    transcribe_preference, audio_bytes
                )
            st.rerun()

    _still_transcribing = False
    if st.session_state.get("transcribing"):
        transcription_future: Future = st.session_state.get("transcription_future")
        if transcription_future and transcription_future.done():
            st.session_state["transcribing"] = False
            try:
                text = transcription_future.result()
            except AudioMuitoLongoError:
                st.session_state["transcription_too_long"] = True
            except Exception:
                logging.exception("Erro ao transcrever áudio")
                st.session_state["transcription_error"] = True
            else:
                if text:
                    if len(text) > _MAX_PREFERENCE_CHARS:
                        text = text[:_MAX_PREFERENCE_CHARS]
                        st.session_state["transcription_truncated"] = True
                    st.session_state["preference_text"] = text
                else:
                    st.session_state["transcription_empty"] = True
            st.rerun()
        else:
            _still_transcribing = True

    with status_slot.container():
        if _still_transcribing:
            st.caption("🎤 Transcrevendo áudio...")
        if st.session_state.get("transcription_rate_limited"):
            st.caption(
                f"⚠️ Limite de {_MAX_TRANSCRIPTIONS_PER_HOUR} transcrições por hora atingido. "
                "Digite sua preferência manualmente."
            )
        if st.session_state.get("transcription_too_long"):
            st.caption(f"⚠️ Áudio muito longo — grave até {_MAX_AUDIO_SECONDS} segundos ou digite sua preferência.")
        if st.session_state.get("transcription_error"):
            st.caption("❌ Não conseguimos transcrever o áudio. Digite sua preferência manualmente.")
        if st.session_state.get("transcription_empty"):
            st.caption("⚠️ Não detectamos fala no áudio. Tente gravar novamente ou digite sua preferência.")
        if st.session_state.get("transcription_truncated"):
            st.caption(f"⚠️ Transcrição excedeu {_MAX_PREFERENCE_CHARS} caracteres e foi cortada.")

    with text_area_slot.container():
        preference = st.text_area(
            "O que você quer assistir?",
            placeholder="Ex: filmes de terror dos anos 2010, séries parecidas com O Senhor dos Anéis...",
            height=68,
            max_chars=_MAX_PREFERENCE_CHARS,
            key="preference_text",
        )
        load_preference_counter_script(_MAX_PREFERENCE_CHARS)

    if _still_transcribing:
        time.sleep(0.5)
        st.rerun()

_queries_made = _queries_in_last_hour(_ip_history, _client_ip)
_remaining = _MAX_QUERIES_PER_HOUR - _queries_made

if _remaining <= 0:
    _seconds = _seconds_until_available(_ip_history, _client_ip)
    components.html(f"""
    <style>
      body {{ margin: 0; padding: 0; background: transparent; font-family: 'Source Sans Pro', sans-serif; }}
      .msg-warning {{
        background: rgba(250,204,21,0.1);
        border: 1px solid rgba(250,204,21,0.3);
        border-radius: 10px;
        padding: 12px 16px;
        color: #fbbf24;
        font-size: 14px;
        max-width: 50%;
      }}
      .time-countdown {{ font-weight: 600; }}
    </style>
    <div class="msg-warning">
      ⚠️ Limite de {_MAX_QUERIES_PER_HOUR} consultas atingido. Disponível novamente em
      <span class="time-countdown" id="countdown"></span>.
    </div>
    <script>
      let remaining = {_seconds};
      const el = document.getElementById('countdown');
      function update() {{
        if (remaining <= 0) {{
          el.textContent = '00:00';
          window.parent.location.reload();
          return;
        }}
        const m = Math.floor(remaining / 60);
        const s = remaining % 60;
        el.textContent = String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
        remaining--;
      }}
      update();
      setInterval(update, 1000);
    </script>
    """, height=55)
else:
    st.caption(f"Consultas restantes: {_remaining}/{_MAX_QUERIES_PER_HOUR} por hora")

# ==============================================================================
# LÓGICA DO BOTÃO E BUSCA ASSÍNCRONA
# ==============================================================================
searching = st.session_state.get("searching", False)

if searching:
    rec_col, cancel_col, _ = st.columns([1, 1, 6], gap="small")
    with rec_col:
        st.button("Recomendar", type="primary", disabled=True)
    with cancel_col:
        if st.button("Cancelar", type="primary", key="btn_cancelar"):
            st.session_state["searching"] = False
            st.session_state["search_completed"] = False
            st.session_state["search_error"] = False
            st.session_state["titles"] = []
            st.session_state["future"] = None
            st.rerun()

    future: Future = st.session_state.get("future")
    if future and future.done():
        st.session_state["searching"] = False
        st.session_state["search_completed"] = True
        try:
            st.session_state["titles"] = future.result()
        except Exception:
            logging.exception("Erro ao buscar recomendações")
            st.session_state["search_error"] = True
            st.session_state["titles"] = []
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
    rec_col, _, __ = st.columns([1, 1, 6], gap="small")
    with rec_col:
        if st.button("Recomendar", type="primary", disabled=_remaining <= 0) and preference:
            _ip_history.setdefault(_client_ip, []).append(time.time())
            st.session_state["future"] = _executor.submit(recommend, preference)
            st.session_state["searching"] = True
            st.session_state["search_completed"] = False
            st.session_state["search_error"] = False
            st.session_state["titles"] = []
            st.rerun()

# ==============================================================================
# EXIBIÇÃO DOS RESULTADOS
# ==============================================================================
titles = st.session_state.get("titles", [])

if st.session_state.get("search_error"):
    st.markdown("""
    <div class="msg-error">
      ❌ Algo deu errado ao buscar as recomendações. Tente novamente em instantes.
    </div>
    """, unsafe_allow_html=True)

if st.session_state.get("search_completed") and not titles and not st.session_state.get("search_error"):
    st.markdown("""
    <div class="msg-warning">
      ⚠️ Não encontramos nada com essa descrição. Tente usar outras palavras ou ser mais específico.
    </div>
    """, unsafe_allow_html=True)
elif titles:
    word = "opção" if len(titles) == 1 else "opções"
    st.markdown(f"**Encontramos {len(titles)} {word} para você!**")
    st.html(render_grid(titles))

render_footer()
