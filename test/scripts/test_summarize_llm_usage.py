"""
Testa scripts/summarize_llm_usage.py com logs sintéticos no formato real de
shared_utils.llm_metrics (nenhuma chamada à AWS).

Foco: a soma entre tentativas do laço de retry do workflow — o contador de LLM zera a cada
processo, então o "— total" de cada tentativa precisa ser somado, sem contar duas vezes o total
do estágio interno e o do script externo (backfill_historico.py).
"""

import pytest
import summarize_llm_usage as sul

TS = "02/11/2026 14:38:35"


def total(label, calls, tokens_in, tokens_out, cost, extra=""):
    return (
        f"{TS} INFO LLM [{label} — total]: {calls} chamada(s) (tradução 1, detecção 2) | modelos: m 1 | "
        f"tokens {tokens_in} in / {tokens_out} out | {cost}{extra}"
    )


def falhas(label, failed, of):
    return f"{TS} WARNING LLM [{label} — total] falhas: {failed} de {of} — interrompida {failed} (ex.: 'x')"


# Tentativa 1 termina por exit 75 (totais interno e externo colados); a 2 termina com o AGG
# rodando entre o total do estágio e o do script externo, como no run real de 2026-11-02.
LOG_DUAS_TENTATIVAS = [
    "Tentativa 1/6...",
    f"{TS} INFO Enriquecimento concluído com sucesso para movie year=2025.",
    total("Backfill enriquecimento", "4.139", "646.950", "120.777", "US$ 0,1471"),
    falhas("Backfill enriquecimento", 7, "4.139"),
    f"{TS} INFO Balanço total [Backfill enriquecimento] 'overview_pt': com fonte 1.818",
    total("Backfill histórico", "4.139", "646.950", "120.777", "US$ 0,1471"),
    falhas("Backfill histórico", 7, "4.139"),
    "Token expirado — renovando credenciais AWS (nova sessão de 1h via OIDC)...",
    "Tentativa 2/6...",
    total("Backfill enriquecimento", "12.419", "1.873.661", "336.347", "US$ 0,4381"),
    falhas("Backfill enriquecimento", 81, "12.419"),
    f"{TS} INFO Rodando Glue AGG localmente (sem acionar job) para propagar o backfill à camada SPEC...",
    f"{TS} INFO Glue AGG (local) processado com sucesso.",
    total("Backfill histórico", "12.419", "1.873.661", "336.347", "US$ 0,4381"),
    falhas("Backfill histórico", 81, "12.419"),
]


class TestCollectAttempts:
    def test_uma_entrada_por_tentativa_e_vale_o_ultimo_total_do_trecho(self):
        attempts = sul.collect_attempts(LOG_DUAS_TENTATIVAS)

        assert [a.calls for a in attempts] == [4139, 12419]

    def test_le_tokens_custo_e_falhas_do_total_externo(self):
        primeira, segunda = sul.collect_attempts(LOG_DUAS_TENTATIVAS)

        assert (primeira.tokens_in, primeira.tokens_out, primeira.cost, primeira.failed) == (646950, 120777, 0.1471, 7)
        assert (segunda.tokens_in, segunda.tokens_out, segunda.cost, segunda.failed) == (1873661, 336347, 0.4381, 81)

    def test_tentativa_sem_falhas_fica_com_zero_falhas(self):
        attempts = sul.collect_attempts(["Tentativa 1/6...", total("Backfill x", "10", "100", "20", "US$ 0,0100")])

        assert attempts[0].failed == 0

    def test_total_sem_chamadas_conta_como_tentativa_zerada(self):
        linhas = [f"{TS} INFO LLM [Backfill x — total]: nenhuma chamada ao LLM (tudo reaproveitado)."]

        attempts = sul.collect_attempts(linhas)

        assert len(attempts) == 1
        assert attempts[0].calls == 0

    def test_tentativa_sem_total_no_log_e_ignorada(self):
        linhas = ["Tentativa 1/6...", f"{TS} INFO nada de LLM aqui", "Tentativa 2/6...", total("x", "5", "1", "1", "US$ 0,0001")]

        attempts = sul.collect_attempts(linhas)

        assert [a.calls for a in attempts] == [5]

    def test_linha_de_falhas_sem_total_anterior_e_ignorada(self):
        assert sul.collect_attempts([falhas("x", 3, "10")]) == []

    def test_custo_indisponivel_marca_custo_incompleto(self):
        [attempt] = sul.collect_attempts([total("x", "5", "1", "1", "custo indisponível")])

        assert attempt.cost == 0.0
        assert attempt.cost_complete is False

    def test_chamadas_sem_custo_marcam_custo_incompleto_mas_somam_o_custo_conhecido(self):
        [attempt] = sul.collect_attempts([total("x", "5", "1", "1", "US$ 0,0500 (+2 chamada(s) sem custo)")])

        assert attempt.cost == 0.05
        assert attempt.cost_complete is False

    def test_total_sem_tokens_mantem_tokens_zerados(self):
        [attempt] = sul.collect_attempts([f"{TS} INFO LLM [x — total]: 5 chamada(s) (tradução 5) | US$ 0,0100"])

        assert (attempt.calls, attempt.tokens_in, attempt.tokens_out) == (5, 0, 0)


