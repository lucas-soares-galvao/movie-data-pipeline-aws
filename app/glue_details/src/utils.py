"""utils.py — Funções auxiliares do job Glue Details."""

import logging
import sys
import threading
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

import awswrangler as wr
import pandas as pd
import requests

# noqa: F401 = diz ao linter para ignorar "import não usado" — esses imports são
# re-exportados para que main.py os importe diretamente de src.utils.
from shared_utils.api_client import get_api_secret, api_get as tmdb_get  # noqa: F401
from shared_utils.glue_helpers import get_resolved_option  # noqa: F401
from shared_utils.traducao import (
    eligible_keywords_pt,
    eligible_overview_pt,
    eligible_tagline_pt,
    reuse_existing_translation,
    resolve_translate_fn,
    translate_pending_column,
    translate_text,
    translate_text_aws,
)
from shared_utils.triggers import trigger_glue_job  # noqa: F401

logger = logging.getLogger()

TMDB_BASE_URL = "https://api.themoviedb.org/3"


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
    # FORCE_REFETCH não pode estar em required_args porque getResolvedOptions falha para qualquer
    # argumento não passado na chamada (sem suporte a valor padrão). Lemos manualmente aqui
    # para mantê-lo opcional sem precisar altererar os runs normais.
    params["FORCE_REFETCH"] = False
    for i, arg in enumerate(sys.argv):
        if arg == "--FORCE_REFETCH" and i + 1 < len(sys.argv):
            params["FORCE_REFETCH"] = sys.argv[i + 1].lower() == "true"
            break

    # Opcional: qual serviço de tradução usar ("google" ou "aws"). "aws" (padrão) é o
    # comportamento do caminho automático via EventBridge — não passado nesse caminho,
    # então cai no default. Backfills manuais (scripts/) sobrescrevem para "google".
    params["TRANSLATE_PROVIDER"] = "aws"
    for i, arg in enumerate(sys.argv):
        if arg == "--TRANSLATE_PROVIDER" and i + 1 < len(sys.argv):
            params["TRANSLATE_PROVIDER"] = sys.argv[i + 1]
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
        append = "credits,keywords,release_dates,videos,external_ids,recommendations,similar,alternative_titles,translations"
    else:
        append = "credits,keywords,content_ratings,videos,external_ids,recommendations,similar,alternative_titles,translations"

    params = {
        "api_key": api_key,
        "language": "en-US",
        "append_to_response": append,
    }

    return tmdb_get(url, params)


_TMDB_MAX_WORKERS = 20      # ~20 req/s concorrentes — bem abaixo do rate limit de ~40 req/s do TMDB
_TRANSLATE_MAX_WORKERS = 10  # traduções EN→PT paralelas via Google Translate


