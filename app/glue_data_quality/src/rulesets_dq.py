"""Raciocinio: concentra regras por tabela para desacoplar validacao da logica de execucao."""

rulesets_dq = {
    "tb_configuration_countries_tmdb": [
        # Exemplo de regra para a tabela de países
        'IsComplete "iso_3166_1"',
        'IsUnique "iso_3166_1"',
        'IsComplete "english_name"',
        'IsComplete "native_name"',
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
    "tb_details_movie_tmdb": [
        # Detalhes de filmes: cada linha corresponde a um ID único com runtime em minutos
        'IsComplete "id"',
        'IsUnique "id"',
        'ColumnValues "runtime" >= 0',
        "RowCount > 0",
    ],
    "tb_details_tv_tmdb": [
        # Detalhes de séries: temporadas e episódios devem ser valores positivos
        'IsComplete "id"',
        'IsUnique "id"',
        'ColumnValues "number_of_seasons" >= 1',
        'ColumnValues "number_of_episodes" >= 1',
        "RowCount > 0",
    ],
}
