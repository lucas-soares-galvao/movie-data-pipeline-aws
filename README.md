# Projeto
Repositório de pipeline AWS completo.

## Orquestracao Lambda -> Glue ETL

O fluxo da `lambda_api` para o `glue_etl` foi separado em dois tipos de execucao:

- `TABLE_SCOPE=static`: executa apenas as tabelas `genre` e `configuration` uma vez por invocacao da Lambda.
- `TABLE_SCOPE=discover`: executa apenas a tabela `discover`, uma vez por ano processado.

Quando a Lambda dispara o Glue com `TABLE_SCOPE=discover`, ela tambem envia `YEAR=<ano>`. Nesse caso, o ETL le somente o prefixo anual correspondente em S3, evitando reprocessar anos anteriores e evitando reprocessar `genre` e `configuration` a cada ano.

Os argumentos `MEDIA_TYPE`, `DISCOVER_TABLE`, `GENRE_TABLE`, `CONFIGURATION_TABLE`, `CONFIGURATION`, `PARTITION_COLUMNS`, `YEAR` e `TABLE_SCOPE` sao enviados dinamicamente pela Lambda em cada `start_job_run`. Os argumentos fixos do job continuam definidos no Terraform.