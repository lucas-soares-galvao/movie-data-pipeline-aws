"""traducao.py — Orquestração de tradução para português: elegibilidade, cache e
paralelismo (serviço de tradução via LLM, ver traducao_llm.py)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

__all__ = [
    "translate_in_parallel",
    "reuse_existing_translation",
    "resolve_pt_translation",
]

logger = logging.getLogger()

# Teto de tentativas de tradução por linha antes de desistir dela (ver
# resolve_pt_translation). Sem esse teto, conteúdo genuinamente não traduzível (nomes
# próprios, termos curtos que o tradutor devolve sem alterar) nunca teria
# detected_language_pt_column == "pt" e seria reenviado ao LLM a cada execução,
# para sempre.
_MAX_TRANSLATION_ATTEMPTS_DEFAULT = 3

# Página de erro do Google Translate, histórica: gravada como "tradução" por versões
# anteriores do código (quando o serviço de tradução ainda era Google Translate, ver
# traducao_google.py — removido), que não validavam o conteúdo antes de persistir.
# Mantida aqui só para higienizar dado LEGADO já gravado no SOT (ver Passo 0 de
# resolve_pt_translation) — não tem relação com o LLM, que não produz esse tipo de
# resposta. Ancorada no início e no formato "Error <status> (<motivo>)!!<n>" para não
# casar com uma tradução legítima que apenas mencione "Error".
_GOOGLE_ERROR_PAGE_PATTERN = re.compile(r"^Error \d{3} \([^)]*\)!!\d")


def _is_google_error_page(text: object) -> bool:
    """True se `text` é a página de erro histórica do Google Translate, e não uma
    tradução — usado só para higienizar dado legado (ver _GOOGLE_ERROR_PAGE_PATTERN).

    Aceita qualquer tipo (o valor vem de colunas de DataFrame, onde pode ser None/NaN);
    só uma string que começa com o padrão de erro conta.
    """
    return isinstance(text, str) and _GOOGLE_ERROR_PAGE_PATTERN.match(text) is not None


def translate_in_parallel(
    values: list[str], translate_fn: Callable[[str], str], max_workers: int = 5
) -> list[str]:
    """
    Aplica translate_fn a cada item de values em paralelo via ThreadPoolExecutor.

    Recebe a função de tradução como parâmetro (em vez de chamar translate_text_llm
    diretamente) para que os chamadores continuem passando sua própria referência
    local de translate_text_llm — a mesma que seus testes fazem mock.

    Args:
        values:       Textos a traduzir, na ordem em que devem ser retornados.
        translate_fn: Função chamada para cada item (ex.: translate_text_llm).
        max_workers:  Número de threads concorrentes.

    Returns:
        Lista de textos traduzidos, na mesma ordem de values.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(translate_fn, values))


def _detect_missing(
    df: pd.DataFrame,
    text_column: str,
    language_column: str,
    detect_fn: Callable[[str], str | None],
) -> pd.DataFrame:
    """Detecta o idioma de text_column em language_column, só para linhas onde
    language_column ainda está vazia/nula — evita redetectar o que já foi calculado
    numa execução anterior.

    Equivalente a shared_utils.idioma.add_detected_language_column(only_missing=True),
    duplicado aqui (em vez de importado) para não criar import circular: idioma.py
    importa deste módulo (ver histórico de make_capped_fallback, hoje removido).
    """
    if language_column not in df.columns:
        df[language_column] = None
    pending = df[language_column].isna() | (df[language_column] == "")
    if pending.any():
        df.loc[pending, language_column] = df.loc[pending, text_column].fillna("").apply(detect_fn)
    return df


