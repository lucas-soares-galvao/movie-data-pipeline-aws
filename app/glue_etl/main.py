"""
main.py — Ponto de Entrada do Job Glue ETL

==============================================================================
O QUE ESTE JOB FAZ?
==============================================================================
Este job é a segunda etapa do pipeline: ele pega os dados brutos (JSON)
salvos pela Lambda no bucket SOR e os transforma em dados estruturados
(Parquet) no bucket SOT.

ANALOGIA: Como uma padaria que recebe os ingredientes brutos (farinha, ovos,
leite) e transforma em um produto padronizado (pão fatiado, embalado,
etiquetado). O produto final é uniforme, independente de qual fornecedor
entregou os ingredientes.

FLUXO COMPLETO:
  1. Lê os argumentos do job (passados pela Lambda ao disparar)
  2. Mapeia TABLE_TYPE → como ler e como escrever os dados
  3. Lê os dados JSON do SOR
  4. Escreve em Parquet no SOT, registrando no Glue Catalog
  5. Dispara o job Glue Data Quality para validar os dados
  6. Se for "discover", dispara o job Glue Details para enriquecimento

TIPOS DE TABELA (TABLE_TYPE):
  ┌──────────────────────┬────────────────┬──────────────┬──────────────┐
  │ TABLE_TYPE           │ Particionado?  │ Modo escrita │ Trigger DQ?  │
  ├──────────────────────┼────────────────┼──────────────┼──────────────┤
  │ discover             │ Sim (por year) │ overwrite_   │ Sim          │
  │                      │                │ partitions   │              │
  ├──────────────────────┼────────────────┼──────────────┼──────────────┤
  │ genre                │ Não            │ overwrite    │ Sim          │
  ├──────────────────────┼────────────────┼──────────────┼──────────────┤
  │ configuration        │ Não            │ overwrite    │ Sim          │
  ├──────────────────────┼────────────────┼──────────────┼──────────────┤
  │ watch_providers_ref  │ Não            │ overwrite    │ Sim          │
  └──────────────────────┴────────────────┴──────────────┴──────────────┘

POR QUE "overwrite_partitions" PARA DISCOVER?
O discover é atualizado diariamente para cada ano (2022, 2023, 2024).
Com "overwrite_partitions", ao atualizar o ano 2024, os dados dos anos
2022 e 2023 permanecem intactos no SOT. Se usasse "overwrite" simples,
apagaria TODOS os anos a cada run — seria necessário reprocessar o histórico.
"""

import logging
import sys

from src.utils import (
    get_parameters_glue,
    read_from_sor,
    trigger_data_quality,
    trigger_details,
    write_parquet_to_sot,
)

# Configuração de logging para o Glue (diferente do Lambda — redireciona para stdout)
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger()

# ==============================================================================
# MAPEAMENTO: TABLE_TYPE → comportamento de partição e escrita
# ==============================================================================
# Estes dicionários centralizam a lógica de "como tratar cada tipo de tabela".
# Usar dicts em vez de if/elif múltiplos facilita a adição de novos tipos no futuro.

# "discover" particionado por ["year"] → cria subpastas ano=2024/, ano=2023/, etc.
# Outros tipos: None → sem partição, arquivo único sobrescrito a cada run.
_TABLE_TYPE_TO_PARTITION = {
    "discover":            ["year"],
    "genre":               None,
    "configuration":       None,
    "watch_providers_ref": None,
}

# "overwrite_partitions" → preserva partições não presentes no DataFrame atual.
# "overwrite" → substitui TODA a tabela a cada execução.
_TABLE_TYPE_TO_MODE = {
    "discover":            "overwrite_partitions",
    "genre":               "overwrite",
    "configuration":       "overwrite",
    "watch_providers_ref": "overwrite",
}


def main() -> None:
    """
    Função principal do job Glue ETL.

    Lê argumentos → lê dados do SOR → grava Parquet no SOT → dispara jobs downstream.
    """
    # Lê todos os argumentos passados pelo Lambda ao iniciar este job.
    # Argumentos chegam no formato "--NOME_DO_ARG valor", e get_parameters_glue()
    # os converte para um dicionário Python simples.
    args = get_parameters_glue()

    s3_bucket_sor = args["S3_BUCKET_SOR"]        # Bucket de origem (dados brutos JSON)
    s3_bucket_sot = args["S3_BUCKET_SOT"]        # Bucket de destino (Parquet processado)
    media_type    = args["MEDIA_TYPE"]            # "movie" ou "tv"
    database      = args["DATABASE"]              # Banco no Glue Catalog (ex: "db_movie_tmdb")
    table_type    = args["TABLE_TYPE"]            # Tipo de tabela: genre, discover, etc.
    table_name    = args["TABLE_NAME"]            # Nome da tabela no Catalog
    dq_job_name   = args["GLUE_DATA_QUALITY_JOB_NAME"]  # Job de validação de dados
    details_job_name = args["GLUE_DETAILS_JOB_NAME"]    # Job de enriquecimento (detalhes)
    year          = args.get("YEAR")              # Ano (presente apenas no discover)
    end_year      = args.get("END_YEAR")          # Último ano do ciclo

    # Busca as configurações de partição e modo de escrita para este TABLE_TYPE
    partition_cols = _TABLE_TYPE_TO_PARTITION[table_type]
    mode = _TABLE_TYPE_TO_MODE[table_type]

    logger.info(
        f"Processando table_type={table_type} | media_type={media_type} | year={year}"
    )

    # PASSO 1: Lê os dados do bucket SOR (dispatch por table_type)
    df = read_from_sor(s3_bucket_sor, media_type, table_type, year)

    # PASSO 2: Grava o DataFrame como Parquet no SOT e atualiza o Glue Catalog
    write_parquet_to_sot(
        df=df,
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_name,
        database=database,
        partition_cols=partition_cols,
        mode=mode,
    )

    # PASSO 3: Dispara o job Glue Data Quality para validar a tabela recém-gravada.
    # O DQ roda em paralelo com este job — não esperamos ele terminar.
    trigger_data_quality(
        dq_job_name=dq_job_name,
        table_name=table_name,
        database=database,
        year=year,
    )

    # PASSO 4: Se for "discover", dispara o Glue Details para enriquecimento.
    # O Details vai buscar na API TMDB o runtime (filmes) ou nº de temporadas (séries)
    # para cada ID coletado no discover deste ano.
    # O Details só dispara o AGG no último run (media_type="tv" + year==end_year).
    if table_type == "discover":
        trigger_details(
            details_job_name=details_job_name,
            media_type=media_type,
            year=year,
            end_year=end_year,
            database=database,
        )

    logger.info("Job Glue ETL finalizado com sucesso!")


# Ponto de entrada: o Glue executa o arquivo como script Python standalone.
# "__name__ == '__main__'" garante que main() só seja chamado quando executado
# diretamente (não quando importado em testes).
if __name__ == "__main__":
    main()
