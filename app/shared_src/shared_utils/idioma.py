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
    provider: str = "google",
) -> Callable[[str], Optional[str]]:
    """
    Resolve a função de detecção de idioma composta, espelhando `provider` de
    `resolve_translate_fn` (`shared_utils.traducao`): o serviço escolhido vira
    primário, o outro vira fallback automático se o primário falhar (devolver
    None).

    `provider="google"` (default) → primário=langdetect (local, grátis),
    fallback=AWS Comprehend, capado por aws_fallback_max_chars caracteres nesta
    execução (rede de segurança de custo, já que o Comprehend cobra por caractere
    processado — ver make_capped_fallback em shared_utils.traducao).
    `provider="aws"` → primário=AWS Comprehend — sem cap, já que quem escolheu
    "aws" explicitamente já aceitou o custo do primário —, fallback=langdetect
    (local, grátis, sem necessidade de cap).

    `detect_local`/`detect_aws` são recebidos como parâmetro (em vez de resolvidos
    aqui dentro) pelo mesmo motivo de `resolve_translate_fn`: os chamadores passam
    suas próprias referências locais — as mesmas que seus testes fazem mock.

    Args:
        detect_local:           Função de detecção local (langdetect).
        detect_aws:             Função de detecção via AWS Comprehend.
        aws_fallback_max_chars: Orçamento de caracteres para o fallback ao Comprehend
                                nesta execução, aplicado somente quando
                                `provider="google"` (Comprehend é o fallback).
                                Ignorado quando `provider="aws"` (Comprehend já é
                                o primário escolhido explicitamente).
        provider:               `"google"` (langdetect primário) ou `"aws"`
                                (Comprehend primário). Default `"google"`
                                preserva o comportamento anterior a este parâmetro.

    Returns:
        Função (texto) -> código de idioma detectado (ou None) que tenta o
        detector primário e cai para o fallback automaticamente se o primário
        devolver None.

    Raises:
        ValueError: se `provider` não for `"google"` nem `"aws"`.
    """
    try:
        primary, fallback = {
            "google": (detect_local, detect_aws),
            "aws": (detect_aws, detect_local),
        }[provider]
    except KeyError:
        raise ValueError(
            f"provider de detecção inválido: {provider!r} (esperado 'google' ou 'aws')"
        ) from None

    if provider == "google":
        fallback = make_capped_fallback(fallback, aws_fallback_max_chars, on_over_budget=lambda text: None)

    def _detect_with_fallback(text: str) -> Optional[str]:
        result = primary(text)
        if result is not None:
            return result
        return fallback(text)

    return _detect_with_fallback


def add_detected_language_column(
    df: pd.DataFrame,
    source_column: str,
    target_column: str,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
    only_missing: bool = False,
) -> pd.DataFrame:
    """
    Adiciona target_column ao DataFrame com o idioma detectado de source_column.

    Aplica detect_fn (default: resolve_detect_language_fn(), langdetect com fallback
    AWS Comprehend) a cada valor de source_column, tratando nulo/NaN como string
    vazia (mesmo tratamento já usado em resolve_pt_translation). Sem
    ThreadPoolExecutor: a maioria das chamadas é local/CPU-bound (langdetect); o
    fallback AWS é raro o bastante (só quando o local falha) para não justificar
    paralelismo.

    detect_fn é recebido como parâmetro (em vez de resolvido aqui dentro) pelo mesmo
    motivo de resolve_pt_translation: os chamadores continuam passando sua própria
    referência local — a mesma que seus testes fazem mock.

    Args:
        df:            DataFrame a atualizar (modificado in-place em target_column).
        source_column: Nome da coluna com o texto a ter o idioma detectado.
        target_column: Nome da coluna a preencher com o código de idioma detectado.
        detect_fn:     Função (texto) -> idioma detectado (ou None). Por padrão usa
                       resolve_detect_language_fn().
        only_missing:  Quando True, só detecta para linhas onde target_column ainda
                       está vazia/nula, preservando valores já calculados em execuções
                       anteriores (evita recomputar à toa, e reenviar caracteres ao
                       fallback pago do AWS Comprehend, para o que já foi detectado).

    Returns:
        df com target_column adicionada (também modificado in-place).
    """
    if target_column not in df.columns:
        df[target_column] = None

    if only_missing:
        pending_mask = df[target_column].isna() | (df[target_column] == "")
    else:
        pending_mask = pd.Series(True, index=df.index)

    if pending_mask.any():
        fn = detect_fn or resolve_detect_language_fn()
        df.loc[pending_mask, target_column] = df.loc[pending_mask, source_column].fillna("").apply(fn)
    return df
