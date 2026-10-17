"""
backfill_shared.py — Código comum aos scripts de backfill manual em scripts/.

Reúne o que hoje se repetia, byte-a-byte ou quase, em backfill_discover.py,
backfill_referencias.py, backfill_traducao.py, backfill_data_quality.py e
backfill_enriquecimento.py:

  - leitura de variável de ambiente obrigatória (`require_env`)
  - setup de logging (`setup_logging`)
  - leitura do range de anos do backfill (`read_year_range`)
  - wrapper de exit code 75 para retomada automática (`run_with_retry_exit`)
  - mensagem de log de progresso do checkpoint (`log_resume_progress`)
  - checkpoint em S3 para retomada automática de backfills (`load_checkpoint`,
    `save_checkpoint`, `clear_checkpoint` e helpers de token expirado)
  - notificação por e-mail (SNS) de sucesso total do backfill (`notify_backfill_success`)

Checkpoint em S3
----------------
Usado pelos scripts que iteram por ano (backfill_discover.py,
backfill_enriquecimento.py, backfill_data_quality.py, backfill_traducao.py)
para persistir, a cada unidade de trabalho concluída (ex.: "movie:2020"),
o progresso em s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{table_group}.json.

Se o script for interrompido (ex.: ExpiredTokenException/ExpiredToken) e
reiniciado com o mesmo table_group e o mesmo range de anos, ele pula direto
para as unidades ainda não concluídas em vez de recomeçar do start_year.
"""

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError

_SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _sao_paulo_converter(timestamp: float) -> time.struct_time:
    """Converte o timestamp do LogRecord para horário de São Paulo.

    Atribuído a `logging.Formatter.converter` (atributo de classe) logo abaixo
    — afeta `%(asctime)s` de todos os 7 scripts de backfill no processo
    inteiro, sem precisar duplicar configuração em cada `logging.basicConfig`.
    """
    return datetime.fromtimestamp(timestamp, tz=_SAO_PAULO_TZ).timetuple()


logging.Formatter.converter = staticmethod(_sao_paulo_converter)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
logger = logging.getLogger()


RETRYABLE_EXIT_CODE = 75

# ExpiredTokenException é o código retornado pelo STS (ex.: Lambda, Glue).
# ExpiredToken é o código equivalente retornado pelo S3 (ex.: ListObjectsV2
# via awswrangler, get_object/put_object/delete_object). Ambos indicam a
# mesma causa — credencial AWS expirada no meio de um backfill longo — e
# devem ser tratados como retomáveis.
_EXPIRED_TOKEN_CODES = frozenset({"ExpiredTokenException", "ExpiredToken"})

# Duração (s) da sessão AWS do workflow, exportada por backfill.yml; liga a guarda
# `session_budget_low`. Folga cobre o tempo entre a criação da sessão (step de credenciais,
# antes do pip install) e o início do processo, além de gravações finais mais lentas que o normal.
SESSION_SECONDS_ENV = "BACKFILL_SESSION_SECONDS"
_SESSION_SAFETY_MARGIN_SECONDS = 300
_PROCESS_START = time.monotonic()

# Valor da chave "mode" do checkpoint num "Reprocessar tudo" (ver _checkpoint_mode).
_REPROCESS_ALL_MODE = "reprocess_all"


def setup_logging() -> logging.Logger:
    """Retorna o logger configurado no nível de módulo (ver topo do arquivo), com segredos
    (api_key do TMDB dentro da URL de uma exceção do requests, etc.) mascarados em tudo o que é
    logado — o log do Actions de um repositório público é público, e a saída dos scripts também
    alimenta o step summary.

    Import local de shared_utils.secret_redaction (não no topo do módulo): mesmo racional de
    resolve_pending_units_by_year — backfill_data_quality.py/backfill_rename_colunas.py não colocam
    app/shared_src em sys.path, então uma dependência no topo quebraria o `import backfill_shared`.
    """
    sys.path.insert(0, str(_REPO_ROOT / "app" / "shared_src"))
    from shared_utils.secret_redaction import install_log_redaction

    install_log_redaction()
    return logging.getLogger()