def resolve_pt_translation(
    df: pd.DataFrame,
    source_column: str,
    target_column: str,
    detected_language_en_column: str,
    detected_language_pt_column: str,
    translation_attempts_column: str,
    detect_fn: Callable[[str], str | None],
    translate_fn: Callable[[str], str],
    max_workers: int = 5,
    max_attempts: int = _MAX_TRANSLATION_ATTEMPTS_DEFAULT,
    needs_translation_column: str | None = None,
) -> tuple[pd.DataFrame, int]:
    """
    Sincroniza target_column (já inicializada pelo chamador — nativo do TMDB, cache
    reaproveitado ou vazia) com source_column, mantendo detected_language_en_column/
    detected_language_pt_column como o idioma real detectado da fonte e do resultado,
    respectivamente — em vez da antiga heurística de string-diff, que não
    distinguia "não precisava traduzir" de "tradução falhou silenciosamente".

    Passo 0 (auto-reparo): descarta de target_column o que for a página de erro
    histórica do Google Translate (ver _is_google_error_page) — dado legado gravado
    antes da migração para tradução via LLM — e zera detected_language_pt_column e
    translation_attempts_column dessas linhas. Sem zerar o contador, uma linha que já
    tivesse esgotado o teto de tentativas ficaria com o texto de erro para sempre;
    zerando, ela volta a ser elegível em qualquer job que chame esta função (inclusive
    quando o texto veio do cache de reuse_existing_translation, que não filtra).

    Passos: (1) detecta detected_language_en_column a partir de source_column, só onde
    ainda vazia; (2) detecta detected_language_pt_column a partir do valor atual de
    target_column, só onde ainda vazia — cobre tradução nativa/cache já presentes antes
    desta chamada; (3) atalho de cópia direta: fonte já detectada como "pt" e
    target_column ainda vazia → copia sem chamar tradutor e marca
    detected_language_pt_column="pt" direto; (4) elegível para o tradutor = fonte
    preenchida E detected_language_pt_column != "pt" E translation_attempts_column <
    max_attempts; (5) traduz as linhas elegíveis; (6) incrementa
    translation_attempts_column para as linhas elegíveis desta execução; (7) redetecta
    detected_language_pt_column só nas linhas recém-traduzidas (a detecção do passo 2,
    nelas, ficou obsoleta); (8) se needs_translation_column for informado, grava nela
    fonte preenchida E detected_language_pt_column != "pt" — ao contrário da
    elegibilidade do passo 4, propositalmente SEM o teto de tentativas: reflete se o
    dado, como está agora, ainda não está em português, mesmo que o pipeline já tenha
    desistido de retentar essa linha.

    translation_attempts_column existe porque conteúdo genuinamente não traduzível
    (nomes próprios, termos curtos que o tradutor devolve sem alterar) nunca teria
    detected_language_pt_column == "pt" e seria retentado para sempre sem um teto —
    relevante também para o LLM, que não é determinístico (ver traducao_llm.py).

    Args:
        df:                Dataframe a atualizar (modificado in-place).
        source_column:     Coluna de texto original (ex.: "overview_en").
        target_column:     Coluna de tradução, já inicializada pelo chamador.
        detected_language_en_column: Coluna com o idioma detectado de source_column.
        detected_language_pt_column: Coluna com o idioma detectado de target_column.
        translation_attempts_column: Contador de tentativas de tradução por linha;
                           criado como 0 se ausente em df.
        detect_fn:         Função (texto) -> idioma detectado (ou None).
        translate_fn:      Função (texto) -> texto traduzido.
        max_workers:       Threads concorrentes usadas na tradução.
        max_attempts:      Teto de tentativas antes de desistir de uma linha.
        needs_translation_column: Se informado, nome da coluna booleana a gravar com
                           "fonte preenchida E detected_language_pt_column != 'pt'"
                           (estado atual do dado, sem considerar o teto de tentativas).
                           Se None (default), nenhuma coluna é criada — usado pelos
                           chamadores que não precisam desse sinal (ex.: tabela
                           configuration).

    Returns:
        Tupla (df, quantidade traduzida com sucesso nesta chamada).
    """
    if translation_attempts_column not in df.columns:
        df[translation_attempts_column] = 0

    polluted = df[target_column].apply(_is_google_error_page).astype(bool)
    if polluted.any():
        df.loc[polluted, target_column] = None
        df.loc[polluted, detected_language_pt_column] = None
        df.loc[polluted, translation_attempts_column] = 0
        logger.info(
            f"{polluted.sum()} valor(es) de '{target_column}' eram a página de erro do "
            "Google Translate, não uma tradução — descartado(s) para retradução."
        )

    df = _detect_missing(df, source_column, detected_language_en_column, detect_fn)
    df = _detect_missing(df, target_column, detected_language_pt_column, detect_fn)

    target_empty = df[target_column].isna() | (df[target_column] == "")
    direct_copy_mask = target_empty & (df[detected_language_en_column] == "pt")
    df.loc[direct_copy_mask, target_column] = df.loc[direct_copy_mask, source_column]
    df.loc[direct_copy_mask, detected_language_pt_column] = "pt"

    has_source = df[source_column].notna() & (df[source_column] != "")
    already_pt = df[detected_language_pt_column] == "pt"
    attempts_exhausted = df[translation_attempts_column] >= max_attempts
    eligible_mask = has_source & ~already_pt & ~attempts_exhausted

    logger.info(
        f"Traduzindo até {eligible_mask.sum()} registros para '{target_column}' "
        f"({max_workers} workers)..."
    )
    if not eligible_mask.any():
        if needs_translation_column:
            df[needs_translation_column] = has_source & (df[detected_language_pt_column] != "pt")
        return df, 0

    values = df.loc[eligible_mask, source_column].fillna("").tolist()
    translated = translate_in_parallel(values, translate_fn, max_workers=max_workers)
    df.loc[eligible_mask, target_column] = translated
    df.loc[eligible_mask, translation_attempts_column] = df.loc[eligible_mask, translation_attempts_column] + 1

    success_count = sum(1 for original, result in zip(values, translated) if original and result != original)
    failure_count = len(values) - success_count
    logger.info(
        f"{success_count} registros traduzidos com sucesso ({target_column}); "
        f"{failure_count} falha(s) de tradução / {len(values)} elegível(is)."
    )

    df.loc[eligible_mask, detected_language_pt_column] = (
        df.loc[eligible_mask, target_column].fillna("").apply(detect_fn)
    )

    if needs_translation_column:
        df[needs_translation_column] = has_source & (df[detected_language_pt_column] != "pt")

    return df, success_count


def reuse_existing_translation(
    df: pd.DataFrame,
    previous_df: pd.DataFrame | None,
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
    retentar sozinho. Se o valor reaproveitado for a página de erro histórica do
    Google (dado legado), esta função ainda o reaproveita — quem o descarta é
    resolve_pt_translation (passo 0), para a checagem morar num só lugar.

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
