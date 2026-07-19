"""
backfill_traducao.py — Adiciona overview_pt, tagline_pt e keywords_pt (e as
colunas de diagnóstico *_detected_language_en/*_detected_language_pt/
*_translation_attempts/*_needs_translation) aos detalhes históricos.

Lê tb_details_movie_tmdb e tb_details_tv_tmdb ano a ano e traduz para
português, via Google Translate ou AWS Translate (TRANSLATE_PROVIDER — ver
abaixo), os campos ainda pendentes (espelhando o que o Glue Details faz para
dados novos). As três colunas usam a mesma regra de elegibilidade, resolvida
por shared_utils.traducao.resolve_pt_translation: o campo de origem
preenchido e o idioma detectado do RESULTADO (*_detected_language_pt, e não
da fonte) ainda diferente de "pt" — original_language não entra no critério
(é o idioma de produção original do título, não o idioma do texto retornado
pela API; não garante que overview_en/tagline/keywords já estejam em
português — ver shared_utils/traducao.py):
  - overview_pt:  overview_en preenchido, overview_detected_language_pt != "pt"
  - tagline_pt:   tagline preenchida, tagline_detected_language_pt != "pt"
  - keywords_pt:  keywords preenchidas, keywords_detected_language_pt != "pt"
Quando o idioma detectado da fonte (*_detected_language_en) já é "pt", o
texto é copiado diretamente para a coluna _pt sem chamar tradução — evita
reenviar ao Google/AWS um texto que já está em português. Basear a
elegibilidade no idioma detectado do RESULTADO (em vez de comparar string com
a fonte, como antes) evita tanto retraduzir o que já está correto quanto
deixar uma mistradução silenciosa (resultado diferente da fonte, mas em
outro idioma que não pt) permanentemente marcada como concluída.
*_translation_attempts limita quantas vezes uma linha é reenviada ao
tradutor — sem esse teto, conteúdo genuinamente não traduzível (nomes
próprios, termos curtos que o tradutor devolve sem alterar) seria retentado
para sempre, já que seu idioma detectado nunca vira "pt" (ver docstring de
resolve_pt_translation). *_needs_translation (booleano) grava o mesmo
critério de elegibilidade acima, mas SEM o teto de *_translation_attempts —
reflete se o campo, como está agora, ainda não está em português, mesmo
esgotado o número de tentativas automáticas. Não é gerado collection_name_pt
— diferente dos demais, ele vem de uma chamada à API do TMDB (não do Google
Translate) e foi deixado fora deste script. Não re-chama a API do TMDB para
os campos acima.

Como este script lê a partição inteira (sem filtro de delta), partições
gravadas antes da padronização de nomenclatura para inglês (ver CLAUDE.md)
ainda carregam o schema antigo (pt-BR: *_idioma_detectado_en/pt,
*_tentativas_traducao, *_precisa_traducao) — descartado antes de escrever
(ver shared_utils.traducao.LEGACY_TRANSLATION_COLUMNS), senão o awswrangler
reintroduziria essas colunas no Glue Catalog a partir do DataFrame gravado.

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

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)
    BACKFILL_WAIT_SECONDS (padrão: 300 — pausa entre partições para não saturar Google Translate)
    TRANSLATE_PROVIDER    (padrão: "google" — grátis, mas instável sob alto volume;
                            "aws" usa AWS Translate, API oficial paga por caractere,
                            útil para testar um período menor via BACKFILL_START_YEAR/
                            BACKFILL_END_YEAR. Se o intervalo pedido cobrir mais de 1
                            ano, "aws" é rebaixado automaticamente para "google" —
                            proteção de custo, ver backfill_shared.apply_translate_cost_guard.
                            Em qualquer um dos dois casos, o serviço não escolhido é
                            usado como fallback automático, capado por caracteres
                            quando é o AWS — ver shared_utils.traducao.resolve_translate_fn)

Retomada automática:
    Se a credencial AWS expirar (ExpiredTokenException do STS ou ExpiredToken
    do S3), o script sai com exit code 75
    (backfill_shared.RETRYABLE_EXIT_CODE). O workflow renova a credencial
    e roda o script de novo — como o progresso é lido do checkpoint em S3
    (s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{TABLE_GROUP}.json), as
    partições (ano+tipo) já concluídas são puladas.
"""

import os
import sys
import time
from pathlib import Path

from typing import Callable, Optional

import awswrangler as wr
import boto3
import pandas as pd
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "shared_src"))
from shared_utils.idioma import (  # noqa: E402
    detect_language_aws,
    detect_language_langdetect,
    resolve_detect_language_fn,
)
from shared_utils.traducao import (  # noqa: E402
    LEGACY_TRANSLATION_COLUMNS,
    resolve_pt_translation,
    resolve_translate_fn,
    translate_text,
    translate_text_aws,  # noqa: F401 — reexportado para os testes verificarem identidade
)

import backfill_shared as shared

