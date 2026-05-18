"""Raciocinio: entrypoint do Glue ETL; resolve argumentos, executa transformacoes e aciona Data Quality."""

import sys

from src.utils import (
    TABLE_SCOPE_ALL,
    build_partition_columns,
    build_source_path,
    build_tables_config,
    call_glue_data_quality,
    filter_tables_config,
    process_tmdb,
    resolve_args,
    resolve_dq_partition_values,
)


def main(argv: list[str] | None = None) -> None:
    """Executa o job ETL e delega o processamento para a camada de utilitarios.

    Raciocinio do fluxo:
    1) resolve obrigatorios e opcionais sem quebrar execucoes parciais;
    2) aplica o pipeline por tabela (discover/genre/configuration) com regras de escopo;
    3) dispara Data Quality por tabela para manter validacao desacoplada do ETL.
    """
    argv = argv or sys.argv
    args = resolve_args(argv)

    # Parametros base de infraestrutura e catalogo usados em todas as tabelas processadas.
    bucket_sor = args["S3_BUCKET_SOR"]
    bucket_sot = args["S3_BUCKET_SOT"]
    media_type = args["MEDIA_TYPE"]
    database = args["DATABASE"]
    configuration = args["CONFIGURATION"]
    partition_columns = args.get("PARTITION_COLUMNS", "")
    glue_data_quality_job_name = args["GLUE_DATA_QUALITY_JOB_NAME"]
    year = args.get("YEAR")
    table_scope = args.get("TABLE_SCOPE", TABLE_SCOPE_ALL)

    # Define quais tabelas entram no ciclo conforme tipo de midia e escopo solicitado.
    table_configs = filter_tables_config(build_tables_config(media_type, args), table_scope)

    for cfg in table_configs:
        # Cada iteracao representa um dataset independente no lake (tabela de destino).
        table = cfg["table"]
        date_column = cfg["date_column"]
        partition_columns_list = build_partition_columns(partition_columns, date_column)
        source_year = year if table_scope == "discover" and cfg["path"] == "discover" else None

        # Le JSON bruto no SOR e escreve Parquet no SOT com metadados de catalogo.
        result = process_tmdb(
            source_path=build_source_path(bucket_sor, cfg["path"], media_type, configuration, year=source_year),
            destination_path=f"s3://{bucket_sot}/tmdb/{table}/",
            database=database,
            table=table,
            partition_columns=partition_columns_list,
            date_column=date_column,
        )

        partitions = result.get("partitions", [])
        print(f"Processed table={table}, partitions={partitions}")

        # Envia recorte de particao apenas quando fizer sentido (discover por ano).
        dq_partition_values = resolve_dq_partition_values(
            table_path=cfg["path"],
            partition_columns_list=partition_columns_list,
            year=year,
        )
        # Dispara o job de Data Quality por tabela para rastrear qualidade por dominio.
        call_glue_data_quality(
            glue_data_quality_job_name,
            database=database,
            table=table,
            partition_values=dq_partition_values,
        )

    print("TMDB ETL executed successfully!")


if __name__ == "__main__":
    main()
