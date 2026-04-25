"""Funcoes utilitarias compartilhadas pela aplicacao."""

import awswrangler as wr
import pandas as pd


COLUNAS_SOT = [
    "id",
    "title",
    "original_title",
    "overview",
    "release_date",
    "original_language",
    "adult",
    "video",
    "genre_ids",
    "popularity",
    "vote_average",
    "vote_count",
    "year",
    "month",
]

COLUNAS_IDENTIFICACAO_FILME = ["id", "title", "original_title"]


def obter_valor_argumento(argv, arg_name):
    """Le um argumento no formato --ARG_NAME valor."""
    flag = f"--{arg_name}"
    for index, arg in enumerate(argv):
        if arg == flag and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _normalizar_prefixo_s3(prefixo):
    """Garante um prefixo S3 com uma unica barra final."""
    return f"{prefixo.strip('/')}/"


def _garantir_colunas_sot(df):
    """Completa colunas opcionais antes de gravar a tabela curada."""
    for coluna in COLUNAS_SOT:
        if coluna not in df.columns:
            df[coluna] = None

    df_sot = df[COLUNAS_SOT].copy()
    df_sot["year"] = df_sot["year"].astype(str)
    df_sot["month"] = df_sot["month"].astype(str).str.zfill(2)
    return df_sot


def _normalizar_payload_sor(df):
    """Normaliza o payload lido da SOR para linhas de filmes.

    Alguns arquivos JSON mensais podem ser lidos como uma unica coluna
    contendo lista de dicts (um array JSON por arquivo). Nesse caso,
    este metodo explode a lista e converte cada item em uma linha.
    """
    colunas_particao = {"year", "month"}
    colunas_dados = [c for c in df.columns if c not in colunas_particao]

    # Se o dataframe ja possui colunas de filme, nao precisa normalizar.
    if any(coluna in df.columns for coluna in COLUNAS_IDENTIFICACAO_FILME):
        return df

    if len(colunas_dados) != 1:
        return df

    coluna_payload = colunas_dados[0]
    serie_payload = df[coluna_payload]
    if serie_payload.empty:
        return df

    if serie_payload.map(lambda valor: isinstance(valor, list)).any():
        df_expandido = df[["year", "month", coluna_payload]].explode(coluna_payload, ignore_index=True)
        df_expandido = df_expandido[df_expandido[coluna_payload].notna()].reset_index(drop=True)
        if df_expandido.empty:
            return df_expandido

        detalhes = pd.json_normalize(df_expandido[coluna_payload])
        return pd.concat([detalhes, df_expandido[["year", "month"]]], axis=1)

    if serie_payload.map(lambda valor: isinstance(valor, dict)).any():
        detalhes = pd.json_normalize(serie_payload)
        return pd.concat([detalhes, df[["year", "month"]].reset_index(drop=True)], axis=1)

    return df


def _ler_sor_com_fallback_json(wr_module, caminho_origem):
    """Le a SOR priorizando NDJSON e mantendo compatibilidade com JSON legado."""
    try:
        return wr_module.s3.read_json(path=caminho_origem, dataset=True, lines=True)
    except Exception:
        return wr_module.s3.read_json(path=caminho_origem, dataset=True)


def carregar_sor_json_para_tabela_sot(
    s3_bucket_sor,
    s3_bucket_sot,
    catalog_database,
    catalog_table,
    sor_prefix="tmdb/discover_movie/",
    sot_prefix="tmdb/movies_sot/",
    wr_module=None,
):
    """Le JSON da SOR e materializa tabela SOT em Parquet no Glue Catalog."""
    wr_module = wr_module or wr
    sor_prefix_normalizado = _normalizar_prefixo_s3(sor_prefix)
    sot_prefix_normalizado = _normalizar_prefixo_s3(sot_prefix)

    caminho_origem = f"s3://{s3_bucket_sor}/{sor_prefix_normalizado}"
    caminho_destino = f"s3://{s3_bucket_sot}/{sot_prefix_normalizado}"

    df = _ler_sor_com_fallback_json(wr_module, caminho_origem)
    if df.empty:
        return {
            "catalog_database": catalog_database,
            "catalog_table": catalog_table,
            "s3_source": caminho_origem,
            "s3_target": caminho_destino,
            "status": "no_data",
            "total_records": 0,
        }

    if "year" not in df.columns or "month" not in df.columns:
        raise ValueError("Arquivos SOR sem particoes year/month no caminho S3.")

    df = _normalizar_payload_sor(df)

    df_sot = _garantir_colunas_sot(df)

    # Evita criar linhas em branco quando o payload nao foi parseado corretamente.
    if df_sot[COLUNAS_IDENTIFICACAO_FILME].isna().all().all():
        raise ValueError(
            "Payload SOR nao contem colunas de filmes validas apos normalizacao. "
            "Verifique o formato JSON gravado na SOR."
        )

    wr_module.s3.to_parquet(
        df=df_sot,
        path=caminho_destino,
        dataset=True,
        mode="overwrite_partitions",
        compression="snappy",
        partition_cols=["year", "month"],
        database=catalog_database,
        table=catalog_table,
    )

    return {
        "catalog_database": catalog_database,
        "catalog_table": catalog_table,
        "s3_source": caminho_origem,
        "s3_target": caminho_destino,
        "status": "written",
        "total_records": len(df_sot.index),
    }
