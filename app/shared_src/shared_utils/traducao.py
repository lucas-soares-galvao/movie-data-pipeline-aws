"""traducao.py — Orquestração de tradução para português: elegibilidade, cache e
paralelismo (serviço de tradução via LLM, ver traducao_llm.py)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

import pandas as pd

__all__ = [
    "translate_in_parallel",
    "detect_in_parallel",
    "DETECT_MAX_WORKERS_DEFAULT",
    "format_elapsed",
    "reuse_existing_translation",
    "reuse_detected_language",
    "resolve_pt_translation",
]

logger = logging.getLogger()

_T = TypeVar("_T")

# Teto de tentativas de tradução por linha antes de desistir dela (ver
# resolve_pt_translation). Sem esse teto, conteúdo genuinamente não traduzível (nomes
# próprios, termos curtos que o tradutor devolve sem alterar) nunca teria
# detected_language_pt_column == "pt" e seria reenviado ao LLM a cada execução,
# para sempre.
_MAX_TRANSLATION_ATTEMPTS_DEFAULT = 3

# Threads da detecção de idioma. Cada chamada é curta (max_tokens=10, ver idioma_llm.py)
# e o modelo pago do OpenRouter não tem teto de requisições da plataforma; 10 é o mesmo
# valor já usado na tradução de glue_details (_TRANSLATE_MAX_WORKERS_LLM).
DETECT_MAX_WORKERS_DEFAULT = 10

# Progresso intermediário só vale a pena em lotes grandes — em um lote de poucas linhas
# o resumo final já diz tudo, e um log de progresso por coluna só polui.
_PROGRESS_MIN_TOTAL = 20
_PROGRESS_STEP_PCT = 10


def format_elapsed(seconds: float) -> str:
    """Formata uma duração em segundos como "45s" ou "3m12s" (ou "1h05m10s")."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _with_progress(fn: Callable[[str], _T], total: int, label: str) -> Callable[[str], _T]:
    """Envolve fn para logar o progresso (a cada _PROGRESS_STEP_PCT %) conforme as
    chamadas terminam — o log some em ordem de conclusão, não de submissão."""
    lock = threading.Lock()
    state = {"done": 0, "next_pct": _PROGRESS_STEP_PCT}
    started = time.monotonic()

    def wrapped(value: str) -> _T:
        result = fn(value)
        with lock:
            state["done"] += 1
            pct = state["done"] * 100 // total
            if pct >= state["next_pct"]:
                state["next_pct"] = (pct // _PROGRESS_STEP_PCT + 1) * _PROGRESS_STEP_PCT
                logger.info(
                    f"{label}: {state['done']}/{total} ({pct}%) — "
                    f"{format_elapsed(time.monotonic() - started)}"
                )
        return result

    return wrapped


def translate_in_parallel(
    values: list[str],
    translate_fn: Callable[[str], _T],
    max_workers: int = 5,
    progress_label: str | None = None,
) -> list[_T]:
    """
    Aplica translate_fn a cada item de values em paralelo via ThreadPoolExecutor.

    Recebe a função de tradução como parâmetro (em vez de chamar translate_text_llm
    diretamente) para que os chamadores continuem passando sua própria referência
    local de translate_text_llm — a mesma que seus testes fazem mock. Também serve
    para qualquer outra função de texto -> valor (ex.: detect_language_llm, ver
    detect_in_parallel).

    Args:
        values:         Textos a processar, na ordem em que devem ser retornados.
        translate_fn:   Função chamada para cada item (ex.: translate_text_llm).
        max_workers:    Número de threads concorrentes.
        progress_label: Se informado e values tiver pelo menos _PROGRESS_MIN_TOTAL
                        itens, loga o progresso a cada 10% com esse rótulo.

    Returns:
        Lista de resultados, na mesma ordem de values.
    """
    run_fn = translate_fn
    if progress_label and len(values) >= _PROGRESS_MIN_TOTAL:
        run_fn = _with_progress(translate_fn, len(values), progress_label)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(run_fn, values))