def _expected_bucket_owner_kwargs() -> dict[str, str]:
    """Retorna o kwarg `ExpectedBucketOwner` a espalhar nas chamadas boto3 ao S3.

    Mesma lógica de shared_utils.s3_helpers.expected_bucket_owner_kwargs, duplicada
    aqui porque os scripts de backfill não importam o pacote shared_utils (rodam como
    processo próprio, fora do runtime do Glue/Lambda, ver trigger_agg_locally).

    O valor vem de AWS_ACCOUNT_ID (injetada pelo Terraform a partir de
    data.aws_caller_identity.current.account_id). Sem essa variável definida, retorna
    um dicionário vazio — permite rodar os scripts localmente sem configurá-la.
    """
    account_id = os.environ.get("AWS_ACCOUNT_ID")
    return {"ExpectedBucketOwner": account_id} if account_id else {}


def require_env(name: str) -> str:
    """Lê variável de ambiente obrigatória ou levanta erro."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def read_year_range(
    start_env: str = "BACKFILL_START_YEAR",
    end_env: str = "BACKFILL_END_YEAR",
    start_default: int = 2000,
) -> tuple[int, int]:
    """Lê o range de anos do backfill a partir de variáveis de ambiente opcionais."""
    start_year = int(os.environ.get(start_env, start_default))
    end_year = int(os.environ.get(end_env, datetime.now().year))
    return start_year, end_year


def run_with_retry_exit(main_fn: Callable[[], object]) -> None:
    """Roda main_fn() e traduz token expirado no exit code 75 (retomável).

    Chamado explicitamente pelo bloco `if __name__ == "__main__":` de cada
    script que usa checkpoint. O workflow (.github/workflows/backfill.yml)
    reconhece o exit code 75, renova a credencial e roda o script de novo —
    como o progresso é lido do checkpoint em S3, as unidades já concluídas
    são puladas. `main_fn` pode retornar `None` (maioria dos scripts) ou
    `bool` (`backfill_discover.py`/`backfill_enriquecimento.py`, sinalizando
    se o backfill terminou sem falhas pendentes, consumido por
    `backfill_historico.py`) — o retorno é sempre ignorado aqui.
    """
    try:
        main_fn()
    except ClientError as exc:
        codigo = expired_token_exit_code(exc)
        if codigo is not None:
            sys.exit(codigo)
        raise


def session_budget_low(longest_unit_seconds: float) -> bool:
    """Indica se a sessão AWS atual não comporta mais uma unidade tão longa quanto a maior já feita.

    A credencial do workflow dura 1h (ver renovar_credenciais em backfill.yml) e só é renovada
    quando o script sai com 75. Uma unidade (ex.: enriquecimento de um ano, ~15 min) só entra no
    checkpoint depois de gravar: se o token expira no meio dela, todo o trabalho — inclusive o
    gasto com o LLM — é refeito na tentativa seguinte. Checar ANTES de iniciar a unidade evita
    isso, ao custo de renovar a sessão um pouco antes.

    Desligada quando BACKFILL_SESSION_SECONDS não está definida (execução local, sem workflow
    para renovar a credencial e retomar). O relógio é o do processo (`_PROCESS_START`): cada
    tentativa do workflow é um processo novo, logo começa junto com a sessão renovada.

    Args:
        longest_unit_seconds: duração da maior unidade já concluída neste processo; 0 se
            nenhuma — sem estimativa não há o que comparar, então a primeira unidade de cada
            processo sempre roda (garante progresso a cada tentativa).

    Returns:
        `True` se o tempo restante da sessão (menos a folga) for menor que a estimativa.
    """
    session_seconds = os.environ.get(SESSION_SECONDS_ENV)
    if not session_seconds or longest_unit_seconds <= 0:
        return False
    remaining = int(session_seconds) - (time.monotonic() - _PROCESS_START) - _SESSION_SAFETY_MARGIN_SECONDS
    return remaining < longest_unit_seconds


def exit_if_session_budget_low(longest_unit_seconds: float) -> None:
    """Sai com `RETRYABLE_EXIT_CODE` (75) se a sessão AWS não comporta outra unidade (ver
    `session_budget_low`), para o workflow renovar a credencial e retomar do checkpoint."""
    if session_budget_low(longest_unit_seconds):
        logger.warning(
            "Sessão AWS sem tempo para outra unidade (a maior levou %.0fs): saindo para renovar "
            "a credencial e retomar do checkpoint.",
            longest_unit_seconds,
        )
        sys.exit(RETRYABLE_EXIT_CODE)


def log_resume_progress(log: logging.Logger, unidade_label: str, total: int, pendentes: int) -> None:
    """Loga quantas unidades de trabalho já foram concluídas, se houver progresso salvo.

    `unidade_label` é a frase já formatada que descreve as unidades concluídas
    (ex.: "invocações já concluídas", "runs já concluídos"), preservando a
    redação específica de cada script.
    """
    if pendentes < total:
        log.info(
            "%d de %d %s no checkpoint; retomando com %d pendente(s).",
            total - pendentes, total, unidade_label, pendentes,
        )


def _checkpoint_key(table_group: str) -> str:
    """Monta a chave S3 do checkpoint de um table_group."""
    return f"tmdb/backfill_checkpoints/{table_group}.json"


def reprocess_all_enabled() -> bool:
    """Indica se o run é um "Reprocessar tudo" (input `reprocessar_tudo` do workflow).

    O workflow exporta o input como BACKFILL_REPROCESS_ALL ("true"/"false"). Lida em um lugar só
    para os scripts e o checkpoint concordarem sobre o modo do run.
    """
    return os.environ.get("BACKFILL_REPROCESS_ALL", "").lower() == "true"


def _checkpoint_mode() -> str | None:
    """Modo gravado no checkpoint: "reprocess_all" num "Reprocessar tudo", None no run normal.

    Um checkpoint só é reaproveitado por um run do MESMO modo (ver load_checkpoint): sem isso, um
    "Reprocessar tudo" herdaria as unidades que um run normal anterior já concluíra e as pularia
    — terminando "com sucesso" sem reprocessar nada. Dentro do mesmo modo a retomada continua
    valendo (retry por token expirado e novo disparo após timeout de 6h).
    """
    return _REPROCESS_ALL_MODE if reprocess_all_enabled() else None


def is_expired_token_error(exc: ClientError) -> bool:
    """Indica se um `ClientError` representa uma credencial AWS expirada.

    Cobre tanto o código do STS (`ExpiredTokenException`, ex.: Lambda, Glue)
    quanto o do S3 (`ExpiredToken`, ex.: ListObjectsV2/get_object/put_object).

    Args:
        exc: exceção `ClientError` capturada em qualquer chamada AWS do backfill.

    Returns:
        `True` se o código do erro for um dos códigos de token expirado.
    """
    return exc.response.get("Error", {}).get("Code") in _EXPIRED_TOKEN_CODES


def expired_token_exit_code(exc: ClientError) -> int | None:
    """Traduz uma exceção de nível de processo para o exit code do script.

    Usado no bloco `if __name__ == "__main__":` de cada script de backfill:
    um erro de token expirado é retomável (o workflow renova a credencial
    e roda o script de novo, que retoma do checkpoint) — qualquer outro erro
    deve continuar propagando normalmente (exit code 1 com traceback).

    Args:
        exc: exceção `ClientError` capturada no nível mais externo do script.

    Returns:
        `RETRYABLE_EXIT_CODE` (75) se for um erro de token expirado, `None`
        caso contrário (o chamador deve relançar a exceção original).
    """
    if is_expired_token_error(exc):
        return RETRYABLE_EXIT_CODE
    return None


def log_expired_token(exc: ClientError, contexto: str) -> None:
    """Loga um erro claro se a credencial AWS expirou durante `contexto`."""
    if is_expired_token_error(exc):
        logger.error(
            "Credenciais AWS expiraram durante %s. O workflow vai renovar a credencial "
            "e retomar do checkpoint automaticamente (ver scripts/backfill_shared.py).",
            contexto,
        )


def load_checkpoint(
    s3_client: Any, bucket: str, table_group: str, start_year: int, end_year: int,
) -> set[str]:
    """Lê o checkpoint salvo em S3 e retorna as unidades já concluídas.

    Args:
        s3_client: cliente boto3 do S3.
        bucket: bucket onde o checkpoint é armazenado.
        table_group: identifica o backfill (ex.: "detalhes_e_providers").
        start_year: ano inicial do run atual.
        end_year: ano final do run atual.

    Returns:
        Conjunto de unit_ids já concluídos. Vazio se não existir checkpoint ou
        se o range de anos salvo não bater com o run atual (nesse caso o
        checkpoint antigo é ignorado, não apagado).
    """
    key = _checkpoint_key(table_group)
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key, **_expected_bucket_owner_kwargs())
    except ClientError as exc:
        codigo = exc.response.get("Error", {}).get("Code")
        if codigo in ("NoSuchKey", "404"):
            return set()
        log_expired_token(exc, f"leitura do checkpoint '{key}'")
        raise

    data = json.loads(response["Body"].read())
    if data.get("start_year") != start_year or data.get("end_year") != end_year:
        logger.warning(
            "Checkpoint '%s' tem range incompatível (start_year=%s, end_year=%s salvos "
            "vs. %s-%s do run atual). Ignorando e recomeçando do zero.",
            key, data.get("start_year"), data.get("end_year"), start_year, end_year,
        )
        return set()

    if data.get("mode") != _checkpoint_mode():
        logger.warning(
            "Checkpoint '%s' foi gravado por um run em modo '%s' e este run é '%s'. Ignorando e "
            "recomeçando do zero (o checkpoint antigo é sobrescrito na próxima unidade concluída).",
            key, data.get("mode") or "normal", _checkpoint_mode() or "normal",
        )
        return set()

    completed = set(data.get("completed", []))
    logger.info("Checkpoint '%s' encontrado: %d unidade(s) já concluída(s).", key, len(completed))
    return completed


def save_checkpoint(
    s3_client: Any, bucket: str, table_group: str, start_year: int, end_year: int, completed: set[str],
) -> None:
    """Sobrescreve o checkpoint em S3 com o conjunto atualizado de unidades concluídas."""
    key = _checkpoint_key(table_group)
    payload: dict[str, Any] = {
        "start_year": start_year,
        "end_year": end_year,
        "completed": sorted(completed),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    mode = _checkpoint_mode()
    if mode:
        payload["mode"] = mode
    body = json.dumps(payload).encode()
    try:
        s3_client.put_object(Bucket=bucket, Key=key, Body=body, **_expected_bucket_owner_kwargs())
    except ClientError as exc:
        log_expired_token(exc, f"escrita do checkpoint '{key}'")
        raise


def clear_checkpoint(s3_client: Any, bucket: str, table_group: str) -> None:
    """Remove o checkpoint em S3. Chamado quando o backfill termina sem falhas pendentes."""
    key = _checkpoint_key(table_group)
    try:
        s3_client.delete_object(Bucket=bucket, Key=key, **_expected_bucket_owner_kwargs())
    except ClientError as exc:
        log_expired_token(exc, f"remoção do checkpoint '{key}'")
        raise
    logger.info("Checkpoint '%s' removido — backfill concluído sem pendências.", key)


def resolve_pending_units_by_year(
    *,
    label: str,
    start_year: int,
    end_year: int,
    db_movie: str,
    db_tv: str,
    secret_arn: str,
    s3_client: Any,
    s3_bucket_temp: str,
    table_group: str,
) -> tuple[list[int], str, set[str], list[tuple[str, int, str]]]:
    """Resolve o range de anos, a chave de API do TMDB e as unidades (media_type, year,
    database) ainda pendentes segundo o checkpoint — sequência repetida, byte-a-byte,
    entre backfill_discover.py e backfill_enriquecimento.py (python:S1192 do SonarQube).

    Import local de shared_utils.api_client (não no topo do módulo): mesmo racional de
    trigger_agg_locally logo abaixo — backfill_data_quality.py e
    backfill_rename_colunas.py importam backfill_shared sem nunca ter inserido
    app/shared_src em sys.path (não chamam esta função), então uma dependência de
    shared_utils no topo do módulo quebraria o `import backfill_shared` deles.

    Args:
        label:          Nome do backfill para a mensagem de log (ex.: "discover",
                         "enriquecimento").
        start_year:     Ano inicial do range do backfill.
        end_year:       Ano final do range do backfill.
        db_movie:       Banco de dados de filmes no Glue Catalog.
        db_tv:          Banco de dados de séries no Glue Catalog.
        secret_arn:     ARN do secret com a chave de API do TMDB.
        s3_client:      Cliente boto3 do S3 (para ler o checkpoint).
        s3_bucket_temp: Bucket onde o checkpoint é armazenado.
        table_group:    Identifica o checkpoint (ver load_checkpoint).

    Returns:
        Tupla (years, api_key, completed, pendentes): `years` é a lista de anos do
        range; `api_key` é a chave TMDB já resolvida; `completed` é o conjunto mutável
        de unit_ids já concluídos (o chamador continua atualizando e salvando via
        save_checkpoint a cada unidade processada); `pendentes` é a lista de
        (media_type, year, database) ainda não concluídas.
    """
    sys.path.insert(0, str(_REPO_ROOT / "app" / "shared_src"))
    from shared_utils.api_client import get_api_secret

    years = list(range(start_year, end_year + 1))
    total_units = len(years) * 2
    logger.info(
        "Backfill de %s: %d anos (%d-%d) x 2 tipos = %d unidades",
        label, len(years), start_year, end_year, total_units,
    )

    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_api_secret(secret_arn, "tmdb_api_key")

    completed = load_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year)

    unidades = [
        (media_type, year, database)
        for year in years
        for media_type, database in [("movie", db_movie), ("tv", db_tv)]
    ]
    pendentes = [u for u in unidades if f"{u[0]}:{u[1]}" not in completed]
    log_resume_progress(logger, "unidades já concluídas", len(unidades), len(pendentes))

    return years, api_key, completed, pendentes


def _read_processed_dates(s3_bucket_sot: str, table: str, year: int) -> Any | None:
    """Lê id e processed_date de uma partição year; None se ela não existir.

    Import local de awswrangler pelo mesmo motivo de report_stale_processed_date. Token expirado
    propaga (retomável); qualquer outra falha de leitura é tratada como partição inexistente.
    """
    import awswrangler as wr

    try:
        return wr.s3.read_parquet(
            path=f"s3://{s3_bucket_sot}/tmdb/{table}/",
            dataset=True,
            columns=["id", "processed_date"],
            partition_filter=lambda x: x["year"] == str(year),
        )
    # Partição pode não existir (ano sem dados), degrada graciosamente.
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, ClientError) and is_expired_token_error(exc):
            log_expired_token(exc, f"verificação de '{table}' year={year}")
            raise
        logger.info("Sem dados para verificar em '%s' year=%d: %s", table, year, exc)
        return None


def report_stale_processed_date(
    *,
    tables: list[str],
    s3_bucket_sot: str,
    years: list[int],
    run_start_date: date,
    sample_size: int = 5,
) -> int:
    """Lista, por tabela e ano, os registros que o "Reprocessar tudo" não rebuscou.

    Um registro rebuscado do TMDB é regravado com processed_date = hoje (ver
    app/glue_details/src/utils.py:_common_fields); quem ficou com processed_date anterior ao início
    do run foi preservado do run anterior — falha de API após os retries (429/5xx/timeout) ou
    registro sem year (títulos que o TMDB diz não existir mais, HTTP 404, são removidos, não
    preservados). Sem esta verificação, o run termina "com sucesso" mesmo com esses registros
    defasados, porque a unidade entra no checkpoint de qualquer forma.

    Cada tabela/ano com pendência é logada como ERROR (o workflow transforma linhas ERROR em aviso
    no step summary). Nunca levanta exceção, exceto ClientError de token expirado (retomável, ver
    run_with_retry_exit). Um run que atravessa a meia-noite (horário de São Paulo) pode listar
    registros do dia anterior como não rebuscados: falso positivo, nunca falso negativo.

    Import local de awswrangler/pandas (não no topo do módulo): backfill_data_quality.py e
    backfill_rename_colunas.py importam backfill_shared sem instalar essas dependências.

    Args:
        tables:         Tabelas de details do SOT (movie e tv) a verificar.
        s3_bucket_sot:  Bucket SOT onde os parquets estão gravados.
        years:          Anos (partições year) a verificar.
        run_start_date: Data (horário de SP) em que o run começou; processed_date menor que ela
                         indica registro não rebuscado.
        sample_size:    Quantos ids de exemplo logar por tabela/ano.

    Returns:
        Total de registros não rebuscados em todas as tabelas e anos verificados.
    """
    import pandas as pd

    total_stale = 0
    for table in tables:
        for year in years:
            df = _read_processed_dates(s3_bucket_sot, table, year)
            if df is None:
                continue
            stale = df[pd.to_datetime(df["processed_date"]).dt.date < run_start_date]
            if stale.empty:
                continue
            total_stale += len(stale)
            logger.error(
                "Reprocessar tudo: %d registro(s) de '%s' year=%d NÃO foram rebuscados do TMDB "
                "(processed_date anterior a %s) e mantêm o dado do run anterior. Exemplos de id: %s",
                len(stale), table, year, run_start_date.isoformat(),
                ", ".join(str(i) for i in stale["id"].head(sample_size)),
            )

    if total_stale:
        logger.error(
            "Reprocessar tudo: %d registro(s) no total ficaram sem reprocessar. Para tentar de novo "
            "só o que falhou, dispare o workflow de novo com o mesmo range e 'Reprocessar tudo' "
            "ligado após limpar o checkpoint, ou investigue os ids acima.", total_stale,
        )
    else:
        logger.info(
            "Reprocessar tudo: todos os registros de details dos anos verificados foram "
            "reprocessados nesta execução."
        )
    return total_stale


def trigger_agg_locally(
    *,
    s3_bucket_spec: str,
    s3_prefix_spec: str,
    s3_bucket_temp: str,
    db_movie: str,
    db_tv: str,
    db_unified: str,
    table_name: str,
    dq_job_name: str,
    environment: str,
) -> None:
    """Roda o Glue AGG dentro do processo do backfill, sem acioná-lo como job Glue.

    Réplica direta de app/glue_agg/main.py: run_athena_query -> write_parquet_to_spec ->
    trigger_glue_job (dispara o Glue Data Quality sobre a tabela unificada, fire-and-forget,
    mesmo padrão já usado pelos demais scripts). Viável porque app/glue_agg/src/utils.py é
    Python puro (awswrangler + pandas, sem Spark/GlueContext) — só get_parameters_glue()
    dependeria do runtime do Glue (awsglue.utils.getResolvedOptions), e não é usada aqui.

    Import local (não no topo do módulo) com um sys.path.insert extra para app/glue_agg:
    diferente de app/glue_etl/src/utils.py e app/glue_details/src/utils.py (que só importam de
    shared_utils), app/glue_agg/src/utils.py faz `from src.queries import
    _DISCOVER_UNIFIED_QUERY` — import absoluto de um pacote top-level literal "src", herdado de
    como o wheel do job real é empacotado (ver infra/scripts/build_glue_wheel.py). Sem inserir
    app/glue_agg (não só a raiz do repo) em sys.path antes deste import,
    `from app.glue_agg.src.utils import ...` levanta `ModuleNotFoundError: No module named 'src'`.

    Chamar SEMPRE antes de clear_checkpoint, nunca depois: se este helper propagar token
    expirado, run_with_retry_exit traduz em exit 75 e o script inteiro é re-executado — se o
    checkpoint já tivesse sido limpo, a reexecução reprocessaria todas as unidades do zero só
    para retentar o AGG. Chamando antes, uma reexecução por token expirado encontra
    `pendentes=[]` (checkpoint intacto) e vai direto para o AGG de novo.

    Erros que não são token expirado são capturados e logados como ERROR — uma falha aqui não
    deve derrubar um backfill que já terminou com sucesso: o trigger agendado (sábado/domingo
    08:00 BRT, aws_glue_trigger.agg_weekly) e o alarme SNS de falha
    (infra/cloudwatch_glue_alarms.tf) continuam cobrindo o caso, mesma garantia que o
    `::warning::` do workflow dava antes desta função existir. Token expirado propaga — é
    recuperável, e run_with_retry_exit precisa vê-lo para traduzir em exit code 75.

    Args:
        s3_bucket_spec: Bucket S3 SPEC de destino da tabela unificada.
        s3_prefix_spec: Prefixo do caminho S3 dentro do bucket SPEC (= project_prefix, "tmdb").
        s3_bucket_temp: Bucket S3 TEMP usado como área de resultados temporários do Athena.
        db_movie:       Banco de dados de filmes no Glue Catalog.
        db_tv:          Banco de dados de séries no Glue Catalog.
        db_unified:     Banco de dados unificado no Glue Catalog.
        table_name:     Nome da tabela unificada de destino (tb_..._discover_unified_<env>).
        dq_job_name:    Nome do job Glue Data Quality a disparar sobre a tabela unificada.
        environment:    "dev" ou "prod" — usado para construir os nomes das tabelas de origem.

    Returns:
        None. Nunca levanta exceção, exceto ClientError de token expirado.
    """
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "app" / "shared_src"))
    sys.path.insert(0, str(_REPO_ROOT / "app" / "glue_agg"))
    from app.glue_agg.src.utils import (
        run_athena_query,
        trigger_glue_job,
        write_parquet_to_spec,
    )

    logger.info(
        "Rodando Glue AGG localmente (sem acionar job) para propagar o backfill à camada SPEC..."
    )
    try:
        df = run_athena_query(
            db_movie=db_movie,
            db_tv=db_tv,
            db_unified=db_unified,
            s3_bucket_temp=s3_bucket_temp,
            env=environment,
        )
        write_parquet_to_spec(
            df=df,
            s3_bucket_spec=s3_bucket_spec,
            s3_prefix_spec=s3_prefix_spec,
            table_name=table_name,
            database=db_unified,
        )
        trigger_glue_job(dq_job_name, TABLE_NAME=table_name, DATABASE=db_unified)
    except ClientError as exc:
        if is_expired_token_error(exc):
            log_expired_token(exc, "execução local do Glue AGG")
            raise
        logger.exception(
            "Falha ao rodar o Glue AGG localmente. O backfill principal já terminou; o "
            "trigger agendado (sáb/dom 08:00 BRT) e o alarme SNS de falha continuam cobrindo "
            "este caso."
        )
    except Exception:  # falha do AGG não deve derrubar o backfill já concluído
        logger.exception(
            "Falha ao rodar o Glue AGG localmente. O backfill principal já terminou; o "
            "trigger agendado (sáb/dom 08:00 BRT) e o alarme SNS de falha continuam cobrindo "
            "este caso."
        )
    else:
        # Fraseado deliberadamente para NÃO bater com a regex do workflow que extrai o
        # "resumo real" do log (grep -E "conclu[ií]d|atualizadas|disparado com sucesso|
        # submetidas" | tail -1) — se batesse, essa linha substituiria o resumo do
        # backfill em si no step summary, já que é a última linha cronologicamente.
        logger.info(
            "Glue AGG (local) processado com sucesso — tabela unificada gravada e Data "
            "Quality acionado."
        )


def notify_backfill_success(table_group: str, summary: str) -> None:
    """Publica no SNS de sucesso do backfill — última etapa de um script já concluído.

    ARN lido de SNS_TOPIC_ARN_BACKFILL_SUCCESS (opcional, não require_env): sem ela,
    loga WARNING e não publica, em vez de abortar — a ausência de uma variável só de
    notificação não pode derrubar um backfill que já terminou com sucesso, e isso
    também permite rodar os scripts localmente (fora do workflow) sem configurá-la.

    Nunca propaga exceção (nem token expirado): diferente de trigger_agg_locally, esta
    função roda depois de clear_checkpoint — deixar propagar forçaria run_with_retry_exit
    a sinalizar exit 75 e reprocessar o backfill inteiro do zero só por causa de uma
    falha de observabilidade.

    Args:
        table_group: identifica o backfill no corpo/logs (o assunto do email é fixo,
            sem table_group — quem identifica o backfill é o corpo da mensagem, que já
            nomeia o tipo em todos os 8 scripts, ex.: "Backfill de discover concluído...").
        summary: corpo da mensagem — reaproveita a mesma string já logada como
            "concluído" pelo script chamador.
    """
    topic_arn = os.environ.get("SNS_TOPIC_ARN_BACKFILL_SUCCESS")
    if not topic_arn:
        logger.warning(
            "SNS_TOPIC_ARN_BACKFILL_SUCCESS não definida — notificação de sucesso do "
            "backfill '%s' não enviada.", table_group,
        )
        return

    environment = os.environ.get("ENVIRONMENT", "?").upper()
    try:
        boto3.client("sns").publish(
            TopicArn=topic_arn,
            Subject=f"[{environment}] BACKFILL - SUCESSO",
            Message=summary,
        )
    except Exception:  # falha ao notificar não deve afetar um backfill já concluído
        logger.exception("Falha ao publicar notificação de sucesso do backfill '%s'", table_group)
    else:
        logger.info("Notificação de sucesso do backfill '%s' enviada via SNS.", table_group)
