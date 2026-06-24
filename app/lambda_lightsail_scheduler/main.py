"""Lambda que liga/desliga a instância Lightsail do FilmBot para reduzir custo."""

import logging
import os
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Inicia ou para uma instância Lightsail conforme a ação recebida.

    Parâmetros do event (enviados pelo EventBridge Scheduler):
        action (str): "start" para ligar ou "stop" para desligar a instância.

    Variáveis de ambiente obrigatórias:
        LIGHTSAIL_INSTANCE_NAME: nome da instância cadastrada no Lightsail.
    """
    action = event.get("action")
    instance_name = os.environ["LIGHTSAIL_INSTANCE_NAME"]

    # Lightsail usa us-east-1 independentemente da região da Lambda (sa-east-1)
    # porque a API do Lightsail só responde nessa região.
    client = boto3.client("lightsail", region_name="us-east-1")

    if action == "stop":
        client.stop_instance(instanceName=instance_name)
        logger.info(f"Instância '{instance_name}' sendo parada.")
        return {"status": "stopping", "instance": instance_name}

    elif action == "start":
        client.start_instance(instanceName=instance_name)
        logger.info(f"Instância '{instance_name}' sendo iniciada.")
        return {"status": "starting", "instance": instance_name}

    else:
        raise ValueError(f"Ação desconhecida: '{action}'. Use 'stop' ou 'start'.")
