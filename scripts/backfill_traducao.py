"""
backfill_traducao.py — Adiciona overview_pt, tagline_pt e keywords_pt (e as
colunas de diagnóstico *_detected_language_en/*_detected_language_pt/
*_translation_attempts/*_needs_translation) aos detalhes históricos.

Lê tb_details_movie_tmdb e tb_details_tv_tmdb ano a ano e traduz para
português, via LLM (OpenRouter — ver shared_utils.traducao_llm), os campos
ainda pendentes (espelhando o que o Glue Details faz para dados novos). As
três colunas usam a mesma regra de elegibilidade, resolvida por
shared_utils.traducao.resolve_pt_translation: o campo de origem preenchido e
o idioma detectado do RESULTADO (*_detected_language_pt, e não da fonte)
ainda diferente de "pt" — original_language não entra no critério (é o
idioma de produção original do título, não o idioma do texto retornado pela
API; não garante que overview_en/tagline/keywords já estejam em português —
ver shared_utils/traducao.py):
  - overview_pt:  overview_en preenchido, overview_detected_language_pt != "pt"
  - tagline_pt:   tagline preenchida, tagline_detected_language_pt != "pt"
  - keywords_pt:  keywords preenchidas, keywords_detected_language_pt != "pt"
Quando o idioma detectado da fonte (*_detected_language_en) já é "pt", o
texto é copiado diretamente para a coluna _pt sem chamar tradução — evita
reenviar ao LLM um texto que já está em português. Basear a
elegibilidade no idioma detectado do RESULTADO (em vez de comparar string com
a fonte, como antes) evita tanto retraduzir o que já está correto quanto
deixar uma mistradução silenciosa (resultado diferente da fonte, mas em
outro idioma que não pt) permanentemente marcada como concluída.
*_translation_attempts limita quantas vezes uma linha é reenviada ao
tradutor — sem esse teto, conteúdo genuinamente não traduzível (nomes
próprios, termos curtos que o tradutor devolve sem alterar) seria retentado
para sempre, já que seu idioma detectado nunca vira "pt" (ver docstring de
resolve_pt_translation). *_needs_translation (booleano) grava o mesmo
critério de elegibilidade acima — mais "texto do destino não alterado em
relação à fonte", porque o detector de idioma erra em textos curtos e uma
tradução correta detectada como outro idioma não é pendência — mas SEM o
teto de *_translation_attempts: reflete se o campo, como está agora, ainda
não está em português, mesmo esgotado o número de tentativas automáticas. Não é gerado collection_name_pt
— diferente dos demais, ele vem de uma chamada à API do TMDB (não de tradução
por LLM) e foi deixado fora deste script. Não re-chama a API do TMDB para
os campos acima.

Leitura feita diretamente do S3 (parquet) — sem Athena/CTAS — para evitar
necessidade de athena:GetWorkGroup e glue:DeleteTable no usuário prod_temp.

Uso:
    python scripts/backfill_traducao.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    TABLE_GROUP            (identifica o checkpoint; valor "traducao" neste script)
    S3_BUCKET_SOT          (parquets reais de tb_details_movie/tv_tmdb)
    S3_BUCKET_TEMP         (onde o checkpoint de retomada é armazenado)
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_DETAILS_MOVIE
    TABLE_DETAILS_TV
    GLUE_DATA_QUALITY_JOB_NAME (usada pela chamada local ao Glue AGG ao final, ver "Glue AGG" abaixo)
    S3_BUCKET_SPEC, S3_PREFIX_SPEC, DB_UNIFIED, TABLE_DISCOVER_UNIFIED, ENVIRONMENT
                                (idem, ver "Glue AGG" abaixo)

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)
    BACKFILL_WAIT_SECONDS (padrão: 30 — pausa entre partições para não disparar rajadas
                            de chamada ao LLM; só aplicada quando a partição efetivamente
                            traduziu algo — partições vazias ou já 100% traduzidas seguem
                            direto para a próxima, sem espera)
    BACKFILL_RESET_ATTEMPTS (padrão: desligado; "true" ativa o reparo pontual de dado legado:
                            descarta os *_pt gravados com um texto de erro legado no lugar da
                            tradução e zera *_detected_language_pt/*_translation_attempts
                            dessas linhas, que então são retraduzidas via LLM mesmo que já
                            tivessem esgotado o teto de tentativas. Limpar o checkpoint antes,
                            senão as partições já concluídas são puladas)
    FILMBOT_SECRET_ARN    (ARN do secret unificado, usado por
                            shared_utils.llm_client.load_llm_api_key para ler o campo
                            llm_api_key — chave do LLM via OpenRouter. Sem ela (nem
                            LLM_API_KEY definida), cada tradução/detecção falha
                            individualmente e devolve o texto original/None, sem
                            derrubar o script)

Glue AGG:
    Ao final, antes de limpar o checkpoint, roda o Glue AGG (query Athena de unificação +
    escrita da tabela SPEC + disparo do Data Quality sobre a tabela unificada) diretamente no
    processo — ver backfill_shared.trigger_agg_locally. Faz sentido aqui porque overview_pt/
    tagline_pt/keywords_pt entram na tabela SPEC final. Uma falha nessa etapa é logada como
    ERROR mas não derruba o backfill (que já terminou com sucesso) — o trigger agendado
    (sábado/domingo 08:00 BRT) e o alarme SNS de falha continuam cobrindo o caso.

Notificação:
    Ao final, publica no tópico SNS de sucesso do backfill (SNS_TOPIC_ARN_BACKFILL_SUCCESS,
    opcional) — ver backfill_shared.notify_backfill_success.

Retomada automática:
    Se a credencial AWS expirar (ExpiredTokenException do STS ou ExpiredToken
    do S3), o script sai com exit code 75
    (backfill_shared.RETRYABLE_EXIT_CODE). O workflow renova a credencial
    e roda o script de novo — como o progresso é lido do checkpoint em S3
    (s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{TABLE_GROUP}.json), as
    partições (ano+tipo) já concluídas são puladas.
"""

