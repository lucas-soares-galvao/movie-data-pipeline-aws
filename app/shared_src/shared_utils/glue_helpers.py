"""glue_helpers.py — Utilitários compartilhados para jobs Glue."""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict

from awsglue.utils import getResolvedOptions

logger = logging.getLogger()


def get_resolved_option(args: list) -> Dict[str, Any]:
    """
    Wrapper de getResolvedOptions — converte lista de nomes em dicionário nome→valor.

    Args:
        args: Lista com os nomes dos argumentos esperados pelo job Glue.

    Returns:
        Dicionário nome→valor com os argumentos resolvidos.
    """
    return getResolvedOptions(sys.argv, args)


def configure_glue_logging() -> logging.Logger:
    """
    Configura logging padrão para jobs Glue (stdout, INFO, formato com timestamp).

    Returns:
        O logger raiz configurado.
    """
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    return logging.getLogger()
