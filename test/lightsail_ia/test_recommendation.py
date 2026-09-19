import hashlib
from unittest.mock import MagicMock

import pytest
from src import recommendation


class _Rerun(Exception):
    """Sinaliza st.rerun() — em produção ele aborta o script imediatamente; usar
    side_effect=_Rerun no mock reproduz esse corte (essencial aqui: quase todo ramo desta
    função termina em rerun, e sem o corte o código seguinte executaria por engano em
    modo bare, misturando estados de branches diferentes numa mesma chamada de teste)."""


class _FakeFuture:
    def __init__(self, done: bool = True, result=None, exception: BaseException | None = None):
        self._done = done
        self._result = result
        self._exception = exception

    def done(self) -> bool:
        return self._done

    def result(self):
        if self._exception is not None:
            raise self._exception
        return self._result


class _FakeAudioValue:
    def __init__(self, data: bytes):
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _stub(monkeypatch, initial_state: dict | None = None, rerun_raises: bool = True) -> dict:
    session_state = dict(initial_state or {})
    monkeypatch.setattr(recommendation.st, "session_state", session_state)
    rerun = MagicMock(side_effect=_Rerun) if rerun_raises else MagicMock()
    monkeypatch.setattr(recommendation.st, "rerun", rerun)
    monkeypatch.setattr(recommendation.time, "sleep", MagicMock())
    monkeypatch.setattr(recommendation.st, "audio_input", lambda *a, **k: None)
    monkeypatch.setattr(recommendation.st, "text_area", lambda *a, **k: "")
    monkeypatch.setattr(recommendation.st, "button", lambda *a, key=None, **k: False)
    mocks = {"session_state": session_state, "rerun": rerun}
    for name in (
        "load_recommendation_css", "load_countdown_script", "render_feedback",
        "load_preference_counter_script", "load_audio_cancel_script",
        "load_audio_timer_script", "load_textarea_autogrow_script",
    ):
        m = MagicMock()
        monkeypatch.setattr(recommendation, name, m)
        mocks[name] = m
    return mocks


def _patch_button(monkeypatch, clicked_keys: set):
    monkeypatch.setattr(recommendation.st, "button", lambda *a, key=None, **k: key in clicked_keys)


def _patch_executor_submit(monkeypatch, future):
    submit = MagicMock(return_value=future)
    monkeypatch.setattr(recommendation._executor, "submit", submit)
    return submit


@pytest.fixture(autouse=True)
def _limpar_rate_limit_histories():
    recommendation._ip_history.clear()
    recommendation._audio_ip_history.clear()


class TestGreeting:
    def test_com_nome_exibe_primeiro_nome_na_saudacao(self, monkeypatch):
        _stub(monkeypatch, {"user_name": "Ana Silva"}, rerun_raises=False)
        calls = []
        monkeypatch.setattr(recommendation.st, "markdown", lambda content, **k: calls.append(content))

        recommendation.render_recommendation("1.2.3.4")

        assert any("Olá" in c and "Ana" in c for c in calls)

    def test_sem_nome_nao_exibe_saudacao(self, monkeypatch):
        _stub(monkeypatch, {}, rerun_raises=False)
        calls = []
        monkeypatch.setattr(recommendation.st, "markdown", lambda content, **k: calls.append(content))

        recommendation.render_recommendation("1.2.3.4")

        assert not any("Olá" in c for c in calls)


class TestEstadoOcioso:
    def test_sem_audio_sem_busca_completa_sem_chamar_rerun(self, monkeypatch):
        mocks = _stub(monkeypatch, {})

        recommendation.render_recommendation("1.2.3.4")

        mocks["rerun"].assert_not_called()
        mocks["load_preference_counter_script"].assert_called_once()