def detect_in_parallel(
    texts: list[str],
    detect_fn: Callable[[str], str | None],
    max_workers: int = DETECT_MAX_WORKERS_DEFAULT,
    label: str | None = None,
) -> list[str | None]:
    """
    Aplica detect_fn a cada texto em paralelo (ver translate_in_parallel) e, se label
    for informado, loga o progresso e um resumo final (detectados / falhas).

    Falha = texto não vazio cujo detect_fn devolveu None (chamada ao LLM falhou ou
    resposta fora do padrão ISO 639-1, ver detect_language_llm). Texto vazio devolve
    None sem chamada de rede e não conta como falha. O resumo existe porque cada falha
    individual só vira um WARNING solto — com milhares de linhas, sem ele não dá para
    saber se o LLM está degradado.

    Args:
        texts:       Textos a ter o idioma detectado, na ordem a retornar.
        detect_fn:   Função (texto) -> código ISO 639-1 (ou None).
        max_workers: Número de threads concorrentes.
        label:       Rótulo usado nos logs (ex.: "Detecção de idioma 'overview'").
                     Sem ele, nada é logado.

    Returns:
        Lista de códigos de idioma (ou None), na mesma ordem de texts.
    """
    if not texts:
        return []
    started = time.monotonic()
    results = translate_in_parallel(texts, detect_fn, max_workers=max_workers, progress_label=label)
    if label:
        detected = sum(1 for result in results if result is not None)
        failures = sum(1 for text, result in zip(texts, results) if result is None and text.strip())
        logger.info(
            f"{label}: {detected} detectado(s), {failures} falha(s) em {len(texts)} texto(s) "
            f"({format_elapsed(time.monotonic() - started)})."
        )
    return results


def _detect_missing(
    df: pd.DataFrame,
    text_column: str,
    language_column: str,
    detect_fn: Callable[[str], str | None],
    max_workers: int = DETECT_MAX_WORKERS_DEFAULT,
) -> pd.DataFrame:
    """Detecta o idioma de text_column em language_column, só para linhas onde
    language_column ainda está vazia/nula — evita redetectar o que já foi calculado
    numa execução anterior.

    Equivalente a shared_utils.idioma.add_detected_language_column(only_missing=True),
    duplicado aqui (em vez de importado) para não criar import circular: idioma.py
    importa deste módulo (detect_in_parallel).
    """
    if language_column not in df.columns:
        df[language_column] = None
    pending = df[language_column].isna() | (df[language_column] == "")
    if pending.any():
        texts = df.loc[pending, text_column].fillna("").tolist()
        df.loc[pending, language_column] = detect_in_parallel(
            texts, detect_fn, max_workers=max_workers, label=f"Detecção de idioma '{text_column}'",
        )
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

    df = _detect_missing(df, source_column, detected_language_en_column, detect_fn, max_workers)
    df = _detect_missing(df, target_column, detected_language_pt_column, detect_fn, max_workers)

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
    translated = translate_in_parallel(
        values, translate_fn, max_workers=max_workers, progress_label=f"Tradução '{target_column}'",
    )
    df.loc[eligible_mask, target_column] = translated
    df.loc[eligible_mask, translation_attempts_column] = df.loc[eligible_mask, translation_attempts_column] + 1

    success_count = sum(1 for original, result in zip(values, translated) if original and result != original)
    failure_count = len(values) - success_count
    logger.info(
        f"{success_count} registros traduzidos com sucesso ({target_column}); "
        f"{failure_count} falha(s) de tradução / {len(values)} elegível(is)."
    )

    df.loc[eligible_mask, detected_language_pt_column] = detect_in_parallel(
        df.loc[eligible_mask, target_column].fillna("").tolist(),
        detect_fn,
        max_workers=max_workers,
        label=f"Redetecção de idioma '{target_column}'",
    )

    if needs_translation_column:
        df[needs_translation_column] = has_source & (df[detected_language_pt_column] != "pt")

    return df, success_count


