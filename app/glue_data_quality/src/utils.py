"""
utils.py — Funções auxiliares do job Glue Data Quality.

==============================================================================
O QUE ESTE ARQUIVO FAZ?
==============================================================================
Este arquivo contém as ferramentas que o job principal (main.py) usa para
executar a verificação de qualidade dos dados. Pense nele como a "caixa de
ferramentas" do inspetor de qualidade:

  1. get_parameters_glue()      → lê as instruções do job (qual tabela verificar)
  2. get_ruleset()              → busca as "regras de inspeção" da tabela
  3. read_table_from_catalog()  → abre a tabela para inspecionar
  4. evaluate_data_quality()    → executa a inspeção regra por regra
  5. write_results_to_s3()      → arquiva os resultados da inspeção
  6. notify_failed_outcomes()   → dispara alerta por email se algo falhar

TECNOLOGIAS UTILIZADAS:
  - AWS Glue Data Quality (EvaluateDataQuality): motor de avaliação de regras
  - Apache Spark / PySpark: processa os dados em memória distribuída
  - AWS Wrangler: grava os resultados em Parquet no S3
  - Boto3 (SNS): envia notificações por email em caso de falha

ANALOGIA: Como um controle de qualidade numa fábrica.
  Antes do produto sair, um inspetor verifica uma lista de critérios:
  "a embalagem está intacta?", "o peso está correto?", "a validade está impressa?"
  Se algum critério falhar, aciona um alarme — aqui, o SNS envia um email.

Responsabilidades:
  - Ler os argumentos do job (TABLE_NAME, DATABASE, S3_BUCKET_DATA_QUALITY, ENVIRONMENT)
  - Buscar o ruleset (conjunto de regras DQDL) da tabela em rulesets_dq.py
  - Ler a tabela do Glue Catalog como DynamicFrame
  - Avaliar a qualidade dos dados com EvaluateDataQuality
  - Gravar o resultado da avaliação no S3 como Parquet, particionado por source_table
"""

import logging
import sys
from typing import Any, Dict, Optional

import awswrangler as wr
import boto3
from awsglue.context import GlueContext
from awsglue.dynamicframe import DynamicFrame
from awsglue.utils import GlueArgumentError, getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.sql.functions import col, current_timestamp, from_utc_timestamp, lit, when
from pyspark.sql.types import StringType

from src.rulesets_dq import rulesets_dq

logger = logging.getLogger()


