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
import watchtower
from agent import (
    _AUDIO_DURATION_TOLERANCE_SECONDS,
    _MAX_AUDIO_SECONDS,
    AudioMuitoLongoError,
    _audio_duration_seconds,
    recommend,
    transcribe_preference,
)
from componentes import (
    load_audio_cancel_script,
    load_audio_timer_script,
    load_countdown_script,
    load_login_button_toggle_script,
    load_login_css,
    load_main_css,
    load_preference_counter_script,
    load_textarea_autogrow_script,
    render_feedback,
    render_footer,
    render_grid,
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
_MAX_QUERIES_PER_HOUR = 15
_MAX_TRANSCRIPTIONS_PER_HOUR = 30  # Whisper é bem mais barato que o fluxo LLM+Athena
_MAX_PREFERENCE_CHARS = 150
_MAX_LOGIN_ATTEMPTS = 3
_LOGIN_LOCKOUT_SECONDS = 60


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


@st.cache_resource
def _create_login_attempt_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de tentativas de login incorretas por IP."""
    return {}


_login_attempt_history = _create_login_attempt_history()


def _get_client_ip() -> str:
    """Extrai o IP do cliente a partir do header X-Forwarded-For repassado pelo Caddy."""
    # Confiar no primeiro valor só é seguro porque o Caddyfile sobrescreve X-Forwarded-For
    # (header_up) em vez de anexar — do contrário um cliente poderia forjar esse valor e
    # burlar o rate limit por IP abaixo.
    forwarded = st.context.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else "local"


def _events_in_window(history: dict[str, list[float]], ip: str, window_seconds: int) -> int:
    """Conta eventos dentro da janela de tempo (em segundos) para o IP no histórico
    informado e limpa registros expirados. Reusada para consultas (`_ip_history`),
    transcrições (`_audio_ip_history`) e tentativas de login incorretas (`_login_attempt_history`)."""
    now = time.time()
    filtered = [t for t in history.get(ip, []) if t > now - window_seconds]
    history[ip] = filtered
    return len(filtered)


def _seconds_until_available(history: dict[str, list[float]], ip: str, window_seconds: int) -> int:
    """Calcula quantos segundos faltam até o evento mais antigo do IP expirar, na janela
    de tempo (em segundos) informada."""
    entries = history.get(ip, [])
    if not entries:
        return 0
    return max(0, math.ceil(entries[0] + window_seconds - time.time()))


st.set_page_config(page_title="FilmBot", page_icon="🎬", layout="wide")

_client_ip = _get_client_ip()

# ==============================================================================
# AUTENTICAÇÃO
# ==============================================================================
if not st.session_state.get("authenticated"):
    load_login_css()

    _failed_attempts = _events_in_window(_login_attempt_history, _client_ip, _LOGIN_LOCKOUT_SECONDS)
    _locked_out = _failed_attempts >= _MAX_LOGIN_ATTEMPTS

    _, col, _ = st.columns([1, 1.1, 1])
    with col:
        with st.container(key="login-card"):
            st.markdown("""
            <p class="login-title">🎬 <span class="accent-gradient-text">FilmBot</span></p>
            <p class="login-subtitle">Seu assistente de filmes e séries com IA</p>
            <hr class="login-divider">
            """, unsafe_allow_html=True)

            password = st.text_input(
                "", placeholder="Digite a senha de acesso...",
                type="password", label_visibility="collapsed",
            )
            error_placeholder = st.empty()
            submit = st.button(
                "Entrar →", use_container_width=True, key="btn_entrar",
                disabled=_locked_out or not password,
            )
            load_login_button_toggle_script(_locked_out)

            if _locked_out:
                _seconds = _seconds_until_available(_login_attempt_history, _client_ip, _LOGIN_LOCKOUT_SECONDS)
                with error_placeholder:
                    render_feedback(
                        "warning",
                        "Muitas tentativas incorretas. Tente novamente em",
                        extra_html=' <span class="time-countdown" id="countdown"></span>.',
                    )
                load_countdown_script(_seconds)
            elif submit and password == st.secrets.get("auth", {}).get("password", ""):
                st.session_state["authenticated"] = True
                st.rerun()
            elif submit and password:
                _login_attempt_history.setdefault(_client_ip, []).append(time.time())
                if _events_in_window(_login_attempt_history, _client_ip, _LOGIN_LOCKOUT_SECONDS) >= _MAX_LOGIN_ATTEMPTS:
                    st.rerun()
                with error_placeholder:
                    render_feedback("error", "Senha incorreta. Tente novamente.")

    render_login_footer()
    st.stop()

# ==============================================================================
# PÁGINA PRINCIPAL
# ==============================================================================
load_main_css()

with st.container(key="header-row"):
    title_col, logout_col = st.columns([9, 1])
    with title_col:
        st.markdown(
            '<div class="header-brand">'
            '<span class="header-icon">🎬</span>'
            '<div class="header-text">'
            '<p class="header-title">FilmBot</p>'
            '<p class="header-subtitle">Seu assistente de filmes e séries com IA</p>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    with logout_col:
        if st.button("Sair", key="btn_sair"):
            st.session_state["authenticated"] = False
            st.rerun()

with st.container(key="hero-section"):
    st.markdown(
        """
        <div class="hero-heading-wrap">
          <h1 class="hero-heading">O que você quer <span class="accent-gradient-text">assistir</span> hoje?</h1>
          <p class="hero-subtitle">Digite ou grave o seu pedido</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Card único (fundo cinza + borda) envolvendo textarea + gravador +
    # contador — substitui o fundo próprio que só a textarea tinha antes,
    # unificando os três num painel só. Placeholders criados na ordem visual
    # desejada (texto em cima, gravador embaixo) dentro dele. Um
    # st.container() reserva a posição no layout no momento em que é criado
    # — pode ser populado depois, em qualquer ordem. Isso deixa popular
    # footer_slot (áudio) ANTES de text_area_slot (texto), como a regra de
    # session_state abaixo exige, com o gravador aparecendo depois na tela.
    input_card = st.container(key="input-card")
    with input_card:
        text_area_slot = st.container(key="text-area-slot")
        footer_slot = st.container(key="input-footer-row")
    # Avisos de transcrição (áudio muito longo, erro, rate limit, etc.) e o
    # status "Transcrevendo áudio..." ficam fora do card cinza, abaixo dele —
    # não são parte do "formulário" em si, são feedback sobre uma ação em
    # andamento ou já concluída (ou rejeitada).
    audio_messages_slot = st.container(key="audio-messages")

    # ------------------------------------------------------------------
    # CAPTURA DE ÁUDIO E TRANSCRIÇÃO (precisa rodar ANTES do text_area abaixo:
    # o Streamlit proíbe setar session_state["preference_text"] depois que o
    # widget com essa key já rodou no mesmo script run).
    # ------------------------------------------------------------------
    with footer_slot:
        with st.container(key="recorder-card"):
            _audio_widget_seq = st.session_state.get("audio_widget_seq", 0)
            audio_value = st.audio_input(
                "Gravar preferência em áudio", label_visibility="collapsed",
                key=f"audio_input_{_audio_widget_seq}",
            )
            _max_audio_label = f"{_MAX_AUDIO_SECONDS // 60:02d}:{_MAX_AUDIO_SECONDS % 60:02d}"
            st.markdown(
                f'<span id="audio-timer-badge" class="recorder-timer">00:00 / {_max_audio_label}</span>',
                unsafe_allow_html=True,
            )

        _audio_queries_made = _events_in_window(_audio_ip_history, _client_ip, 3600)
        _audio_remaining = _MAX_TRANSCRIPTIONS_PER_HOUR - _audio_queries_made

        if (
            audio_value is not None
            and not st.session_state.get("transcribing")
            and not st.session_state.get("audio_awaiting_confirmation")
        ):
            audio_bytes = audio_value.getvalue()
            audio_hash = hashlib.md5(audio_bytes).hexdigest()
            if audio_hash != st.session_state.get("audio_last_hash"):
                st.session_state["audio_last_hash"] = audio_hash
                st.session_state["transcription_error"] = False
                st.session_state["transcription_empty"] = False
                st.session_state["transcription_too_long"] = False
                st.session_state["transcription_rate_limited"] = False
                st.session_state["transcription_truncated"] = False
                # Checa a duração já aqui, assim que os bytes chegam — não importa qual
                # script JS parou a gravação (limite de tempo ou clique manual), a
                # decisão de rejeitar fica determinística no servidor, sem depender do
                # fluxo de confirmação nem do round-trip assíncrono de transcrição.
                # + _AUDIO_DURATION_TOLERANCE_SECONDS: o auto-stop no cliente
                # (audio_timer.js) já para a gravação assim que o tempo decorrido
                # atinge _MAX_AUDIO_SECONDS — um áudio que usou o tempo cheio (o caso
                # normal, não abuso) mede um pouco além disso por jitter do poll de
                # 250ms + arredondamento de encoding (ver constante em agent.py).
                # Rejeitar sem essa folga barrava exatamente quem gravou até o limite
                # em vez de transcrever.
                if _audio_duration_seconds(audio_bytes) > _MAX_AUDIO_SECONDS + _AUDIO_DURATION_TOLERANCE_SECONDS:
                    st.session_state["transcription_too_long"] = True
                    st.session_state["audio_widget_seq"] = _audio_widget_seq + 1
                else:
                    st.session_state["audio_pending_bytes"] = audio_bytes
                    st.session_state["audio_awaiting_confirmation"] = True
                st.rerun()

        if st.session_state.get("audio_awaiting_confirmation"):
            if _audio_remaining <= 0:
                st.session_state["audio_awaiting_confirmation"] = False
                st.session_state.pop("audio_pending_bytes", None)
                st.session_state["transcription_rate_limited"] = True
                st.session_state["audio_widget_seq"] = _audio_widget_seq + 1
                st.rerun()
            else:
                with st.container(key="audio-confirm-buttons"):
                    use_clicked = st.button("▶️ Usar gravação", type="primary", key="btn_usar_audio")
                    cancel_clicked = st.button("✕ Cancelar", key="btn_cancelar_audio")

                if use_clicked:
                    st.session_state["audio_awaiting_confirmation"] = False
                    # .pop(..., None) em vez de .pop() puro: o clique de "Usar gravação"
                    # é simulado via JS (audio_cancel_recording.js), que agora só clica
                    # uma vez por instância do botão — mas essa checagem aqui é rede de
                    # segurança extra contra qualquer evento duplicado que ainda chegue
                    # ao backend, evitando KeyError num segundo pop() e uma submissão
                    # duplicada pro executor.
                    pending_bytes = st.session_state.pop("audio_pending_bytes", None)
                    # Reseta o widget (nova key) também no caminho de sucesso: sem isso, o
                    # gravador nativo mantém o botão "▶️ Play" da gravação já usada
                    # indefinidamente (recordingUrl só é limpo trocando a key do widget),
                    # e o CSS que trava a largura do card em repouso (principal.css) corta
                    # esse botão extra por não esperar um segundo botão nesse estado.
                    st.session_state["audio_widget_seq"] = _audio_widget_seq + 1
                    if pending_bytes is not None:
                        _audio_ip_history.setdefault(_client_ip, []).append(time.time())
                        st.session_state["transcribing"] = True
                        st.session_state["transcription_future"] = _executor.submit(
                            transcribe_preference, pending_bytes
                        )
                    st.rerun()
                elif cancel_clicked:
                    st.session_state["audio_awaiting_confirmation"] = False
                    st.session_state.pop("audio_pending_bytes", None)
                    st.session_state["audio_widget_seq"] = _audio_widget_seq + 1
                    st.rerun()

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
                # audio_messages_slot (fora do card cinza, ver comentário acima em sua
                # criação) em vez de st.caption() direto aqui dentro: esse texto é
                # feedback sobre uma ação em andamento, não parte do formulário, mesmo
                # motivo pelo qual os avisos/erros de transcrição já vivem lá fora.
                with audio_messages_slot:
                    st.caption("🎤 Transcrevendo áudio...")
                time.sleep(0.5)
                st.rerun()

    with audio_messages_slot:
        if st.session_state.get("transcription_rate_limited"):
            _audio_seconds = _seconds_until_available(_audio_ip_history, _client_ip, 3600)
            render_feedback(
                "warning",
                f"Limite de {_MAX_TRANSCRIPTIONS_PER_HOUR} transcrições por hora atingido. "
                "Disponível novamente em",
                extra_html=(
                    ' <span class="time-countdown" id="audio-countdown"></span>.'
                    " Digite sua preferência manualmente enquanto isso."
                ),
            )
            load_countdown_script(_audio_seconds, element_id="audio-countdown")
        if st.session_state.get("transcription_too_long"):
            render_feedback("warning", f"Áudio muito longo (máx. {_MAX_AUDIO_SECONDS}s).")
        if st.session_state.get("transcription_error"):
            render_feedback("error", "Erro ao transcrever. Digite manualmente.")
        if st.session_state.get("transcription_empty"):
            render_feedback(
                "warning",
                "Não detectamos fala no áudio. Tente gravar novamente ou digite sua preferência.",
            )
        if st.session_state.get("transcription_truncated"):
            render_feedback(
                "warning",
                f"Transcrição excedeu {_MAX_PREFERENCE_CHARS} caracteres e foi cortada.",
            )

    with text_area_slot:
        preference = st.text_area(
            "O que você quer assistir?",
            placeholder="Ex: filmes de terror dos anos 2010. Séries mais populares da HBO.",
            height=120,
            max_chars=_MAX_PREFERENCE_CHARS,
            key="preference_text",
            label_visibility="collapsed",
        )

_queries_made = _events_in_window(_ip_history, _client_ip, 3600)
_remaining = _MAX_QUERIES_PER_HOUR - _queries_made

# ==============================================================================
# LÓGICA DO BOTÃO E BUSCA ASSÍNCRONA
# ==============================================================================
searching = st.session_state.get("searching", False)

with st.container(key="hero-actions"):
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
        if st.button(
            "✨ Recomendar",
            type="primary",
            disabled=_remaining <= 0 or not preference,
            use_container_width=True,
            key="btn_recomendar",
        ) and preference:
            _ip_history.setdefault(_client_ip, []).append(time.time())
            st.session_state["future"] = _executor.submit(recommend, preference)
            st.session_state["searching"] = True
            st.session_state["search_completed"] = False
            st.session_state["search_error"] = False
            st.session_state["titles"] = []
            st.rerun()

    if _remaining <= 0:
        _seconds = _seconds_until_available(_ip_history, _client_ip, 3600)
        render_feedback(
            "warning",
            f"Limite de {_MAX_QUERIES_PER_HOUR} consultas atingido. Disponível novamente em",
            extra_html=' <span class="time-countdown" id="countdown"></span>.',
        )
        load_countdown_script(_seconds)
    else:
        _counter_class = "query-counter-text query-counter-low" if _remaining <= 3 else "query-counter-text"
        st.markdown(
            f'<p class="{_counter_class}">Consultas restantes: '
            f'{_remaining}/{_MAX_QUERIES_PER_HOUR} por hora</p>',
            unsafe_allow_html=True,
        )

# Fica fora do container do hero/actions de propósito: é só um injetor de JS
# (height=0, sem presença visual), e a posição no DOM não importa (cada
# script busca o textarea globalmente via querySelector). Colocado depois de
# hero-actions (não entre hero-section e hero-actions) porque cada
# st.container() de nível superior é um item a mais no `gap` do bloco
# vertical da página — entre os dois, ele dobrava o respiro do botão
# "Recomendar" em relação à textarea (32px em vez dos 16px do gap normal).
with st.container(key="hero-scripts"):
    load_preference_counter_script(_MAX_PREFERENCE_CHARS, rate_limited=_remaining <= 0)
    load_audio_cancel_script()
    load_audio_timer_script(_MAX_AUDIO_SECONDS)
    load_textarea_autogrow_script()

# ==============================================================================
# EXIBIÇÃO DOS RESULTADOS
# ==============================================================================
titles = st.session_state.get("titles", [])
_search_error = st.session_state.get("search_error")
_no_results = st.session_state.get("search_completed") and not titles and not _search_error

if _search_error or _no_results:
    with st.container(key="results-messages"):
        if _search_error:
            render_feedback(
                "error",
                "Algo deu errado ao buscar as recomendações. Tente novamente em instantes.",
            )
        if _no_results:
            render_feedback(
                "warning",
                "Não encontramos nada com essa descrição. Tente usar outras palavras ou "
                "ser mais específico.",
            )

if titles:
    word = "opção" if len(titles) == 1 else "opções"
    st.markdown(
        f'<hr class="results-divider">'
        f'<p class="results-heading">Encontramos {len(titles)} {word} para você!</p>',
        unsafe_allow_html=True,
    )
    st.html(render_grid(titles))

render_footer()