def _run_parallel(func: Any, items: list, max_workers: int = _TMDB_MAX_WORKERS) -> None:
    """
    Executa func(item) em paralelo para cada item da lista.

    Propaga exceções levantadas dentro de func — se alguma thread falhar de forma
    inesperada, o job é interrompido. Erros tratáveis (ex: HTTPError de um ID)
    devem ser capturados dentro de func antes de chegar aqui.

    Args:
        func:        Função a executar para cada item. Deve aceitar um único argumento.
        items:       Lista de itens a processar.
        max_workers: Número máximo de threads simultâneas.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(func, item) for item in items]
        for future in as_completed(futures):
            future.result()


# ── Funções auxiliares de extração ──────────────────────────────────────────────
# Cada função "_extract_*" isola a lógica de um campo específico da resposta da API TMDB.
# Isso permite testar cada campo individualmente e facilita a leitura de _parse_detail().
# Convenção: retornam None quando o dado não existe, em vez de string vazia.


def _extract_names_from_list(
    items: list,
    *,
    filter_field: Optional[str] = None,
    filter_value: Optional[str] = None,
) -> Optional[str]:
    """
    Extrai nomes de uma lista de dicts e os une por vírgula.

    Usada pelas funções _extract_* que seguem o padrão: filtrar uma lista,
    extrair o campo "name" de cada item e juntar em string separada por vírgula.

    Args:
        items:         Lista de dicts com chave "name".
        filter_field:  Campo a verificar como critério de inclusão (ex: "job").
                       Se None, inclui todos os itens que tiverem "name".
        filter_value:  Valor esperado no filter_field (ex: "Director").

    Returns:
        String com nomes separados por vírgula, ou None se a lista for vazia.
    """
    if filter_field and filter_value:
        names = [item["name"] for item in (items or [])
                 if item.get("name") and item.get(filter_field) == filter_value]
    else:
        names = [item["name"] for item in (items or []) if item.get("name")]
    return ", ".join(names) if names else None


def _extract_cast(credits: dict, limit: int = 5) -> Optional[str]:
    """Top N atores por ordem de billing, separados por vírgula."""
    cast = credits.get("cast", [])
    names = [c["name"] for c in sorted(cast, key=lambda x: x.get("order", 999))[:limit]]
    return ", ".join(names) if names else None


def _extract_director(credits: dict) -> Optional[str]:
    """Diretor(es) do filme/série (job == 'Director' no crew)."""
    return _extract_names_from_list(credits.get("crew", []), filter_field="job", filter_value="Director")


def _extract_writers(credits: dict) -> Optional[str]:
    """Roteiristas (job in Screenplay/Writer no crew), deduplicados."""
    crew = credits.get("crew", [])
    names: list[str] = []
    seen: set[str] = set()
    for c in crew:
        if c.get("job") in ("Screenplay", "Writer") and c.get("name"):
            name = c["name"]
            if name not in seen:
                seen.add(name)
                names.append(name)
    return ", ".join(names) if names else None


def _extract_composer(credits: dict) -> Optional[str]:
    """Compositor(es) da trilha sonora (job == 'Original Music Composer')."""
    return _extract_names_from_list(credits.get("crew", []), filter_field="job", filter_value="Original Music Composer")


def _extract_keywords(keywords_data: dict) -> Optional[str]:
    """Keywords como string separada por vírgula."""
    kws = keywords_data.get("keywords") or keywords_data.get("results") or []
    names = [kw["name"] for kw in kws if kw.get("name")]
    return ", ".join(names) if names else None


def _extract_certification_br_movie(release_dates: dict) -> Optional[str]:
    """Extrai classificação indicativa BR do endpoint release_dates (filmes)."""
    for entry in release_dates.get("results", []):
        if entry.get("iso_3166_1") == "BR":
            for rd in entry.get("release_dates", []):
                cert = rd.get("certification")
                if cert:
                    return cert
    return None


def _extract_certification_br_tv(content_ratings: dict) -> Optional[str]:
    """Extrai classificação indicativa BR do endpoint content_ratings (TV)."""
    for entry in content_ratings.get("results", []):
        if entry.get("iso_3166_1") == "BR":
            return entry.get("rating") or None
    return None


def _extract_trailer_url(videos: dict) -> Optional[str]:
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


def _extract_production_companies(companies: list) -> Optional[str]:
    """Nomes das produtoras, separados por vírgula."""
    return _extract_names_from_list(companies)


def _extract_creators(created_by: list) -> Optional[str]:
    """Criadores de série, separados por vírgula."""
    return _extract_names_from_list(created_by)


def _extract_networks(networks: list) -> Optional[str]:
    """Redes de TV, separadas por vírgula."""
    return _extract_names_from_list(networks)


def _extract_spoken_languages(spoken_languages: list) -> Optional[str]:
    """Idiomas falados, separados por vírgula."""
    names = [sl.get("name") or sl.get("english_name", "") for sl in (spoken_languages or [])]
    names = [n for n in names if n]
    return ", ".join(names) if names else None


def _extract_spoken_languages_iso(spoken_languages: list) -> Optional[List[str]]:
    """Códigos ISO 639-1 dos idiomas falados como array."""
    codes = [sl["iso_639_1"] for sl in (spoken_languages or []) if sl.get("iso_639_1")]
    return codes if codes else None


def _extract_producers(credits: dict, limit: int = 3) -> Optional[str]:
    """Produtor(es) e produtores executivos, deduplicados, limitados a top N."""
    crew = credits.get("crew", [])
    names: list[str] = []
    seen: set[str] = set()
    for c in crew:
        if c.get("job") in ("Producer", "Executive Producer") and c.get("name"):
            name = c["name"]
            if name not in seen:
                seen.add(name)
                names.append(name)
            if len(names) >= limit:
                break
    return ", ".join(names) if names else None


def _extract_cinematographer(credits: dict) -> Optional[str]:
    """Diretor(es) de fotografia (job == 'Director of Photography' no crew)."""
    return _extract_names_from_list(credits.get("crew", []), filter_field="job", filter_value="Director of Photography")


def _extract_editor(credits: dict) -> Optional[str]:
    """Montador(es) do filme/série (job == 'Editor' no crew)."""
    return _extract_names_from_list(credits.get("crew", []), filter_field="job", filter_value="Editor")


def _extract_production_countries(production_countries: list) -> Optional[str]:
    """Países de produção, separados por vírgula."""
    return _extract_names_from_list(production_countries)


def _extract_production_countries_iso(production_countries: list) -> Optional[List[str]]:
    """Códigos ISO 3166-1 dos países de produção como array."""
    codes = [c["iso_3166_1"] for c in (production_countries or []) if c.get("iso_3166_1")]
    return codes if codes else None


def _extract_recommended_titles(recommendations: dict, content_type: str, limit: int = 10) -> Optional[str]:
    """Top N títulos recomendados pelo TMDB, separados por vírgula."""
    results = recommendations.get("results", [])
    field = "title" if content_type == "movie" else "name"
    names = [r[field] for r in results[:limit] if r.get(field)]
    return ", ".join(names) if names else None


def _extract_similar_titles(similar: dict, content_type: str, limit: int = 10) -> Optional[str]:
    """Top N títulos similares pelo TMDB, separados por vírgula."""
    results = similar.get("results", [])
    field = "title" if content_type == "movie" else "name"
    names = [r[field] for r in results[:limit] if r.get(field)]
    return ", ".join(names) if names else None


def _extract_recommended_ids(recommendations: dict, limit: int = 10) -> Optional[str]:
    """Top N IDs recomendados pelo TMDB, separados por vírgula."""
    results = recommendations.get("results", [])
    ids = [str(r["id"]) for r in results[:limit] if r.get("id") is not None]
    return ", ".join(ids) if ids else None


def _extract_similar_ids(similar: dict, limit: int = 10) -> Optional[str]:
    """Top N IDs similares pelo TMDB, separados por vírgula."""
    results = similar.get("results", [])
    ids = [str(r["id"]) for r in results[:limit] if r.get("id") is not None]
    return ", ".join(ids) if ids else None


def _extract_pt_br_translation(translations: dict) -> Dict[str, Optional[str]]:
    """
    Extrai overview e tagline em pt-BR do array de translations da API do TMDB.

    Args:
        translations: Dicionário com chave "translations" contendo a lista de traduções.

    Returns:
        Dicionário com chaves "overview_pt_tmdb" e "tagline_pt_tmdb" (None se pt-BR ausente).
    """
    result: Dict[str, Optional[str]] = {"overview_pt_tmdb": None, "tagline_pt_tmdb": None}

    for t in translations.get("translations", []):
        if t.get("iso_639_1") == "pt" and t.get("iso_3166_1") == "BR":
            data = t.get("data", {})
            overview = data.get("overview")
            tagline = data.get("tagline")
            if overview and overview.strip():
                result["overview_pt_tmdb"] = overview.strip()
            if tagline and tagline.strip():
                result["tagline_pt_tmdb"] = tagline.strip()
            break

    return result


def _extract_alternative_titles(alternative_titles: dict, content_type: str) -> Optional[str]:
    """Títulos alternativos/regionais, separados por vírgula."""
    list_field = "titles" if content_type == "movie" else "results"
    titles = alternative_titles.get(list_field, [])
    names = [t["title"] for t in titles if t.get("title")]
    return ", ".join(names) if names else None


# ── Montagem do registro final ────────────────────────────────────────────────
# As três funções abaixo separam os campos em: comuns a ambos os tipos, exclusivos
# de filmes e exclusivos de séries. _parse_detail() combina os três em um dict final.


def _common_fields(detail: dict, content_type: str) -> dict:
    """Campos compartilhados entre filmes e séries na resposta da API TMDB."""
    credits = detail.get("credits", {})
    pt_br_translation = _extract_pt_br_translation(detail.get("translations", {}))
    return {
        "id":                       detail.get("id"),
        "overview_en":              detail.get("overview"),
        "poster_path_en":           detail.get("poster_path"),
        "backdrop_path_en":         detail.get("backdrop_path"),
        "original_language":        detail.get("original_language"),
        "tagline":                  detail.get("tagline") or None,
        "status":                   detail.get("status"),
        "production_companies":     _extract_production_companies(detail.get("production_companies")),
        "production_countries":     _extract_production_countries(detail.get("production_countries")),
        "production_countries_iso": _extract_production_countries_iso(detail.get("production_countries")),
        "spoken_languages":         _extract_spoken_languages(detail.get("spoken_languages")),
        "spoken_languages_iso":     _extract_spoken_languages_iso(detail.get("spoken_languages")),
        "actor_names":              _extract_cast(credits),
        "director":                 _extract_director(credits),
        "screenplay":               _extract_writers(credits),
        "music_composer":           _extract_composer(credits),
        "producer":                 _extract_producers(credits),
        "cinematographer":          _extract_cinematographer(credits),
        "editor":                   _extract_editor(credits),
        "keywords":                 _extract_keywords(detail.get("keywords", {})),
        "trailer_url":              _extract_trailer_url(detail.get("videos", {})),
        "imdb_id":                  detail.get("external_ids", {}).get("imdb_id"),
        "recommended_titles":       _extract_recommended_titles(detail.get("recommendations", {}), content_type),
        "recommended_ids":          _extract_recommended_ids(detail.get("recommendations", {})),
        "similar_titles":           _extract_similar_titles(detail.get("similar", {}), content_type),
        "similar_ids":              _extract_similar_ids(detail.get("similar", {})),
        "alternative_titles":       _extract_alternative_titles(detail.get("alternative_titles", {}), content_type),
        "overview_pt_tmdb":         pt_br_translation["overview_pt_tmdb"],
        "tagline_pt_tmdb":          pt_br_translation["tagline_pt_tmdb"],
        "dt_processamento":         date.today(),
    }


def _movie_fields(detail: dict) -> dict:
    """Campos exclusivos de filmes (complementam _common_fields)."""
    release_date = detail.get("release_date") or ""
    collection = detail.get("belongs_to_collection")
    return {
        "year":            release_date[:4] if release_date else None,
        "runtime":         detail.get("runtime"),
        "collection_id":   collection.get("id") if collection else None,
        "collection_name": collection.get("name") if collection else None,
        "budget":          detail.get("budget") or None,
        "revenue":         detail.get("revenue") or None,
        "origin_country":  detail.get("origin_country"),
        "certification":   _extract_certification_br_movie(detail.get("release_dates", {})),
    }


def _tv_fields(detail: dict) -> dict:
    """Campos exclusivos de séries (complementam _common_fields)."""
    first_air_date = detail.get("first_air_date") or ""
    return {
        "year":               first_air_date[:4] if first_air_date else None,
        "number_of_seasons":  detail.get("number_of_seasons"),
        "number_of_episodes": detail.get("number_of_episodes"),
        "episode_run_time":   detail.get("episode_run_time", []),
        "created_by":         _extract_creators(detail.get("created_by")),
        "networks":           _extract_networks(detail.get("networks")),
        "in_production":      detail.get("in_production"),
        "last_air_date":      detail.get("last_air_date"),
        "tv_type":            detail.get("type"),
        "certification":      _extract_certification_br_tv(detail.get("content_ratings", {})),
    }


def _parse_detail(detail: dict, content_type: str) -> Optional[dict]:
    """Extrai os campos relevantes da resposta de /movie/{id} ou /tv/{id}."""
    specific_fields = _movie_fields(detail) if content_type == "movie" else _tv_fields(detail)
    return {**_common_fields(detail, content_type), **specific_fields}


def _fetch_collections_pt_br(api_key: str, collection_ids: List[int]) -> Dict[int, str]:
    """
    Busca nomes de coleções em pt-BR na API do TMDB.

    Faz chamadas paralelas para /collection/{id} com language=pt-BR.

    Args:
        api_key:        Chave de API do TMDB.
        collection_ids: Lista de IDs de coleções únicos a consultar.

    Returns:
        Dicionário collection_id → nome em português.
    """
    if not collection_ids:
        return {}

    result: Dict[int, str] = {}
    lock = threading.Lock()

    def _fetch(col_id: int) -> None:
        try:
            url = f"{TMDB_BASE_URL}/collection/{col_id}"
            data = tmdb_get(url, {"api_key": api_key, "language": "pt-BR"})
            name = data.get("name")
            if name and name.strip():
                with lock:
                    result[col_id] = name.strip()
        except Exception as exc:
            logger.warning(f"Falha ao buscar coleção {col_id} em pt-BR: {exc}")

    logger.info(f"Buscando {len(collection_ids)} coleções em pt-BR ({_TMDB_MAX_WORKERS} workers)...")
    _run_parallel(_fetch, collection_ids)

    logger.info(f"Coleções pt-BR encontradas: {len(result)}/{len(collection_ids)}.")
    return result


def _add_collection_name_pt(df: pd.DataFrame, api_key: str) -> pd.DataFrame:
    """
    Adiciona coluna collection_name_pt ao DataFrame de detalhes de filmes.

    Busca nomes de coleções em pt-BR na API do TMDB, deduplicando por collection_id.

    Args:
        df:      DataFrame de detalhes com coluna collection_id.
        api_key: Chave de API do TMDB.

    Returns:
        DataFrame com a coluna collection_name_pt adicionada.
    """
    df["collection_name_pt"] = None

    mask = df["collection_id"].notna()
    if not mask.any():
        return df

    unique_ids = df.loc[mask, "collection_id"].dropna().astype(int).unique().tolist()
    mapping = _fetch_collections_pt_br(api_key, unique_ids)

    if mapping:
        df.loc[mask, "collection_name_pt"] = (
            df.loc[mask, "collection_id"].astype(int).map(mapping)
        )

    return df


def _add_translations_pt(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    previous_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Adiciona coluna overview_pt ao DataFrame de detalhes.

    Prioriza tradução pt-BR vinda do TMDB (overview_pt_tmdb). Em seguida, reaproveita
    a tradução já existente no S3 quando overview_en não mudou desde o último
    processamento (ver reuse_existing_translation). Para registros sem
    tradução TMDB nem cache aproveitável, com idioma original diferente de pt e
    overview_en não-vazio, traduz via Google Translate. Para registros já em pt ou
    sem overview_en, overview_pt fica nulo — o glue_agg usará overview_en nesses casos.
    """
    # translate_fn resolvido em runtime (não como default de parâmetro) para que
    # patch("src.utils.translate_text", ...) nos testes continue funcionando quando
    # o chamador não passa um translate_fn explícito.
    translate_fn = translate_fn or translate_text
    df["overview_pt"] = df["overview_pt_tmdb"]
    df = reuse_existing_translation(df, previous_df, "overview_en", "overview_pt")

    eligible_mask = eligible_overview_pt(df)
    if not eligible_mask.any():
        return df

    logger.info(
        f"Traduzindo overview de até {eligible_mask.sum()} registros sem tradução TMDB pt-BR "
        f"({_TRANSLATE_MAX_WORKERS} workers)."
    )
    success_count = translate_pending_column(
        df, "overview_en", "overview_pt", eligible_mask, translate_fn, max_workers=_TRANSLATE_MAX_WORKERS
    )
    logger.info(f"{success_count} registros traduzidos com sucesso (overview_pt).")
    return df


