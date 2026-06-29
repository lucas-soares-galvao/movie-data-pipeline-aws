"""utils.py — Funções auxiliares do job Glue Details."""

import logging
import sys
import threading
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import awswrangler as wr
import pandas as pd
import requests
from awsglue.utils import getResolvedOptions
from deep_translator import GoogleTranslator

# noqa: F401 = diz ao linter para ignorar "import não usado" — esses imports são
# re-exportados para que main.py os importe diretamente de src.utils.
from shared_utils.api_client import get_api_secret, api_get as tmdb_get  # noqa: F401
from shared_utils.triggers import trigger_glue_job  # noqa: F401

logger = logging.getLogger()

TMDB_BASE_URL = "https://api.themoviedb.org/3"


def get_resolved_option(args: list) -> Dict[str, Any]:
    """Wrapper de getResolvedOptions — converte lista de nomes em dicionário nome→valor."""
    return getResolvedOptions(sys.argv, args)


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos obrigatórios do job Glue Details.

    Returns:
        Dicionário com todos os argumentos resolvidos.
    """
    required_args = [
        "S3_BUCKET_SOT",
        "S3_BUCKET_TEMP",
        "DATABASE",
        "TABLE_DISCOVER_MOVIE",
        "TABLE_DISCOVER_TV",
        "TABLE_DETAILS_MOVIE",
        "TABLE_DETAILS_TV",
        "TABLE_WATCH_PROVIDERS_MOVIE",
        "TABLE_WATCH_PROVIDERS_TV",
        "TMDB_SECRET_ARN",
        "GLUE_AGG_JOB_NAME",
        "GLUE_DATA_QUALITY_JOB_NAME",
        "MEDIA_TYPE",
        "YEAR",
        "END_YEAR",
    ]
    params = get_resolved_option(required_args)

    # Opcional: quando True, ignora o delta mensal e re-busca todos os IDs na API.
    # Não faz parte dos required_args para manter compatibilidade com runs normais.
    params["FORCE_REFETCH"] = False
    for i, arg in enumerate(sys.argv):
        if arg == "--FORCE_REFETCH" and i + 1 < len(sys.argv):
            params["FORCE_REFETCH"] = sys.argv[i + 1].lower() == "true"
            break

    return params


def fetch_ids_from_sot(
    database: str,
    table_discover: str,
    s3_bucket_temp: str,
    year: str,
) -> List[int]:
    """
    Busca IDs distintos da tabela de discover no SOT via Athena, filtrados pelo ano.

    Usa o SOT (não o SOR) porque os IDs já foram deduplicados pelo Glue ETL.

    Args:
        database:       Nome do banco de dados no Glue Catalog.
        table_discover: Nome da tabela de discover (movie ou tv).
        s3_bucket_temp: Bucket S3 para os resultados temporários do Athena.
        year:           Ano a processar (string, ex: "2025").

    Returns:
        Lista de IDs inteiros únicos.
    """
    s3_output = f"s3://{s3_bucket_temp}/tmdb/athena/glue_details/"
    # DISTINCT evita buscar detalhes do mesmo ID mais de uma vez
    # WHERE year filtra apenas a partição do ano atual (não processa anos passados novamente)
    query = f"SELECT DISTINCT id FROM {database}.{table_discover} WHERE year = '{year}'"

    logger.info(f"Buscando IDs em '{table_discover}' para year={year}...")
    df = wr.athena.read_sql_query(
        sql=query,
        database=database,
        s3_output=s3_output,
        ctas_approach=False,  # False = query direta (mais simples, sem criar tabela temporária no S3)
    )

    ids = df["id"].astype(int).tolist()
    logger.info(f"IDs encontrados: {len(ids)}.")
    return ids


def fetch_existing_ids_from_details(
    database: str,
    table_details: str,
    s3_bucket_temp: str,
) -> List[int]:
    """
    Retorna IDs já presentes na tabela de detalhes em qualquer partição year.

    Usado para calcular o delta: apenas IDs ausentes precisam ser buscados na API.
    Um ID processado em QUALQUER partição year neste mês é considerado existente —
    evita re-buscar IDs cujo release_date pertence a um year diferente do discover year,
    o que causaria escritas concorrentes na mesma partição S3.
    Retorna lista vazia se a tabela não existir ainda (primeira execução).

    Args:
        database:       Nome do banco de dados no Glue Catalog.
        table_details:  Nome da tabela de detalhes (movie ou tv).
        s3_bucket_temp: Bucket S3 para resultados temporários do Athena.

    Returns:
        Lista de IDs inteiros já processados este mês (qualquer partição year).
    """
    s3_output = f"s3://{s3_bucket_temp}/tmdb/athena/glue_details/"
    # Considera "existente" qualquer ID processado este mês, independente da partição year.
    # IDs de meses anteriores são stale e voltam para re-fetch no dia 1.
    query = (
        f"SELECT DISTINCT id FROM {database}.{table_details} "
        f"WHERE dt_processamento >= date_trunc('month', current_date)"
    )

    logger.info(f"Verificando IDs já processados em '{table_details}' (mês atual, todas as partições year)...")
    try:
        df = wr.athena.read_sql_query(
            sql=query,
            database=database,
            s3_output=s3_output,
            ctas_approach=False,
        )
        ids = df["id"].astype(int).tolist()
        logger.info(f"IDs já em details (mês atual, todas as partições): {len(ids)}.")
        return ids
    except Exception as exc:
        logger.warning(
            f"Não foi possível consultar '{table_details}' "
            f"(tabela pode não existir ainda): {exc}"
        )
        return []


def fetch_ids_stale_watch_providers(
    database: str,
    table_discover: str,
    table_watch_providers: str,
    s3_bucket_temp: str,
    year: str,
) -> List[int]:
    """
    Retorna IDs do discover que precisam de atualização de watch providers.

    Inclui: sem registro, com dt_atualizacao nulo (migração) ou desatualizado antes do mês atual.

    Args:
        database:              Nome do banco de dados no Glue Catalog.
        table_discover:        Nome da tabela de discover.
        table_watch_providers: Nome da tabela de watch providers.
        s3_bucket_temp:        Bucket S3 para resultados temporários do Athena.
        year:                  Ano a verificar.

    Returns:
        Lista de IDs inteiros a atualizar.
    """
    s3_output = f"s3://{s3_bucket_temp}/tmdb/athena/glue_details/"
    query = f"""
        SELECT DISTINCT d.id
        FROM {database}.{table_discover} d
        LEFT JOIN {database}.{table_watch_providers} wp
            ON d.id = wp.id AND wp.year = '{year}'
        WHERE d.year = '{year}'
          AND (
              wp.id IS NULL
              OR wp.dt_atualizacao IS NULL
              OR wp.dt_atualizacao < date_trunc('month', current_date)
          )
    """

    logger.info(
        f"Identificando IDs com watch providers ausentes/desatualizados "
        f"em '{table_watch_providers}' para year={year}..."
    )
    try:
        df = wr.athena.read_sql_query(
            sql=query,
            database=database,
            s3_output=s3_output,
            ctas_approach=False,
        )
        ids = df["id"].astype(int).tolist()
        logger.info(f"IDs para atualizar watch providers: {len(ids)}.")
        return ids
    except Exception as exc:
        logger.warning(f"Erro ao consultar watch providers desatualizados: {exc}")
        return []


def fetch_tmdb_details(api_key: str, content_type: str, item_id: int) -> dict:
    """
    Busca os detalhes de um filme ou série pelo ID na API do TMDB.

    Args:
        api_key:      Chave de API do TMDB.
        content_type: "movie" ou "tv".
        item_id:      ID do filme ou série no TMDB.

    Returns:
        Dicionário com os campos retornados pela API.
    """
    endpoint = "movie" if content_type == "movie" else "tv"
    url = f"{TMDB_BASE_URL}/{endpoint}/{item_id}"

    if content_type == "movie":
        append = "credits,keywords,release_dates,videos,external_ids,recommendations,similar,alternative_titles"
    else:
        append = "credits,keywords,content_ratings,videos,external_ids,recommendations,similar,alternative_titles"

    params = {
        "api_key": api_key,
        "language": "en-US",
        "append_to_response": append,
    }

    return tmdb_get(url, params)


_TMDB_MAX_WORKERS = 20      # ~20 req/s concorrentes — bem abaixo do rate limit de ~40 req/s do TMDB
_TRANSLATE_MAX_WORKERS = 10  # traduções EN→PT paralelas via Google Translate


def _extrair_elenco(creditos: dict, limite: int = 5) -> Optional[str]:
    """Top N atores por ordem de billing, separados por vírgula."""
    cast = creditos.get("cast", [])
    nomes = [c["name"] for c in sorted(cast, key=lambda x: x.get("order", 999))[:limite]]
    return ", ".join(nomes) if nomes else None


def _extrair_diretor(creditos: dict) -> Optional[str]:
    """Diretor(es) do filme/série (job == 'Director' no crew)."""
    crew = creditos.get("crew", [])
    diretores = [c["name"] for c in crew if c.get("job") == "Director"]
    return ", ".join(diretores) if diretores else None


def _extrair_roteiristas(creditos: dict) -> Optional[str]:
    """Roteiristas (job in Screenplay/Writer no crew), deduplicados."""
    crew = creditos.get("crew", [])
    nomes: list[str] = []
    vistos: set[str] = set()
    for c in crew:
        if c.get("job") in ("Screenplay", "Writer") and c.get("name"):
            nome = c["name"]
            if nome not in vistos:
                vistos.add(nome)
                nomes.append(nome)
    return ", ".join(nomes) if nomes else None


def _extrair_compositor(creditos: dict) -> Optional[str]:
    """Compositor(es) da trilha sonora (job == 'Original Music Composer')."""
    crew = creditos.get("crew", [])
    compositores = [c["name"] for c in crew if c.get("job") == "Original Music Composer"]
    return ", ".join(compositores) if compositores else None


def _extrair_keywords(dados_keywords: dict) -> Optional[str]:
    """Keywords como string separada por vírgula."""
    kws = dados_keywords.get("keywords") or dados_keywords.get("results") or []
    nomes = [kw["name"] for kw in kws if kw.get("name")]
    return ", ".join(nomes) if nomes else None


def _extrair_certificacao_br_movie(release_dates: dict) -> Optional[str]:
    """Extrai classificação indicativa BR do endpoint release_dates (filmes)."""
    for entry in release_dates.get("results", []):
        if entry.get("iso_3166_1") == "BR":
            for rd in entry.get("release_dates", []):
                cert = rd.get("certification")
                if cert:
                    return cert
    return None


def _extrair_certificacao_br_tv(content_ratings: dict) -> Optional[str]:
    """Extrai classificação indicativa BR do endpoint content_ratings (TV)."""
    for entry in content_ratings.get("results", []):
        if entry.get("iso_3166_1") == "BR":
            return entry.get("rating") or None
    return None


def _extrair_trailer_url(videos: dict) -> Optional[str]:
    """Primeiro trailer oficial do YouTube, com fallback para não-oficial."""
    for v in videos.get("results", []):
        if (v.get("type") == "Trailer"
                and v.get("site") == "YouTube"
                and v.get("official", False)):
            return f"https://youtube.com/watch?v={v['key']}"
    for v in videos.get("results", []):
        if v.get("type") == "Trailer" and v.get("site") == "YouTube":
            return f"https://youtube.com/watch?v={v['key']}"
    return None


def _extrair_produtoras(companies: list) -> Optional[str]:
    """Nomes das produtoras, separados por vírgula."""
    nomes = [c["name"] for c in (companies or []) if c.get("name")]
    return ", ".join(nomes) if nomes else None


def _extrair_criadores(created_by: list) -> Optional[str]:
    """Criadores de série, separados por vírgula."""
    nomes = [c["name"] for c in (created_by or []) if c.get("name")]
    return ", ".join(nomes) if nomes else None


def _extrair_networks(networks: list) -> Optional[str]:
    """Redes de TV, separadas por vírgula."""
    nomes = [n["name"] for n in (networks or []) if n.get("name")]
    return ", ".join(nomes) if nomes else None


def _extrair_spoken_languages(spoken_languages: list) -> Optional[str]:
    """Idiomas falados, separados por vírgula."""
    nomes = [sl.get("english_name") or sl.get("name", "") for sl in (spoken_languages or [])]
    nomes = [n for n in nomes if n]
    return ", ".join(nomes) if nomes else None


def _extrair_produtores(creditos: dict, limite: int = 3) -> Optional[str]:
    """Produtor(es) e produtores executivos, deduplicados, limitados a top N."""
    crew = creditos.get("crew", [])
    nomes: list[str] = []
    vistos: set[str] = set()
    for c in crew:
        if c.get("job") in ("Producer", "Executive Producer") and c.get("name"):
            nome = c["name"]
            if nome not in vistos:
                vistos.add(nome)
                nomes.append(nome)
            if len(nomes) >= limite:
                break
    return ", ".join(nomes) if nomes else None


def _extrair_cinematografo(creditos: dict) -> Optional[str]:
    """Diretor(es) de fotografia (job == 'Director of Photography' no crew)."""
    crew = creditos.get("crew", [])
    nomes = [c["name"] for c in crew if c.get("job") == "Director of Photography"]
    return ", ".join(nomes) if nomes else None


def _extrair_montador(creditos: dict) -> Optional[str]:
    """Montador(es) do filme/série (job == 'Editor' no crew)."""
    crew = creditos.get("crew", [])
    nomes = [c["name"] for c in crew if c.get("job") == "Editor"]
    return ", ".join(nomes) if nomes else None


def _extrair_paises_producao(production_countries: list) -> Optional[str]:
    """Países de produção, separados por vírgula."""
    nomes = [c.get("name", "") for c in (production_countries or []) if c.get("name")]
    return ", ".join(nomes) if nomes else None


def _extrair_titulos_recomendados(recommendations: dict, content_type: str, limite: int = 10) -> Optional[str]:
    """Top N títulos recomendados pelo TMDB, separados por vírgula."""
    results = recommendations.get("results", [])
    campo = "title" if content_type == "movie" else "name"
    nomes = [r[campo] for r in results[:limite] if r.get(campo)]
    return ", ".join(nomes) if nomes else None


def _extrair_titulos_similares(similar: dict, content_type: str, limite: int = 10) -> Optional[str]:
    """Top N títulos similares pelo TMDB, separados por vírgula."""
    results = similar.get("results", [])
    campo = "title" if content_type == "movie" else "name"
    nomes = [r[campo] for r in results[:limite] if r.get(campo)]
    return ", ".join(nomes) if nomes else None


def _extrair_titulos_alternativos(alternative_titles: dict, content_type: str) -> Optional[str]:
    """Títulos alternativos/regionais, separados por vírgula."""
    campo_lista = "titles" if content_type == "movie" else "results"
    titulos = alternative_titles.get(campo_lista, [])
    nomes = [t["title"] for t in titulos if t.get("title")]
    return ", ".join(nomes) if nomes else None


def _parse_detail(detalhe: dict, content_type: str) -> Optional[dict]:
    """Extrai os campos relevantes da resposta de /movie/{id} ou /tv/{id}."""
    creditos = detalhe.get("credits", {})
    keywords_data = detalhe.get("keywords", {})
    videos_data = detalhe.get("videos", {})
    external_ids = detalhe.get("external_ids", {})
    recommendations_data = detalhe.get("recommendations", {})
    similar_data = detalhe.get("similar", {})
    alt_titles_data = detalhe.get("alternative_titles", {})

    if content_type == "movie":
        release_date = detalhe.get("release_date") or ""
        year = release_date[:4] if release_date else None
        collection = detalhe.get("belongs_to_collection")
        return {
            "id":                    detalhe.get("id"),
            "runtime":               detalhe.get("runtime"),
            "overview_en":           detalhe.get("overview"),
            "poster_path_en":        detalhe.get("poster_path"),
            "backdrop_path_en":      detalhe.get("backdrop_path"),
            "original_language":     detalhe.get("original_language"),
            "tagline":               detalhe.get("tagline") or None,
            "status":                detalhe.get("status"),
            "collection_name":       collection.get("name") if collection else None,
            "budget":                detalhe.get("budget") or None,
            "revenue":               detalhe.get("revenue") or None,
            "production_companies":  _extrair_produtoras(detalhe.get("production_companies")),
            "production_countries":  _extrair_paises_producao(detalhe.get("production_countries")),
            "spoken_languages":      _extrair_spoken_languages(detalhe.get("spoken_languages")),
            "actor_names":           _extrair_elenco(creditos),
            "director":              _extrair_diretor(creditos),
            "screenplay":            _extrair_roteiristas(creditos),
            "music_composer":        _extrair_compositor(creditos),
            "producer":              _extrair_produtores(creditos),
            "cinematographer":       _extrair_cinematografo(creditos),
            "editor":                _extrair_montador(creditos),
            "keywords":              _extrair_keywords(keywords_data),
            "certification":         _extrair_certificacao_br_movie(detalhe.get("release_dates", {})),
            "trailer_url":           _extrair_trailer_url(videos_data),
            "imdb_id":               external_ids.get("imdb_id"),
            "origin_country":        detalhe.get("origin_country"),
            "recommended_titles":    _extrair_titulos_recomendados(recommendations_data, content_type),
            "similar_titles":        _extrair_titulos_similares(similar_data, content_type),
            "alternative_titles":    _extrair_titulos_alternativos(alt_titles_data, content_type),
            "dt_processamento":      date.today(),
            "year":                  year,
        }
    else:  # tv
        first_air_date = detalhe.get("first_air_date") or ""
        year = first_air_date[:4] if first_air_date else None
        return {
            "id":                    detalhe.get("id"),
            "number_of_seasons":     detalhe.get("number_of_seasons"),
            "number_of_episodes":    detalhe.get("number_of_episodes"),
            "episode_run_time":      detalhe.get("episode_run_time", []),
            "overview_en":           detalhe.get("overview"),
            "poster_path_en":        detalhe.get("poster_path"),
            "backdrop_path_en":      detalhe.get("backdrop_path"),
            "original_language":     detalhe.get("original_language"),
            "tagline":               detalhe.get("tagline") or None,
            "status":                detalhe.get("status"),
            "production_companies":  _extrair_produtoras(detalhe.get("production_companies")),
            "production_countries":  _extrair_paises_producao(detalhe.get("production_countries")),
            "spoken_languages":      _extrair_spoken_languages(detalhe.get("spoken_languages")),
            "created_by":            _extrair_criadores(detalhe.get("created_by")),
            "networks":              _extrair_networks(detalhe.get("networks")),
            "in_production":         detalhe.get("in_production"),
            "last_air_date":         detalhe.get("last_air_date"),
            "tv_type":               detalhe.get("type"),
            "actor_names":           _extrair_elenco(creditos),
            "director":              _extrair_diretor(creditos),
            "screenplay":            _extrair_roteiristas(creditos),
            "music_composer":        _extrair_compositor(creditos),
            "producer":              _extrair_produtores(creditos),
            "cinematographer":       _extrair_cinematografo(creditos),
            "editor":                _extrair_montador(creditos),
            "keywords":              _extrair_keywords(keywords_data),
            "certification":         _extrair_certificacao_br_tv(detalhe.get("content_ratings", {})),
            "trailer_url":           _extrair_trailer_url(videos_data),
            "imdb_id":               external_ids.get("imdb_id"),
            "recommended_titles":    _extrair_titulos_recomendados(recommendations_data, content_type),
            "similar_titles":        _extrair_titulos_similares(similar_data, content_type),
            "alternative_titles":    _extrair_titulos_alternativos(alt_titles_data, content_type),
            "dt_processamento":      date.today(),
            "year":                  year,
        }


def _adicionar_traducoes_pt(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adiciona coluna overview_pt ao DataFrame de detalhes.

    Traduz apenas registros com original_language='en' (EN→PT via Google Translate).
    Para outros idiomas, overview_pt fica nulo — o glue_agg usará overview_en nesses casos.
    """
    df["overview_pt"] = None

    mask = df["original_language"] == "en"
    if not mask.any():
        return df

    def _translate(texto: str) -> str:
        """Traduz texto de inglês para português via Google Translate."""
        if not texto:
            return ""
        try:
            return GoogleTranslator(source="en", target="pt").translate(texto)
        except Exception as exc:
            logger.warning(f"Falha ao traduzir: {exc}. Mantendo original.")
            return texto

    total = mask.sum()
    logger.info(f"Traduzindo {total} registros com original_language='en' ({_TRANSLATE_MAX_WORKERS} workers).")

    valores = df.loc[mask, "overview_en"].fillna("").tolist()
    with ThreadPoolExecutor(max_workers=_TRANSLATE_MAX_WORKERS) as executor:
        traduzidos = list(executor.map(_translate, valores))
    df.loc[mask, "overview_pt"] = traduzidos

    return df


