"""utils.py — Espera jobs Glue terminarem antes de acionar o job alvo."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger()

_TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "STOPPED", "ERROR", "TIMEOUT"})


def wait_for_job_runs(
    glue_client: Any, wait_for: list[dict[str, str]], poll_interval: int = 15,
) -> None:
    """Aguarda cada job run em `wait_for` atingir um estado terminal.

    `trigger_glue_job` (shared_utils.triggers) é fire-and-forget — quem dispara os jobs em
    `wait_for` não sabe quando eles terminam. Sem essa espera, o job acionado em seguida (ver
    main.py) poderia começar antes das escritas dos jobs em `wait_for` estarem completas.

    Não aborta em caso de falha de um job individual: loga e segue para o próximo, para não
    perder a espera pelos demais jobs por causa de um que falhou.

    Args:
        glue_client: cliente boto3 do Glue.
        wait_for: lista de `{"job_name": ..., "run_id": ...}` a aguardar.
        poll_interval: segundos entre cada consulta de `get_job_run`.
    """
    for job in wait_for:
        job_name, run_id = job["job_name"], job["run_id"]
        while True:
            state = glue_client.get_job_run(JobName=job_name, RunId=run_id)["JobRun"]["JobRunState"]
            if state in _TERMINAL_STATES:
                if state != "SUCCEEDED":
                    logger.error(
                        f"Job '{job_name}' (run_id={run_id}) terminou em '{state}' — "
                        "seguindo para o próximo mesmo assim."
                    )
                break
            time.sleep(poll_interval)