import os
import re
import sys
import time
from pathlib import Path

from typing import Callable, Optional

import awswrangler as wr
import boto3
import pandas as pd
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "shared_src"))
from shared_utils.idioma_llm import detect_language_llm  # noqa: E402
from shared_utils.llm_metrics import log_llm_usage_summary  # noqa: E402
from shared_utils.traducao import resolve_pt_translation
from shared_utils.traducao_llm import translate_text_llm

import backfill_shared as shared

logger = shared.setup_logging()

_TRANSLATE_MAX_WORKERS = 5

# Texto de erro legado, gravado como "tradução" por versões anteriores do código (antes
# da migração para LLM), que não validavam o conteúdo antes de persistir. Ancorado no
# início e no formato "Error <status> (<motivo>)!!<n>" para não casar com uma tradução
# legítima que apenas mencione "Error".
_LEGACY_ERROR_PAGE_PATTERN = re.compile(r"^Error \d{3} \([^)]*\)!!\d")

# (coluna traduzida, idioma detectado do resultado, contador de tentativas) de cada campo
_TRANSLATION_COLUMNS = [
    ("overview_pt", "overview_detected_language_pt", "overview_translation_attempts"),
    ("tagline_pt", "tagline_detected_language_pt", "tagline_translation_attempts"),
    ("keywords_pt", "keywords_detected_language_pt", "keywords_translation_attempts"),
]


def _reset_polluted_translations(df: pd.DataFrame) -> int:
    """
    Descarta dos campos *_pt o que for o texto de erro legado (ver
    _LEGACY_ERROR_PAGE_PATTERN) e zera o idioma detectado e o contador de tentativas dessas linhas, para que
    resolve_pt_translation as retraduza via LLM mesmo que já tivessem esgotado o teto de
    tentativas (sem zerar o contador, a linha ficaria com o texto de erro para sempre).

    Ativada só por BACKFILL_RESET_ATTEMPTS=true (reparo pontual de dado legado).

    Returns:
        Quantidade de valores *_pt descartados (soma dos três campos).
    """
    reset_count = 0
    for target_column, language_column, attempts_column in _TRANSLATION_COLUMNS:
        if target_column not in df.columns:
            continue
        polluted = df[target_column].apply(
            lambda value: isinstance(value, str) and _LEGACY_ERROR_PAGE_PATTERN.match(value) is not None
        ).astype(bool)
        if polluted.any():
            df.loc[polluted, target_column] = None
            df.loc[polluted, language_column] = None
            df.loc[polluted, attempts_column] = 0
            reset_count += int(polluted.sum())
    return reset_count