# ---------------------------------------------------------------------------
# Leitura de argumentos do job
# ---------------------------------------------------------------------------


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos obrigatórios e opcionais passados ao job Glue pelo Glue ETL.

    Argumentos obrigatórios: TABLE_NAME, DATABASE, DATABASE_RESULTS, S3_BUCKET_DATA_QUALITY, ENVIRONMENT.
    Argumento opcional:      YEAR (presente apenas para tabelas de discover).

    Returns:
        Dicionário com todos os argumentos resolvidos.
    """
    # Argumentos que SEMPRE devem estar presentes — sem eles, o job não sabe o que fazer
    required_args = [
        "TABLE_NAME",           # Qual tabela validar? Ex: "tb_discover_movie_tmdb"
        "DATABASE",             # Em qual banco do Glue Catalog a tabela está?
        "DATABASE_RESULTS",     # Em qual banco salvar os resultados de DQ?
        "S3_BUCKET_DATA_QUALITY", # Onde salvar os resultados no S3?
        "ENVIRONMENT",          # "dev" ou "prod" — aparece no email de alerta
        "SNS_TOPIC_ARN_DQ_METRICS", # Endereço do "grupo de WhatsApp" para alertas SNS
    ]
    args = getResolvedOptions(sys.argv, required_args)

    # YEAR é opcional: o Glue ETL passa --YEAR apenas para runs de discover
    # (tabelas de gênero e configuração não têm partição por ano)
    # Se não existir o argumento YEAR, o try/except evita que o job quebre
    try:
        args.update(getResolvedOptions(sys.argv, ["YEAR"]))
    except (SystemExit, GlueArgumentError):
        pass  # não há YEAR — tabela sem partição por ano; ok continuar

    return args


# ---------------------------------------------------------------------------
# Ruleset (conjunto de regras DQDL)
# ---------------------------------------------------------------------------


def get_ruleset(table_name: str) -> str:
    """
    Busca as regras de qualidade definidas em rulesets_dq.py para a tabela e
    monta a string no formato DQDL exigida pelo Glue Data Quality.

    ANALOGIA: Como um formulário de inspeção numa oficina mecânica.
    O mecânico tem um checklist diferente para cada tipo de veículo (carro, moto,
    caminhão). Aqui, cada tabela tem seu próprio checklist (ruleset) em rulesets_dq.py.

    Formato DQDL que o Glue espera (string literal):
      Rules = [
        IsComplete "id",
        IsUnique "id",
        RowCount > 0
      ]

    Args:
        table_name: Nome da tabela no Glue Catalog.

    Returns:
        String com as regras no formato DQDL.

    Raises:
        KeyError: Se não houver regras definidas para a tabela em rulesets_dq.py.
    """
    rules = rulesets_dq.get(table_name)
    if rules is None:
        # Erro proposital: não faz sentido executar DQ numa tabela sem regras definidas.
        # Isso avisa o desenvolvedor para adicionar as regras em rulesets_dq.py
        # antes de colocar a tabela no pipeline.
        raise KeyError(
            f"Nenhuma regra de DQ definida para a tabela '{table_name}'. "
            f"Adicione as regras em rulesets_dq.py."
        )

    # Junta as regras em uma string no formato que o Glue Data Quality entende.
    # Exemplo com 2 regras: "Rules = [\n  IsComplete \"id\",\n  RowCount > 0\n]"
    ruleset = "Rules = [\n  " + ",\n  ".join(rules) + "\n]"
    logger.info(f"Ruleset para '{table_name}':\n{ruleset}")
    return ruleset


# ---------------------------------------------------------------------------
# Leitura da tabela no Glue Catalog
# ---------------------------------------------------------------------------


def read_table_from_catalog(
    glue_context: GlueContext,
    database: str,
    table_name: str,
    year: Optional[str] = None,
):
    """
    Lê uma tabela registrada no Glue Catalog e a retorna como DynamicFrame.

    O DynamicFrame é o formato padrão do AWS Glue para representar dados
    distribuídos (semelhante ao DataFrame do Spark, mas com suporte extra
    a esquemas flexíveis e tipos aninhados).

    Quando `year` é informado (tabelas de discover particionadas por ano), aplica
    um `push_down_predicate` para ler **apenas** a partição recém-escrita. Isso
    evita que o Glue tente acessar arquivos de outras partições que possam ter
    metadados obsoletos no Catalog após re-escritas anteriores.

    Args:
        glue_context: Contexto do Glue criado no main.py.
        database:     Nome do banco de dados no Glue Catalog.
        table_name:   Nome da tabela a ser lida.
        year:         Ano da partição a filtrar. None lê a tabela inteira.

    Returns:
        DynamicFrame com os dados da tabela (ou partição, quando year é fornecido).
    """
    logger.info(f"Lendo tabela '{database}.{table_name}' do Glue Catalog...")
    # Monta os argumentos da leitura. Para tabelas sem partição (gêneros, configurações),
    # só precisamos de database e table_name.
    kwargs: Dict[str, Any] = {
        "database": database,
        "table_name": table_name,
    }
    if year is not None:
        # push_down_predicate = "filtro de partição empurrado para baixo"
        # Em vez de carregar TODOS os dados e depois filtrar em memória,
        # o Glue instrui o S3 a já retornar apenas os arquivos da pasta "year=XXXX/".
        # Isso é muito mais rápido e barato para tabelas grandes com vários anos.
        kwargs["push_down_predicate"] = f"year = '{year}'"
        logger.info(f"Aplicando filtro de partição: year = '{year}'")
    return glue_context.create_dynamic_frame.from_catalog(**kwargs)


# ---------------------------------------------------------------------------
# Avaliação da qualidade dos dados
# ---------------------------------------------------------------------------


def evaluate_data_quality(
    glue_context: GlueContext,
    dynamic_frame,
    ruleset: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
):
    """
    Executa a avaliação de qualidade dos dados com o EvaluateDataQuality do Glue.

    O Glue DQ retorna um DynamicFrame com colunas em PascalCase:
      - Rule             : expressão da regra (ex.: 'IsComplete "id"')
      - Outcome          : "Passed" ou "Failed"
      - FailureReason    : motivo da falha (null se passou)
      - EvaluatedMetrics : métricas calculadas para a regra

    As colunas são renomeadas para snake_case (necessário para que o Athena
    consiga ler failure_reason corretamente) e as seguintes colunas de contexto
    são adicionadas:
      - partition        : ano da partição da tabela avaliada (None se não aplicável)
      - datetime_process : timestamp do momento da avaliação
      - source_database  : banco de dados no Glue Catalog
      - source_table     : nome da tabela avaliada (usada como partição no S3)

    Args:
        glue_context:  Contexto do Glue.
        dynamic_frame: DynamicFrame com os dados da tabela lida do Catalog.
        ruleset:       String de regras no formato DQDL.
        table_name:    Nome da tabela avaliada.
        database:      Nome do banco de dados no Glue Catalog.
        year:          Ano da partição. Preenchido apenas para tabelas de discover.

    Returns:
        Spark DataFrame com os resultados da avaliação e colunas de contexto.
    """
    logger.info(f"Avaliando qualidade de dados da tabela '{table_name}'...")

    # Para tabelas de discover (particionadas por ano), aplica filtro duplo:
    # 1. push_down_predicate no read_table_from_catalog (filtro no S3 — evita ler arquivos errados)
    # 2. Este filtro no DataFrame Spark (garante que apenas linhas do ano correto são avaliadas)
    # O filtro duplo é necessário porque o Glue Catalog às vezes inclui metadados de outras
    # partições no cache, então o push_down_predicate sozinho pode não ser suficiente.
    if year is not None:
        df_source = dynamic_frame.toDF().filter(col("year") == year)
        dynamic_frame = DynamicFrame.fromDF(df_source, glue_context, "filtered_frame")
        logger.info(f"Filtro aplicado no DataFrame: year = '{year}'")

    # Executa as regras sobre o DynamicFrame e retorna outro DynamicFrame com os resultados.
    # publishing_options controla o que o Glue publica no seu próprio painel e no CloudWatch.
    # Isso permite ver um histórico visual de DQ no console da AWS, além dos resultados no S3.
    dq_results = EvaluateDataQuality.apply(
        frame=dynamic_frame,
        ruleset=ruleset,
        publishing_options={
            # Nome do contexto que aparece nos resultados publicados no Glue Studio.
            # Ao abrir o job no console AWS, você vê a aba "Data Quality" com esse nome.
            "dataQualityEvaluationContext": table_name,
            # Publica métricas no CloudWatch (serviço de monitoramento da AWS).
            # Isso permite criar alarmes: "Se a taxa de sucesso cair abaixo de X%, me avise."
            "enableDataQualityCloudWatchMetrics": True,
            # Publica os resultados no painel de Data Quality do Glue Studio.
            # Visível em: AWS Console → Glue → Data Quality → Results
            "enableDataQualityResultsPublishing": True,
        },
    )

    # Converte DynamicFrame → Spark DataFrame e renomeia colunas PascalCase → snake_case.
    # O Glue DQ devolve colunas como "Rule", "Outcome", "FailureReason" (PascalCase).
    # O Athena espera nomes em snake_case para funcionar corretamente com o schema registrado.
    # Sem o rename, failure_reason apareceria como null no Athena mesmo com falhas reais.
    df = (
        dq_results.toDF()
        .withColumnRenamed("Rule", "rule")
        .withColumnRenamed("Outcome", "outcome")
        .withColumnRenamed("FailureReason", "failure_reason")
        .withColumnRenamed("EvaluatedMetrics", "evaluated_metrics")
        .drop(
            "EvaluatedRule"
        )  # coluna interna do Glue DQ que não faz parte do nosso schema
    )

    # EvaluatedMetrics é retornada pelo Glue DQ como map<string, double> — tipo complexo.
    # O AWS Wrangler não consegue serializar esse tipo ao escrever Parquet particionado no S3.
    # O cast para StringType converte o mapa em texto (ex: "{'completeness': 1.0}"),
    # preservando a informação sem causar erros de serialização.
    df = df.withColumn("evaluated_metrics", col("evaluated_metrics").cast(StringType()))

    # Classifica cada regra pela dimensão de qualidade com base no prefixo DQDL.
    # Isso permite filtrar no Athena: "Quais regras de 'completude' falharam esta semana?"
    # Dimensões de qualidade de dados:
    #   completude  → campos obrigatórios preenchidos (IsComplete)
    #   unicidade   → sem duplicatas (IsUnique)
    #   validade    → valores dentro do intervalo esperado (ColumnValues)
    #   integridade → tabela não vazia (RowCount)
    df = df.withColumn(
        "category",
        when(col("rule").startswith("IsComplete"), "completude")
        .when(col("rule").startswith("IsUnique"), "unicidade")
        .when(col("rule").startswith("ColumnValues"), "validade")
        .when(col("rule").startswith("RowCount"), "integridade"),
    )

    # Adiciona colunas de contexto para rastreabilidade histórica
    df = df.withColumn(
        "partition", lit(year).cast(StringType())  # ano da partição avaliada (None para tabelas sem partição)
    )
    df = df.withColumn(
        "datetime_process", from_utc_timestamp(current_timestamp(), "America/Sao_Paulo")
        # converte de UTC para horário de Brasília — facilita leitura nos relatórios
    )
    df = df.withColumn("source_database", lit(database))  # banco avaliado — útil em ambientes dev/prod
    df = df.withColumn("source_table", lit(table_name))   # tabela avaliada — usada como partição no S3

    logger.info(f"Avaliação concluída. Regras avaliadas: {df.count()}")
    return df


# ---------------------------------------------------------------------------
# Gravação dos resultados no S3
# ---------------------------------------------------------------------------


def write_results_to_s3(
    df,
    s3_bucket_data_quality: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
) -> None:
    """
    Grava o DataFrame com os resultados do Data Quality no S3 como Parquet,
    particionado pela coluna source_table, e atualiza o Glue Catalog automaticamente.

    Usa o AWS Wrangler (mesmo padrão do Glue ETL) para registrar as partições
    no Catalog após a escrita, eliminando a necessidade de MSCK REPAIR TABLE no Athena.

    A coluna 'partition' (ano) é mantida como dado normal dentro do Parquet —
    não é usada em partition_cols — para evitar que o Wrangler remova seu valor
    do arquivo e o Athena retorne null ao consultar a tabela.

    Caminho de escrita:
      s3://<bucket>/tmdb/tb_data_quality_tmdb/
        └── source_table=<table_name>/
              └── part-00000.parquet  (contém a coluna partition como dado)

    Args:
        df:                     Spark DataFrame com os resultados da avaliação.
        s3_bucket_data_quality: Nome do bucket de Data Quality.
        table_name:             Nome da tabela avaliada (informativo para o log).
        database:               Nome do banco de dados no Glue Catalog.
        year:                   Ano da partição (informativo; já está na coluna
                                'partition' do DataFrame).
    """
    # Todas as tabelas gravadas aqui vão para a mesma tabela de resultados no S3.
    # É uma única tabela "tb_data_quality_tmdb" particionada por source_table,
    # facilitando consultas do tipo: "Quais regras falharam para discover_movie?"
    output_table = "tb_data_quality_tmdb"
    s3_path = f"s3://{s3_bucket_data_quality}/tmdb/{output_table}/"

    logger.info(
        f"Gravando resultados em {s3_path} | source_table='{table_name}' | partition='{year}'"
    )

    # df.toPandas() converte do formato Spark (distribuído, para grandes volumes)
    # para Pandas (single-machine, mais simples), necessário para o AWS Wrangler.
    # O resultado da DQ é pequeno (uma linha por regra), então a conversão é segura.
    wr.s3.to_parquet(
        df=df.toPandas(),
        path=s3_path,
        dataset=True,           # registra no Glue Catalog automaticamente
        database=database,      # banco onde registrar a tabela de resultados
        table=output_table,     # nome da tabela no Catalog
        partition_cols=["source_table"],   # partição por nome de tabela avaliada
        mode="overwrite_partitions",       # substitui apenas a partição da tabela avaliada agora
    )

    logger.info(f"Resultados de '{table_name}' gravados com sucesso!")


# ---------------------------------------------------------------------------
# Notificação SNS para outcomes Failed
# ---------------------------------------------------------------------------


def notify_failed_outcomes(
    df,
    table_name: str,
    sns_topic_arn: str,
    environment: str,
    year: Optional[str] = None,
) -> None:
    """
    Verifica se alguma regra DQ teve outcome "Failed" e publica no SNS.

    O job termina com SUCCEEDED mesmo quando regras falham — essa função
    garante que o time seja notificado sobre falhas de métricas de dados,
    não apenas sobre crashes do job.

    Args:
        df:            Spark DataFrame com os resultados da avaliação (colunas rule, outcome, failure_reason).
        table_name:    Nome da tabela avaliada.
        sns_topic_arn: ARN do tópico SNS para publicar a notificação.
        environment:   Ambiente (dev, prod) para compor o subject do e-mail.
        year:          Partição avaliada, se aplicável.
    """
    # Filtra apenas as regras que falharam no resultado da avaliação
    failed_df = df.filter(col("outcome") == "Failed")
    count = failed_df.count()

    if count == 0:
        # Todas as regras passaram — nenhuma notificação necessária
        logger.info(f"Todas as regras passaram para '{table_name}'.")
        return

    # Extrai informações de contexto da primeira linha para compor o email
    first_row = df.select("datetime_process", "source_database").first()
    datetime_process = first_row["datetime_process"]
    source_database = first_row["source_database"]

    # Coleta as linhas de falha para incluir no corpo do email
    rows = failed_df.select("rule", "failure_reason", "category").collect()

    # Monta o corpo do email linha por linha
    lines = [
        "[DQ Métrica Falha]",
        f"Ambiente: {environment}",
        f"Banco: {source_database}",
        f"Tabela: {table_name}",
        f"Data/Hora: {datetime_process.strftime('%d/%m/%Y %H:%M:%S')}",
    ]
    if year is not None:
        lines.append(f"Partição: year={year}")
    lines.append(f"Regras com falha ({count}):")
    for row in rows:
        # Exemplo de linha: "• [completude] IsComplete "id" → Value: 0.98 does not meet threshold: >= 1.0"
        lines.append(f"  • [{row['category']}] {row['rule']} → {row['failure_reason']}")

    message = "\n".join(lines)

    # Publica a mensagem no SNS — o SNS entrega para todos os emails inscritos no tópico.
    # Subject aparece como assunto do email; Message é o corpo.
    boto3.client("sns").publish(
        TopicArn=sns_topic_arn,
        Subject=f"[{environment.upper()}] DQ Métrica Falha",
        Message=message,
    )
    logger.warning(f"{count} regra(s) falharam para '{table_name}'. Notificação SNS enviada.")
