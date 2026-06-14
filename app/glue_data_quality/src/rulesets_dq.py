"""rulesets_dq.py — Regras DQDL de qualidade de dados por tabela."""

rulesets_dq = {
    "tb_configuration_countries_tmdb": [
        # Completude
        'IsComplete "iso_3166_1"',
        'IsComplete "english_name"',
        'IsComplete "native_name"',
        # Unicidade
        'IsUnique "iso_3166_1"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "tb_configuration_languages_tmdb": [
        # Completude
        'IsComplete "iso_639_1"',
        'IsComplete "english_name"',
        # Unicidade
        'IsUnique "iso_639_1"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "tb_genre_movie_tmdb": [
        # Completude
        'IsComplete "id"',
        'IsComplete "name"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "tb_genre_tv_tmdb": [
        # Completude
        'IsComplete "id"',
        'IsComplete "name"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "tb_discover_movie_tmdb": [
        # Completude
        'IsComplete "id"',
        'IsComplete "title"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        'ColumnValues "vote_average" >= 0',
        'ColumnValues "vote_average" <= 10',
        # Integridade
        "RowCount > 0",
    ],
    "tb_discover_tv_tmdb": [
        # Completude
        'IsComplete "id"',
        'IsComplete "name"',  # séries usam "name", não "title"
        # Unicidade
        'IsUnique "id"',
        # Validade
        'ColumnValues "vote_average" >= 0',
        'ColumnValues "vote_average" <= 10',
        # Integridade
        "RowCount > 0",
    ],
    "tb_details_movie_tmdb": [
        # Completude
        'IsComplete "id"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        # runtime pode ser 0 (duração não informada pela API), mas nunca negativo
        'ColumnValues "runtime" >= 0',
        # Integridade
        "RowCount > 0",
    ],
    "tb_details_tv_tmdb": [
        # Completude
        'IsComplete "id"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        'ColumnValues "number_of_seasons" >= 1',   # série ativa deve ter ao menos 1 temporada
        'ColumnValues "number_of_episodes" >= 1',  # série deve ter ao menos 1 episódio cadastrado
        # Integridade
        "RowCount > 0",
    ],
    "tb_watch_providers_movie_tmdb": [
        # Completude
        'IsComplete "id"',
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        'IsComplete "provider_type"',
        # Unicidade
        'Uniqueness "id" "provider_id" "provider_type" = 1',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "tb_watch_providers_tv_tmdb": [
        # Completude
        'IsComplete "id"',
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        'IsComplete "provider_type"',
        # Unicidade
        'Uniqueness "id" "provider_id" "provider_type" = 1',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "tb_watch_providers_ref_movie_tmdb": [
        # Completude
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        # Unicidade
        'IsUnique "provider_id"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "tb_watch_providers_ref_tv_tmdb": [
        # Completude
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        # Unicidade
        'IsUnique "provider_id"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "tb_now_playing_movie_tmdb": [
        # Completude
        'IsComplete "id"',
        'IsComplete "title"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        'ColumnValues "vote_average" >= 0',
        'ColumnValues "vote_average" <= 10',
        # Integridade
        "RowCount > 0",
    ],
    "tb_discover_unified_tmdb": [
        # Completude
        'IsComplete "id"',
        'IsComplete "media_type"',
        'IsComplete "title"',
        # Unicidade
        'Uniqueness "id" "media_type" = 1',
        # Validade
        'ColumnValues "media_type" in ["movie", "tv"]',
        'ColumnValues "vote_average" >= 0',
        'ColumnValues "vote_average" <= 10',
        # Integridade
        "RowCount > 0",
    ],
}
