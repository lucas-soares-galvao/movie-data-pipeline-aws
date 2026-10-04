"""idioma.py — Orquestração de detecção de idioma: aplicação em coluna de DataFrame
(serviço de detecção via LLM, ver idioma_llm.py)."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from shared_utils.idioma_llm import detect_language_llm

__all__ = [
    "detect_language_llm",
    "add_detected_language_column",
]


def add_detected_language_column(
    df: pd.DataFrame,
    source_column: str,
    target_column: str,
    detect_fn: Callable[[str], str | None] | None = None,
    only_missing: bool = False,
) -> pd.DataFrame:
    """
    Adiciona target_column ao DataFrame com o idioma detectado de source_column.

    Aplica detect_fn (default: detect_language_llm) a cada valor de source_column,
    tratando nulo/NaN como string vazia (mesmo tratamento já usado em
    resolve_pt_translation). Sem ThreadPoolExecutor: toda chamada é uma requisição de
    rede ao LLM; o paralelismo real desse caminho é delegado ao chamador (ex.:
    resolve_pt_translation/translate_in_parallel), não a esta função, usada hoje só
    para colunas de baixo volume (overview do discover, name_pt da configuration).

    detect_fn é recebido como parâmetro (em vez de resolvido aqui dentro) pelo mesmo
    motivo de resolve_pt_translation: os chamadores continuam passando sua própria
    referência local — a mesma que seus testes fazem mock.

    Args:
        df:            DataFrame a atualizar (modificado in-place em target_column).
        source_column: Nome da coluna com o texto a ter o idioma detectado.
        target_column: Nome da coluna a preencher com o código de idioma detectado.
        detect_fn:     Função (texto) -> idioma detectado (ou None). Por padrão usa
                       detect_language_llm.
        only_missing:  Quando True, só detecta para linhas onde target_column ainda
                       está vazia/nula, preservando valores já calculados em execuções
                       anteriores (evita recomputar à toa).

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
        fn = detect_fn or detect_language_llm
        df.loc[pending_mask, target_column] = df.loc[pending_mask, source_column].fillna("").apply(fn)
    return df
