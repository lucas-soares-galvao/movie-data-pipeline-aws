import logging
import threading
from types import SimpleNamespace

import pytest
from shared_utils import llm_metrics as m


def _resposta(model="qwen/qwen3.8-flash", prompt=10, completion=5, cost=0.001):
    return SimpleNamespace(model=model, usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, cost=cost))


class TestRecordCall:
    def test_sem_escopo_aberto_nao_faz_nada_nem_lanca(self):
        m.record_call("detecção", _resposta(), "texto", m.OK)
        m.record_failure("detecção", RuntimeError("x"), "texto")
        m.record_balance("overview_pt", fonte=1)

    def test_acumula_chamadas_tokens_custo_e_modelo(self):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", _resposta(prompt=10, completion=5, cost=0.001), "a", m.OK)
            m.record_call("tradução", _resposta(model="deepseek/v", prompt=20, completion=7, cost=0.002), "b", m.OK)
        assert usage.total_calls == 2
        assert usage.prompt_tokens == 30
        assert usage.completion_tokens == 12
        assert usage.cost == pytest.approx(0.003)
        assert usage.calls_without_cost == 0
        assert usage.models == {"qwen/qwen3.8-flash": 1, "deepseek/v": 1}

    def test_separa_as_chamadas_por_operacao(self):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", _resposta(), "a", m.OK)
            m.record_call("detecção", _resposta(), "a", m.OK)
            m.record_call("detecção", _resposta(), "b", m.OK)
        assert usage.calls_by_operation == {"tradução": 1, "detecção": 2}

    def test_custo_ausente_conta_chamada_sem_custo(self):
        resposta = SimpleNamespace(model="m", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", resposta, "a", m.OK)
        assert usage.calls_without_cost == 1
        assert usage.cost == 0

    def test_custo_cai_para_hidden_params_quando_usage_nao_tem(self):
        resposta = SimpleNamespace(
            model="m", usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            _hidden_params={"response_cost": 0.5},
        )
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", resposta, "a", m.OK)
        assert usage.cost == pytest.approx(0.5)
        assert usage.calls_without_cost == 0

    def test_resposta_sem_usage_nem_modelo_vira_desconhecido(self):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", SimpleNamespace(), "a", m.OK)
        assert usage.models == {"modelo indisponível": 1}
        assert usage.prompt_tokens == 0 and usage.completion_tokens == 0
        assert usage.calls_without_cost == 1

    def test_valores_de_tipo_invalido_sao_ignorados(self):
        """bool é subclasse de int e str não é número: nenhum dos dois pode virar token/custo."""
        resposta = SimpleNamespace(model="", usage=SimpleNamespace(prompt_tokens="10", completion_tokens=True, cost=True))
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", resposta, "a", m.OK)
        assert usage.prompt_tokens == 0 and usage.completion_tokens == 0
        assert usage.calls_without_cost == 1
        assert usage.models == {"modelo indisponível": 1}

    def test_resposta_que_lanca_ao_ser_lida_nao_derruba_a_chamada(self):
        class Quebrada:
            @property
            def usage(self):
                raise RuntimeError("boom")

        with m.llm_usage_scope() as usage:
            m.record_call("tradução", Quebrada(), "a", m.OK)
        assert usage.total_calls == 1
        assert usage.models == {"modelo indisponível": 1}

    def test_sem_mudanca_nao_e_falha(self):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", _resposta(), "sexy", m.NO_CHANGE)
        assert usage.outcomes == {m.NO_CHANGE: 1}
        assert usage.failures == {}
        assert usage.samples == {}

    def test_resposta_vazia_e_invalida_sao_falhas_com_exemplo(self):
        with m.llm_usage_scope() as usage:
            m.record_call("detecção", _resposta(), "texto a", m.EMPTY)
            m.record_call("detecção", _resposta(), "texto b", m.INVALID)
        assert usage.failures == {m.EMPTY: 1, m.INVALID: 1}
        assert usage.samples[m.EMPTY] == ["'texto a'"]


class TestRecordFailure:
    def test_causa_e_o_nome_da_classe_e_o_exemplo_traz_a_mensagem(self):
        with m.llm_usage_scope() as usage:
            m.record_failure("detecção", ImportError("tenacity import failed"), "Cupido, o mensageiro")
        assert usage.failures == {"ImportError": 1}
        assert usage.total_calls == 1
        assert usage.samples["ImportError"] == ["'Cupido, o mensageiro': tenacity import failed"]

    def test_guarda_no_maximo_3_exemplos_por_causa(self):
        with m.llm_usage_scope() as usage:
            for i in range(5):
                m.record_failure("tradução", TimeoutError("t"), f"texto {i}")
        assert usage.failures == {"TimeoutError": 5}
        assert len(usage.samples["TimeoutError"]) == 3

    def test_trunca_texto_e_mensagem_longos(self):
        with m.llm_usage_scope() as usage:
            m.record_failure("tradução", RuntimeError("e" * 500), "t" * 500)
        exemplo = usage.samples["RuntimeError"][0]
        assert "t" * 80 + "…" in exemplo
        assert "e" * 100 + "…" in exemplo
        assert len(exemplo) < 250


class TestEscopos:
    def test_escopos_aninhados_acumulam_nos_dois(self):
        with m.llm_usage_scope() as externo:
            m.record_call("tradução", _resposta(), "a", m.OK)
            with m.llm_usage_scope() as interno:
                m.record_call("tradução", _resposta(), "b", m.OK)
            m.record_call("tradução", _resposta(), "c", m.OK)
        assert externo.total_calls == 3
        assert interno.total_calls == 1

    def test_escopo_e_fechado_mesmo_com_excecao(self):
        with pytest.raises(RuntimeError), m.llm_usage_scope():
            raise RuntimeError("boom")
        assert m._active == []

    def test_soma_exata_com_varias_threads(self):
        def trabalhar():
            for _ in range(50):
                m.record_call("detecção", _resposta(prompt=1, completion=1, cost=0.5), "a", m.OK)

        with m.llm_usage_scope() as usage:
            threads = [threading.Thread(target=trabalhar) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        assert usage.total_calls == 1000
        assert usage.prompt_tokens == 1000
        assert usage.cost == pytest.approx(500)


class TestLogLlmUsage:
    def test_sem_chamadas_avisa_que_nao_houve(self, caplog):
        with m.llm_usage_scope() as usage, caplog.at_level(logging.INFO):
            m.log_llm_usage("Detalhes movie 3/4", usage)
        assert "LLM [Detalhes movie 3/4]: nenhuma chamada ao LLM" in caplog.text

    def test_linha_info_com_chamadas_modelos_tokens_e_custo(self, caplog):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", _resposta(prompt=1000, completion=234, cost=0.001), "a", m.OK)
            m.record_call("tradução", _resposta(prompt=1000, completion=0, cost=0.002), "b", m.OK)
            m.record_call("detecção", _resposta(model="deepseek/v", prompt=1, completion=1, cost=0.0), "c", m.OK)
        with caplog.at_level(logging.INFO):
            m.log_llm_usage("x", usage)
        linha = next(r.message for r in caplog.records if r.message.startswith("LLM [x]:"))
        assert "3 chamada(s) (tradução 2, detecção 1)" in linha
        assert "modelos: qwen/qwen3.8-flash 2, deepseek/v 1" in linha
        assert "tokens 2.001 in / 235 out" in linha
        assert "US$ 0,0030" in linha
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_custo_indisponivel_quando_nenhuma_chamada_trouxe_custo(self, caplog):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", SimpleNamespace(), "a", m.OK)
        with caplog.at_level(logging.INFO):
            m.log_llm_usage("x", usage)
        assert "custo indisponível" in caplog.text

    def test_custo_parcial_informa_quantas_chamadas_ficaram_sem_custo(self, caplog):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", _resposta(cost=0.01), "a", m.OK)
            m.record_call("tradução", SimpleNamespace(), "b", m.OK)
        with caplog.at_level(logging.INFO):
            m.log_llm_usage("x", usage)
        assert "US$ 0,0100 (+1 chamada(s) sem custo)" in caplog.text

    def test_mostra_sem_mudanca_sem_tratar_como_falha(self, caplog):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", _resposta(), "sexy", m.NO_CHANGE)
        with caplog.at_level(logging.INFO):
            m.log_llm_usage("x", usage)
        assert "sem mudança 1 (o LLM devolveu o próprio texto)" in caplog.text
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_falhas_geram_linha_warning_com_causas_e_exemplos(self, caplog):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", _resposta(), "ok", m.OK)
            m.record_failure("detecção", ImportError("tenacity import failed"), "Cupido")
            m.record_failure("detecção", ImportError("tenacity import failed"), "Outro")
            m.record_call("detecção", _resposta(), "vazio", m.EMPTY)
        with caplog.at_level(logging.INFO):
            m.log_llm_usage("x", usage)
        aviso = next(r.message for r in caplog.records if r.levelno == logging.WARNING)
        assert aviso.startswith("LLM [x] falhas: 3 de 4 — ImportError 2 (ex.: 'Cupido': tenacity import failed)")
        assert "vazia 1 (ex.: 'vazio')" in aviso
        assert [r for r in caplog.records if r.levelno == logging.INFO and r.message.startswith("LLM [x]:")]

    def test_falha_sem_exemplo_guardado_nao_quebra_a_linha(self, caplog):
        with m.llm_usage_scope() as usage:
            m.record_call("tradução", _resposta(), "a", m.OK)
            usage.outcomes["Estranha"] = 2  # causa sem exemplo registrado
        with caplog.at_level(logging.INFO):
            m.log_llm_usage("x", usage)
        assert "Estranha 2" in caplog.text


class TestBalanco:
    def test_record_balance_soma_por_coluna(self):
        with m.llm_usage_scope() as usage:
            m.record_balance("overview_pt", fonte=10, pendentes=1)
            m.record_balance("overview_pt", fonte=5, pendentes=2)
            m.record_balance("tagline_pt", fonte=3)
        assert usage.balance == {"overview_pt": {"fonte": 15, "pendentes": 3}, "tagline_pt": {"fonte": 3}}

    def test_total_mostra_contagens_e_percentual_reaproveitado(self, caplog):
        with m.llm_usage_scope() as usage:
            m.record_balance("overview_pt", fonte=1000, reaproveitadas=250, ja_pt=900, traduzidas=100, ok=98,
                             iguais=2, mantidas=0, pendentes=24)
        with caplog.at_level(logging.INFO):
            m.log_balance_totals("Backfill discover", usage)
        linha = next(r.message for r in caplog.records if r.message.startswith("Balanço total"))
        assert linha.startswith("Balanço total [Backfill discover] 'overview_pt': com fonte 1.000 | reaproveitadas 250")
        assert "pendentes 24" in linha
        assert "25% reaproveitado" in linha

    def test_sem_fonte_ou_sem_reaproveitamento_nao_calcula_percentual(self, caplog):
        with m.llm_usage_scope() as usage:
            m.record_balance("name_pt", traduzidas=3)
        with caplog.at_level(logging.INFO):
            m.log_balance_totals("Glue ETL", usage)
        assert "traduzidas 3" in caplog.text
        assert "reaproveitado" not in caplog.text

    def test_sem_balanco_nao_loga_nada(self, caplog):
        with m.llm_usage_scope() as usage, caplog.at_level(logging.INFO):
            m.log_balance_totals("x", usage)
        assert "Balanço total" not in caplog.text


class TestDecoradorLogLlmUsageSummary:
    def test_loga_total_e_balanco_ao_fim_e_preserva_retorno_e_argumentos(self, caplog):
        @m.log_llm_usage_summary("Backfill teste")
        def main(a, b=2):
            m.record_call("tradução", _resposta(), "x", m.OK)
            m.record_balance("overview_pt", fonte=4)
            return a + b

        with caplog.at_level(logging.INFO):
            assert main(1, b=5) == 6
        assert main.__name__ == "main"
        assert "LLM [Backfill teste — total]: 1 chamada(s)" in caplog.text
        assert "Balanço total [Backfill teste] 'overview_pt'" in caplog.text

    def test_loga_mesmo_quando_a_execucao_sai_por_excecao(self, caplog):
        @m.log_llm_usage_summary("Backfill teste")
        def main():
            m.record_call("tradução", _resposta(), "x", m.OK)
            raise SystemExit(75)

        with caplog.at_level(logging.INFO), pytest.raises(SystemExit):
            main()
        assert "LLM [Backfill teste — total]: 1 chamada(s)" in caplog.text
        assert m._active == []

    def test_sem_chamadas_loga_que_nao_houve_nenhuma(self, caplog):
        @m.log_llm_usage_summary("Glue ETL")
        def main():
            return None

        with caplog.at_level(logging.INFO):
            main()
        assert "LLM [Glue ETL — total]: nenhuma chamada ao LLM" in caplog.text