class TestCapturaDeAudio:
    def test_audio_novo_dentro_do_limite_marca_aguardando_confirmacao(self, monkeypatch):
        mocks = _stub(monkeypatch, {})
        audio_bytes = b"audio-valido"
        monkeypatch.setattr(recommendation.st, "audio_input", lambda *a, **k: _FakeAudioValue(audio_bytes))
        monkeypatch.setattr(recommendation, "_audio_duration_seconds", lambda data: 5.0)

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        state = mocks["session_state"]
        assert state["audio_awaiting_confirmation"] is True
        assert state["audio_pending_bytes"] == audio_bytes
        assert state["audio_last_hash"] == hashlib.sha256(audio_bytes).hexdigest()
        assert state["transcription_too_long"] is False

    def test_audio_muito_longo_marca_flag_sem_pedir_confirmacao(self, monkeypatch):
        mocks = _stub(monkeypatch, {})
        audio_bytes = b"audio-longo-demais"
        monkeypatch.setattr(recommendation.st, "audio_input", lambda *a, **k: _FakeAudioValue(audio_bytes))
        monkeypatch.setattr(recommendation, "_audio_duration_seconds", lambda data: 999.0)

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        state = mocks["session_state"]
        assert state["transcription_too_long"] is True
        assert "audio_pending_bytes" not in state
        assert state["audio_widget_seq"] == 1

    def test_mesmo_audio_de_antes_nao_reprocessa(self, monkeypatch):
        audio_bytes = b"audio-repetido"
        audio_hash = hashlib.sha256(audio_bytes).hexdigest()
        mocks = _stub(monkeypatch, {"audio_last_hash": audio_hash})
        monkeypatch.setattr(recommendation.st, "audio_input", lambda *a, **k: _FakeAudioValue(audio_bytes))

        recommendation.render_recommendation("1.2.3.4")

        mocks["rerun"].assert_not_called()


class TestConfirmacaoDeAudio:
    def test_rate_limit_atingido_cancela_confirmacao_automaticamente(self, monkeypatch):
        client_ip = "1.2.3.4"
        recommendation._audio_ip_history[client_ip] = [recommendation.time.time()] * recommendation._MAX_TRANSCRIPTIONS_PER_HOUR
        mocks = _stub(monkeypatch, {
            "audio_awaiting_confirmation": True, "audio_pending_bytes": b"x",
        })

        with pytest.raises(_Rerun):
            recommendation.render_recommendation(client_ip)

        state = mocks["session_state"]
        assert state["audio_awaiting_confirmation"] is False
        assert "audio_pending_bytes" not in state
        assert state["transcription_rate_limited"] is True

    def test_rate_limit_atingido_nao_renderiza_botoes_de_confirmacao(self, monkeypatch):
        # Confirma que a função retorna assim que marca o rate limit, sem cair no bloco
        # de botões usar/cancelar — só observável com rerun sem abortar (rerun_raises=False),
        # já que em produção o st.rerun() real já corta a execução sozinho.
        client_ip = "1.2.3.4"
        recommendation._audio_ip_history[client_ip] = [recommendation.time.time()] * recommendation._MAX_TRANSCRIPTIONS_PER_HOUR
        _stub(monkeypatch, {
            "audio_awaiting_confirmation": True, "audio_pending_bytes": b"x",
        }, rerun_raises=False)
        button = MagicMock(return_value=False)
        monkeypatch.setattr(recommendation.st, "button", button)

        recommendation.render_recommendation(client_ip)

        chamadas_com_key = {c.kwargs.get("key") for c in button.call_args_list}
        assert "btn_usar_audio" not in chamadas_com_key
        assert "btn_cancelar_audio" not in chamadas_com_key

    def test_usar_gravacao_submete_transcricao_no_executor(self, monkeypatch):
        mocks = _stub(monkeypatch, {
            "audio_awaiting_confirmation": True, "audio_pending_bytes": b"abc",
        })
        _patch_button(monkeypatch, {"btn_usar_audio"})
        future = _FakeFuture(done=False)
        submit = _patch_executor_submit(monkeypatch, future)

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        submit.assert_called_once_with(recommendation.transcribe_preference, b"abc")
        state = mocks["session_state"]
        assert state["transcribing"] is True
        assert state["transcription_future"] is future
        assert "audio_pending_bytes" not in state

    def test_cancelar_gravacao_descarta_bytes_pendentes(self, monkeypatch):
        mocks = _stub(monkeypatch, {
            "audio_awaiting_confirmation": True, "audio_pending_bytes": b"abc",
        })
        _patch_button(monkeypatch, {"btn_cancelar_audio"})

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        state = mocks["session_state"]
        assert state["audio_awaiting_confirmation"] is False
        assert "audio_pending_bytes" not in state

    def test_sem_clique_mantem_estado_de_confirmacao_sem_rerun(self, monkeypatch):
        mocks = _stub(monkeypatch, {
            "audio_awaiting_confirmation": True, "audio_pending_bytes": b"abc",
        })

        recommendation.render_recommendation("1.2.3.4")

        mocks["rerun"].assert_not_called()
        assert mocks["session_state"]["audio_awaiting_confirmation"] is True


