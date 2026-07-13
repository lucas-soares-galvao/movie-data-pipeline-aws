"""traducao.py — Orquestração de tradução para português: elegibilidade, cache,
paralelismo e escolha do serviço (Google Translate ou AWS Translate)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional

import pandas as pd

from shared_utils.traducao_aws import translate_text_aws
from shared_utils.traducao_google import translate_text

__all__ = [
    "translate_text",
    "translate_text_aws",
    "resolve_translate_fn",
    "translate_in_parallel",
    "translate_pending_column",
    "reuse_existing_translation",
    "eligible_overview_pt",
    "eligible_tagline_pt",
    "eligible_keywords_pt",
]

logger = logging.getLogger()


def resolve_translate_fn(
    provider: str,
    translate_google: Callable[[str], str] = translate_text,
    translate_aws: Callable[[str], str] = translate_text_aws,
) -> Callable[[str], str]:
    """
    Resolve o provedor de tradução (`"google"` ou `"aws"`) para a função correspondente.

    Cada caminho do pipeline escolhe um único serviço por execução — sem composição
    de primário+fallback: `glue_details`/`glue_etl` (caminho automático via
    EventBridge) usam `"aws"` por padrão; os backfills manuais (`scripts/`) usam
    `"google"` por padrão, mas podem apontar para `"aws"` para testes pontuais.

    `translate_google`/`translate_aws` são recebidos como parâmetro (em vez de resolvidos
    aqui dentro) pelo mesmo motivo de `translate_in_parallel`: os chamadores passam suas
    próprias referências locais de `translate_text`/`translate_text_aws` — as mesmas que
    seus testes fazem mock (ex.: `patch("src.utils.translate_text", ...)`). Resolver via
    referência direta ao módulo quebraria esse patch.

    Args:
        provider:         `"google"` (deep_translator, grátis) ou `"aws"` (AWS Translate,
                          pago por caractere).
        translate_google: Função a devolver quando `provider="google"`.
        translate_aws:    Função a devolver quando `provider="aws"`.

    Returns:
        `translate_google` ou `translate_aws`, conforme `provider`.

    Raises:
        ValueError: se `provider` não for `"google"` nem `"aws"`.
    """
    try:
        return {"google": translate_google, "aws": translate_aws}[provider]
    except KeyError:
        raise ValueError(
            f"TRANSLATE_PROVIDER inválido: {provider!r} (esperado 'google' ou 'aws')"
        ) from None


def translate_in_parallel(
    values: List[str], translate_fn: Callable[[str], str], max_workers: int = 10
) -> List[str]:
    """
    Aplica translate_fn a cada item de values em paralelo via ThreadPoolExecutor.

    Recebe a função de tradução como parâmetro (em vez de chamar translate_text
    diretamente) para que os chamadores continuem passando sua própria referência
    local de translate_text — a mesma que seus testes fazem mock.

    Args:
        values:       Textos a traduzir, na ordem em que devem ser retornados.
        translate_fn: Função chamada para cada item (ex.: translate_text).
        max_workers:  Número de threads concorrentes.

    Returns:
        Lista de textos traduzidos, na mesma ordem de values.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(translate_fn, values))


def translate_pending_column(
    df: pd.DataFrame,
    source_column: str,
    target_column: str,
    eligible_mask: "pd.Series[bool]",
    translate_fn: Callable[[str], str],
    max_workers: int = 10,
) -> int:
    """
    Traduz source_column → target_column para os registros elegíveis ainda pendentes.

    Um registro é considerado "já traduzido" (e não é retraduzido) quando
    target_column está preenchida e é diferente de source_column — cobre tanto
    tradução nativa do TMDB (glue_details) quanto sucesso em um run anterior
    (backfill). Registros sem target_column, ou cuja target_column ficou
    igual à source_column (tradução que falhou — ver translate_text/translate_text_aws),
    continuam pendentes e são (re)tentados.

    translate_fn é recebido como parâmetro (em vez de chamar translate_text
    diretamente) para que os chamadores continuem passando sua própria
    referência local — a mesma que seus testes fazem mock.

    Args:
        df:            DataFrame a atualizar (modificado in-place em target_column).
        source_column: Nome da coluna com o texto de origem.
        target_column: Nome da coluna a preencher com o texto traduzido.
        eligible_mask: Máscara booleana dos registros candidatos à tradução.
        translate_fn:  Função chamada para cada texto (ex.: translate_text).
        max_workers:   Número de threads concorrentes.

    Returns:
        Quantidade traduzida com sucesso nesta chamada. Sucesso é contado
        comparando cada resultado com o texto original, já que translate_fn
        devolve o próprio texto original quando a tradução falha após todas
        as tentativas.
    """
    if target_column not in df.columns:
        df[target_column] = None

    already_translated = (
        df[target_column].notna()
        & (df[target_column] != "")
        & (df[target_column] != df[source_column])
    )
    mask = eligible_mask & ~already_translated
    if not mask.any():
        return 0

    values = df.loc[mask, source_column].fillna("").tolist()
    translated = translate_in_parallel(values, translate_fn, max_workers=max_workers)
    df.loc[mask, target_column] = translated

    return sum(1 for original, result in zip(values, translated) if original and result != original)


