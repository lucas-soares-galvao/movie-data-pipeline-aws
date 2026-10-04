"""llm_metrics.py — Métricas de uso do LLM (chamadas, falhas por causa, modelo, tokens, custo)
e balanço de tradução, para os logs dos jobs Glue e dos scripts de backfill."""

from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

__all__ = [
    "OK",
    "NO_CHANGE",
    "EMPTY",
    "INVALID",
    "LlmUsage",
    "llm_usage_scope",
    "log_llm_usage",
    "log_balance_totals",
    "log_llm_usage_summary",
    "record_call",
    "record_failure",
    "record_balance",
]

logger = logging.getLogger()

# Desfechos de uma chamada ao LLM. Exceção = o nome da própria classe (ex.: "APIError").
OK = "ok"
NO_CHANGE = "sem_mudanca"  # tradução igual ao original — informativo, não é falha da chamada
EMPTY = "vazia"
INVALID = "fora_do_padrao"  # detecção devolveu algo que não é um código ISO 639-1

_NON_FAILURES = frozenset({OK, NO_CHANGE})

# Exemplos de falha por causa e corte de cada exemplo — mesmo corte de 80 caracteres já usado
# nos logs de tradução/detecção, para não despejar texto de filme inteiro no log.
_MAX_SAMPLES = 3
_SAMPLE_CHARS = 80
_ERROR_CHARS = 100

_F = TypeVar("_F", bound=Callable[..., Any])

# Rótulos de cada contagem do balanço, na ordem em que aparecem no log do total do run.
_BALANCE_LABELS = (
    ("fonte", "com fonte"),
    ("reaproveitadas", "reaproveitadas"),
    ("ja_pt", "já em pt"),
    ("traduzidas", "traduzidas"),
    ("ok", "ok"),
    ("iguais", "iguais à fonte"),
    ("mantidas", "mantidas por detecção indisponível"),
    ("pendentes", "pendentes"),
)


class LlmUsage:
    """Acumulador de uso do LLM e de balanço de tradução durante um escopo.

    Não é criado diretamente: use llm_usage_scope(). Todas as mutações acontecem sob o lock do
    módulo, porque as chamadas ao LLM rodam em threads (ThreadPoolExecutor).
    """

    def __init__(self) -> None:
        self.calls_by_operation: dict[str, int] = {}
        self.outcomes: dict[str, int] = {}
        self.models: dict[str, int] = {}
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost = 0.0
        self.calls_without_cost = 0
        self.samples: dict[str, list[str]] = {}
        self.balance: dict[str, dict[str, int]] = {}

    @property
    def total_calls(self) -> int:
        return sum(self.calls_by_operation.values())

    @property
    def failures(self) -> dict[str, int]:
        return {cause: n for cause, n in self.outcomes.items() if cause not in _NON_FAILURES}


_lock = threading.Lock()
_active: list[LlmUsage] = []


@contextmanager
def llm_usage_scope() -> Iterator[LlmUsage]:
    """Abre um escopo que acumula o uso do LLM feito enquanto ele estiver aberto.

    Escopos podem ser aninhados (uma unidade dentro do run inteiro): cada chamada é somada em
    todos os escopos abertos. Não usa threading.local de propósito — as chamadas ao LLM rodam em
    threads de um pool criado dentro do escopo, que não herdariam um valor local à thread.
    """
    usage = LlmUsage()
    with _lock:
        _active.append(usage)
    try:
        yield usage
    finally:
        with _lock:
            _active.remove(usage)


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "…"