class TestTranscricaoEmAndamento:
    def test_ainda_nao_concluida_mostra_status_e_aguarda(self, monkeypatch):
        _stub(monkeypatch, {
            "transcribing": True, "transcription_future": _FakeFuture(done=False),
        })

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        recommendation.time.sleep.assert_called_once()

    def test_concluida_com_texto_grava_preference_text(self, monkeypatch):
        mocks = _stub(monkeypatch, {
            "transcribing": True,
            "transcription_future": _FakeFuture(done=True, result="filmes de terror"),
        })

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        state = mocks["session_state"]
        assert state["transcribing"] is False
        assert state["preference_text"] == "filmes de terror"

    def test_concluida_sem_texto_marca_transcricao_vazia(self, monkeypatch):
        mocks = _stub(monkeypatch, {
            "transcribing": True, "transcription_future": _FakeFuture(done=True, result=""),
        })

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        state = mocks["session_state"]
        assert state["transcription_empty"] is True
        assert "preference_text" not in state

    def test_texto_maior_que_limite_e_truncado(self, monkeypatch):
        texto_longo = "a" * (recommendation._MAX_PREFERENCE_CHARS + 50)
        mocks = _stub(monkeypatch, {
            "transcribing": True, "transcription_future": _FakeFuture(done=True, result=texto_longo),
        })

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        state = mocks["session_state"]
        assert len(state["preference_text"]) == recommendation._MAX_PREFERENCE_CHARS
        assert state["transcription_truncated"] is True

    def test_audio_muito_longo_durante_transcricao_marca_flag(self, monkeypatch):
        mocks = _stub(monkeypatch, {
            "transcribing": True,
            "transcription_future": _FakeFuture(done=True, exception=recommendation.AudioMuitoLongoError()),
        })

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        assert mocks["session_state"]["transcription_too_long"] is True

    def test_erro_generico_na_transcricao_marca_flag_de_erro(self, monkeypatch):
        mocks = _stub(monkeypatch, {
            "transcribing": True,
            "transcription_future": _FakeFuture(done=True, exception=RuntimeError("boom")),
        })

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        assert mocks["session_state"]["transcription_error"] is True


class TestMensagensDeTranscricao:
    def test_rate_limited_mostra_aviso_com_countdown(self, monkeypatch):
        mocks = _stub(monkeypatch, {"transcription_rate_limited": True})

        recommendation.render_recommendation("1.2.3.4")

        mocks["render_feedback"].assert_called_once()
        assert mocks["render_feedback"].call_args.args[0] == "warning"
        mocks["load_countdown_script"].assert_called_once()

    def test_audio_muito_longo_mostra_aviso(self, monkeypatch):
        mocks = _stub(monkeypatch, {"transcription_too_long": True})

        recommendation.render_recommendation("1.2.3.4")

        assert mocks["render_feedback"].call_args.args[0] == "warning"

    def test_erro_de_transcricao_mostra_mensagem_de_erro(self, monkeypatch):
        mocks = _stub(monkeypatch, {"transcription_error": True})

        recommendation.render_recommendation("1.2.3.4")

        assert mocks["render_feedback"].call_args.args[0] == "error"

    def test_transcricao_vazia_mostra_aviso(self, monkeypatch):
        mocks = _stub(monkeypatch, {"transcription_empty": True})

        recommendation.render_recommendation("1.2.3.4")

        assert mocks["render_feedback"].call_args.args[0] == "warning"

    def test_transcricao_truncada_mostra_aviso(self, monkeypatch):
        mocks = _stub(monkeypatch, {"transcription_truncated": True})

        recommendation.render_recommendation("1.2.3.4")

        assert mocks["render_feedback"].call_args.args[0] == "warning"


