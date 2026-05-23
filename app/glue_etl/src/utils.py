"""Raciocinio: transforma JSON TMDB em Parquet catalogado e aciona Data Quality conforme escopo."""

import awswrangler as wr
import boto3
import pandas as pd
from awsglue.utils import getResolvedOptions


# Argumentos obrigatorios para execucao do Glue ETL.
# Eles definem buckets de origem/destino, tabelas de catalogo e job de DQ a ser disparado.
REQUIRED_ARGS = [
    "S3_BUCKET_SOR",
    "S3_BUCKET_SOT",
    "MEDIA_TYPE",
    "DATABASE",
    "DISCOVER_TABLE",
    "GENRE_TABLE",
    "CONFIGURATION_TABLE",
    "CONFIGURATION",
    "PARTITION_COLUMNS",
    "GLUE_DATA_QUALITY_JOB_NAME"
]

OPTIONAL_ARGS = [
    "TABLE_SCOPE",
    "YEAR"
]


def _resolve_optional_args(argv: list[str], optional_args: list[str]) -> dict[str, str]:
    """Resolve argumentos opcionais sem falhar quando nao forem enviados ao job."""
    resolved: dict[str, str] = {}

    for arg in optional_args:
        option = f"--{arg}"
        if option in argv:
            index = argv.index(option)
            if index + 1 < len(argv):
                resolved[arg] = argv[index + 1]

    return resolved


def resolve_args(argv: list[str]) -> dict[str, str]:
    """Resolve argumentos Glue combinando obrigatorios e opcionais."""
    args = getResolvedOptions(argv, REQUIRED_ARGS)
    args.update(_resolve_optional_args(argv, OPTIONAL_ARGS))
    return args


# Mapeamento declarativo de tabelas por tipo de midia.
# Isso evita if/else espalhado no fluxo principal do ETL.
TABLES_BY_MEDIA = {
    "movie": [
        {"path": "discover", "table_arg": "DISCOVER_TABLE", "date_column": "release_date"},
        {"path": "genre", "table_arg": "GENRE_TABLE", "date_column": None},
        {"path": "configuration", "table_arg": "CONFIGURATION_TABLE", "date_column": None}
    ],
    "tv": [
        {"path": "discover", "table_arg": "DISCOVER_TABLE", "date_column": "first_air_date"},
        {"path": "genre", "table_arg": "GENRE_TABLE", "date_column": None},
        {"path": "configuration", "table_arg": "CONFIGURATION_TABLE", "date_column": None}
    ]
}

TABLE_SCOPE_ALL = "all"
TABLE_SCOPE_DISCOVER = "discover"
TABLE_SCOPE_STATIC = "static"


def _add_temporal_partition_columns(df: pd.DataFrame, date_column: str) -> pd.DataFrame:
    """Deriva ano/mes da coluna de data para escrita particionada."""
    df[date_column] = pd.to_datetime(df[date_column], errors="coerce")
    df["year"] = df[date_column].dt.year.astype("Int64").astype(str)
    df["month"] = df[date_column].dt.strftime("%m")
    return df


def _build_partition_values(df: pd.DataFrame, partition_columns: list[str] | None) -> list[str]:
    """Monta paths de particao no formato coluna=valor para uso posterior no Glue DQ."""
    if not partition_columns:
        return []

    partition_values = []
    unique_partitions = df[partition_columns].drop_duplicates()
    for _, row in unique_partitions.iterrows():
        part_str = "/".join(f"{col}={row[col]}" for col in partition_columns)
        partition_values.append(part_str)
    return partition_values


def _is_temporal_partition(partition_columns: list[str] | None, date_column: str | None) -> bool:
    """Define se o dataset deve receber particionamento temporal (ano/mes)."""
    return bool(date_column) and bool(partition_columns)


def process_tmdb(
    source_path: str,
    destination_path: str,
    database: str,
    table: str,
    partition_columns: list[str] | None = None,
    date_column: str | None = None,
) -> dict:
    """Le JSON da TMDB no S3, transforma quando necessario e grava Parquet no S3."""
    # Etapa 1: leitura do dado bruto no SOR.
    df = wr.s3.read_json(source_path)
    # Etapa 2: escolhe estrategia de escrita conforme existe (ou nao) particionamento.
    mode = "overwrite_partitions" if partition_columns else "overwrite"

    if _is_temporal_partition(partition_columns, date_column):
        # Para tabelas temporais, materializa year/month a partir da data de referencia.
        df = _add_temporal_partition_columns(df, date_column)

    # Etapa 3: persistencia em Parquet com registro no Glue Catalog.
    wr.s3.to_parquet(
        df=df,
        path=destination_path,
        dataset=True,
        partition_cols=partition_columns if partition_columns else [],
        database=database,
        table=table,
        mode=mode
    )

    partition_values = _build_partition_values(df, partition_columns)

    return {
        "partitions": partition_values
    }

def call_glue_data_quality(
    job_name: str,
    database: str,
    table: str,
    partition_values: list[str] | None = None,
) -> dict:
    """Dispara o job de Glue Data Quality para uma tabela do Catalog."""
    # Dispara DQ de forma assincrona e retorna identificadores para rastreio.
    glue = boto3.client("glue")

    arguments = {
        "--DATABASE": database,
        "--TABLE": table
    }
    if partition_values:
        arguments["--PARTITION_VALUES"] = ",".join(partition_values)

    response = glue.start_job_run(
        JobName=job_name,
        Arguments=arguments
    )

    return {
        "job_name": job_name,
        "job_run_id": response["JobRunId"]
    }


def build_tables_config(media_type: str, args: dict) -> list[dict]:
    """Monta a configuracao ETL por tabela conforme o tipo de midia."""
    configs = TABLES_BY_MEDIA.get(media_type)
    if configs is None:
        raise ValueError(f"Unsupported MEDIA_TYPE: {media_type}")

    return [
        {
            "path": cfg["path"],
            "table": args[cfg["table_arg"]],
            "date_column": cfg["date_column"]
        }
        for cfg in configs
    ]


def build_source_path(
    bucket_sor: str,
    table_path: str,
    media_type: str,
    configuration: str,
    year: str | None = None,
) -> str:
    """Monta o caminho de origem no S3 para extracao da tabela."""
    if table_path == "configuration":
        return f"s3://{bucket_sor}/tmdb/{table_path}/{configuration}/"
    if table_path == "discover" and year:
        return f"s3://{bucket_sor}/tmdb/{table_path}/{media_type}/year={year}/"
    return f"s3://{bucket_sor}/tmdb/{table_path}/{media_type}/"


def build_partition_columns(partition_columns: str, date_column: str | None) -> list[str]:
    """Retorna colunas de particionamento apenas para datasets temporais do discover."""
    if not partition_columns or not date_column:
        return []
    return [column.strip() for column in partition_columns.split(",") if column.strip()]


def filter_tables_config(configs: list[dict], table_scope: str) -> list[dict]:
    """Filtra as tabelas do ETL conforme o escopo de execucao solicitado."""
    if table_scope == TABLE_SCOPE_DISCOVER:
        return [cfg for cfg in configs if cfg["path"] == "discover"]
    if table_scope == TABLE_SCOPE_STATIC:
        return [cfg for cfg in configs if cfg["path"] != "discover"]
    return configs


def resolve_dq_partition_values(
    table_path: str,
    partition_columns_list: list[str],
    year: str | None,
) -> list[str] | None:
    """Define quais valores de particao serao enviados ao job de Data Quality."""
    if not partition_columns_list:
        return None
    if year and table_path == "discover":
        return [f"year={year}"]
    return None


