"""glue_helpers.py — Utilitários compartilhados para jobs Glue."""

from __future__ import annotations

import logging
import sys
from typing import Any

from shared_utils.secret_redaction import install_log_redaction

logger = logging.getLogger()


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