class TestBotaoRecomendar:
    def test_limite_atingido_mostra_aviso_com_countdown(self, monkeypatch):
        client_ip = "1.2.3.4"
        recommendation._ip_history[client_ip] = [recommendation.time.time()] * recommendation._MAX_QUERIES_PER_HOUR
        mocks = _stub(monkeypatch, {})

        recommendation.render_recommendation(client_ip)

        mocks["render_feedback"].assert_called_once()
        assert mocks["render_feedback"].call_args.args[0] == "warning"
        mocks["load_countdown_script"].assert_called_once()

    def test_contador_baixo_usa_classe_de_destaque(self, monkeypatch):
        client_ip = "1.2.3.4"
        recommendation._ip_history[client_ip] = [recommendation.time.time()] * (recommendation._MAX_QUERIES_PER_HOUR - 2)
        _stub(monkeypatch, {})
        calls = []
        monkeypatch.setattr(recommendation.st, "markdown", lambda content, **k: calls.append(content))

        recommendation.render_recommendation(client_ip)

        assert any("query-counter-low" in c for c in calls)

    def test_clique_com_preferencia_submete_busca_no_executor(self, monkeypatch):
        mocks = _stub(monkeypatch, {})
        monkeypatch.setattr(recommendation.st, "text_area", lambda *a, **k: "filmes de terror")
        _patch_button(monkeypatch, {"btn_recomendar"})
        future = _FakeFuture(done=False)
        submit = _patch_executor_submit(monkeypatch, future)

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        submit.assert_called_once_with(recommendation.recommend, "filmes de terror")
        state = mocks["session_state"]
        assert state["searching"] is True
        assert state["future"] is future
        assert state["search_completed"] is False

    def test_clique_sem_preferencia_nao_submete_busca(self, monkeypatch):
        mocks = _stub(monkeypatch, {})
        monkeypatch.setattr(recommendation.st, "text_area", lambda *a, **k: "")
        _patch_button(monkeypatch, {"btn_recomendar"})
        submit = _patch_executor_submit(monkeypatch, _FakeFuture())

        recommendation.render_recommendation("1.2.3.4")

        submit.assert_not_called()
        mocks["rerun"].assert_not_called()


class TestBuscaEmAndamento:
    def test_ainda_buscando_mostra_spinner_e_aguarda(self, monkeypatch):
        _stub(monkeypatch, {"searching": True, "future": _FakeFuture(done=False)})

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        recommendation.time.sleep.assert_called_once()

    def test_cancelar_busca_reseta_estado(self, monkeypatch):
        mocks = _stub(monkeypatch, {
            "searching": True, "future": _FakeFuture(done=False), "titles": [{"title": "X"}],
        })
        _patch_button(monkeypatch, {"btn_cancelar"})

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        state = mocks["session_state"]
        assert state["searching"] is False
        assert state["search_completed"] is False
        assert state["titles"] == []
        assert state["future"] is None

    def test_busca_concluida_com_sucesso_grava_titulos(self, monkeypatch):
        titulos = [{"title": "Duna"}]
        mocks = _stub(monkeypatch, {
            "searching": True, "future": _FakeFuture(done=True, result=titulos),
        })

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        state = mocks["session_state"]
        assert state["searching"] is False
        assert state["search_completed"] is True
        assert state["titles"] == titulos

    def test_busca_concluida_com_erro_marca_flag_e_esvazia_titulos(self, monkeypatch):
        mocks = _stub(monkeypatch, {
            "searching": True, "future": _FakeFuture(done=True, exception=RuntimeError("boom")),
        })

        with pytest.raises(_Rerun):
            recommendation.render_recommendation("1.2.3.4")

        state = mocks["session_state"]
        assert state["search_error"] is True
        assert state["titles"] == []


class TestFeedbackDeResultado:
    def test_erro_de_busca_mostra_mensagem_de_erro(self, monkeypatch):
        mocks = _stub(monkeypatch, {"search_error": True})

        recommendation.render_recommendation("1.2.3.4")

        assert any(c.args[0] == "error" for c in mocks["render_feedback"].call_args_list)

    def test_busca_concluida_sem_resultados_mostra_aviso(self, monkeypatch):
        mocks = _stub(monkeypatch, {"search_completed": True, "titles": []})

        recommendation.render_recommendation("1.2.3.4")

        assert any(c.args[0] == "warning" for c in mocks["render_feedback"].call_args_list)

    def test_busca_concluida_com_resultados_nao_mostra_feedback_de_erro_ou_vazio(self, monkeypatch):
        mocks = _stub(monkeypatch, {"search_completed": True, "titles": [{"title": "Duna"}]})

        recommendation.render_recommendation("1.2.3.4")

        mocks["render_feedback"].assert_not_called()