class TestRenderSummary:
    def test_soma_as_tentativas_do_run_real(self):
        resumo = sul.render_summary(sul.collect_attempts(LOG_DUAS_TENTATIVAS))

        assert "## LLM (soma de 2 tentativas)" in resumo
        assert "16.558 chamada(s)" in resumo
        assert "tokens 2.520.611 in / 457.124 out" in resumo
        assert "US$ 0,5852" in resumo
        assert "88 falha(s) (0.5%)" in resumo

    def test_uma_tentativa_so_nao_escreve_nada(self):
        assert sul.render_summary([sul.Attempt(calls=10)]) == ""

    def test_sem_tentativas_nao_escreve_nada(self):
        assert sul.render_summary([]) == ""

    def test_custo_incompleto_e_sinalizado_como_parcial(self):
        attempts = [sul.Attempt(calls=1, cost=0.01), sul.Attempt(calls=1, cost=0.02, cost_complete=False)]

        assert "US$ 0,0300 (parcial: há chamadas sem custo)" in sul.render_summary(attempts)

    def test_sem_chamadas_nas_tentativas_nao_divide_por_zero(self):
        resumo = sul.render_summary([sul.Attempt(), sul.Attempt()])

        assert "0 chamada(s)" in resumo
        assert "0 falha(s)" in resumo
        assert "%" not in resumo


class TestMain:
    def test_escreve_o_resumo_do_arquivo_de_log(self, tmp_path, capsys):
        log = tmp_path / "backfill_output.log"
        log.write_text("\n".join(LOG_DUAS_TENTATIVAS), encoding="utf-8")

        assert sul.main([str(log)]) == 0

        assert "soma de 2 tentativas" in capsys.readouterr().out

    def test_log_com_uma_tentativa_nao_imprime_nada(self, tmp_path, capsys):
        log = tmp_path / "backfill_output.log"
        log.write_text("\n".join(["Tentativa 1/6...", total("x", "5", "1", "1", "US$ 0,0001")]), encoding="utf-8")

        assert sul.main([str(log)]) == 0

        assert capsys.readouterr().out == ""

    def test_tolera_bytes_invalidos_no_log(self, tmp_path):
        log = tmp_path / "backfill_output.log"
        log.write_bytes(b"\xff\xfe linha invalida\n")

        assert sul.main([str(log)]) == 0

    @pytest.mark.parametrize("argv", [[], ["a", "b"]])
    def test_numero_de_argumentos_invalido_devolve_2_com_uso_no_stderr(self, argv, capsys):
        assert sul.main(argv) == 2

        assert "Uso:" in capsys.readouterr().err

    def test_sem_argv_le_os_argumentos_do_processo(self, tmp_path, monkeypatch, capsys):
        log = tmp_path / "backfill_output.log"
        log.write_text("\n".join(LOG_DUAS_TENTATIVAS), encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["summarize_llm_usage.py", str(log)])

        assert sul.main() == 0

        assert "soma de 2 tentativas" in capsys.readouterr().out
