"""
main.py — Ponto de entrada do job Glue Data Quality.

Este arquivo contém apenas a lógica principal do fluxo, em ordem:

  1. Cria o SparkContext e o GlueContext — necessários para ler tabelas do Catalog
     e executar o motor de avaliação de qualidade.
  2. Lê os argumentos do job (TABLE_NAME, DATABASE, S3_BUCKET_DATA_QUALITY, ENVIRONMENT).
  3. Busca as regras de qualidade definidas em rulesets_dq.py para a tabela recebida.
  4. Lê os dados da tabela diretamente do Glue Catalog.
  5. Avalia as regras e gera o relatório de qualidade (Passed / Failed por regra).
  6. Grava o resultado como Parquet no bucket de Data Quality,
     particionado pela coluna source_table.

Este job é acionado pelo Glue ETL logo após gravar cada tabela no SOT.
O Glue ETL passa os argumentos --TABLE_NAME, --DATABASE e opcionalmente --YEAR.
"""

import logging
import sys

from awsglue.context import GlueContext
from pyspark.context import SparkContext

from src.utils import (
    evaluate_data_quality,
    get_parameters_glue,
    get_ruleset,
    read_table_from_catalog,
    write_results_to_s3,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)


def main() -> None:
    """Executa o pipeline de avaliação de qualidade de dados."""

    # --- 1. Cria os contextos do Spark e do Glue ---
    # SparkContext: ponto de entrada do Spark (motor de processamento distribuído).
    # GlueContext: adiciona funcionalidades do AWS Glue sobre o Spark, como
    #              leitura do Glue Catalog e integração com o Data Quality.
    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)

    # --- 2. Lê os argumentos do job ---
    # Os argumentos são passados pelo Glue ETL ao acionar este job.
    args = get_parameters_glue()
    table_name = args["TABLE_NAME"]
    database = args["DATABASE"]
    s3_bucket_data_quality = args["S3_BUCKET_DATA_QUALITY"]
    year = args.get("YEAR")  # None para tabelas sem partição (gêneros, config)

    logger.info(
        f"Iniciando Data Quality | tabela: '{table_name}' | banco: '{database}'"
    )

    # --- 3. Busca as regras de qualidade para esta tabela ---
    # As regras ficam centralizadas em rulesets_dq.py, desacopladas da lógica de execução.
    ruleset = get_ruleset(table_name)

    # --- 4. Lê os dados da tabela no Glue Catalog ---
    # O Glue Catalog funciona como um catálogo central de metadados (nome, schema, localização).
    # Para tabelas de discover (particionadas por ano), filtra apenas a partição recém-escrita
    # via push_down_predicate, evitando erros de arquivo não encontrado em partições anteriores.
    dynamic_frame = read_table_from_catalog(glue_context, database, table_name, year)

    # --- 5. Avalia a qualidade dos dados ---
    # Para cada regra do ruleset, o Glue verifica se os dados passam ou falham.
    df_results = evaluate_data_quality(
        glue_context, dynamic_frame, ruleset, table_name, database, year
    )

    # --- 6. Grava o resultado no bucket de Data Quality ---
    # Para discover: particionado por source_table + partition (ano), sobrescrevendo
    # apenas aquele ano. Para genre/config: sobrescreve apenas source_table.
    write_results_to_s3(df_results, s3_bucket_data_quality, table_name, database, year)

    logger.info("Job Glue Data Quality finalizado com sucesso!")


if __name__ == "__main__":
    main()