def _number(value: Any) -> float | None:
    """Número do atributo, ou None se ausente/inválido (inclui bool, que é subclasse de int)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _extract(response: Any) -> tuple[str | None, int, int, float | None]:
    """Lê (modelo, tokens de entrada, tokens de saída, custo) da resposta, sem nunca lançar.

    O OpenRouter devolve usage.cost em toda resposta; o litellm.completion_cost() não conhece os
    modelos do projeto ("This model isn't mapped yet"), então ele não é usado. Qualquer campo
    ausente vira "desconhecido" em vez de quebrar a chamada ao LLM.
    """
    try:
        model = getattr(response, "model", None)
        usage = getattr(response, "usage", None)
        prompt = _number(getattr(usage, "prompt_tokens", None)) or 0
        completion = _number(getattr(usage, "completion_tokens", None)) or 0
        cost = _number(getattr(usage, "cost", None))
        if cost is None:
            cost = _number((getattr(response, "_hidden_params", None) or {}).get("response_cost"))
    except Exception:  # noqa: BLE001 — registrar métrica nunca pode derrubar uma chamada ao LLM
        return None, 0, 0, None
    return (model if isinstance(model, str) and model else None), int(prompt), int(completion), cost


def _add_sample(usage: LlmUsage, cause: str, sample: str) -> None:
    samples = usage.samples.setdefault(cause, [])
    if len(samples) < _MAX_SAMPLES:
        samples.append(sample)


def record_call(operation: str, response: Any, text: str, outcome: str) -> None:
    """Registra uma chamada ao LLM que obteve resposta (mesmo que vazia/inválida/sem mudança).

    Args:
        operation: "tradução" ou "detecção".
        response:  Resposta do litellm (modelo, tokens e custo são lidos dela, se existirem).
        text:      Texto enviado — só os primeiros caracteres entram nos exemplos de falha.
        outcome:   OK, NO_CHANGE, EMPTY ou INVALID.
    """
    model, prompt, completion, cost = _extract(response)
    with _lock:
        for usage in _active:
            usage.calls_by_operation[operation] = usage.calls_by_operation.get(operation, 0) + 1
            usage.outcomes[outcome] = usage.outcomes.get(outcome, 0) + 1
            usage.models[model or "modelo indisponível"] = usage.models.get(model or "modelo indisponível", 0) + 1
            usage.prompt_tokens += prompt
            usage.completion_tokens += completion
            if cost is None:
                usage.calls_without_cost += 1
            else:
                usage.cost += cost
            if outcome not in _NON_FAILURES:
                _add_sample(usage, outcome, repr(_truncate(text, _SAMPLE_CHARS)))


def record_failure(operation: str, exc: BaseException, text: str) -> None:
    """Registra uma chamada ao LLM que lançou exceção; a causa é o nome da classe da exceção.

    Args:
        operation: "tradução" ou "detecção".
        exc:       Exceção capturada (a mensagem entra no exemplo — é por ela que se distingue,
                   por exemplo, "tenacity import failed" de um timeout).
        text:      Texto enviado.
    """
    cause = type(exc).__name__
    sample = f"{_truncate(text, _SAMPLE_CHARS)!r}: {_truncate(str(exc), _ERROR_CHARS)}"
    with _lock:
        for usage in _active:
            usage.calls_by_operation[operation] = usage.calls_by_operation.get(operation, 0) + 1
            usage.outcomes[cause] = usage.outcomes.get(cause, 0) + 1
            _add_sample(usage, cause, sample)


def record_balance(label: str, **counts: int) -> None:
    """Soma contagens do balanço de tradução de uma coluna (ex.: "overview_pt") nos escopos abertos.

    Args:
        label:  Nome da coluna de tradução.
        counts: Contagens a somar (fonte, reaproveitadas, ja_pt, traduzidas, ok, iguais, mantidas,
                pendentes) — chaves ausentes simplesmente não são somadas.
    """
    with _lock:
        for usage in _active:
            totals = usage.balance.setdefault(label, {})
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + int(value)


def _fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _fmt_cost(value: float) -> str:
    return f"US$ {value:.4f}".replace(".", ",")


def log_llm_usage(label: str, usage: LlmUsage) -> None:
    """Loga o uso do LLM acumulado no escopo: 1 linha INFO e, havendo falhas, 1 linha WARNING.

    Args:
        label: Rótulo do escopo (ex.: "Detalhes movie 3/4").
        usage: Acumulador devolvido por llm_usage_scope().
    """
    with _lock:
        total = usage.total_calls
        if not total:
            logger.info(f"LLM [{label}]: nenhuma chamada ao LLM (tudo reaproveitado ou já em português).")
            return
        by_operation = ", ".join(f"{op} {_fmt_int(n)}" for op, n in usage.calls_by_operation.items())
        models = ", ".join(f"{m} {_fmt_int(n)}" for m, n in sorted(usage.models.items(), key=lambda kv: -kv[1]))
        if usage.calls_without_cost == total:
            cost = "custo indisponível"
        elif usage.calls_without_cost:
            cost = f"{_fmt_cost(usage.cost)} (+{_fmt_int(usage.calls_without_cost)} chamada(s) sem custo)"
        else:
            cost = _fmt_cost(usage.cost)
        no_change = usage.outcomes.get(NO_CHANGE, 0)
        parts = [
            f"{_fmt_int(total)} chamada(s) ({by_operation})",
            f"modelos: {models}",
            f"tokens {_fmt_int(usage.prompt_tokens)} in / {_fmt_int(usage.completion_tokens)} out",
            cost,
        ]
        if no_change:
            parts.append(f"sem mudança {_fmt_int(no_change)} (o LLM devolveu o próprio texto)")
        failures = usage.failures
        warning = None
        if failures:
            causes = "; ".join(
                f"{cause} {_fmt_int(n)}" + (f" (ex.: {usage.samples[cause][0]})" if usage.samples.get(cause) else "")
                for cause, n in sorted(failures.items(), key=lambda kv: -kv[1])
            )
            warning = f"LLM [{label}] falhas: {_fmt_int(sum(failures.values()))} de {_fmt_int(total)} — {causes}"
    logger.info(f"LLM [{label}]: " + " | ".join(parts))
    if warning:
        logger.warning(warning)


def log_balance_totals(label: str, usage: LlmUsage) -> None:
    """Loga o balanço de tradução acumulado no escopo, uma linha INFO por coluna traduzida.

    Args:
        label: Rótulo do escopo (ex.: "Backfill discover").
        usage: Acumulador devolvido por llm_usage_scope().
    """
    with _lock:
        lines = []
        for column, totals in usage.balance.items():
            parts = [f"{name} {_fmt_int(totals[key])}" for key, name in _BALANCE_LABELS if key in totals]
            source = totals.get("fonte", 0)
            reused = totals.get("reaproveitadas", 0)
            if source and "reaproveitadas" in totals:
                parts.append(f"{round(100 * reused / source)}% reaproveitado")
            lines.append(f"Balanço total [{label}] '{column}': " + " | ".join(parts))
    for line in lines:
        logger.info(line)


def log_llm_usage_summary(label: str) -> Callable[[_F], _F]:
    """Decorador para main(): loga o total de uso do LLM e o balanço de tradução da execução.

    O log sai num finally, então também aparece quando a execução termina por exceção ou por
    exit code de retomada (ex.: 75) — o gasto com o LLM já aconteceu.

    Args:
        label: Nome da execução (ex.: "Backfill discover", "Glue ETL").
    """

    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with llm_usage_scope() as usage:
                try:
                    return func(*args, **kwargs)
                finally:
                    log_llm_usage(f"{label} — total", usage)
                    log_balance_totals(label, usage)

        return wrapper  # type: ignore[return-value]

    return decorator
