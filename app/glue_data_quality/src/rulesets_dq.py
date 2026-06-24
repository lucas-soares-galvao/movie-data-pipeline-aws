"""
rulesets_dq.py — Regras DQDL de qualidade de dados por tabela.

DQDL (Data Quality Definition Language) é a linguagem de regras do AWS Glue Data Quality.
Cada regra verifica uma dimensão de qualidade dos dados:

- IsComplete "coluna"          → a coluna não pode ter valores nulos
- IsUnique "coluna"            → a coluna não pode ter valores duplicados
- Uniqueness "c1" "c2" = 1     → a combinação de colunas deve ser única
- ColumnValues "coluna" >= N   → valores devem estar dentro de um range
- ColumnValues "coluna" in [X] → valores devem pertencer a uma lista
- RowCount > 0                 → a tabela deve ter pelo menos 1 registro

As regras são agrupadas por dimensão (Completude, Unicidade, Validade, Integridade)
para facilitar a classificação automática feita em utils.py.
"""

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
