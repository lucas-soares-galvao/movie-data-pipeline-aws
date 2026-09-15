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

# Regras DQDL repetidas em várias tabelas — extraídas em constantes (python:S1192)
# para evitar duplicação de literais e ter um único ponto de ajuste por regra.
_ID_NOT_NULL = 'IsComplete "id"'
_NAME_NOT_NULL = 'IsComplete "name"'
_ID_UNIQUE = 'IsUnique "id"'
_VOTE_AVERAGE_MIN = 'ColumnValues "vote_average" >= 0'
_VOTE_AVERAGE_MAX = 'ColumnValues "vote_average" <= 10'
_POPULARITY_MIN = 'ColumnValues "popularity" >= 0'
_PROVIDER_ID_NOT_NULL = 'IsComplete "provider_id"'
_PROVIDER_NAME_NOT_NULL = 'IsComplete "provider_name"'
_ROWCOUNT_POSITIVE = "RowCount > 0"

rulesets_dq = {
    "configuration_countries": [
        # Completude
        'IsComplete "iso_3166_1"',
        'IsComplete "native_name"',
        'IsComplete "english_name"',
        'IsComplete "name_pt"',
        # Unicidade
        'IsUnique "iso_3166_1"',
        # Validade
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "configuration_languages": [
        # Completude
        'IsComplete "iso_639_1"',
        'IsComplete "english_name"',
        'IsComplete "name_pt"',
        # Unicidade
        'IsUnique "iso_639_1"',
        # Validade
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "genre_movie": [
        # Completude
        _ID_NOT_NULL,
        _NAME_NOT_NULL,
        # Unicidade
        _ID_UNIQUE,
        # Validade
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "genre_tv": [
        # Completude
        _ID_NOT_NULL,
        _NAME_NOT_NULL,
        # Unicidade
        _ID_UNIQUE,
        # Validade
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "discover_movie": [
        # Completude
        _ID_NOT_NULL,
        'IsComplete "title"',
        # Unicidade
        _ID_UNIQUE,
        # Validade
        _VOTE_AVERAGE_MIN,
        _VOTE_AVERAGE_MAX,
        _POPULARITY_MIN,
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "discover_tv": [
        # Completude
        _ID_NOT_NULL,
        _NAME_NOT_NULL,
        # Unicidade
        _ID_UNIQUE,
        # Validade
        _VOTE_AVERAGE_MIN,
        _VOTE_AVERAGE_MAX,
        _POPULARITY_MIN,
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "details_movie": [
        # Completude
        _ID_NOT_NULL,
        # Unicidade
        _ID_UNIQUE,
        # Validade
        'ColumnValues "runtime" >= 0',
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "details_tv": [
        # Completude
        _ID_NOT_NULL,
        # Unicidade
        _ID_UNIQUE,
        # Validade
        'ColumnValues "number_of_seasons" >= 1',
        'ColumnValues "number_of_episodes" >= 1',
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "watch_providers_movie": [
        # Completude
        _ID_NOT_NULL,
        _PROVIDER_ID_NOT_NULL,
        _PROVIDER_NAME_NOT_NULL,
        'IsComplete "provider_type"',
        # Unicidade
        'Uniqueness "id" "provider_id" "provider_type" = 1',
        # Validade
        'ColumnValues "provider_type" in ["flatrate", "rent", "buy"]',
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "watch_providers_tv": [
        # Completude
        _ID_NOT_NULL,
        _PROVIDER_ID_NOT_NULL,
        _PROVIDER_NAME_NOT_NULL,
        'IsComplete "provider_type"',
        # Unicidade
        'Uniqueness "id" "provider_id" "provider_type" = 1',
        # Validade
        'ColumnValues "provider_type" in ["flatrate", "rent", "buy"]',
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "watch_providers_ref_movie": [
        # Completude
        _PROVIDER_ID_NOT_NULL,
        _PROVIDER_NAME_NOT_NULL,
        'IsComplete "canonical_name"',
        # Unicidade
        'IsUnique "provider_id"',
        # Validade
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "watch_providers_ref_tv": [
        # Completude
        _PROVIDER_ID_NOT_NULL,
        _PROVIDER_NAME_NOT_NULL,
        'IsComplete "canonical_name"',
        # Unicidade
        'IsUnique "provider_id"',
        # Validade
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "now_playing_movie": [
        # Completude
        _ID_NOT_NULL,
        'IsComplete "theater_start_date"',
        'IsComplete "theater_end_date"',
        # Unicidade
        _ID_UNIQUE,
        # Validade
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
    "discover_unified": [
        # Completude
        _ID_NOT_NULL,
        'IsComplete "media_type"',
        'IsComplete "title"',
        'IsComplete "year"',
        # Unicidade
        'Uniqueness "id" "media_type" = 1',
        # Validade
        'ColumnValues "media_type" in ["movie", "tv"]',
        _VOTE_AVERAGE_MIN,
        _VOTE_AVERAGE_MAX,
        _POPULARITY_MIN,
        # Integridade
        _ROWCOUNT_POSITIVE,
    ],
}
