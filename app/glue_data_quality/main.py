"""
main.py — Ponto de Entrada do Job Glue Data Quality

==============================================================================
O QUE É "QUALIDADE DE DADOS"?
==============================================================================
Dados de qualidade ruim são como ingredientes estragados numa receita:
mesmo que o processo seja perfeito, o resultado final será ruim.

Problemas comuns de qualidade de dados:
- Campos obrigatórios nulos (id=None, title=None)
- Valores fora do intervalo esperado (vote_average=15 quando máximo é 10)
- Duplicatas (mesmo filme aparecendo com dois IDs)
- Tabela vazia (zero registros — processamento silenciosamente falhou)

ESTE JOB VERIFICA TUDO ISSO AUTOMATICAMENTE.

==============================================================================
COMO FUNCIONA O AWS GLUE DATA QUALITY?
==============================================================================
É um serviço dentro do Glue que permite escrever "regras" em uma linguagem
especial (DQDL - Data Quality Definition Language) e avaliá-las contra dados.

EXEMPLO DE REGRAS:
  'IsComplete "id"'          → A coluna "id" não pode ter valores nulos
  'IsUnique "id"'            → Cada valor de "id" deve ser único (sem duplicatas)
  'RowCount > 0'             → A tabela não pode estar vazia
  'ColumnValues "vote_average" between 0 and 10'  → Notas devem estar entre 0 e 10

RESULTADO DA AVALIAÇÃO: "Passed" ou "Failed" para cada regra.
Os resultados são salvos no bucket DQ em Parquet para auditoria.
Se houver falhas, uma notificação é enviada via SNS (email).

==============================================================================
POR QUE USAR SPARK (GLUE SPARK JOB)?
==============================================================================
O Data Quality do Glue requer o GlueContext (que requer SparkContext).
Diferente dos outros jobs (PythonShell), este é um job Spark que inicializa
um cluster distribuído para avaliar as regras — daí o maior custo e tempo
de inicialização comparado ao ETL.
==============================================================================
"""

import logging
import sys

from awsglue.context import GlueContext
from pyspark.context import SparkContext

from src.utils import (
    evaluate_data_quality,
    get_parameters_glue,
    get_ruleset,
    notify_failed_outcomes,
    read_table_from_catalog,
    write_results_to_s3,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger()


def main() -> None:
    """
    Executa o pipeline completo de avaliação de qualidade de dados.

    Fluxo: argumentos → contextos Spark → lê dados → avalia regras → salva resultados → notifica.
    """

    # ==========================================================================
    # PASSO 1: Criar os Contextos Spark e Glue
    # ==========================================================================
    # SparkContext = "motor" do Apache Spark para processamento distribuído.
    # GlueContext = "adaptador" que conecta o Spark às funcionalidades do AWS Glue
    #               (leitura do Catalog, engine de Data Quality, etc.)
    #
    # SparkContext.getOrCreate() evita criar um novo contexto se já existe um
    # (importante em testes e reruns).
    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)

    # ==========================================================================
    # PASSO 2: Ler os Argumentos do Job
    # ==========================================================================
    # Argumentos passados pelo Glue ETL ao disparar este job:
    # - TABLE_NAME: qual tabela validar (ex: "tb_discover_movie_tmdb")
    # - DATABASE: banco no Glue Catalog onde a tabela está
    # - DATABASE_RESULTS: banco onde salvar os resultados de DQ
    # - S3_BUCKET_DATA_QUALITY: bucket para salvar os resultados em Parquet
    # - ENVIRONMENT: "dev" ou "prod" (para contexto nas notificações)
    # - SNS_TOPIC_ARN_DQ_METRICS: ARN do tópico SNS para notificações de DQ
    # - YEAR: ano da partição (apenas para tabelas de discover)
    args = get_parameters_glue()
    table_name             = args["TABLE_NAME"]
    database               = args["DATABASE"]
    database_results       = args["DATABASE_RESULTS"]
    s3_bucket_data_quality = args["S3_BUCKET_DATA_QUALITY"]
    environment            = args["ENVIRONMENT"]
    sns_topic_arn_dq_metrics = args["SNS_TOPIC_ARN_DQ_METRICS"]
    year = args.get("YEAR")  # None para tabelas sem partição (gêneros, configurações)

    logger.info(
        f"Iniciando Data Quality | tabela: '{table_name}' | banco: '{database}'"
    )

    # ==========================================================================
    # PASSO 3: Buscar as Regras de Qualidade para Esta Tabela
    # ==========================================================================
    # As regras ficam em rulesets_dq.py, mapeadas por nome de tabela.
    # Isso desacopla as regras da lógica de execução — para adicionar novas regras,
    # basta editar rulesets_dq.py sem tocar no main.py.
    ruleset = get_ruleset(table_name)

    # ==========================================================================
    # PASSO 4: Ler os Dados da Tabela no Glue Catalog
    # ==========================================================================
    # O Glue Catalog registra onde os dados estão no S3.
    # Para tabelas particionadas por ano (discover), usa "push_down_predicate"
    # para ler APENAS a partição recém-gravada — mais eficiente e evita erros
    # de "arquivo não encontrado" em partições antigas que podem ter sido movidas.
    dynamic_frame = read_table_from_catalog(glue_context, database, table_name, year)

    # ==========================================================================
    # PASSO 5: Avaliar as Regras de Qualidade
    # ==========================================================================
    # O motor de Data Quality do Glue avalia cada regra do ruleset contra o DynamicFrame.
    # O resultado é um DataFrame com colunas:
    # - rule:       Texto da regra avaliada (ex: 'IsComplete "id"')
    # - outcome:    "Passed" ou "Failed"
    # - source_table: nome da tabela avaliada
    # - partition:  ano (se particionada)
    df_results = evaluate_data_quality(
        glue_context, dynamic_frame, ruleset, table_name, database, year
    )

    # ==========================================================================
    # PASSO 6: Salvar os Resultados no Bucket de Data Quality
    # ==========================================================================
    # Resultados em Parquet, particionados por source_table (e ano, se discover).
    # Isso permite consultar no Athena: "Quais tabelas falharam na última semana?"
    write_results_to_s3(
        df_results,
        s3_bucket_data_quality,
        table_name,
        database_results,
        year,
    )

    # ==========================================================================
    # PASSO 7: Notificar se Houver Falhas
    # ==========================================================================
    # Se qualquer regra falhou, envia email via SNS com o nome da tabela e
    # quais regras falharam. A equipe pode então investigar o problema nos logs.
    notify_failed_outcomes(df_results, table_name, sns_topic_arn_dq_metrics, environment, year)

    logger.info("Job Glue Data Quality finalizado com sucesso!")


if __name__ == "__main__":
    main()
