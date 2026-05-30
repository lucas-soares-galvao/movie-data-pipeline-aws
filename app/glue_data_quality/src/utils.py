"""
utils.py — Funções auxiliares do job Glue Data Quality.

Aqui ficam as funções que realizam tarefas específicas:
  - Ler argumentos opcionais do job
  - Ler dados da tabela SOT (Parquet)
  - Avaliar as regras de qualidade (DQDL simplificado)
  - Salvar os resultados no bucket de Data Quality

As regras suportadas são:
  IsComplete "coluna"               → verifica se não há valores nulos
  IsUnique "coluna"                 → verifica se não há valores duplicados
  ColumnValues "coluna" between X and Y → verifica se os valores estão no intervalo
  RowCount > N                      → verifica se a tabela tem mais de N linhas
"""

import logging
import sys
from datetime import datetime
from typing import List, Optional

import awswrangler as wr
import pandas as pd

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Utilitários gerais
# ---------------------------------------------------------------------------

def get_optional_arg(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Lê um argumento opcional de sys.argv sem lançar erro se estiver ausente.

    Args:
        name:    Nome do argumento (sem o prefixo "--").
        default: Valor retornado caso o argumento não seja encontrado.

    Returns:
        O valor do argumento como string, ou `default` se não encontrado.
    """
    for i, token in enumerate(sys.argv):
        if token == f"--{name}" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if token.startswith(f"--{name}="):
            return token.split("=", 1)[1]
    return default


# ---------------------------------------------------------------------------
# Leitura dos dados da camada SOT
# ---------------------------------------------------------------------------

def read_table_from_sot(
    s3_bucket_sot: str,
    table_name: str,
    year: Optional[str] = None,
) -> pd.DataFrame:
    """
    Lê os dados de uma tabela no bucket SOT (formato Parquet).

    Para tabelas de discover (particionadas por ano), é possível
    informar o ano para ler apenas a partição correspondente, evitando
    que todos os dados históricos sejam carregados desnecessariamente.

    Args:
        s3_bucket_sot: Nome do bucket SOT.
        table_name:    Nome da tabela (usado como subpasta dentro do bucket).
        year:          Ano da partição a ser lida. Se None, lê todos os dados.

    Returns:
        DataFrame com os dados da tabela (ou partição).
    """
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"

    if year is not None:
        # Lê apenas a partição do ano informado, muito mais eficiente
        # do que carregar todos os anos
        logger.info("Lendo s3_path=%s | filtro year=%s", s3_path, year)
        df = wr.s3.read_parquet(
            path=s3_path,
            dataset=True,
            partition_filter=lambda x: x.get("year") == year,
        )
    else:
        logger.info("Lendo todos os dados de s3_path=%s", s3_path)
        df = wr.s3.read_parquet(path=s3_path, dataset=True)

    logger.info("Lidos %d registros da tabela '%s'.", len(df), table_name)
    return df


# ---------------------------------------------------------------------------
# Avaliação das regras de qualidade
# ---------------------------------------------------------------------------

def evaluate_rules(
    df: pd.DataFrame,
    rules: List[str],
    database: str,
    table_name: str,
    year: Optional[str] = None,
) -> List[dict]:
    """
    Avalia cada regra da lista e retorna um resultado por regra.

    As regras seguem a sintaxe DQDL simplificada:
      IsComplete "coluna"
      IsUnique "coluna"
      ColumnValues "coluna" between X and Y
      RowCount > N

    Args:
        df:         DataFrame com os dados a validar.
        rules:      Lista de regras DQDL (strings).
        database:   Banco de dados no Glue Catalog (para registro no resultado).
        table_name: Nome da tabela (para registro no resultado).
        year:       Ano da partição (para registro no resultado; pode ser None).

    Returns:
        Lista de dicionários, um por regra, com os campos:
          - rule            : texto da regra avaliada
          - outcome         : "PASS" ou "FAIL"
          - failure_reason  : descrição do motivo da falha (None se PASS)
          - partition       : valor do ano ou "sem particao"
          - datetime_process: momento da avaliação
          - source_database : banco de dados avaliado
    """
    results = []
    now = datetime.utcnow()
    partition_label = year if year is not None else "sem particao"

    for rule in rules:
        rule = rule.strip()
        outcome = "PASS"
        failure_reason = None

        try:
            if rule.startswith("IsComplete"):
                # Verifica se há valores nulos na coluna informada
                col = _extract_column_name(rule)
                null_count = int(df[col].isna().sum())
                if null_count > 0:
                    outcome = "FAIL"
                    failure_reason = f"{null_count} valores nulos na coluna '{col}'"

            elif rule.startswith("IsUnique"):
                # Verifica se há valores duplicados na coluna informada
                col = _extract_column_name(rule)
                dup_count = int(df[col].duplicated().sum())
                if dup_count > 0:
                    outcome = "FAIL"
                    failure_reason = f"{dup_count} valores duplicados na coluna '{col}'"

            elif rule.startswith("RowCount"):
                # Exemplo: "RowCount > 0"
                # Verifica se o total de linhas satisfaz a condição
                parts = rule.split()  # ["RowCount", ">", "0"]
                operator = parts[1]
                threshold = int(parts[2])
                row_count = len(df)
                if operator == ">" and not (row_count > threshold):
                    outcome = "FAIL"
                    failure_reason = f"RowCount={row_count} não satisfaz RowCount > {threshold}"

            elif rule.startswith("ColumnValues"):
                # Exemplo: 'ColumnValues "vote_average" between 0 and 10'
                # Verifica se todos os valores estão no intervalo [min, max]
                col = _extract_column_name(rule)
                between_part = rule.split("between")[1].strip()  # "0 and 10"
                low_str, high_str = between_part.split("and")
                low = float(low_str.strip())
                high = float(high_str.strip())
                out_of_range = int(((df[col] < low) | (df[col] > high)).sum())
                if out_of_range > 0:
                    outcome = "FAIL"
                    failure_reason = (
                        f"{out_of_range} valores fora do intervalo "
                        f"[{low}, {high}] na coluna '{col}'"
                    )

            else:
                # Regra não reconhecida — registra como FAIL para forçar revisão
                outcome = "FAIL"
                failure_reason = f"Regra não reconhecida: '{rule}'"

        except Exception as exc:
            # Se ocorrer qualquer erro ao avaliar a regra, registra como FAIL
            outcome = "FAIL"
            failure_reason = f"Erro ao avaliar regra: {exc}"
            logger.error("Erro ao avaliar regra '%s': %s", rule, exc)

        result = {
            "rule": rule,
            "outcome": outcome,
            "failure_reason": failure_reason,
            "partition": partition_label,
            "datetime_process": now,
            "source_database": database,
        }
        results.append(result)

        logger.info("[%s] %s | motivo: %s", outcome, rule, failure_reason)

    return results


def _extract_column_name(rule: str) -> str:
    """
    Extrai o nome da coluna de uma regra DQDL.

    O nome da coluna está entre aspas duplas na regra.
    Ex.: 'IsComplete "vote_average"' → 'vote_average'

    Args:
        rule: String com a regra DQDL.

    Returns:
        Nome da coluna como string.
    """
    start = rule.index('"') + 1
    end = rule.index('"', start)
    return rule[start:end]


# ---------------------------------------------------------------------------
# Gravação dos resultados de qualidade
# ---------------------------------------------------------------------------

def save_dq_results(
    results: List[dict],
    s3_bucket_data_quality: str,
    table_name: str,
) -> None:
    """
    Salva os resultados da avaliação de qualidade como Parquet no bucket
    de Data Quality, particionado por nome da tabela de origem.

    O caminho de destino segue o padrão:
      s3://{bucket}/tmdb/tb_data_quality_tmdb/source_table={table_name}/

    Args:
        results:                Lista de resultados retornada por evaluate_rules().
        s3_bucket_data_quality: Nome do bucket de Data Quality.
        table_name:             Nome da tabela avaliada (usada como partição).
    """
    df_results = pd.DataFrame(results)

    # Adiciona a coluna de partição com o nome da tabela de origem
    df_results["source_table"] = table_name

    s3_path = f"s3://{s3_bucket_data_quality}/tmdb/tb_data_quality_tmdb/"

    logger.info(
        "Salvando %d resultados de DQ em %s | partição source_table=%s",
        len(df_results), s3_path, table_name,
    )

    # overwrite_partitions: substitui apenas os resultados desta tabela,
    # preservando resultados de outras tabelas já gravados
    wr.s3.to_parquet(
        df=df_results,
        path=s3_path,
        dataset=True,
        partition_cols=["source_table"],
        mode="overwrite_partitions",
    )

    logger.info("Resultados de DQ para '%s' salvos com sucesso!", table_name)
