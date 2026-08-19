"""recommendation.py — formulário de preferência (texto/áudio) e busca assíncrona do FilmBot."""

import hashlib
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor

import streamlit as st
from src.agent import (
    _AUDIO_DURATION_TOLERANCE_SECONDS,
    _MAX_AUDIO_SECONDS,
    AudioMuitoLongoError,
    _audio_duration_seconds,
    recommend,
    transcribe_preference,
)
from src.components import (
    icon,
    load_audio_cancel_script,
    load_audio_timer_script,
    load_countdown_script,
    load_preference_counter_script,
    load_recommendation_css,
    load_textarea_autogrow_script,
    render_feedback,
)
from src.infrastructure import (
    events_in_window,
    seconds_until_available,
)

_executor = ThreadPoolExecutor(max_workers=2)

_MAX_QUERIES_PER_HOUR = 15
_MAX_TRANSCRIPTIONS_PER_HOUR = 30  # Whisper é bem mais barato que o fluxo LLM+Athena
_MAX_PREFERENCE_CHARS = 150


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


def render_recommendation(client_ip: str) -> None:
    """Renderiza o formulário de preferência (texto/áudio) e dispara/acompanha a
    busca assíncrona de recomendações. Os resultados ficam em `st.session_state`
    (`titles`, `search_error`, `search_completed`) para a tela de cards consumir."""
    load_recommendation_css()

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

            _audio_queries_made = events_in_window(_audio_ip_history, client_ip, 3600)
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
                        # e o CSS que trava a largura do card em repouso (recommendation.css) corta
                        # esse botão extra por não esperar um segundo botão nesse estado.
                        st.session_state["audio_widget_seq"] = _audio_widget_seq + 1
                        if pending_bytes is not None:
                            _audio_ip_history.setdefault(client_ip, []).append(time.time())
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
                        st.caption(
                            f'{icon("mic", size=14)} Transcrevendo áudio...',
                            unsafe_allow_html=True,
                        )
                    time.sleep(0.5)
                    st.rerun()

        with audio_messages_slot:
            if st.session_state.get("transcription_rate_limited"):
                _audio_seconds = seconds_until_available(_audio_ip_history, client_ip, 3600)
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

    _queries_made = events_in_window(_ip_history, client_ip, 3600)
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
                "Recomendar",
                type="primary",
                disabled=_remaining <= 0,
                use_container_width=True,
                key="btn_recomendar",
            ) and preference:
                _ip_history.setdefault(client_ip, []).append(time.time())
                st.session_state["future"] = _executor.submit(recommend, preference)
                st.session_state["searching"] = True
                st.session_state["search_completed"] = False
                st.session_state["search_error"] = False
                st.session_state["titles"] = []
                st.rerun()

        if _remaining <= 0:
            _seconds = seconds_until_available(_ip_history, client_ip, 3600)
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

        # Erro de busca/sem-resultado ficam empilhados aqui embaixo (não em cards.py) para
        # aparecerem sempre perto do botão "Recomendar" — no lugar do rate limit quando
        # sozinhos, ou logo abaixo dele quando os dois coexistem — em vez de lá embaixo,
        # depois do rodapé.
        _search_error = st.session_state.get("search_error")
        _titles = st.session_state.get("titles", [])
        _no_results = st.session_state.get("search_completed") and not _titles and not _search_error
        if _search_error:
            render_feedback(
                "error",
                "Algo deu errado ao buscar as recomendações. Tente novamente em instantes.",
            )
        elif _no_results:
            render_feedback(
                "warning",
                "Não encontramos nada com essa descrição. Tente usar outras palavras ou "
                "ser mais específico.",
            )

    # Fica fora do container do hero/actions de propósito: é só um injetor de JS
    # (height=0, sem presença visual), e a posição no DOM não importa (cada
    # script busca o textarea globalmente via querySelector). Colocado depois de
    # hero-actions (não entre hero-section e hero-actions) porque cada
    # st.container() de nível superior é um item a mais no `gap` do bloco
    # vertical da página — entre os dois, ele dobrava o respiro do botão
    # "Recomendar" em relação à textarea (32px em vez dos 16px do gap normal).
    # O mesmo efeito aparece do lado de baixo (hero-scripts → título dos
    # resultados, em cards.py) — ver .results-heading em cards.css, que também
    # precisa de !important pra vencer a margem nativa que o Streamlit aplica
    # por instância em <p> (achado adicional só encontrado ali).
    with st.container(key="hero-scripts"):
        load_preference_counter_script(_MAX_PREFERENCE_CHARS, rate_limited=_remaining <= 0)
        load_audio_cancel_script()
        load_audio_timer_script(_MAX_AUDIO_SECONDS)
        load_textarea_autogrow_script()
