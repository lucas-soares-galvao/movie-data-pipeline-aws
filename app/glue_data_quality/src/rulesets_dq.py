"""Raciocinio: concentra regras por tabela para desacoplar validacao da logica de execucao."""

rulesets_dq = {
    "tb_configuration_countries_tmdb": [
        # iso_3166_1 é o código único do país (ex: "BR"); deve existir e ser único
        'IsComplete "iso_3166_1"',
        'IsUnique "iso_3166_1"',
        'IsComplete "english_name"',
        'IsComplete "native_name"',
        "RowCount > 0",
    ],
    "tb_configuration_languages_tmdb": [
        # iso_639_1 é o código único do idioma (ex: "pt"); deve existir e ser único
        'IsComplete "iso_639_1"',
        'IsUnique "iso_639_1"',
        'IsComplete "english_name"',
        "RowCount > 0",
    ],
    "tb_genre_movie_tmdb": [
        # Cada gênero tem um id numérico único e um nome; ambos devem estar presentes
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',
        "RowCount > 0",
    ],
    "tb_genre_tv_tmdb": [
        # Mesma estrutura dos gêneros de filme: id único + nome obrigatório
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',
        "RowCount > 0",
    ],
    "tb_discover_movie_tmdb": [
        # vote_average vem da API na escala 0-10; fora disso indica dado corrompido
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "title"',
        'ColumnValues "vote_average" between 0 and 10',
        "RowCount > 0",
    ],
    "tb_discover_tv_tmdb": [
        # Mesma validação do discover de filmes, mas o campo de título é "name" (não "title")
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',
        'ColumnValues "vote_average" between 0 and 10',
        "RowCount > 0",
    ],
    "tb_details_movie_tmdb": [
        # runtime em minutos; pode ser 0 para filmes sem duração informada, mas não negativo
        'IsComplete "id"',
        'IsUnique "id"',
        'ColumnValues "runtime" >= 0',
        "RowCount > 0",
    ],
    "tb_details_tv_tmdb": [
        # Séries devem ter ao menos 1 temporada e 1 episódio cadastrados no TMDB
        'IsComplete "id"',
        'IsUnique "id"',
        'ColumnValues "number_of_seasons" >= 1',
        'ColumnValues "number_of_episodes" >= 1',
        "RowCount > 0",
    ],
    "tb_watch_providers_movie_tmdb": [
        # provider_type indica a modalidade (flatrate, rent, buy); todos os campos são chave
        'IsComplete "id"',
        'IsComplete "provider_type"',
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        "RowCount > 0",
    ],
    "tb_watch_providers_tv_tmdb": [
        # Mesma estrutura dos provedores de filmes
        'IsComplete "id"',
        'IsComplete "provider_type"',
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        "RowCount > 0",
    ],
}