def _adicionar_traducoes_keywords_pt(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adiciona coluna keywords_pt ao DataFrame de detalhes.

    Traduz keywords de inglês para português via Google Translate.
    Keywords da TMDB são sempre em inglês, independente do idioma original do título.
    """
    df["keywords_pt"] = None

    mask = df["keywords"].notna() & (df["keywords"] != "")
    if not mask.any():
        return df

    def _translate(texto: str) -> str:
        """Traduz keywords de inglês para português via Google Translate."""
        if not texto:
            return ""
        try:
            return GoogleTranslator(source="en", target="pt").translate(texto)
        except Exception as exc:
            logger.warning(f"Falha ao traduzir keywords: {exc}. Mantendo original.")
            return texto

    total = mask.sum()
    logger.info(f"Traduzindo keywords de {total} registros ({_TRANSLATE_MAX_WORKERS} workers).")

    valores = df.loc[mask, "keywords"].fillna("").tolist()
    with ThreadPoolExecutor(max_workers=_TRANSLATE_MAX_WORKERS) as executor:
        traduzidos = list(executor.map(_translate, valores))
    df.loc[mask, "keywords_pt"] = traduzidos

    return df


def collect_and_write_details(
    api_key: str,
    ids: List[int],
    content_type: str,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
) -> None:
    """
    Busca detalhes de cada ID em paralelo e grava no SOT como Parquet particionado por year.

    IDs que falharem na API são descartados silenciosamente.

    Args:
        api_key:       Chave de API do TMDB.
        ids:           Lista de IDs a consultar.
        content_type:  "movie" ou "tv".
        s3_bucket_sot: Nome do bucket SOT de destino.
        table_name:    Nome da tabela no Glue Catalog.
        database:      Nome do banco de dados no Glue Catalog.
    """
    registros = []
    lock = threading.Lock()  # evita race condition ao acumular registros entre threads

    def fetch_and_parse(item_id: int) -> None:
        """Busca detalhes de um ID na TMDB e acumula o registro parseado."""
        try:
            detalhe = fetch_tmdb_details(api_key, content_type, item_id)
            registro = _parse_detail(detalhe, content_type)
            with lock:
                registros.append(registro)
        except requests.RequestException as exc:
            logger.warning(f"Erro ao buscar detalhes do ID {item_id}: {exc}")

    logger.info(f"Buscando detalhes de {len(ids)} IDs ({content_type}) com {_TMDB_MAX_WORKERS} workers...")
    with ThreadPoolExecutor(max_workers=_TMDB_MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_parse, item_id): item_id for item_id in ids}
        for future in as_completed(futures):
            future.result()  # propaga exceções inesperadas (além de RequestException)

    if not registros:
        logger.warning(f"Nenhum detalhe coletado para '{content_type}'. Nada gravado.")
        return

    df = pd.DataFrame(registros)
    # Remove linhas sem year — registros sem data de lançamento não podem ser particionados
    # e causariam erro ao tentar criar a pasta "year=None/" no S3
    df = df.dropna(subset=["year"])

    df = _adicionar_traducoes_pt(df)
    df = _adicionar_traducoes_keywords_pt(df)
    # original_language foi usado apenas para filtrar a tradução; já existe em tb_discover
    df = df.drop(columns=["original_language"])

    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"

    # Merge de dados existentes com novos (evita perder registros ao usar overwrite_partitions):
    # 1. Para cada partição year afetada, lê os registros que já existem no S3
    # 2. Remove do existente qualquer ID que será re-escrito (evita duplicatas)
    # 3. Concatena existentes + novos em um único DataFrame
    # 4. Grava de volta com overwrite_partitions (substitui só as partições afetadas)
    df_existing = pd.DataFrame()
    for yr in df["year"].dropna().unique().tolist():
        try:
            df_read = wr.s3.read_parquet(
                path=s3_path,
                dataset=True,
                partition_filter=lambda x, _yr=yr: x["year"] == str(_yr),
            )
            if not df_read.empty:
                df_existing = pd.concat(
                    [df_existing, df_read[~df_read["id"].isin(df["id"])]],
                    ignore_index=True,
                )
                logger.info(f"Mantendo {len(df_read[~df_read['id'].isin(df['id'])])} registros existentes para year={yr}.")
        except Exception as exc:
            logger.info(f"Sem dados existentes para year={yr} em '{table_name}': {exc}")

    if not df_existing.empty:
        df = pd.concat([df_existing, df], ignore_index=True)

    # Garante unicidade de IDs no DataFrame final.
    # keep="last" preserva o registro novo (concat coloca novos por último) sobre o existente stale.
    df = df.drop_duplicates(subset=["id"], keep="last")

    logger.info(
        f"Gravando {len(df)} registros de detalhes em {s3_path} | "
        f"particao=[year] | mode=overwrite_partitions"
    )
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' gravada com sucesso no SOT.")


def repair_details_duplicates(
    database: str,
    table_details: str,
    s3_bucket_sot: str,
    s3_bucket_temp: str,
    year: str,
) -> None:
    """
    Remove IDs duplicados da partição year atual da tabela de detalhes.

    Lê diretamente a partição do ano corrente, aplica drop_duplicates pelo id mais recente
    (dt_processamento DESC) e grava de volta apenas se houver mudanças.
    Deve ser chamado no final do ciclo (year == end_year) para cada media_type.

    Args:
        database:       Nome do banco de dados no Glue Catalog.
        table_details:  Nome da tabela de detalhes (movie ou tv).
        s3_bucket_sot:  Nome do bucket SOT onde os dados estão gravados.
        s3_bucket_temp: Bucket S3 para resultados temporários do Athena (não usado; mantido por compatibilidade).
        year:           Ano da partição a reparar.
    """
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_details}/"

    logger.info(f"Verificando duplicatas na partição year={year} de '{table_details}'...")
    try:
        df_yr = wr.s3.read_parquet(
            path=s3_path,
            dataset=True,
            partition_filter=lambda x: x["year"] == str(year),
        )
    except Exception as exc:
        logger.warning(f"Não foi possível ler '{table_details}' year={year}: {exc}")
        return

    if df_yr.empty:
        logger.info(f"Partição year={year} de '{table_details}' vazia. Nada a reparar.")
        return

    before = len(df_yr)
    # Ordena crescente: keep="last" mantém o registro com dt_processamento mais recente
    df_deduped = (
        df_yr
        .sort_values("dt_processamento", ascending=True)
        .drop_duplicates(subset=["id"], keep="last")
        .reset_index(drop=True)
    )
    after = len(df_deduped)

    if before == after:
        logger.info(f"Nenhuma duplicata em '{table_details}' year={year}. Nada a reparar.")
        return

    logger.info(
        f"Partição year={year} em '{table_details}': "
        f"{before - after} duplicatas removidas ({before} → {after} registros). Regravando..."
    )
    wr.s3.to_parquet(
        df=df_deduped,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_details,
    )
    logger.info(f"Partição year={year} de '{table_details}' reparada com sucesso.")


def repair_discover_duplicates(
    database: str,
    table_discover: str,
    s3_bucket_sot: str,
    year: str,
) -> None:
    """
    Remove IDs duplicados da partição year atual da tabela de discover.

    Lê diretamente a partição do ano corrente, aplica drop_duplicates pelo id
    e grava de volta apenas se houver mudanças.
    Deve ser chamado no final do ciclo (year == end_year) para cada media_type.

    Args:
        database:        Nome do banco de dados no Glue Catalog.
        table_discover:  Nome da tabela de discover (movie ou tv).
        s3_bucket_sot:   Nome do bucket SOT onde os dados estão gravados.
        year:            Ano da partição a reparar.
    """
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_discover}/"

    logger.info(f"Verificando duplicatas na partição year={year} de '{table_discover}'...")
    try:
        df_yr = wr.s3.read_parquet(
            path=s3_path,
            dataset=True,
            partition_filter=lambda x: x["year"] == str(year),
        )
    except Exception as exc:
        logger.warning(f"Não foi possível ler '{table_discover}' year={year}: {exc}")
        return

    if df_yr.empty:
        logger.info(f"Partição year={year} de '{table_discover}' vazia. Nada a reparar.")
        return

    before = len(df_yr)
    # Ordena crescente: keep="last" mantém o registro com maior popularity (o mais popular)
    df_deduped = (
        df_yr
        .sort_values("popularity", ascending=True)
        .drop_duplicates(subset=["id"], keep="last")
        .reset_index(drop=True)
    )
    after = len(df_deduped)

    if before == after:
        logger.info(f"Nenhuma duplicata em '{table_discover}' year={year}. Nada a reparar.")
        return

    logger.info(
        f"Partição year={year} em '{table_discover}': "
        f"{before - after} duplicatas removidas ({before} → {after} registros). Regravando..."
    )
    wr.s3.to_parquet(
        df=df_deduped,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_discover,
    )
    logger.info(f"Partição year={year} de '{table_discover}' reparada com sucesso.")


def repair_watch_providers_duplicates(
    database: str,
    table_watch_providers: str,
    s3_bucket_sot: str,
    year: str,
) -> None:
    """
    Remove linhas duplicadas da partição year atual da tabela de watch providers.

    Duplicatas são definidas pela chave (id, provider_type, provider_id) — provider_id
    é o identificador canônico estável do TMDB e não muda com rebranding de provedores.
    Mantém o registro com dt_atualizacao mais recente.
    Deve ser chamado no final do ciclo (year == end_year) para cada media_type.

    Args:
        database:              Nome do banco de dados no Glue Catalog.
        table_watch_providers: Nome da tabela de watch providers (movie ou tv).
        s3_bucket_sot:         Nome do bucket SOT onde os dados estão gravados.
        year:                  Ano da partição a reparar.
    """
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_watch_providers}/"

    logger.info(f"Verificando duplicatas na partição year={year} de '{table_watch_providers}'...")
    try:
        df_yr = wr.s3.read_parquet(
            path=s3_path,
            dataset=True,
            partition_filter=lambda x: x["year"] == str(year),
        )
    except Exception as exc:
        logger.warning(f"Não foi possível ler '{table_watch_providers}' year={year}: {exc}")
        return

    if df_yr.empty:
        logger.info(f"Partição year={year} de '{table_watch_providers}' vazia. Nada a reparar.")
        return

    before = len(df_yr)
    # Ordena crescente: keep="last" mantém o registro com dt_atualizacao mais recente
    df_deduped = (
        df_yr
        .sort_values("dt_atualizacao", ascending=True)
        .drop_duplicates(subset=["id", "provider_type", "provider_id"], keep="last")
        .reset_index(drop=True)
    )
    after = len(df_deduped)

    if before == after:
        logger.info(f"Nenhuma duplicata em '{table_watch_providers}' year={year}. Nada a reparar.")
        return

    logger.info(
        f"Partição year={year} em '{table_watch_providers}': "
        f"{before - after} duplicatas removidas ({before} → {after} registros). Regravando..."
    )
    wr.s3.to_parquet(
        df=df_deduped,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_watch_providers,
    )
    logger.info(f"Partição year={year} de '{table_watch_providers}' reparada com sucesso.")


def fetch_tmdb_watch_providers(api_key: str, content_type: str, item_id: int) -> dict:
    """
    Busca provedores de streaming para um título na região BR.

    Args:
        api_key:      Chave de API do TMDB.
        content_type: "movie" ou "tv".
        item_id:      ID do filme ou série no TMDB.

    Returns:
        Dicionário com chaves "flatrate", "rent", "buy", ou vazio se BR não disponível.
    """
    endpoint = "movie" if content_type == "movie" else "tv"
    url = f"{TMDB_BASE_URL}/{endpoint}/{item_id}/watch/providers"
    params = {"api_key": api_key}

    results = tmdb_get(url, params).get("results", {})
    return results.get("BR", {})


def _parse_watch_providers(br_data: dict, item_id: int, year: Optional[str]) -> List[dict]:
    """
    Converte a seção BR de watch/providers em registros normalizados (um por provedor × tipo).

    Tipos: flatrate (assinatura), rent (aluguel), buy (compra).

    Args:
        br_data: Seção "BR" da resposta da API (pode ser vazio se BR não disponível).
        item_id: ID do título no TMDB.
        year:    Ano de partição.

    Returns:
        Lista de registros com: id, provider_type, provider_id, provider_name, dt_atualizacao, year.
    """
    records = []
    for provider_type in ("flatrate", "rent", "buy"):
        for p in br_data.get(provider_type, []):
            name = p.get("provider_name")
            if not name:
                continue  # ignora provedores sem nome (dados incompletos da API)
            records.append({
                "id":             item_id,
                "provider_type":  provider_type,
                "provider_id":    p.get("provider_id"),
                "provider_name":  name,
                "dt_atualizacao": date.today(),
                "year":           year,
            })
    return records


def collect_and_write_watch_providers(
    api_key: str,
    ids: List[int],
    content_type: str,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
    year: str,
) -> None:
    """
    Busca provedores de streaming BR para cada ID em paralelo e grava no SOT.

    Args:
        api_key:       Chave de API do TMDB.
        ids:           Lista de IDs a consultar.
        content_type:  "movie" ou "tv".
        s3_bucket_sot: Nome do bucket SOT de destino.
        table_name:    Nome da tabela no Glue Catalog.
        database:      Nome do banco de dados no Glue Catalog.
        year:          Ano de partição.
    """
    registros: List[dict] = []
    lock = threading.Lock()

    def fetch_and_parse(item_id: int) -> None:
        """Busca watch providers de um ID na TMDB e acumula os registros parseados."""
        try:
            br_data = fetch_tmdb_watch_providers(api_key, content_type, item_id)
            parsed = _parse_watch_providers(br_data, item_id, year)
            if parsed:
                with lock:
                    registros.extend(parsed)
        except requests.RequestException as exc:
            logger.warning(f"Erro ao buscar watch providers do ID {item_id}: {exc}")

    logger.info(
        f"Buscando watch providers BR de {len(ids)} IDs ({content_type}) "
        f"com {_TMDB_MAX_WORKERS} workers..."
    )
    with ThreadPoolExecutor(max_workers=_TMDB_MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_parse, item_id): item_id for item_id in ids}
        for future in as_completed(futures):
            future.result()

    if not registros:
        logger.warning(f"Nenhum watch provider BR coletado para '{content_type}'. Nada gravado.")
        return

    df = pd.DataFrame(registros)
    df = df.dropna(subset=["year"])

    # Merge: lê registros existentes do ano, remove os IDs que serão atualizados,
    # e concatena com os novos dados para preservar IDs não-stale.
    df_existing = pd.DataFrame()
    try:
        df_read = wr.s3.read_parquet(
            path=f"s3://{s3_bucket_sot}/tmdb/{table_name}/",
            dataset=True,
            partition_filter=lambda x: x["year"] == year,
        )
        if not df_read.empty:
            df_existing = df_read[~df_read["id"].isin(ids)]
            logger.info(f"Mantendo {len(df_existing)} registros não-stale de '{table_name}'.")
    except Exception as exc:
        logger.info(f"Sem dados existentes para year={year} em '{table_name}': {exc}")

    if not df_existing.empty:
        df = pd.concat([df_existing, df], ignore_index=True)

    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"
    logger.info(
        f"Gravando {len(df)} registros de watch providers em {s3_path} | "
        f"particao=[year] | mode=overwrite_partitions"
    )
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' gravada com sucesso no SOT.")
