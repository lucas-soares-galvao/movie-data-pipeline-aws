"""Raciocinio: concentra regras por tabela para desacoplar validacao da logica de execucao."""

rulesets_dq = {
    "tb_configuration_countries_tmdb": [
        # Exemplo de regra para a tabela de países
        'IsComplete "iso_3166_1"',
        'IsUnique "iso_3166_1"',
        'IsComplete "english_name"',
        'IsComplete "name"',
        "RowCount > 0",
    ],
    "tb_configuration_languages_tmdb": [
        # Exemplo de regra para a tabela de idiomas
        'IsComplete "iso_639_1"',
        'IsUnique "iso_639_1"',
        'IsComplete "english_name"',
        "RowCount > 0",
    ],
    "tb_genre_movie_tmdb": [
        # Exemplo de regra para a tabela de gêneros de filmes
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',
        "RowCount > 0",
    ],
    "tb_genre_tv_tmdb": [
        # Exemplo de regra para a tabela de gêneros de TV
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',
        "RowCount > 0",
    ],
    "tb_discover_movie_tmdb": [
        # Exemplo de regra para a tabela de filmes descobertos
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "title"',
        'ColumnValues "vote_average" between 0 and 10',
        "RowCount > 0",
    ],
    "tb_discover_tv_tmdb": [
        # Exemplo de regra para a tabela de séries descobertas
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',
        'ColumnValues "vote_average" between 0 and 10',
        "RowCount > 0",
    ],
}
