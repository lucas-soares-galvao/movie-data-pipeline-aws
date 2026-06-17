"""rulesets_dq.py — Regras DQDL de qualidade de dados por tabela."""

rulesets_dq = {
    "configuration_countries": [
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
    "configuration_languages": [
        # Completude
        'IsComplete "iso_639_1"',
        'IsComplete "english_name"',
        # Unicidade
        'IsUnique "iso_639_1"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "genre_movie": [
        # Completude
        'IsComplete "id"',
        'IsComplete "name"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "genre_tv": [
        # Completude
        'IsComplete "id"',
        'IsComplete "name"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "discover_movie": [
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
    "discover_tv": [
        # Completude
        'IsComplete "id"',
        'IsComplete "name"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        'ColumnValues "vote_average" >= 0',
        'ColumnValues "vote_average" <= 10',
        # Integridade
        "RowCount > 0",
    ],
    "details_movie": [
        # Completude
        'IsComplete "id"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        'ColumnValues "runtime" >= 0',
        # Integridade
        "RowCount > 0",
    ],
    "details_tv": [
        # Completude
        'IsComplete "id"',
        # Unicidade
        'IsUnique "id"',
        # Validade
        'ColumnValues "number_of_seasons" >= 1',
        'ColumnValues "number_of_episodes" >= 1',
        # Integridade
        "RowCount > 0",
    ],
    "watch_providers_movie": [
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
    "watch_providers_tv": [
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
    "watch_providers_ref_movie": [
        # Completude
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        # Unicidade
        'IsUnique "provider_id"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "watch_providers_ref_tv": [
        # Completude
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        # Unicidade
        'IsUnique "provider_id"',
        # Validade
        # Integridade
        "RowCount > 0",
    ],
    "now_playing_movie": [
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
    "discover_unified": [
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
