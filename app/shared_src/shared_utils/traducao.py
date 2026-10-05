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

from shared_utils.llm_metrics import record_balance

__all__ = [
    "translate_in_parallel",
    "detect_in_parallel",
    "DETECT_MAX_WORKERS_DEFAULT",
    "format_elapsed",
    "reuse_existing_translation",
    "reuse_detected_language",
    "resolve_pt_translation",
    "restore_failed_translations",
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

# Quantos ids de exemplo das linhas ainda pendentes entram na linha de balanço.
_BALANCE_SAMPLE_IDS = 3


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
    None sem chamada de rede e não conta como falha — o resumo os mostra à parte
    ("K vazio(s)"), senão "N detectado(s) em T texto(s)" parece perda quando boa parte de T
    nunca foi enviada ao LLM. O resumo existe porque cada falha individual só vira um
    WARNING solto — com milhares de linhas, sem ele não dá para saber se o LLM está
    degradado.

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
        empty = sum(1 for text in texts if not text.strip())
        empty_part = f", {empty} vazio(s)" if empty else ""
        logger.info(
            f"{label}: {detected} detectado(s), {failures} falha(s){empty_part} em {len(texts)} texto(s) "
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


def _pending_mask(
    df: pd.DataFrame,
    source_column: str,
    target_column: str,
    detected_language_pt_column: str,
) -> pd.Series:
    """Linhas "pendentes" (*_needs_translation): fonte preenchida, idioma do destino diferente de
    "pt" (inclui detecção indisponível) E texto do destino não alterado em relação à fonte.

    "Alterado" = destino preenchido e diferente da fonte, sem diferença de maiúsculas/minúsculas
    nem de espaços nas pontas (assim "sexy" -> "Sexy" continua não alterado). Se o texto mudou,
    alguém (o TMDB ou o LLM) o traduziu: a dúvida do detector de idioma — que erra em textos
    curtos, como listas de keywords ("drama turco" detectado como "tr") — não deve reabrir a
    pendência. Destino vazio ou igual à fonte continuam pendentes. Só afeta o sinal/log: quais
    linhas vão ao tradutor (elegibilidade) continua sendo decidido pelo idioma detectado.
    """
    has_source = df[source_column].notna() & (df[source_column] != "")
    has_target = df[target_column].notna() & (df[target_column] != "")
    source_text = df[source_column].fillna("").astype(str).str.strip().str.casefold()
    target_text = df[target_column].fillna("").astype(str).str.strip().str.casefold()
    text_changed = has_target & (target_text != source_text)
    return has_source & (df[detected_language_pt_column] != "pt") & ~text_changed


def _log_balance(
    df: pd.DataFrame,
    source_column: str,
    target_column: str,
    detected_language_pt_column: str,
    has_source: pd.Series,
    *,
    tried: int,
    ok: int,
    same: int,
    kept: int,
    sample_id_column: str | None,
) -> None:
    """Loga a linha de balanço de target_column (estado final desta chamada) e a soma no total
    da execução. "Pendente" é a mesma definição de *_needs_translation (ver _pending_mask), sem o
    teto de tentativas."""
    source = int(has_source.sum())
    already_pt = int((has_source & (df[detected_language_pt_column] == "pt")).sum())
    pending_mask = _pending_mask(df, source_column, target_column, detected_language_pt_column)
    pending_mask = pending_mask.fillna(False).astype(bool)
    pending = int(pending_mask.sum())
    record_balance(
        target_column, fonte=source, ja_pt=already_pt, traduzidas=tried, ok=ok, iguais=same,
        mantidas=kept, pendentes=pending,
    )
    message = (
        f"Balanço '{target_column}': {source} com fonte | {already_pt} já em pt | "
        f"{tried} traduzida(s) ({ok} ok, {same} igual(is) à fonte) | "
        f"{kept} mantida(s) por detecção indisponível | {pending} pendente(s)"
    )
    if pending and sample_id_column and sample_id_column in df.columns:
        sample = df.loc[pending_mask, sample_id_column].head(_BALANCE_SAMPLE_IDS).tolist()
        message += f" (ex.: {sample_id_column} {', '.join(str(value) for value in sample)})"
    logger.info(message)


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
    sample_id_column: str | None = None,
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
    max_attempts E idioma do destino disponível (ver abaixo); (5) traduz as linhas
    elegíveis; (6) incrementa
    translation_attempts_column para as linhas elegíveis desta execução; (7) redetecta
    detected_language_pt_column só nas linhas recém-traduzidas (a detecção do passo 2,
    nelas, ficou obsoleta); (8) se needs_translation_column for informado, grava nela
    fonte preenchida E detected_language_pt_column != "pt" E texto do destino não alterado
    em relação à fonte (ver _pending_mask) — ao contrário da elegibilidade do passo 4,
    propositalmente SEM o teto de tentativas: reflete se o dado, como está agora, ainda não
    está em português, mesmo que o pipeline já tenha desistido de retentar essa linha. O
    critério "texto não alterado" existe porque o detector de idioma erra em textos curtos
    (listas de keywords): uma tradução correta detectada como "en"/"es" não é pendência.

    "Idioma do destino disponível": se target_column tem texto mas a detecção do passo 2
    falhou (detected_language_pt_column nulo — erro/timeout/resposta inválida do LLM), o
    idioma real do destino é desconhecido, não "diferente de pt". Traduzir nesse caso
    sobrescreveria um texto que pode já estar correto (inclusive a tradução nativa do
    TMDB) e, se o tradutor também falhar, o trocaria pela fonte em inglês. Essas linhas
    ficam como estão, sem gastar tentativa; a detecção é refeita na próxima execução
    (valor nulo nunca é reaproveitado, ver reuse_detected_language). Destino vazio não
    entra nessa regra: o idioma nulo ali é esperado, e a linha continua elegível.

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
                           "fonte preenchida E detected_language_pt_column != 'pt' E texto
                           do destino não alterado em relação à fonte" (estado atual do
                           dado, sem considerar o teto de tentativas; fica True enquanto o
                           destino for igual à fonte/vazio e a detecção não confirmar "pt").
                           Se None (default), nenhuma coluna é criada — usado pelos
                           chamadores que não precisam desse sinal (ex.: tabela
                           configuration).
        sample_id_column:  Se informado (e presente em df), até 3 valores dessa coluna das
                           linhas ainda pendentes entram como exemplo na linha de balanço
                           (ex.: "id"). Ignorado se a coluna não existir.

    Returns:
        Tupla (df, quantidade traduzida com sucesso nesta chamada). Ao final loga uma linha de
        balanço da coluna (com fonte / já em pt / traduzidas / mantidas / pendentes) e soma as
        mesmas contagens em shared_utils.llm_metrics para o total da execução.
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
    has_target = df[target_column].notna() & (df[target_column] != "")
    already_pt = df[detected_language_pt_column] == "pt"
    attempts_exhausted = df[translation_attempts_column] >= max_attempts
    detection_unknown = has_target & df[detected_language_pt_column].isna()
    eligible_mask = has_source & ~already_pt & ~attempts_exhausted & ~detection_unknown

    skipped_unknown = int((has_source & ~already_pt & ~attempts_exhausted & detection_unknown).sum())
    if skipped_unknown:
        logger.info(
            f"{skipped_unknown} registro(s) de '{target_column}' mantidos como estão: a detecção do "
            "idioma do texto atual falhou, então não dá para saber se ele já está em português "
            "(a detecção é refeita na próxima execução)."
        )
    logger.info(
        f"Traduzindo até {eligible_mask.sum()} registros para '{target_column}' "
        f"({max_workers} workers)..."
    )
    if not eligible_mask.any():
        if needs_translation_column:
            df[needs_translation_column] = _pending_mask(
                df, source_column, target_column, detected_language_pt_column,
            )
        _log_balance(
            df, source_column, target_column, detected_language_pt_column, has_source,
            tried=0, ok=0, same=0, kept=skipped_unknown, sample_id_column=sample_id_column,
        )
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
        df[needs_translation_column] = _pending_mask(
            df, source_column, target_column, detected_language_pt_column,
        )

    _log_balance(
        df, source_column, target_column, detected_language_pt_column, has_source,
        tried=len(values), ok=success_count, same=failure_count, kept=skipped_unknown,
        sample_id_column=sample_id_column,
    )
    return df, success_count


def restore_failed_translations(
    df: pd.DataFrame,
    previous_df: pd.DataFrame | None,
    source_column: str,
    target_column: str,
    detected_language_pt_column: str,
    needs_translation_column: str | None = None,
    key_column: str = "id",
) -> pd.DataFrame:
    """
    Devolve a tradução antiga às linhas em que a retradução forçada falhou.

    Na retradução forçada o cache é ignorado (ver reuse_existing_translation), então uma falha
    do LLM — translate_text_llm devolve o texto original em erro — trocaria uma tradução boa
    pelo texto em inglês. Esta função roda depois de resolve_pt_translation e restaura, para a
    mesma key_column, o valor antigo de target_column e de detected_language_pt_column quando:
      - o texto novo é igual à fonte (sem diferença de maiúsculas/minúsculas nem de espaços nas
        pontas, mesmo critério de _pending_mask) — sinal de que a tradução falhou; e
      - previous_df tem um texto antigo preenchido, diferente da fonte e com idioma detectado
        "pt" — sinal de que era uma tradução válida. É essa exigência que impede restaurar lixo:
        um texto de erro legado (ex.: "Error 404 (Not Found)!!1") é detectado como outro idioma.

    Tradução que legitimamente fica igual à fonte (nomes próprios) não é restaurada: o texto
    antigo dela também é igual à fonte. Com needs_translation_column, o sinal das linhas
    restauradas é recalculado (_pending_mask) — o idioma restaurado é "pt", então deixam de ser
    pendência. O contador de tentativas não é alterado.

    Args:
        df:              DataFrame já processado por resolve_pt_translation (modificado in-place).
        previous_df:     Registros persistidos antes da retradução, ou None/vazio se não há
                         histórico.
        source_column:   Coluna de texto original (ex.: "overview_en").
        target_column:   Coluna de tradução (ex.: "overview_pt").
        detected_language_pt_column: Coluna com o idioma detectado de target_column.
        needs_translation_column: Se informado e presente em df, é recalculada nas linhas
                         restauradas.
        key_column:      Coluna usada para casar registros antigos e novos.

    Returns:
        df com as linhas falhas restauradas (também modificado in-place).
    """
    if previous_df is None or previous_df.empty:
        return df
    if not {key_column, target_column, detected_language_pt_column}.issubset(previous_df.columns):
        # Schema antigo (partição/tabela gravada antes da coluna existir) — nada a restaurar.
        return df

    cache = (
        previous_df[[key_column, target_column, detected_language_pt_column]]
        .drop_duplicates(subset=key_column, keep="last")
        .set_index(key_column)
    )
    old_target = df[key_column].map(cache[target_column])
    old_language = df[key_column].map(cache[detected_language_pt_column])

    has_source = df[source_column].notna() & (df[source_column] != "")
    source_text = df[source_column].fillna("").astype(str).str.strip().str.casefold()
    target_text = df[target_column].fillna("").astype(str).str.strip().str.casefold()
    old_text = old_target.fillna("").astype(str).str.strip().str.casefold()

    failed = has_source & (target_text == source_text)
    old_valid = old_target.notna() & (old_target != "") & (old_text != source_text) & (old_language == "pt")
    restore = failed & old_valid
    if restore.any():
        df.loc[restore, target_column] = old_target[restore]
        df.loc[restore, detected_language_pt_column] = "pt"
        if needs_translation_column and needs_translation_column in df.columns:
            pending = _pending_mask(df, source_column, target_column, detected_language_pt_column)
            df.loc[restore, needs_translation_column] = pending[restore]
        logger.info(
            f"Retradução de '{target_column}' falhou em {int(restore.sum())} registro(s): "
            "tradução anterior restaurada."
        )
    return df


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
        reused = int(can_reuse.sum())
        record_balance(target_column, reaproveitadas=reused)
        logger.info(
            f"Reaproveitando tradução existente de {reused} de {len(df)} registro(s) "
            f"({round(100 * reused / len(df))}%) para '{target_column}' "
            f"(fonte '{source_column}' inalterada)."
        )
    return df