def _add_translations_pt(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[pd.DataFrame, int]:
    """Adiciona overview_detected_language_en, overview_detected_language_pt,
    overview_pt, overview_translation_attempts e overview_needs_translation aos
    registros com overview_en preenchido — ver resolve_pt_translation em
    shared_utils/traducao.py para a regra de elegibilidade e o teto de
    tentativas."""
    # translate_fn resolvido em runtime (não como default de parâmetro) para que
    # patch("backfill_traducao.translate_text_llm", ...) nos testes continue
    # funcionando quando o chamador não passa um translate_fn explícito.
    translate_fn = translate_fn or translate_text_llm
    detect_fn = detect_fn or detect_language_llm
    if "overview_pt" not in df.columns:
        df["overview_pt"] = None

    return resolve_pt_translation(
        df,
        source_column="overview_en",
        target_column="overview_pt",
        detected_language_en_column="overview_detected_language_en",
        detected_language_pt_column="overview_detected_language_pt",
        translation_attempts_column="overview_translation_attempts",
        detect_fn=detect_fn,
        translate_fn=translate_fn,
        max_workers=_TRANSLATE_MAX_WORKERS,
        needs_translation_column="overview_needs_translation",
        sample_id_column="id",
    )


def _add_translations_tagline_pt(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[pd.DataFrame, int]:
    """Adiciona tagline_detected_language_en, tagline_detected_language_pt,
    tagline_pt, tagline_translation_attempts e tagline_needs_translation aos
    registros com tagline preenchida (espelha glue_details)."""
    translate_fn = translate_fn or translate_text_llm
    detect_fn = detect_fn or detect_language_llm
    if "tagline" not in df.columns:
        return df, 0
    if "tagline_pt" not in df.columns:
        df["tagline_pt"] = None

    return resolve_pt_translation(
        df,
        source_column="tagline",
        target_column="tagline_pt",
        detected_language_en_column="tagline_detected_language_en",
        detected_language_pt_column="tagline_detected_language_pt",
        translation_attempts_column="tagline_translation_attempts",
        detect_fn=detect_fn,
        translate_fn=translate_fn,
        max_workers=_TRANSLATE_MAX_WORKERS,
        needs_translation_column="tagline_needs_translation",
        sample_id_column="id",
    )


def _add_translations_keywords_pt(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[pd.DataFrame, int]:
    """Adiciona keywords_detected_language_en, keywords_detected_language_pt,
    keywords_pt, keywords_translation_attempts e keywords_needs_translation aos
    registros com keywords preenchidas."""
    translate_fn = translate_fn or translate_text_llm
    detect_fn = detect_fn or detect_language_llm
    if "keywords" not in df.columns:
        return df, 0
    if "keywords_pt" not in df.columns:
        df["keywords_pt"] = None

    return resolve_pt_translation(
        df,
        source_column="keywords",
        target_column="keywords_pt",
        detected_language_en_column="keywords_detected_language_en",
        detected_language_pt_column="keywords_detected_language_pt",
        translation_attempts_column="keywords_translation_attempts",
        detect_fn=detect_fn,
        translate_fn=translate_fn,
        max_workers=_TRANSLATE_MAX_WORKERS,
        needs_translation_column="keywords_needs_translation",
        sample_id_column="id",
    )


def _backfill_year(
    database: str,
    table_details: str,
    year: str,
    s3_bucket_sot: str,
    translate_fn: Optional[Callable[[str], str]] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
    reset_polluted: bool = False,
) -> tuple[bool, int]:
    """
    Lê uma partição de year em tb_details_* diretamente do S3, adiciona
    traduções PT e reescreve. Usa S3 em vez de Athena/CTAS para evitar
    permissões athena:GetWorkGroup e glue:DeleteTable.

    Com reset_polluted=True, antes de traduzir descarta os *_pt que sejam o texto de
    erro legado e zera o contador de tentativas dessas linhas (ver
    _reset_polluted_translations).

    Returns:
        Tupla (escreveu, quantidade traduzida com sucesso).
    """
    translate_fn = translate_fn or translate_text_llm
    detect_fn = detect_fn or detect_language_llm
    s3_details_path = f"s3://{s3_bucket_sot}/tmdb/{table_details}/year={year}/"

    try:
        df = wr.s3.read_parquet(path=s3_details_path)
    except ClientError as exc:
        shared.log_expired_token(exc, f"leitura de {s3_details_path}")
        raise
    except Exception as exc:
        if "NoFilesFound" in type(exc).__name__ or "NoFilesFound" in str(exc):
            logger.info("  Nenhum arquivo em %s. Pulando.", s3_details_path)
            return False, 0
        raise

    if df.empty:
        logger.info("  Nenhum registro para year=%s. Pulando.", year)
        return False, 0

    logger.info("  %d registros lidos.", len(df))

    if reset_polluted:
        reset_count = _reset_polluted_translations(df)
        logger.info("  %d valor(es) *_pt com texto de erro legado descartado(s).", reset_count)

    df, success_overview = _add_translations_pt(df, translate_fn, detect_fn)
    df, success_tagline = _add_translations_tagline_pt(df, translate_fn, detect_fn)
    df, success_keywords = _add_translations_keywords_pt(df, translate_fn, detect_fn)
    translated_count = success_overview + success_tagline + success_keywords
    df["year"] = year

    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_details}/"
    try:
        wr.s3.to_parquet(
            df=df,
            path=s3_path,
            dataset=True,
            partition_cols=["year"],
            mode="overwrite_partitions",
            database=database,
            table=table_details,
        )
    except ClientError as exc:
        shared.log_expired_token(exc, f"escrita de {s3_path} (year={year})")
        raise
    logger.info("  %d registros escritos em %s (year=%s).", len(df), s3_path, year)
    return True, translated_count


@log_llm_usage_summary("Backfill tradução")
def main() -> None:
    region = shared.require_env("AWS_REGION")
    os.environ["AWS_DEFAULT_REGION"] = region

    table_group          = shared.require_env("TABLE_GROUP")
    s3_bucket_sot         = shared.require_env("S3_BUCKET_SOT")
    s3_bucket_temp        = shared.require_env("S3_BUCKET_TEMP")
    db_movie              = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv                 = shared.require_env("GLUE_DATABASE_TV")
    table_details_movie   = shared.require_env("TABLE_DETAILS_MOVIE")
    table_details_tv      = shared.require_env("TABLE_DETAILS_TV")
    dq_job_name            = shared.require_env("GLUE_DATA_QUALITY_JOB_NAME")

    start_year, end_year = shared.read_year_range(end_env="BACKFILL_END_YEAR")
    wait_seconds = int(os.environ.get("BACKFILL_WAIT_SECONDS", 30))
    reset_polluted = os.environ.get("BACKFILL_RESET_ATTEMPTS", "").lower() == "true"

    years = list(range(start_year, end_year + 1))
    total = len(years) * 2
    logger.info(
        "Backfill de tradução: %d até %d | %d partições (movie + tv) | pausa=%ds entre partições "
        "| serviço de tradução=LLM (OpenRouter)",
        start_year, end_year, total, wait_seconds,
    )
    s3_client = boto3.client("s3", region_name=region)

    completed = shared.load_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year)

    units = []
    for year in years:
        units.append(("movie", year, db_movie, table_details_movie))
        units.append(("tv", year, db_tv, table_details_tv))

    pending = [u for u in units if f"{u[0]}:{u[1]}" not in completed]
    shared.log_resume_progress(logger, "partições já concluídas", len(units), len(pending))

    total_translated = 0
    for i, (content_type, year, database, table_details) in enumerate(pending, start=1):
        logger.info("[%d/%d] %s | year=%d", i, len(pending), content_type, year)
        _, translated_count = _backfill_year(
            database=database,
            table_details=table_details,
            year=str(year),
            s3_bucket_sot=s3_bucket_sot,
            reset_polluted=reset_polluted,
        )
        total_translated += translated_count
        completed.add(f"{content_type}:{year}")
        shared.save_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year, completed)
        if i < len(pending) and translated_count > 0:
            logger.info("Aguardando %d segundos antes da próxima invocação...", wait_seconds)
            time.sleep(wait_seconds)

    shared.trigger_agg_locally(
        s3_bucket_spec=shared.require_env("S3_BUCKET_SPEC"),
        s3_prefix_spec=shared.require_env("S3_PREFIX_SPEC"),
        s3_bucket_temp=s3_bucket_temp,
        db_movie=db_movie,
        db_tv=db_tv,
        db_unified=shared.require_env("DB_UNIFIED"),
        table_name=shared.require_env("TABLE_DISCOVER_UNIFIED"),
        dq_job_name=dq_job_name,
        environment=shared.require_env("ENVIRONMENT"),
    )
    shared.clear_checkpoint(s3_client, s3_bucket_temp, table_group)
    summary = (
        f"Backfill de tradução concluído: {start_year} até {end_year} | {total_translated} "
        f"campos traduzidos com sucesso (overview_pt + tagline_pt + keywords_pt)"
    )
    logger.info(summary)
    shared.notify_backfill_success(table_group, summary)


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