def reuse_existing_translation(
    df: pd.DataFrame,
    previous_df: Optional[pd.DataFrame],
    source_column: str,
    target_column: str,
    key_column: str = "id",
) -> pd.DataFrame:
    """
    Preenche target_column com a tradução já existente (previous_df) quando
    source_column não mudou entre o registro antigo e o novo, para a mesma
    key_column. Evita retraduzir texto idêntico ao da última execução.

    Não sobrescreve valores já preenchidos em target_column neste run (ex.:
    tradução nativa do TMDB, atribuída antes desta chamada) — essa prioridade é
    preservada. A checagem final de "já traduzido" continua em
    translate_pending_column ou na máscara de elegibilidade do chamador; esta
    função só fornece o valor de cache para essas checagens localizarem. Se o
    valor reaproveitado for igual à fonte (falha de tradução de um run
    anterior), o chamador vai marcá-lo como pendente e retentar sozinho.

    Compartilhada entre glue_details (key_column="id", default) e glue_etl
    (key_column="iso_3166_1"/"iso_639_1" para a tabela configuration).

    Args:
        df:            DataFrame novo (run atual), com colunas key_column,
                        source_column e target_column já inicializada (mesmo
                        que com nulos).
        previous_df:   Registros já persistidos que serão sobrescritos neste
                        run, ou None/vazio se não há histórico.
        source_column: Nome da coluna de texto fonte (ex.: "overview_en").
        target_column: Nome da coluna de tradução a (pré-)preencher.
        key_column:    Coluna usada para casar registros antigos e novos
                       (default "id").

    Returns:
        df com target_column atualizada (também modificado in-place).
    """
    if previous_df is None or previous_df.empty:
        return df
    required_columns = {key_column, source_column, target_column}
    if not required_columns.issubset(previous_df.columns):
        # Schema antigo (partição/tabela gravada antes da coluna existir) — nada a reaproveitar.
        return df

    cache = (
        previous_df[[key_column, source_column, target_column]]
        .drop_duplicates(subset=key_column, keep="last")
        .set_index(key_column)
    )
    old_source = df[key_column].map(cache[source_column])
    old_target = df[key_column].map(cache[target_column])

    new_target_empty = df[target_column].isna() | (df[target_column] == "")
    source_valid = df[source_column].notna() & (df[source_column] != "")
    old_target_valid = old_target.notna() & (old_target != "")
    source_unchanged = source_valid & (old_source == df[source_column])

    can_reuse = new_target_empty & old_target_valid & source_unchanged
    if can_reuse.any():
        df.loc[can_reuse, target_column] = old_target[can_reuse]
        logger.info(
            f"Reaproveitando tradução existente de {can_reuse.sum()} registro(s) "
            f"para '{target_column}' (fonte '{source_column}' inalterada)."
        )
    return df


def eligible_overview_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de overview: idioma original diferente de pt, com overview_en preenchido."""
    return (
        (df["original_language"] != "pt")
        & df["overview_en"].notna()
        & (df["overview_en"] != "")
    )


def eligible_tagline_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de tagline: campo preenchido e idioma original diferente de pt."""
    return (
        df["tagline"].notna()
        & (df["tagline"] != "")
        & (df["original_language"] != "pt")
    )


def eligible_keywords_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de keywords: campo preenchido e idioma original diferente de pt
    (evita reenviar ao Google Translate keywords que já podem estar em português)."""
    return (
        df["keywords"].notna()
        & (df["keywords"] != "")
        & (df["original_language"] != "pt")
    )
