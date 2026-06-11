"""
main.py — Ponto de entrada do job Glue AGG.

==============================================================================
O QUE É O GLUE AGG?
==============================================================================
AGG = Aggregation (Agregação). Este job é o último passo do processamento de
dados antes do produto final ser consumido pelo app de recomendações.

POSIÇÃO NO PIPELINE:
  Lambda → Glue ETL → Glue Details → [GLUE AGG] → app Streamlit
                                          ↑
                               Só roda depois que todos os jobs
                               de Details terminaram (tv + end_year)

O QUE ELE PRODUZ?
  A tabela "tb_discover_unified_tmdb" na camada SPEC (Gold layer):
  - Filmes E séries numa única tabela
  - Com gêneros em texto legível (não IDs numéricos)
  - Com URLs completas das imagens (poster e backdrop)
  - Com nome do idioma original e do país de origem
  - Com duração (filmes) ou temporadas/episódios (séries)
  - Com plataformas de streaming disponíveis no Brasil
  - Com títulos e sinopses em português (traduzidos do inglês quando necessário)

ANALOGIA: Como a "lista consolidada" que um gerente prepara juntando relatórios
  de vários departamentos, traduzindo os jargões técnicos para linguagem do
  cliente e entregando um único documento fácil de consultar.

FLUXO DO JOB:
  1. Lê os argumentos (nomes dos bancos de dados e tabela de destino)
  2. Executa a query SQL no Athena (une filmes + séries + gêneros + detalhes + streaming)
  3. Traduz títulos e sinopses em inglês para português
  4. Salva como Parquet particionado por (media_type, year) no bucket SPEC

O AWS Wrangler registra/atualiza a tabela no Glue Catalog automaticamente
ao gravar no SPEC, dispensando definição manual da tabela no Catalog.
"""

import logging
import sys

from src.utils import (
    get_parameters_glue,
    run_athena_query,
    traduzir_colunas_en,
    write_parquet_to_spec,
)

# Configuração de logging: redireciona para stdout para que o Glue capture nos logs do job
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger()


def main() -> None:
    """Executa o pipeline de agregação: query Athena → tradução → escrita no SPEC."""
    # Lê os parâmetros passados pelo Glue ao iniciar o job
    args = get_parameters_glue()

    s3_bucket_spec = args["S3_BUCKET_SPEC"]   # bucket SPEC (Gold layer) — destino final
    s3_bucket_temp = args["S3_BUCKET_TEMP"]   # bucket temporário para resultados do Athena
    db_movie   = args["DB_MOVIE"]    # banco de dados de filmes no Glue Catalog
    db_tv      = args["DB_TV"]       # banco de dados de séries no Glue Catalog
    db_unified = args["DB_UNIFIED"]  # banco unificado (onde a tabela SPEC será registrada)
    table_name = args["TABLE_NAME"]  # nome da tabela de destino (ex: "tb_discover_unified_tmdb")

    logger.info(
        f"Iniciando Glue AGG | tabela destino: '{table_name}' | db_unified='{db_unified}'"
    )

    # PASSO 1: Executa a query de unificação no Athena.
    # A query une filmes + séries + gêneros + idiomas + países + detalhes + streaming.
    # Retorna um Pandas DataFrame com todos os dados prontos para a camada SPEC.
    df = run_athena_query(
        db_movie=db_movie,
        db_tv=db_tv,
        db_unified=db_unified,
        s3_bucket_temp=s3_bucket_temp,
    )

    # PASSO 2: Traduz title e overview para português para títulos com original_language='en'.
    # O TMDB retorna title/overview em inglês para filmes americanos/britânicos.
    # A tradução acontece aqui (offline) e não no app, para o Streamlit ser rápido.
    df = traduzir_colunas_en(df)

    # PASSO 3: Salva o DataFrame como Parquet no bucket SPEC.
    # Particionado por (media_type, year) → permite filtrar no Athena por tipo e ano.
    # O AWS Wrangler atualiza o Glue Catalog automaticamente — sem MSCK REPAIR TABLE.
    write_parquet_to_spec(
        df=df,
        s3_bucket_spec=s3_bucket_spec,
        table_name=table_name,
        database=db_unified,
    )

    logger.info("Job Glue AGG finalizado com sucesso!")


# Ponto de entrada: o Glue executa este arquivo como script Python standalone.
# "__name__ == '__main__'" garante que main() só seja chamado quando executado diretamente.
if __name__ == "__main__":
    main()
