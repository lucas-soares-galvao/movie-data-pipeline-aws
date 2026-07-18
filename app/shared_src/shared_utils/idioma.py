"""idioma.py — Orquestração de detecção de idioma: local (langdetect) com fallback
para AWS Comprehend, e aplicação em coluna de DataFrame."""

from __future__ import annotations

import logging
from typing import Callable, Optional

import pandas as pd

from shared_utils.idioma_aws import detect_language_aws
from shared_utils.idioma_langdetect import detect_language_langdetect
from shared_utils.traducao import make_capped_fallback

__all__ = [
    "detect_language_langdetect",
    "detect_language_aws",
    "resolve_detect_language_fn",
    "add_detected_language_column",
]

logger = logging.getLogger()

# Orçamento de caracteres por execução para o fallback ao AWS Comprehend, acionado só
# quando o langdetect local falha (textos curtos/ambíguos — minoria dos registros).
# Comprehend cobra ~US$0.0001 por 100 caracteres processados (~US$1/milhão); mesmo
# com volume naturalmente pequeno, o cap segue o mesmo cuidado de custo já aplicado ao
# fallback de tradução (ver _AWS_FALLBACK_MAX_CHARS_DEFAULT em traducao.py), mantendo
# o gasto do caminho automático (~11 execuções/mês do Glue Details via EventBridge —
# ver infra/eventbridge.tf) abaixo de US$1/mês mesmo no pior caso.
_AWS_FALLBACK_MAX_CHARS_DEFAULT = 6_000


def resolve_detect_language_fn(
    detect_local: Callable[[str], Optional[str]] = detect_language_langdetect,
    detect_aws: Callable[[str], Optional[str]] = detect_language_aws,
    aws_fallback_max_chars: int = _AWS_FALLBACK_MAX_CHARS_DEFAULT,
) -> Callable[[str], Optional[str]]:
    """
    Resolve a função de detecção de idioma composta: langdetect (local, grátis)
    primeiro; se falhar (devolver None), cai para AWS Comprehend, capado por
    aws_fallback_max_chars caracteres nesta execução (rede de segurança de custo,
    já que o Comprehend cobra por caractere processado — ver make_capped_fallback
    em shared_utils.traducao).

    `detect_local`/`detect_aws` são recebidos como parâmetro (em vez de resolvidos
    aqui dentro) pelo mesmo motivo de `resolve_translate_fn`: os chamadores passam
    suas próprias referências locais — as mesmas que seus testes fazem mock.

    Args:
        detect_local:           Função de detecção local (langdetect).
        detect_aws:             Função de detecção via AWS Comprehend.
        aws_fallback_max_chars: Orçamento de caracteres para o fallback ao Comprehend
                                nesta execução.

    Returns:
        Função (texto) -> código de idioma detectado (ou None) que tenta o detector
        local e cai para o AWS Comprehend automaticamente se o local falhar.
    """
    capped_aws = make_capped_fallback(detect_aws, aws_fallback_max_chars, on_over_budget=lambda text: None)

    def _detect_with_fallback(text: str) -> Optional[str]:
        result = detect_local(text)
        if result is not None:
            return result
        return capped_aws(text)

    return _detect_with_fallback


def add_detected_language_column(
    df: pd.DataFrame,
    source_column: str,
    target_column: str,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> pd.DataFrame:
    """
    Adiciona target_column ao DataFrame com o idioma detectado de source_column.

    Aplica detect_fn (default: resolve_detect_language_fn(), langdetect com fallback
    AWS Comprehend) a cada valor de source_column, tratando nulo/NaN como string
    vazia (mesmo tratamento já usado em translate_pending_column). Sem
    ThreadPoolExecutor: a maioria das chamadas é local/CPU-bound (langdetect); o
    fallback AWS é raro o bastante (só quando o local falha) para não justificar
    paralelismo.

    detect_fn é recebido como parâmetro (em vez de resolvido aqui dentro) pelo mesmo
    motivo de translate_pending_column: os chamadores continuam passando sua própria
    referência local — a mesma que seus testes fazem mock.

    Args:
        df:            DataFrame a atualizar (modificado in-place em target_column).
        source_column: Nome da coluna com o texto a ter o idioma detectado.
        target_column: Nome da coluna a preencher com o código de idioma detectado.
        detect_fn:     Função (texto) -> idioma detectado (ou None). Por padrão usa
                       resolve_detect_language_fn().

    Returns:
        df com target_column adicionada (também modificado in-place).
    """
    fn = detect_fn or resolve_detect_language_fn()
    df[target_column] = df[source_column].fillna("").apply(fn)
    return df