def reuse_detected_language(
    df: pd.DataFrame,
    previous_df: pd.DataFrame | None,
    text_column: str,
    language_column: str,
    key_column: str = "id",
) -> pd.DataFrame:
    """
    Preenche language_column com o idioma já detectado em previous_df quando
    text_column não mudou entre o registro antigo e o novo, para a mesma key_column —
    evita redetectar (uma chamada ao LLM por linha) texto idêntico ao da última execução.

    Só reaproveita valor não nulo/vazio: uma detecção que falhou (None) na execução
    anterior não é "congelada", fica pendente e é tentada de novo por
    _detect_missing/add_detected_language_column(only_missing=True). Texto alterado
    também força nova detecção, e valores já preenchidos em df nunca são sobrescritos.

    Args:
        df:              DataFrame novo (run atual), com key_column e text_column.
        previous_df:     Registros já persistidos, ou None/vazio se não há histórico.
        text_column:     Coluna de texto cujo idioma foi detectado (ex.: "overview").
        language_column: Coluna com o idioma detectado de text_column; criada como
                         nula em df se ausente.
        key_column:      Coluna usada para casar registros antigos e novos.

    Returns:
        df com language_column atualizada (também modificado in-place).
    """
    if previous_df is None or previous_df.empty:
        return df
    if not {key_column, text_column, language_column}.issubset(previous_df.columns):
        # Schema antigo (partição/tabela gravada antes da coluna existir) — nada a reaproveitar.
        return df

    cache = (
        previous_df[[key_column, text_column, language_column]]
        .drop_duplicates(subset=key_column, keep="last")
        .set_index(key_column)
    )
    old_text = df[key_column].map(cache[text_column])
    old_language = df[key_column].map(cache[language_column])

    if language_column not in df.columns:
        df[language_column] = None
    language_empty = df[language_column].isna() | (df[language_column] == "")
    text_valid = df[text_column].notna() & (df[text_column] != "")
    old_language_valid = old_language.notna() & (old_language != "")

    can_reuse = language_empty & text_valid & old_language_valid & (old_text == df[text_column])
    if can_reuse.any():
        df.loc[can_reuse, language_column] = old_language[can_reuse]
        logger.info(
            f"Reaproveitando idioma detectado de {can_reuse.sum()} registro(s) "
            f"para '{language_column}' (texto '{text_column}' inalterado)."
        )
    return df


def reuse_existing_translation(
    df: pd.DataFrame,
    previous_df: pd.DataFrame | None,
    source_column: str,
    target_column: str,
    key_column: str = "id",
    detected_language_en_column: str | None = None,
    detected_language_pt_column: str | None = None,
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
        detected_language_en_column: Se informado, também reaproveita o idioma já
                       detectado de source_column (ver reuse_detected_language) —
                       poupa a redetecção, que custa uma chamada ao LLM por linha.
        detected_language_pt_column: Idem para o idioma detectado de target_column,
                       reaproveitado quando o texto traduzido é idêntico ao antigo
                       (inclui a tradução recém-reaproveitada acima).

    Returns:
        df com target_column (e as colunas de idioma, se informadas) atualizada
        (também modificado in-place).
    """
    df = _reuse_translation_text(df, previous_df, source_column, target_column, key_column)
    if detected_language_en_column:
        df = reuse_detected_language(df, previous_df, source_column, detected_language_en_column, key_column)
    if detected_language_pt_column:
        df = reuse_detected_language(df, previous_df, target_column, detected_language_pt_column, key_column)
    return df


def _reuse_translation_text(
    df: pd.DataFrame,
    previous_df: pd.DataFrame | None,
    source_column: str,
    target_column: str,
    key_column: str,
) -> pd.DataFrame:
    """Parte de reuse_existing_translation que reaproveita só o texto traduzido."""
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
