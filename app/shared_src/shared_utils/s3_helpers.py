"""s3_helpers.py — Auxiliares para chamadas boto3 ao S3 com proteção contra bucket squatting.

Por que existe
--------------
Toda chamada boto3 a um objeto S3 (`get_object`, `put_object`, `delete_object`)
deve informar o dono esperado do bucket via `ExpectedBucketOwner`. Sem esse
parâmetro, uma chamada direcionada ao nome de um bucket que foi deletado e
recriado por um terceiro (bucket squatting) pode ler/escrever no bucket do
atacante em vez do bucket original — o Cliente passa a apontar para o nome,
não para uma conta específica.

O valor esperado é o account ID da **própria conta** em que o job/Lambda roda,
já que os buckets do pipeline são provisionados na mesma conta do serviço que
os acessa (dev e prod ficam em contas separadas, cada uma acessando os seus
próprios buckets). O Terraform injeta esse valor na variável de ambiente
`AWS_ACCOUNT_ID` a partir de `data.aws_caller_identity.current.account_id`
(Lambda via `environment.variables`, jobs Glue via argumento resolvido e
publicado em `os.environ` — ver `get_parameters_glue`).
"""

import os


def expected_bucket_owner_kwargs() -> dict[str, str]:
    """Retorna o kwarg `ExpectedBucketOwner` a espalhar numa chamada boto3 ao S3.

    A variável de ambiente `AWS_ACCOUNT_ID` é lida a cada chamada (não cacheada
    no import) para que o valor esteja disponível mesmo quando definida durante
    a execução — no caso dos jobs Glue, ela é publicada em `os.environ` dentro
    de `get_parameters_glue`, que roda depois do import deste módulo.

    Returns:
        `{"ExpectedBucketOwner": <account_id>}` quando `AWS_ACCOUNT_ID` está
        definida; dicionário vazio caso contrário. Retornar vazio (em vez de
        `ExpectedBucketOwner=None`) evita enviar um valor inválido ao boto3 e
        permite rodar os scripts localmente / nos testes sem definir a variável.
    """
    account_id = os.environ.get("AWS_ACCOUNT_ID")
    return {"ExpectedBucketOwner": account_id} if account_id else {}
