"""traducao.py — Orquestração de tradução para português: elegibilidade, cache,
paralelismo e escolha do serviço (Google Translate ou AWS Translate)."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional, TypeVar

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
    "is_translated_mask",
    "make_capped_fallback",
]

T = TypeVar("T")

logger = logging.getLogger()

# Orçamento de caracteres por execução para o fallback ao AWS Translate (pago por
# caractere) quando ele não é o serviço escolhido — ver resolve_translate_fn. Medido
# em caracteres (não em número de chamadas) porque é isso que a AWS cobra: uma sinopse
# longa pesa muito mais que uma keyword curta. 6_000 dimensionado para manter o gasto
# do caminho automático (~11 execuções/mês do Glue Details via EventBridge — semanal +
# mensal, ver infra/eventbridge.tf) abaixo de US$1/mês mesmo no pior caso (cap
# totalmente consumido em toda execução), a US$15/milhão de caracteres do AWS Translate.
_AWS_FALLBACK_MAX_CHARS_DEFAULT = 6_000


def make_capped_fallback(
    fallback_fn: Callable[[str], T], max_chars: int, on_over_budget: Callable[[str], T]
) -> Callable[[str], T]:
    """
    Envolve fallback_fn com um orçamento de caracteres thread-safe: enquanto restar
    orçamento, cada chamada consome len(text) caracteres e delega a fallback_fn; textos
    que excederiam o restante são pulados (devolve on_over_budget(text), sem chamar
    fallback_fn) e não consomem o que sobrou — um texto menor que chegue depois ainda
    pode caber.

    Compartilhada entre resolve_translate_fn (fallback de tradução via AWS Translate,
    pago por caractere) e shared_utils.idioma.resolve_detect_language_fn (fallback de
    detecção de idioma via AWS Comprehend, também pago por caractere) — mesmo mecanismo
    de orçamento, resultados diferentes por chamador: tradução devolve o próprio texto
    quando o orçamento acaba (on_over_budget=lambda text: text), detecção devolve None
    (on_over_budget=lambda text: None).

    Thread-safe via threading.Lock + contador mutável de 1 elemento (lista), já que a
    função composta roda dentro de ThreadPoolExecutor (translate_in_parallel/
    translate_pending_column, até 10 workers).

    Args:
        fallback_fn:     Função chamada enquanto houver orçamento restante.
        max_chars:       Orçamento total de caracteres para esta instância.
        on_over_budget:  Função chamada com o texto original quando o orçamento já
                         se esgotou, no lugar de fallback_fn.

    Returns:
        Função (texto) -> resultado que aplica fallback_fn ou on_over_budget conforme
        o orçamento restante.
    """
    remaining = [max_chars]
    lock = threading.Lock()

    def _capped(text: str) -> T:
        length = len(text)
        with lock:
            if length > remaining[0]:
                return on_over_budget(text)
            remaining[0] -= length
        return fallback_fn(text)

    return _capped


def resolve_translate_fn(
    provider: str,
    translate_google: Callable[[str], str] = translate_text,
    translate_aws: Callable[[str], str] = translate_text_aws,
    aws_fallback_max_chars: int = _AWS_FALLBACK_MAX_CHARS_DEFAULT,
) -> Callable[[str], str]:
    """
    Resolve o provedor de tradução (`"google"` ou `"aws"`) para uma função composta
    primário+fallback: o provider escolhido é tentado primeiro; se falhar (resultado
    igual ao texto original, texto não-vazio — mesmo sinal de falha usado em
    translate_pending_column), o outro serviço é tentado automaticamente antes de
    desistir.

    `provider="google"` → primário=Google (grátis), fallback=AWS Translate — pago por
    caractere, por isso limitado a aws_fallback_max_chars caracteres nesta execução
    (rede de segurança de custo; ver make_capped_fallback).
    `provider="aws"` → primário=AWS Translate, fallback=Google (grátis) — sem limite,
    já que quem escolheu "aws" explicitamente já aceitou o custo do primário.

    `translate_google`/`translate_aws` são recebidos como parâmetro (em vez de resolvidos
    aqui dentro) pelo mesmo motivo de `translate_in_parallel`: os chamadores passam suas
    próprias referências locais de `translate_text`/`translate_text_aws` — as mesmas que
    seus testes fazem mock (ex.: `patch("src.utils.translate_text", ...)`). Resolver via
    referência direta ao módulo quebraria esse patch.

    Args:
        provider:               `"google"` (deep_translator, grátis) ou `"aws"` (AWS
                                Translate, pago por caractere).
        translate_google:       Função de tradução via Google.
        translate_aws:          Função de tradução via AWS.
        aws_fallback_max_chars: Orçamento de caracteres para o fallback ao AWS
                                Translate nesta execução, aplicado somente quando
                                `provider="google"` (AWS é o fallback). Ignorado quando
                                `provider="aws"` (AWS já é o primário escolhido
                                explicitamente).

    Returns:
        Função (texto) -> texto traduzido que tenta o primário e cai para o fallback
        automaticamente em caso de falha.

    Raises:
        ValueError: se `provider` não for `"google"` nem `"aws"`.
    """
    try:
        primary, fallback = {
            "google": (translate_google, translate_aws),
            "aws": (translate_aws, translate_google),
        }[provider]
    except KeyError:
        raise ValueError(
            f"TRANSLATE_PROVIDER inválido: {provider!r} (esperado 'google' ou 'aws')"
        ) from None

    if provider == "google":
        fallback = make_capped_fallback(fallback, aws_fallback_max_chars, on_over_budget=lambda text: text)

    def _translate_with_fallback(text: str) -> str:
        result = primary(text)
        if not text or result != text:
            return result
        return fallback(text)

    return _translate_with_fallback


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


def is_translated_mask(
    df: pd.DataFrame,
    source_column: str,
    target_column: str,
    already_native_mask: Optional["pd.Series[bool]"] = None,
) -> "pd.Series[bool]":
    """
    Máscara de registros considerados "já traduzidos" em target_column.

    Um registro conta como traduzido quando target_column está preenchida e é
    diferente de source_column — cobre tanto tradução nativa do TMDB (glue_details)
    quanto sucesso em um run anterior (backfill) ou tradução automática bem-sucedida.
    Registros sem target_column, ou cuja target_column ficou igual à source_column
    (tradução que falhou — ver translate_text/translate_text_aws), não contam.

    already_native_mask cobre o caso em que a própria fonte já estava no idioma-alvo
    (ex.: overview_en detectado como "pt" — ver shared_utils.idioma) e foi copiada
    diretamente para target_column sem chamar tradução: nesse caso target == source,
    mas o registro deve contar como traduzido mesmo assim.

    Args:
        df:                   DataFrame com as colunas source_column e target_column.
        source_column:        Nome da coluna com o texto de origem.
        target_column:        Nome da coluna de tradução. Se ausente em df, nenhum
                              registro conta como traduzido.
        already_native_mask:  Máscara adicional de registros cuja fonte já estava no
                              idioma-alvo. Quando None, o comportamento é idêntico ao
                              predicado original (sem essa exceção).

    Returns:
        Máscara booleana de registros considerados traduzidos.
    """
    if target_column not in df.columns:
        return pd.Series(False, index=df.index)

    filled = df[target_column].notna() & (df[target_column] != "")
    differs = df[target_column] != df[source_column]
    if already_native_mask is not None:
        differs = differs | already_native_mask
    return filled & differs


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
    (backfill) — ver is_translated_mask. Registros sem target_column, ou cuja
    target_column ficou igual à source_column (tradução que falhou — ver
    translate_text/translate_text_aws), continuam pendentes e são (re)tentados.

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

    already_translated = is_translated_mask(df, source_column, target_column)
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


def _already_detected_as_pt(df: pd.DataFrame, idioma_column: str) -> "pd.Series[bool]":
    """Máscara de registros cuja coluna de idioma detectado já é 'pt'. False para
    todos os registros quando idioma_column ainda não existe em df (compatibilidade
    com chamadores/testes que não pré-computam a detecção de idioma)."""
    if idioma_column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[idioma_column] == "pt"


def eligible_overview_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de overview: overview_en preenchido e ainda não
    confirmado como pt-BR pela detecção de idioma (overview_idioma_detectado).

    original_language não é usado como critério: é o idioma original de produção
    do título, não o idioma do texto retornado pela API — não há garantia de que
    overview_en já esteja em português quando original_language == 'pt' (ver
    discussão em traducao_aws.py). A exclusão por overview_idioma_detectado == 'pt'
    evita reenviar ao Google/AWS um texto que a detecção de idioma (shared_utils.idioma)
    já confirmou estar em português — ver otimização de "cópia direta" no chamador
    (glue_details._add_translations_pt/scripts.backfill_traducao). Registros já
    traduzidos (TMDB nativo ou run anterior) são filtrados depois, em
    translate_pending_column.
    """
    has_source = df["overview_en"].notna() & (df["overview_en"] != "")
    return has_source & ~_already_detected_as_pt(df, "overview_idioma_detectado")


def eligible_tagline_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de tagline: campo preenchido e ainda não confirmado
    como pt-BR pela detecção de idioma (tagline_idioma_detectado — ver
    eligible_overview_pt sobre por que original_language não entra no critério, e
    sobre a exclusão por idioma já detectado como 'pt')."""
    has_source = df["tagline"].notna() & (df["tagline"] != "")
    return has_source & ~_already_detected_as_pt(df, "tagline_idioma_detectado")


def eligible_keywords_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de keywords: campo preenchido e ainda não confirmado
    como pt-BR pela detecção de idioma (keywords_idioma_detectado — ver
    eligible_overview_pt sobre por que original_language não entra no critério, e
    sobre a exclusão por idioma já detectado como 'pt')."""
    has_source = df["keywords"].notna() & (df["keywords"] != "")
    return has_source & ~_already_detected_as_pt(df, "keywords_idioma_detectado")
