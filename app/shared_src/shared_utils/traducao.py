"""traducao.py — Orquestração de tradução para português: elegibilidade, cache,
paralelismo e escolha do serviço (Google Translate ou AWS Translate)."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TypeVar

import boto3
import pandas as pd

from shared_utils.traducao_aws import translate_text_aws
from shared_utils.traducao_google import is_google_error_page, translate_text

__all__ = [
    "translate_text",
    "translate_text_aws",
    "get_translate_chars_used_this_month",
    "resolve_translate_fn",
    "translate_in_parallel",
    "reuse_existing_translation",
    "resolve_pt_translation",
    "make_capped_fallback",
]

T = TypeVar("T")

logger = logging.getLogger()

# Orçamento MENSAL de caracteres para o fallback ao AWS Translate (pago por caractere)
# quando ele não é o serviço escolhido — ver resolve_translate_fn e
# get_translate_chars_used_this_month. Medido em caracteres (não em número de chamadas)
# porque é isso que a AWS cobra: uma sinopse longa pesa muito mais que uma keyword curta.
# 2_000_000 == o free tier mensal do AWS Translate (primeiros 12 meses da conta) — acima
# disso o excedente passa a ser cobrado a US$15/milhão de caracteres.
#
# Era um teto POR EXECUÇÃO (6_000) até esta constante ser revista: o Glue Details roda
# ~11x/mês (EventBridge — semanal + mensal, ver infra/eventbridge.tf), e 6_000/execução
# provou ser pequeno demais pra resgatar o que o Google falha (ver
# get_translate_chars_used_this_month) — o orçamento estourava antes de cobrir o volume
# real de falhas. Agora resolve_translate_fn consulta o consumo real do mês (via
# CloudWatch) a cada chamada e usa o que sobrar do teto mensal, em vez de resetar um teto
# fixo a cada execução.
_AWS_FALLBACK_MAX_CHARS_DEFAULT = 2_000_000

# Teto de tentativas de tradução por linha antes de desistir dela (ver
# resolve_pt_translation). Sem esse teto, conteúdo genuinamente não traduzível (nomes
# próprios, termos curtos que o tradutor devolve sem alterar) nunca teria
# detected_language_pt_column == "pt" e seria reenviado ao Google/AWS a cada execução,
# para sempre.
_MAX_TRANSLATION_ATTEMPTS_DEFAULT = 3


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
    resolve_pt_translation, até 5 workers nos chamadores atuais — glue_details e
    backfill_traducao.py).

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


def get_translate_chars_used_this_month(
    cloudwatch_client: object = None, region: str = "us-east-1",
) -> int:
    """
    Soma o `CharacterCount` que o próprio AWS Translate publica no CloudWatch (namespace
    `AWS/Translate`) desde o dia 1 do mês corrente (UTC) até agora — a mesma métrica que a
    AWS usa pra faturar, consultada ao vivo em vez de mantida num contador próprio.

    Um contador próprio precisaria persistir entre execuções (o Glue Details roda como
    processo novo a cada disparo, sem estado em memória compartilhado). O bucket TEMP, onde
    hoje vive o checkpoint de backfill (`scripts.backfill_shared`), não serviria: seu
    lifecycle apaga tudo em 1 dia, sem filtro de prefixo (`infra/s3.tf`,
    `delete-after-1-day`) — um contador mensal não sobreviveria até o fim do mês.
    Consultar o CloudWatch evita esse problema (nenhum estado novo pra persistir) e nunca
    diverge do consumo real faturado (diferente de um contador próprio, que dessincroniza
    se uma execução falhar depois de traduzir mas antes de salvar).

    `CharacterCount` é publicado com as dimensões `LanguagePair` (par de idiomas, um por
    idioma de origem detectado automaticamente — sempre "<origem>-pt" neste projeto) e
    `Operation` — não existe uma dimensão "todos os pares", então é preciso enumerar os
    pares publicados (`list_metrics`) e somar `Sum` de cada um.

    Se a consulta ao CloudWatch falhar (permissão ausente, erro transitório): loga e
    devolve `sys.maxsize`, fazendo `resolve_translate_fn` tratar o orçamento como
    esgotado — mais seguro financeiramente do que assumir consumo zero e arriscar gastar
    sem visibilidade de quanto já foi usado no mês.

    Args:
        cloudwatch_client: Cliente boto3 do CloudWatch já pronto (criado sob demanda, com
                           `region`, se None) — recebido como parâmetro pra os testes
                           poderem mockar, mesmo racional de `translate_google`/
                           `translate_aws` em `resolve_translate_fn`.
        region:            Região do CloudWatch a consultar. AWS Translate não está
                           disponível em sa-east-1 (região principal do pipeline — ver
                           `traducao_aws.translate_text_aws`), então a métrica só existe
                           em us-east-1.

    Returns:
        Caracteres traduzidos via AWS Translate (`TranslateText`) desde o início do mês
        corrente, ou `sys.maxsize` se a consulta ao CloudWatch falhar.
    """
    client = cloudwatch_client or boto3.client("cloudwatch", region_name=region)
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        pairs: set[str] = set()
        paginator = client.get_paginator("list_metrics")
        for page in paginator.paginate(Namespace="AWS/Translate", MetricName="CharacterCount"):
            for metric in page["Metrics"]:
                dims = {d["Name"]: d["Value"] for d in metric["Dimensions"]}
                if "LanguagePair" in dims:
                    pairs.add(dims["LanguagePair"])

        total = 0
        for pair in pairs:
            response = client.get_metric_statistics(
                Namespace="AWS/Translate",
                MetricName="CharacterCount",
                Dimensions=[
                    {"Name": "LanguagePair", "Value": pair},
                    {"Name": "Operation", "Value": "TranslateText"},
                ],
                StartTime=start_of_month,
                EndTime=now,
                Period=2_592_000,  # 30 dias — o mês corrente cabe num único datapoint
                Statistics=["Sum"],
            )
            total += sum(datapoint["Sum"] for datapoint in response["Datapoints"])
        return int(total)
    # Consulta de observabilidade, não pode derrubar o job de tradução.
    except Exception:
        logger.exception(
            "Falha ao consultar CharacterCount do AWS Translate no CloudWatch — "
            "assumindo orçamento mensal esgotado (mais seguro que assumir consumo zero)."
        )
        return sys.maxsize


def resolve_translate_fn(
    provider: str,
    translate_google: Callable[[str], str] = translate_text,
    translate_aws: Callable[[str], str] = translate_text_aws,
    aws_fallback_max_chars: int = _AWS_FALLBACK_MAX_CHARS_DEFAULT,
    get_chars_used_this_month: Callable[[], int] = get_translate_chars_used_this_month,
) -> Callable[[str], str]:
    """
    Resolve o provedor de tradução (`"google"` ou `"aws"`) para uma função composta
    primário+fallback: o provider escolhido é tentado primeiro; se falhar (resultado
    igual ao texto original, texto não-vazio — mesmo sinal de falha usado em
    resolve_pt_translation), o outro serviço é tentado automaticamente antes de
    desistir.

    `provider="google"` → primário=Google (grátis), fallback=AWS Translate — pago por
    caractere, por isso limitado ao que sobrar do orçamento MENSAL de
    aws_fallback_max_chars (rede de segurança de custo; ver make_capped_fallback e
    get_translate_chars_used_this_month). O orçamento é consultado ao vivo a cada chamada
    — não é mais um teto fixo resetado por execução — então chamadas concorrentes/
    sucessivas dentro do mesmo mês naturalmente compartilham o teto real já consumido.
    `provider="aws"` → primário=AWS Translate, fallback=Google (grátis) — sem limite,
    já que quem escolheu "aws" explicitamente já aceitou o custo do primário.

    `translate_google`/`translate_aws` são recebidos como parâmetro (em vez de resolvidos
    aqui dentro) pelo mesmo motivo de `translate_in_parallel`: os chamadores passam suas
    próprias referências locais de `translate_text`/`translate_text_aws` — as mesmas que
    seus testes fazem mock (ex.: `patch("src.utils.translate_text", ...)`). Resolver via
    referência direta ao módulo quebraria esse patch.

    Args:
        provider:                  `"google"` (deep_translator, grátis) ou `"aws"` (AWS
                                   Translate, pago por caractere).
        translate_google:          Função de tradução via Google.
        translate_aws:             Função de tradução via AWS.
        aws_fallback_max_chars:    Orçamento MENSAL de caracteres para o fallback ao AWS
                                   Translate, aplicado somente quando `provider="google"`
                                   (AWS é o fallback). Ignorado quando `provider="aws"`
                                   (AWS já é o primário escolhido explicitamente).
        get_chars_used_this_month: Função sem argumentos que devolve quantos caracteres já
                                   foram consumidos no mês corrente — recebida como
                                   parâmetro pelo mesmo motivo de translate_google/
                                   translate_aws (testes mockam sem tocar o CloudWatch de
                                   verdade).

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
        remaining_budget = max(0, aws_fallback_max_chars - get_chars_used_this_month())
        fallback = make_capped_fallback(fallback, remaining_budget, on_over_budget=lambda text: text)

    def _translate_with_fallback(text: str) -> str:
        result = primary(text)
        if not text or result != text:
            return result
        return fallback(text)

    return _translate_with_fallback


