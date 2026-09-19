"""recommendation.py — formulário de preferência (texto/áudio) e busca assíncrona do FilmBot."""

import hashlib
import html
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


def _render_recommendation_hero(full_name: str) -> None:
    """Saudação + título do formulário de preferência — extraído de
    render_recommendation()."""
    first_name = html.escape(full_name.split()[0]) if full_name else ""
    greeting_html = (
        f'<p class="hero-greeting">Olá, <span class="accent-gradient-text">{first_name}</span></p>'
        if first_name else ""
    )
    st.markdown(
        f"""
        <div class="hero-heading-wrap">
          {greeting_html}
          <h1 class="hero-heading">O que você quer <span class="accent-gradient-text">assistir</span> hoje?</h1>
          <p class="hero-subtitle">Digite ou grave o seu pedido</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_audio_recorder_widget(audio_widget_seq: int):
    """Widget nativo de gravação + badge do timer — extraído de render_recommendation().
    Retorna o valor do áudio gravado (ou None, se nada foi gravado ainda)."""
    with st.container(key="recorder-card"):
        audio_value = st.audio_input(
            "Gravar preferência em áudio", label_visibility="collapsed",
            key=f"audio_input_{audio_widget_seq}",
        )
        _max_audio_label = f"{_MAX_AUDIO_SECONDS // 60:02d}:{_MAX_AUDIO_SECONDS % 60:02d}"
        st.markdown(
            f'<span id="audio-timer-badge" class="recorder-timer">00:00 / {_max_audio_label}</span>',
            unsafe_allow_html=True,
        )
    return audio_value


def _handle_new_audio_capture(audio_value, audio_widget_seq: int) -> None:
    """Processa um áudio recém-gravado (hash + validação de duração) — extraído de
    render_recommendation(). Só é chamada quando não há transcrição/confirmação de áudio
    já em andamento. Sem efeito (sem rerun) quando o hash é igual ao do último áudio já
    processado — evita reprocessar o mesmo áudio a cada rerun do script."""
    audio_bytes = audio_value.getvalue()
    # SHA-256 (não MD5) só para não disparar o achado de hashing fraco
    # (python:S4790) do SonarQube — aqui o hash só detecta se a gravação
    # mudou desde a última, não é verificação de integridade.
    audio_hash = hashlib.sha256(audio_bytes).hexdigest()
    if audio_hash == st.session_state.get("audio_last_hash"):
        return
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
        st.session_state["audio_widget_seq"] = audio_widget_seq + 1
    else:
        st.session_state["audio_pending_bytes"] = audio_bytes
        st.session_state["audio_awaiting_confirmation"] = True
    st.rerun()


def _handle_audio_confirmation(client_ip: str, audio_widget_seq: int, audio_remaining: int) -> None:
    """Bloco "aguardando confirmação de uso do áudio" — extraído de
    render_recommendation(). Cancela a confirmação automaticamente se o rate limit de
    transcrições foi atingido nesse meio-tempo; senão mostra os botões usar/cancelar."""
    if audio_remaining <= 0:
        st.session_state["audio_awaiting_confirmation"] = False
        st.session_state.pop("audio_pending_bytes", None)
        st.session_state["transcription_rate_limited"] = True
        st.session_state["audio_widget_seq"] = audio_widget_seq + 1
        st.rerun()
        return

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
        st.session_state["audio_widget_seq"] = audio_widget_seq + 1
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
        st.session_state["audio_widget_seq"] = audio_widget_seq + 1
        st.rerun()


def _apply_transcription_result(transcription_future: Future) -> None:
    """Processa o resultado de uma transcrição concluída — extraído de
    _handle_transcription_polling() para reduzir complexidade cognitiva
    (python:S3776 do SonarQube): fora do if/else do polling, os ifs abaixo não
    herdam aninhamento extra. Retornos antecipados no lugar do try/except/else
    original preservam o mesmo comportamento (nada roda após uma exceção)."""
    try:
        text = transcription_future.result()
    except AudioMuitoLongoError:
        st.session_state["transcription_too_long"] = True
        return
    except Exception:
        logging.exception(
            "Erro ao transcrever áudio (user_email=%s, user_name=%s)",
            st.session_state.get("user_email"),
            st.session_state.get("user_name"),
        )
        st.session_state["transcription_error"] = True
        return

    if not text:
        st.session_state["transcription_empty"] = True
        return
    if len(text) > _MAX_PREFERENCE_CHARS:
        text = text[:_MAX_PREFERENCE_CHARS]
        st.session_state["transcription_truncated"] = True
    st.session_state["preference_text"] = text


def _handle_transcription_polling(audio_messages_slot) -> None:
    """Acompanha a transcrição assíncrona em andamento — extraído de
    render_recommendation()."""
    transcription_future: Future = st.session_state.get("transcription_future")
    if transcription_future and transcription_future.done():
        st.session_state["transcribing"] = False
        _apply_transcription_result(transcription_future)
        st.rerun()
    else:
        # audio_messages_slot (fora do card cinza, ver comentário na criação do slot em
        # render_recommendation()) em vez de st.caption() direto aqui dentro: esse texto é
        # feedback sobre uma ação em andamento, não parte do formulário, mesmo motivo pelo
        # qual os avisos/erros de transcrição já vivem lá fora.
        with audio_messages_slot:
            st.caption(
                f'{icon("mic", size=14)} Transcrevendo áudio...',
                unsafe_allow_html=True,
            )
        time.sleep(0.5)
        st.rerun()


def _render_transcription_messages(client_ip: str) -> None:
    """Avisos de transcrição (rate limit, muito longo, erro, vazio, truncado) — extraído de
    render_recommendation()."""
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


def _render_search_in_progress() -> None:
    """Spinner + botão "Cancelar" + processamento do resultado da busca assíncrona —
    extraído de render_recommendation(). "Recomendar" fica fora do DOM neste estado (não só
    escondido via CSS, ver render_recommendation()); "Cancelar" é checado antes do
    processamento do resultado, preservando a prioridade que já existia: um clique nesse
    mesmo rerun vence mesmo que a busca tenha terminado no mesmo instante."""
    future: Future = st.session_state.get("future")
    _search_done = bool(future and future.done())

    with st.container(key="search-status-row"):
        if not _search_done:
            st.markdown("""
            <div class="spinner-container">
              <div class="spinner"></div>
              <span class="spinner-text">Buscando as melhores opções para você...</span>
            </div>
            """, unsafe_allow_html=True)
        if st.button("Cancelar", type="primary", key="btn_cancelar"):
            st.session_state["searching"] = False
            st.session_state["search_completed"] = False
            st.session_state["search_error"] = False
            st.session_state["titles"] = []
            st.session_state["future"] = None
            st.rerun()

    if _search_done:
        st.session_state["searching"] = False
        st.session_state["search_completed"] = True
        try:
            st.session_state["titles"] = future.result()
        except Exception:
            logging.exception(
                "Erro ao buscar recomendações (user_email=%s, user_name=%s)",
                st.session_state.get("user_email"),
                st.session_state.get("user_name"),
            )
            st.session_state["search_error"] = True
            st.session_state["titles"] = []
        st.rerun()
    else:
        time.sleep(0.5)
        st.rerun()


def _render_search_trigger(client_ip: str, preference: str, remaining: int) -> None:
    """Contador de consultas restantes (ou aviso de limite) + botão "Recomendar" —
    extraído de render_recommendation()."""
    with st.container(key="query-counter-row"):
        if remaining <= 0:
            _seconds = seconds_until_available(_ip_history, client_ip, 3600)
            render_feedback(
                "warning",
                f"Limite de {_MAX_QUERIES_PER_HOUR} consultas atingido. Disponível novamente em",
                extra_html=' <span class="time-countdown" id="countdown"></span>.',
            )
            load_countdown_script(_seconds)
        else:
            _counter_class = (
                "query-counter-text query-counter-low" if remaining <= 3 else "query-counter-text"
            )
            st.markdown(
                f'<p class="{_counter_class}">Consultas restantes: '
                f'{remaining}/{_MAX_QUERIES_PER_HOUR} por hora</p>',
                unsafe_allow_html=True,
            )

        if st.button(
            "Recomendar",
            type="primary",
            disabled=remaining <= 0,
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


def _render_search_result_feedback() -> None:
    """Erro de busca / "sem resultados" — extraído de render_recommendation(). Ficam
    empilhados perto do botão "Recomendar" (não em cards.py) — no lugar do rate limit
    quando sozinhos, ou logo abaixo dele quando os dois coexistem."""
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


def render_recommendation(client_ip: str) -> None:
    """Renderiza o formulário de preferência (texto/áudio) e dispara/acompanha a
    busca assíncrona de recomendações. Os resultados ficam em `st.session_state`
    (`titles`, `search_error`, `search_completed`) para a tela de cards consumir."""
    load_recommendation_css()

    with st.container(key="hero-section"):
        _render_recommendation_hero(st.session_state.get("user_name", ""))

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
            audio_widget_seq = st.session_state.get("audio_widget_seq", 0)
            audio_value = _render_audio_recorder_widget(audio_widget_seq)

            audio_queries_made = events_in_window(_audio_ip_history, client_ip, 3600)
            audio_remaining = _MAX_TRANSCRIPTIONS_PER_HOUR - audio_queries_made

            if (
                audio_value is not None
                and not st.session_state.get("transcribing")
                and not st.session_state.get("audio_awaiting_confirmation")
            ):
                _handle_new_audio_capture(audio_value, audio_widget_seq)

            if st.session_state.get("audio_awaiting_confirmation"):
                _handle_audio_confirmation(client_ip, audio_widget_seq, audio_remaining)

            if st.session_state.get("transcribing"):
                _handle_transcription_polling(audio_messages_slot)

        with audio_messages_slot:
            _render_transcription_messages(client_ip)

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
            # Ver docstring de _render_search_in_progress() sobre por que o botão
            # "Recomendar" fica fora do DOM neste estado — contador_caracteres.js roda um
            # setInterval indefinido que força `.st-key-btn_recomendar button`.disabled
            # conforme o texto digitado (ver load_preference_counter_script(), chamado
            # incondicionalmente mais abaixo), sem saber que a busca está em andamento; com
            # o botão fora do DOM, o script não encontra nada pra mexer (guard `if (!btn)
            # return`) e a interferência desaparece.
            _render_search_in_progress()
        else:
            # Contador/aviso de rate limit ANTES do botão (não o inverso, como antes):
            # dentro de query-counter-row (flex), a ordem de origem já cobre os dois
            # breakpoints sozinha — row no desktop (1º filho à esquerda, "Recomendar" à
            # direita) e column abaixo de 520px (1º filho no topo), sem precisar de
            # `order`/row-reverse em CSS. Diferente do par áudio/texto acima, não há
            # nenhuma restrição de session_state forçando uma ordem diferente aqui:
            # _remaining/_queries_made já foram calculados antes de hero-actions.
            _render_search_trigger(client_ip, preference, _remaining)

        _render_search_result_feedback()

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