def _add_translations_keywords_pt(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    previous_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Adiciona coluna keywords_pt ao DataFrame de detalhes.

    Reaproveita a tradução já existente no S3 quando keywords não mudou desde o
    último processamento (ver reuse_existing_translation). Caso contrário,
    traduz para português via Google Translate, exceto quando o idioma original
    já é pt (evita reenviar à API keywords que já podem estar em português; a
    TMDB devolve keywords em inglês para os demais idiomas).
    """
    translate_fn = translate_fn or translate_text
    df["keywords_pt"] = None
    df = reuse_existing_translation(df, previous_df, "keywords", "keywords_pt")

    eligible_mask = eligible_keywords_pt(df)
    if not eligible_mask.any():
        return df

    logger.info(f"Traduzindo keywords de até {eligible_mask.sum()} registros ({_TRANSLATE_MAX_WORKERS} workers).")
    success_count = translate_pending_column(
        df, "keywords", "keywords_pt", eligible_mask, translate_fn, max_workers=_TRANSLATE_MAX_WORKERS
    )
    logger.info(f"{success_count} registros traduzidos com sucesso (keywords_pt).")
    return df


def _add_translations_tagline_pt(
    df: pd.DataFrame,
    translate_fn: Optional[Callable[[str], str]] = None,
    previous_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Adiciona coluna tagline_pt ao DataFrame de detalhes.

    Prioriza tradução pt-BR vinda do TMDB (tagline_pt_tmdb). Em seguida, reaproveita
    a tradução já existente no S3 quando tagline não mudou desde o último
    processamento (ver reuse_existing_translation). Para registros sem
    tradução TMDB nem cache aproveitável, com tagline não-nula e idioma original
    diferente de pt, traduz via Google Translate.
    """
    translate_fn = translate_fn or translate_text
    df["tagline_pt"] = df["tagline_pt_tmdb"]
    df = reuse_existing_translation(df, previous_df, "tagline", "tagline_pt")

    eligible_mask = eligible_tagline_pt(df)
    if not eligible_mask.any():
        return df

    logger.info(
        f"Traduzindo tagline de até {eligible_mask.sum()} registros sem tradução TMDB pt-BR "
        f"({_TRANSLATE_MAX_WORKERS} workers)."
    )
    success_count = translate_pending_column(
        df, "tagline", "tagline_pt", eligible_mask, translate_fn, max_workers=_TRANSLATE_MAX_WORKERS
    )
    logger.info(f"{success_count} registros traduzidos com sucesso (tagline_pt).")
    return df


def collect_and_write_details(
    api_key: str,
    ids: List[int],
    content_type: str,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
    translate_provider: str = "aws",
) -> None:
    """
    Busca detalhes de cada ID em paralelo e grava no SOT como Parquet particionado por year.

    IDs que falharem na API são descartados silenciosamente. Registros sem "year"
    (sem release_date/first_air_date) também são descartados; se isso esvaziar
    o DataFrame por completo, a função não grava nada.

    Args:
        api_key:            Chave de API do TMDB.
        ids:                Lista de IDs a consultar.
        content_type:       "movie" ou "tv".
        s3_bucket_sot:      Nome do bucket SOT de destino.
        table_name:         Nome da tabela no Glue Catalog.
        database:           Nome do banco de dados no Glue Catalog.
        translate_provider: "google" ou "aws" — ver resolve_translate_fn. Default "aws"
                             (caminho automático via EventBridge).
    """
    records = []
    lock = threading.Lock()  # evita race condition ao acumular registros entre threads

    def fetch_and_parse(item_id: int) -> None:
        try:
            detail = fetch_tmdb_details(api_key, content_type, item_id)
            record = _parse_detail(detail, content_type)
            with lock:
                records.append(record)
        except requests.RequestException as exc:
            logger.warning(f"Erro ao buscar detalhes do ID {item_id}: {exc}")

    logger.info(f"Buscando detalhes de {len(ids)} IDs ({content_type}) com {_TMDB_MAX_WORKERS} workers...")
    _run_parallel(fetch_and_parse, ids)

    if not records:
        logger.warning(f"Nenhum detalhe coletado para '{content_type}'. Nada gravado.")
        return

    df = pd.DataFrame(records)
    # Remove linhas sem year — registros sem data de lançamento não podem ser particionados
    # e causariam erro ao tentar criar a pasta "year=None/" no S3
    df = df.dropna(subset=["year"])
    if df.empty:
        logger.warning(
            f"Todos os {len(records)} registros coletados para '{content_type}' "
            "ficaram sem 'year' (sem data de lançamento). Nada gravado."
        )
        return

    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"

    # Leitura antecipada dos registros existentes (uma única vez por partição year),
    # produzindo duas visões a partir do mesmo df_read:
    # - df_existing_delta: ids que SERÃO sobrescritos neste run -> cache de tradução
    #   (compara fonte antiga vs. nova antes de chamar as APIs de tradução)
    # - df_existing_keep:  ids que NÃO fazem parte do delta -> preservados no merge final
    df_existing_keep = pd.DataFrame()
    df_existing_delta = pd.DataFrame()
    for yr in df["year"].dropna().unique().tolist():
        try:
            year_str = str(yr)
            df_read = wr.s3.read_parquet(
                path=s3_path,
                dataset=True,
                partition_filter=lambda x: x["year"] == year_str,
            )
            if not df_read.empty:
                mask_delta = df_read["id"].isin(df["id"])
                df_existing_keep = pd.concat([df_existing_keep, df_read[~mask_delta]], ignore_index=True)
                df_existing_delta = pd.concat([df_existing_delta, df_read[mask_delta]], ignore_index=True)
                logger.info(
                    f"year={yr}: {(~mask_delta).sum()} registros existentes preservados (fora do delta); "
                    f"{mask_delta.sum()} disponíveis como cache de tradução (dentro do delta)."
                )
        except Exception as exc:
            logger.info(f"Sem dados existentes para year={yr} em '{table_name}': {exc}")

    translate_fn = resolve_translate_fn(translate_provider, translate_text, translate_text_aws)
    df = _add_translations_pt(df, translate_fn, previous_df=df_existing_delta)
    df = _add_translations_keywords_pt(df, translate_fn, previous_df=df_existing_delta)
    df = _add_translations_tagline_pt(df, translate_fn, previous_df=df_existing_delta)
    if content_type == "movie":
        df = _add_collection_name_pt(df, api_key)
    # Campos intermediários: usados apenas para filtrar/priorizar traduções; não vão para o SOT
    intermediate_columns = ["original_language", "overview_pt_tmdb", "tagline_pt_tmdb"]
    df = df.drop(columns=[c for c in intermediate_columns if c in df.columns])

    # Merge de dados existentes com novos (evita perder registros ao usar overwrite_partitions):
    # concatena os registros preservados (fora do delta) com os novos e garante
    # unicidade por id. keep="last" preserva o registro novo (concat coloca novos
    # por último) sobre o existente stale.
    if not df_existing_keep.empty:
        df = pd.concat([df_existing_keep, df], ignore_index=True)
    df = df.drop_duplicates(subset=["id"], keep="last")

    # Grava de volta — overwrite_partitions substitui apenas as partições afetadas,
    # preservando o histórico de anos anteriores intacto.
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


# ── Remoção de duplicatas intra-partição ─────────────────────────────────────
# As três funções repair_* abaixo seguem o mesmo padrão — implementado em
# _repair_partition_duplicates — e diferem apenas na coluna de ordenação e na
# chave de deduplicação. Ver _repair_partition_duplicates para a lógica completa.


def _repair_partition_duplicates(
    s3_path: str,
    database: str,
    table_name: str,
    year: str,
    sort_by: str,
    subset_cols: List[str],
) -> None:
    """
    Lê uma partição year, remove duplicatas e regrava somente se houver mudanças.

    Padrão: ordena por sort_by ASC → keep="last" mantém o maior valor (mais recente/popular).

    Args:
        s3_path:     Caminho base da tabela no S3 (ex: "s3://bucket/tmdb/tb_name/").
        database:    Nome do banco de dados no Glue Catalog.
        table_name:  Nome da tabela (usado no log e na gravação).
        year:        Partição a verificar.
        sort_by:     Coluna de ordenação antes do drop_duplicates.
        subset_cols: Colunas que definem uma duplicata (ex: ["id"]).
    """
    year_str = str(year)
    logger.info(f"Verificando duplicatas na partição year={year_str} de '{table_name}'...")
    try:
        df_yr = wr.s3.read_parquet(
            path=s3_path,
            dataset=True,
            partition_filter=lambda x: x["year"] == year_str,
        )
    except Exception as exc:
        logger.warning(f"Não foi possível ler '{table_name}' year={year_str}: {exc}")
        return

    if df_yr.empty:
        logger.info(f"Partição year={year_str} de '{table_name}' vazia. Nada a reparar.")
        return

    before = len(df_yr)
    df_deduped = (
        df_yr
        .sort_values(sort_by, ascending=True)
        .drop_duplicates(subset=subset_cols, keep="last")
        .reset_index(drop=True)
    )
    after = len(df_deduped)

    if before == after:
        logger.info(f"Nenhuma duplicata em '{table_name}' year={year_str}. Nada a reparar.")
        return

    logger.info(
        f"Partição year={year_str} em '{table_name}': "
        f"{before - after} duplicatas removidas ({before} → {after} registros). Regravando..."
    )
    wr.s3.to_parquet(
        df=df_deduped,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_name,
    )
    logger.info(f"Partição year={year_str} de '{table_name}' reparada com sucesso.")


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
    _repair_partition_duplicates(s3_path, database, table_details, year, "dt_processamento", ["id"])


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
    _repair_partition_duplicates(s3_path, database, table_discover, year, "popularity", ["id"])


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
    _repair_partition_duplicates(
        s3_path, database, table_watch_providers, year,
        "dt_atualizacao", ["id", "provider_type", "provider_id"],
    )


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
    records: List[dict] = []
    lock = threading.Lock()

    def fetch_and_parse(item_id: int) -> None:
        try:
            br_data = fetch_tmdb_watch_providers(api_key, content_type, item_id)
            parsed = _parse_watch_providers(br_data, item_id, year)
            if parsed:
                with lock:
                    records.extend(parsed)
        except requests.RequestException as exc:
            logger.warning(f"Erro ao buscar watch providers do ID {item_id}: {exc}")

    logger.info(
        f"Buscando watch providers BR de {len(ids)} IDs ({content_type}) "
        f"com {_TMDB_MAX_WORKERS} workers..."
    )
    _run_parallel(fetch_and_parse, ids)

    if not records:
        logger.warning(f"Nenhum watch provider BR coletado para '{content_type}'. Nada gravado.")
        return

    df = pd.DataFrame(records)
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