logger = shared.setup_logging()

_TRANSLATE_MAX_WORKERS = 10


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
    # patch("backfill_traducao.translate_text", ...) nos testes continue funcionando
    # quando o chamador não passa um translate_fn explícito.
    translate_fn = translate_fn or translate_text
    detect_fn = detect_fn or resolve_detect_language_fn()
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
    )


def _add_translations_tagline_pt(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[pd.DataFrame, int]:
    """Adiciona tagline_detected_language_en, tagline_detected_language_pt,
    tagline_pt, tagline_translation_attempts e tagline_needs_translation aos
    registros com tagline preenchida (espelha glue_details)."""
    translate_fn = translate_fn or translate_text
    detect_fn = detect_fn or resolve_detect_language_fn()
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
    )


def _add_translations_keywords_pt(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[pd.DataFrame, int]:
    """Adiciona keywords_detected_language_en, keywords_detected_language_pt,
    keywords_pt, keywords_translation_attempts e keywords_needs_translation aos
    registros com keywords preenchidas."""
    translate_fn = translate_fn or translate_text
    detect_fn = detect_fn or resolve_detect_language_fn()
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
    )


def _backfill_year(
    database: str,
    table_details: str,
    year: str,
    s3_bucket_sot: str,
    translate_fn: Optional[Callable[[str], str]] = None,
    detect_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[bool, int]:
    """
    Lê uma partição de year em tb_details_* diretamente do S3, adiciona
    traduções PT e reescreve. Usa S3 em vez de Athena/CTAS para evitar
    permissões athena:GetWorkGroup e glue:DeleteTable.

    Returns:
        Tupla (escreveu, quantidade traduzida com sucesso).
    """
    translate_fn = translate_fn or translate_text
    detect_fn = detect_fn or resolve_detect_language_fn()
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

    df, success_overview = _add_translations_pt(df, translate_fn, detect_fn)
    df, success_tagline = _add_translations_tagline_pt(df, translate_fn, detect_fn)
    df, success_keywords = _add_translations_keywords_pt(df, translate_fn, detect_fn)
    translated_count = success_overview + success_tagline + success_keywords
    df["year"] = year

    # Partições gravadas antes do rename para inglês ainda carregam o schema antigo
    # (pt-BR) — como este script lê a partição inteira e só adiciona as colunas novas,
    # sem isso as antigas seriam reescritas de volta e reintroduzidas no Glue Catalog
    # via sincronização automática do awswrangler (ver
    # shared_utils.traducao.LEGACY_TRANSLATION_COLUMNS).
    df = df.drop(columns=[c for c in LEGACY_TRANSLATION_COLUMNS if c in df.columns])

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

    start_year, end_year = shared.read_year_range(end_env="BACKFILL_END_YEAR")
    wait_seconds = int(os.environ.get("BACKFILL_WAIT_SECONDS", 300))
    translate_provider = shared.apply_translate_cost_guard(
        os.environ.get("TRANSLATE_PROVIDER", "google"), start_year, end_year,
    )
    # Valida translate_provider cedo (fail-fast) antes de qualquer I/O — resolve_translate_fn
    # é recriado por partição dentro do loop abaixo, mas um provider inválido deve
    # interromper o backfill antes de tocar o S3.
    resolve_translate_fn(translate_provider, translate_text, translate_text_aws)

    years = list(range(start_year, end_year + 1))
    total = len(years) * 2
    logger.info(
        "Backfill de tradução: %d até %d | %d partições (movie + tv) | pausa=%ds entre partições "
        "| serviço de tradução=%s",
        start_year, end_year, total, wait_seconds, translate_provider,
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
        # translate_fn/detect_fn recriados a cada partição — cada ano+tipo tem seu
        # próprio orçamento de fallback ao AWS Translate/Comprehend, em vez de
        # compartilhar um único orçamento com todas as partições do run (que a
        # primeira partição processada poderia esgotar sozinha, deixando as demais
        # sem fallback).
        translate_fn = resolve_translate_fn(translate_provider, translate_text, translate_text_aws)
        detect_fn = resolve_detect_language_fn(detect_language_langdetect, detect_language_aws)
        _, translated_count = _backfill_year(
            database=database,
            table_details=table_details,
            year=str(year),
            s3_bucket_sot=s3_bucket_sot,
            translate_fn=translate_fn,
            detect_fn=detect_fn,
        )
        total_translated += translated_count
        completed.add(f"{content_type}:{year}")
        shared.save_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year, completed)
        if i < len(pending):
            logger.info("Aguardando %d segundos antes da próxima invocação...", wait_seconds)
            time.sleep(wait_seconds)

    shared.clear_checkpoint(s3_client, s3_bucket_temp, table_group)
    logger.info(
        "Backfill de tradução concluído: %d até %d | %d campos traduzidos com sucesso "
        "(overview_pt + tagline_pt + keywords_pt)",
        start_year, end_year, total_translated,
    )


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
