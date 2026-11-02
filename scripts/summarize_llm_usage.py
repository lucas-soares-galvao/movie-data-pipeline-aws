"""
summarize_llm_usage.py — Soma o uso do LLM de todas as tentativas de um run de backfill.

O workflow `backfill.yml` roda o script de backfill dentro de um laço de retry: a cada
exit code 75 (credencial prestes a expirar) o processo Python é reiniciado e o contador de
uso do LLM (`shared_utils.llm_metrics`) recomeça do zero. O log "LLM [<script> — total]" de
cada processo, portanto, mostra só aquela tentativa — num run com retomada, o total
impresso por último subestima o gasto real.

Este script lê o log completo do run (o mesmo `$LOG_FILE` que o workflow usa para montar o
step summary), pega o total de cada tentativa e escreve um resumo em Markdown com a soma.
Não faz nenhuma chamada à AWS e não altera o log.

Como achar o total de cada tentativa: o laço do workflow grava no `$LOG_FILE` uma linha
`Tentativa N/M...` antes de cada execução, que delimita os processos. Dentro de uma tentativa,
vale o ÚLTIMO "— total": scripts encadeados (ex.: `backfill_historico.py`) logam o total do
estágio interno e, mais adiante, o do script externo, que já inclui o interno. Não dá para
somar só linhas seguidas — no fim de um run bem-sucedido o AGG roda entre um total e outro.

Uso:
    python scripts/summarize_llm_usage.py <arquivo_de_log>

Sem soma útil (nenhum total no log, ou uma tentativa só, em que o total do próprio log já
está certo), não escreve nada.
"""

import re
import sys
from dataclasses import dataclass

# Formato produzido por shared_utils.llm_metrics.log_llm_usage (linhas INFO e WARNING de falhas).
_TOTAL_RE = re.compile(r"\bLLM \[[^\]]+ — total\]: (?P<body>.*)$")
_FAILURES_RE = re.compile(r"\bLLM \[[^\]]+ — total\] falhas: (?P<failed>[\d.]+) de ")
# Marcador gravado no $LOG_FILE pelo laço de retry do workflow (backfill.yml) a cada tentativa.
_ATTEMPT_RE = re.compile(r"^Tentativa \d+/\d+")
_CALLS_RE = re.compile(r"^(?P<calls>[\d.]+) chamada\(s\)")
_TOKENS_RE = re.compile(r"tokens (?P<in>[\d.]+) in / (?P<out>[\d.]+) out")
_COST_RE = re.compile(r"US\$ (?P<cost>\d+,\d+)(?: \(\+(?P<no_cost>[\d.]+) chamada\(s\) sem custo\))?")


@dataclass
class Attempt:
    """Uso do LLM de uma tentativa (um processo do script de backfill)."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    cost_complete: bool = True
    failed: int = 0


def _to_int(value: str) -> int:
    return int(value.replace(".", ""))


def _parse_total(body: str) -> Attempt:
    """Lê as contagens do corpo de uma linha "LLM [... — total]: ..."; "nenhuma chamada" vira zeros."""
    attempt = Attempt()
    calls = _CALLS_RE.search(body)
    if not calls:
        return attempt
    attempt.calls = _to_int(calls["calls"])
    tokens = _TOKENS_RE.search(body)
    if tokens:
        attempt.tokens_in = _to_int(tokens["in"])
        attempt.tokens_out = _to_int(tokens["out"])
    cost = _COST_RE.search(body)
    if cost:
        attempt.cost = float(cost["cost"].replace(",", "."))
        attempt.cost_complete = cost["no_cost"] is None
    else:
        attempt.cost_complete = False  # "custo indisponível"
    return attempt


def collect_attempts(lines: list[str]) -> list[Attempt]:
    """Devolve o uso de cada tentativa (último total de cada trecho `Tentativa N/M...` do log)."""
    attempts: list[Attempt] = []
    current: Attempt | None = None
    for line in lines:
        if _ATTEMPT_RE.match(line):
            if current is not None:
                attempts.append(current)
            current = None
            continue
        total = _TOTAL_RE.search(line)
        failures = _FAILURES_RE.search(line)
        if total:
            current = _parse_total(total["body"])
        elif failures and current is not None:
            current.failed = _to_int(failures["failed"])
    if current is not None:
        attempts.append(current)
    return attempts


def _fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def render_summary(attempts: list[Attempt]) -> str:
    """Resumo em Markdown da soma das tentativas; vazio quando há menos de duas."""
    if len(attempts) < 2:
        return ""
    calls = sum(a.calls for a in attempts)
    failed = sum(a.failed for a in attempts)
    cost = f"US$ {sum(a.cost for a in attempts):.4f}".replace(".", ",")
    if not all(a.cost_complete for a in attempts):
        cost += " (parcial: há chamadas sem custo)"
    failures = f"{_fmt_int(failed)} falha(s) ({100 * failed / calls:.1f}%)" if calls else "0 falha(s)"
    return (
        f"## LLM (soma de {len(attempts)} tentativas)\n"
        f"- {_fmt_int(calls)} chamada(s) | tokens {_fmt_int(sum(a.tokens_in for a in attempts))} in / "
        f"{_fmt_int(sum(a.tokens_out for a in attempts))} out | {cost} | {failures}\n"
        "- O \"total\" do log de cada tentativa conta só aquele processo: uma retomada por token "
        "expirado (exit 75) zera o contador.\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Uso: python scripts/summarize_llm_usage.py <arquivo_de_log>", file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8", errors="replace") as log_file:
        summary = render_summary(collect_attempts(log_file.read().splitlines()))
    if summary:
        print(summary, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