def translate_in_parallel(
    values: list[str], translate_fn: Callable[[str], str], max_workers: int = 5
) -> list[str]:
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
    language_column: str,
    detect_fn: Callable[[str], str | None],
) -> pd.DataFrame:
    """Detecta o idioma de text_column em language_column, só para linhas onde
    language_column ainda está vazia/nula — evita redetectar (e reenviar caracteres ao
    fallback pago do AWS Comprehend) o que já foi calculado numa execução anterior.

    Equivalente a shared_utils.idioma.add_detected_language_column(only_missing=True),
    duplicado aqui (em vez de importado) para não criar import circular: idioma.py já
    importa make_capped_fallback deste módulo.
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

    Passo 0 (auto-reparo): descarta de target_column o que for a página de erro do Google
    (ver is_google_error_page) — gravada como "tradução" por versões anteriores de
    translate_text, que não validavam o conteúdo — e zera detected_language_pt_column e
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
    detected_language_pt_column == "pt" e seria retentado para sempre sem um teto.

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

    polluted = df[target_column].apply(is_google_error_page).astype(bool)
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
    retentar sozinho. Se o valor reaproveitado for a página de erro do Google (gravada
    por versões antigas de translate_text), esta função ainda o reaproveita — quem o
    descarta é resolve_pt_translation (passo 0), para a checagem morar num só lugar.

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
