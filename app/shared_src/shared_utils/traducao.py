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
    "reuse_existing_translation",
    "resolve_pt_translation",
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

# Teto de tentativas de tradução por linha antes de desistir dela (ver
# resolve_pt_translation). Sem esse teto, conteúdo genuinamente não traduzível (nomes
# próprios, termos curtos que o tradutor devolve sem alterar) nunca teria
# idioma_pt_column == "pt" e seria reenviado ao Google/AWS a cada execução, para sempre.
_MAX_TENTATIVAS_TRADUCAO_DEFAULT = 3


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
    resolve_pt_translation, até 10 workers).

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
    resolve_pt_translation), o outro serviço é tentado automaticamente antes de
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


def _detect_missing(
    df: pd.DataFrame,
    text_column: str,
    idioma_column: str,
    detect_fn: Callable[[str], Optional[str]],
) -> pd.DataFrame:
    """Detecta o idioma de text_column em idioma_column, só para linhas onde
    idioma_column ainda está vazia/nula — evita redetectar (e reenviar caracteres ao
    fallback pago do AWS Comprehend) o que já foi calculado numa execução anterior.

    Equivalente a shared_utils.idioma.add_detected_language_column(only_missing=True),
    duplicado aqui (em vez de importado) para não criar import circular: idioma.py já
    importa make_capped_fallback deste módulo.
    """
    if idioma_column not in df.columns:
        df[idioma_column] = None
    pending = df[idioma_column].isna() | (df[idioma_column] == "")
    if pending.any():
        df.loc[pending, idioma_column] = df.loc[pending, text_column].fillna("").apply(detect_fn)
    return df


def resolve_pt_translation(
    df: pd.DataFrame,
    source_column: str,
    target_column: str,
    idioma_en_column: str,
    idioma_pt_column: str,
    tentativas_column: str,
    detect_fn: Callable[[str], Optional[str]],
    translate_fn: Callable[[str], str],
    max_workers: int = 10,
    max_tentativas: int = _MAX_TENTATIVAS_TRADUCAO_DEFAULT,
) -> "tuple[pd.DataFrame, int]":
    """
    Sincroniza target_column (já inicializada pelo chamador — nativo do TMDB, cache
    reaproveitado ou vazia) com source_column, mantendo idioma_en_column/
    idioma_pt_column como o idioma real detectado da fonte e do resultado,
    respectivamente — em vez da antiga heurística de string-diff, que não
    distinguia "não precisava traduzir" de "tradução falhou silenciosamente".

    Passos: (1) detecta idioma_en_column a partir de source_column, só onde ainda
    vazia; (2) detecta idioma_pt_column a partir do valor atual de target_column, só
    onde ainda vazia — cobre tradução nativa/cache já presentes antes desta chamada;
    (3) atalho de cópia direta: fonte já detectada como "pt" e target_column ainda
    vazia → copia sem chamar tradutor e marca idioma_pt_column="pt" direto; (4)
    elegível para o tradutor = fonte preenchida E idioma_pt_column != "pt" E
    tentativas_column < max_tentativas; (5) traduz as linhas elegíveis; (6)
    incrementa tentativas_column para as linhas elegíveis desta execução; (7)
    redetecta idioma_pt_column só nas linhas recém-traduzidas (a detecção do passo 2,
    nelas, ficou obsoleta).

    tentativas_column existe porque conteúdo genuinamente não traduzível (nomes
    próprios, termos curtos que o tradutor devolve sem alterar) nunca teria
    idioma_pt_column == "pt" e seria retentado para sempre sem um teto.

    Args:
        df:                Dataframe a atualizar (modificado in-place).
        source_column:     Coluna de texto original (ex.: "overview_en").
        target_column:     Coluna de tradução, já inicializada pelo chamador.
        idioma_en_column:  Coluna com o idioma detectado de source_column.
        idioma_pt_column:  Coluna com o idioma detectado de target_column.
        tentativas_column: Contador de tentativas de tradução por linha; criado
                           como 0 se ausente em df.
        detect_fn:         Função (texto) -> idioma detectado (ou None).
        translate_fn:      Função (texto) -> texto traduzido.
        max_workers:       Threads concorrentes usadas na tradução.
        max_tentativas:    Teto de tentativas antes de desistir de uma linha.

    Returns:
        Tupla (df, quantidade traduzida com sucesso nesta chamada).
    """
    if tentativas_column not in df.columns:
        df[tentativas_column] = 0

    df = _detect_missing(df, source_column, idioma_en_column, detect_fn)
    df = _detect_missing(df, target_column, idioma_pt_column, detect_fn)

    target_empty = df[target_column].isna() | (df[target_column] == "")
    direct_copy_mask = target_empty & (df[idioma_en_column] == "pt")
    df.loc[direct_copy_mask, target_column] = df.loc[direct_copy_mask, source_column]
    df.loc[direct_copy_mask, idioma_pt_column] = "pt"

    has_source = df[source_column].notna() & (df[source_column] != "")
    already_pt = df[idioma_pt_column] == "pt"
    esgotado = df[tentativas_column] >= max_tentativas
    eligible_mask = has_source & ~already_pt & ~esgotado

    logger.info(
        f"Traduzindo até {eligible_mask.sum()} registros para '{target_column}' "
        f"({max_workers} workers)..."
    )
    if not eligible_mask.any():
        return df, 0

    values = df.loc[eligible_mask, source_column].fillna("").tolist()
    translated = translate_in_parallel(values, translate_fn, max_workers=max_workers)
    df.loc[eligible_mask, target_column] = translated
    df.loc[eligible_mask, tentativas_column] = df.loc[eligible_mask, tentativas_column] + 1

    sucesso = sum(1 for original, result in zip(values, translated) if original and result != original)
    logger.info(f"{sucesso} registros traduzidos com sucesso ({target_column}).")

    df.loc[eligible_mask, idioma_pt_column] = (
        df.loc[eligible_mask, target_column].fillna("").apply(detect_fn)
    )
    return df, sucesso


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
    resolve_pt_translation; esta função só fornece o valor de cache para essa
    checagem localizar. Se o valor reaproveitado for igual à fonte (falha de
    tradução de um run anterior), o chamador vai marcá-lo como pendente e
    retentar sozinho.

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
