import boto3
import os


def lambda_handler(event, context):
    action = event.get("action")
    instance_name = os.environ["LIGHTSAIL_INSTANCE_NAME"]

    client = boto3.client("lightsail", region_name="us-east-1")

    if action == "stop":
        client.stop_instance(instanceName=instance_name)
        print(f"Instância '{instance_name}' sendo parada.")
        return {"status": "stopping", "instance": instance_name}

    elif action == "start":
        client.start_instance(instanceName=instance_name)
        print(f"Instância '{instance_name}' sendo iniciada.")
        return {"status": "starting", "instance": instance_name}

    else:
        raise ValueError(f"Ação desconhecida: '{action}'. Use 'stop' ou 'start'.")
