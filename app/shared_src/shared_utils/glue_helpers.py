"""glue_helpers.py — Utilitários compartilhados para jobs Glue."""

from __future__ import annotations

import logging
import sys
from datetime import date
from typing import Any

import pandas as pd

from shared_utils.secret_redaction import install_log_redaction

logger = logging.getLogger()

PROCESSED_DATE_COLUMN = "processed_date"
PROCESSING_TIMEZONE = "America/Sao_Paulo"


def get_resolved_option(args: list) -> dict[str, Any]:
    """
    Wrapper de getResolvedOptions — converte lista de nomes em dicionário nome→valor.

    Import de awsglue feito dentro da função (não no topo do módulo): awsglue só existe
    no runtime do Glue, e este módulo é importado transitivamente por scripts/ (via
    app/glue_details/src/utils.py) que rodam fora desse runtime e nunca chamam esta função.

    Args:
        args: Lista com os nomes dos argumentos esperados pelo job Glue.

    Returns:
        Dicionário nome→valor com os argumentos resolvidos.
    """
    from awsglue.utils import getResolvedOptions

    return getResolvedOptions(sys.argv, args)


def configure_glue_logging() -> logging.Logger:
    """
    Configura logging padrão para jobs Glue (stdout, INFO, formato com timestamp) e mascara
    segredos (api_key e afins) em tudo o que é logado, inclusive tracebacks.

    Returns:
        O logger raiz configurado.
    """
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    # Segredos (ex.: api_key do TMDB dentro da URL de uma exceção do requests) nunca vão ao
    # CloudWatch em texto claro — ver shared_utils.secret_redaction.
    install_log_redaction()
    return logging.getLogger()


def current_processed_date() -> date:
    """
    Data de hoje em America/Sao_Paulo, usada como valor de processed_date.

    Fonte única do fuso de processed_date em todas as tabelas. O fuso é resolvido por pytz
    (dependência do pandas), sem depender de tzdata do sistema no Python Shell do Glue.
    """
    return pd.Timestamp.now(tz=PROCESSING_TIMEZONE).date()


def add_processed_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adiciona ao DataFrame a coluna processed_date (date, YYYY-MM-DD, hora de São Paulo).

    O valor é único para todas as linhas. Só deve ser usada onde a partição/tabela é
    reconstruída por completo (glue_etl e glue_agg); details e watch_providers carimbam
    processed_date por registro, na criação, porque preservam registros antigos no merge.

    A coluna é atribuída no próprio DataFrame (sem copiar) e fica por último: o
    ParquetHiveSerDe resolve colunas por posição, então a ordem precisa bater com a do
    Glue Catalog (infra/glue_catalog.tf). Se a coluna já existir, é sobrescrita no lugar.

    Args:
        df: DataFrame que será gravado.

    Returns:
        O mesmo DataFrame recebido, com processed_date preenchida.
    """
    df[PROCESSED_DATE_COLUMN] = current_processed_date()
    return df
