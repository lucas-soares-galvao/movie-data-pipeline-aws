"""rulesets_dq.py — Regras DQDL de qualidade de dados por tabela."""

rulesets_dq = {
    "tb_configuration_countries_tmdb": [
        'IsComplete "iso_3166_1"',
        'IsUnique "iso_3166_1"',
        'IsComplete "english_name"',
        'IsComplete "native_name"',
        "RowCount > 0",
    ],
    "tb_configuration_languages_tmdb": [
        'IsComplete "iso_639_1"',
        'IsUnique "iso_639_1"',
        'IsComplete "english_name"',
        "RowCount > 0",
    ],
    "tb_genre_movie_tmdb": [
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',
        "RowCount > 0",
    ],
    "tb_genre_tv_tmdb": [
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',
        "RowCount > 0",
    ],
    "tb_discover_movie_tmdb": [
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "title"',
        'ColumnValues "vote_average" between 0 and 10',
        "RowCount > 0",
    ],
    "tb_discover_tv_tmdb": [
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',  # séries usam "name", não "title"
        'ColumnValues "vote_average" between 0 and 10',
        "RowCount > 0",
    ],
    "tb_details_movie_tmdb": [
        'IsComplete "id"',
        'IsUnique "id"',
        # runtime pode ser 0 (duração não informada pela API), mas nunca negativo
        'ColumnValues "runtime" >= 0',
        "RowCount > 0",
    ],
    "tb_details_tv_tmdb": [
        'IsComplete "id"',
        'IsUnique "id"',
        'ColumnValues "number_of_seasons" >= 1',   # série ativa deve ter ao menos 1 temporada
        'ColumnValues "number_of_episodes" >= 1',  # série deve ter ao menos 1 episódio cadastrado
        "RowCount > 0",
    ],
    "tb_watch_providers_movie_tmdb": [
        'IsComplete "id"',
        'IsComplete "provider_type"',
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        "RowCount > 0",
    ],
    "tb_watch_providers_tv_tmdb": [
        'IsComplete "id"',
        'IsComplete "provider_type"',
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        "RowCount > 0",
    ],
    "tb_watch_providers_ref_movie_tmdb": [
        'IsComplete "provider_id"',
        'IsUnique "provider_id"',
        'IsComplete "provider_name"',
        "RowCount > 0",
    ],
    "tb_watch_providers_ref_tv_tmdb": [
        'IsComplete "provider_id"',
        'IsUnique "provider_id"',
        'IsComplete "provider_name"',
        "RowCount > 0",
    ],
}
