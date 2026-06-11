"""
rulesets_dq.py — Regras de Qualidade de Dados por Tabela

==============================================================================
O QUE SÃO RULESETS?
==============================================================================
Um "ruleset" (conjunto de regras) define os critérios que os dados de uma
tabela devem satisfazer para serem considerados de qualidade.

LINGUAGEM DQDL (Data Quality Definition Language):
O AWS Glue Data Quality usa uma linguagem própria para escrever regras.
Cada regra é uma string que o Glue avalia e marca como "Passed" ou "Failed".

TIPOS DE REGRAS USADAS NESTE PROJETO:

  IsComplete "coluna"
  → A coluna não pode ter valores nulos (NULL)
  → Exemplo: IsComplete "id" → todo registro DEVE ter um ID

  IsUnique "coluna"
  → Cada valor da coluna deve aparecer apenas uma vez (sem duplicatas)
  → Exemplo: IsUnique "id" → não podem existir dois filmes com o mesmo ID

  ColumnValues "coluna" between X and Y
  → O valor da coluna deve estar dentro do intervalo [X, Y]
  → Exemplo: ColumnValues "vote_average" between 0 and 10

  ColumnValues "coluna" >= N
  → O valor da coluna deve ser maior ou igual a N
  → Exemplo: ColumnValues "runtime" >= 0 (duração não pode ser negativa)

  RowCount > 0
  → A tabela não pode estar completamente vazia
  → Garante que o processamento produziu ao menos um registro

==============================================================================
ORGANIZAÇÃO:
==============================================================================
Este dicionário mapeia: nome_da_tabela → lista de regras.
O job de Data Quality usa get_ruleset(table_name) para buscar as regras
correspondentes à tabela que está sendo validada.

Centralizar as regras aqui (em vez de espalhar pelo código) facilita:
- Revisar e auditar todas as regras em um só lugar
- Adicionar novas tabelas sem modificar a lógica de execução
- Documentar o que cada regra significa (via comentários)
==============================================================================
"""

# ==============================================================================
# RULESETS: mapeamento table_name → lista de regras DQDL
# ==============================================================================
rulesets_dq = {

    # ==========================================================================
    # TABELA: tb_configuration_countries_tmdb
    # Dados: Lista de países suportados pelo TMDB
    # Ex: {"iso_3166_1": "BR", "english_name": "Brazil", "native_name": "Brasil"}
    # ==========================================================================
    "tb_configuration_countries_tmdb": [
        'IsComplete "iso_3166_1"',   # Código ISO do país (ex: "BR", "US") — obrigatório
        'IsUnique "iso_3166_1"',     # Cada país aparece apenas uma vez na lista
        'IsComplete "english_name"', # Nome em inglês do país — obrigatório para joins
        'IsComplete "native_name"',  # Nome nativo do país — obrigatório para exibição
        "RowCount > 0",              # A lista não pode estar vazia
    ],

    # ==========================================================================
    # TABELA: tb_configuration_languages_tmdb
    # Dados: Lista de idiomas suportados pelo TMDB
    # Ex: {"iso_639_1": "pt", "english_name": "Portuguese", "name": "Português"}
    # ==========================================================================
    "tb_configuration_languages_tmdb": [
        'IsComplete "iso_639_1"',    # Código ISO do idioma (ex: "pt", "en") — obrigatório
        'IsUnique "iso_639_1"',      # Cada idioma aparece apenas uma vez
        'IsComplete "english_name"', # Nome em inglês — obrigatório para joins
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_genre_movie_tmdb
    # Dados: Lista de gêneros de filmes
    # Ex: {"id": 28, "name": "Ação"}, {"id": 12, "name": "Aventura"}
    # ==========================================================================
    "tb_genre_movie_tmdb": [
        'IsComplete "id"',   # ID numérico do gênero — obrigatório (chave de join)
        'IsUnique "id"',     # Cada gênero tem ID único na tabela
        'IsComplete "name"', # Nome do gênero — obrigatório para exibição
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_genre_tv_tmdb
    # Dados: Lista de gêneros de séries
    # Mesma estrutura dos gêneros de filmes, mas com IDs diferentes
    # ==========================================================================
    "tb_genre_tv_tmdb": [
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_discover_movie_tmdb
    # Dados: Lista de filmes populares por ano, coletados pelo discover
    # Ex: {"id": 123, "title": "Avatar", "vote_average": 7.8, "release_date": "2022-12-16"}
    # ==========================================================================
    "tb_discover_movie_tmdb": [
        'IsComplete "id"',                           # ID único do filme na TMDB
        'IsUnique "id"',                             # Sem filmes duplicados
        'IsComplete "title"',                        # Título — obrigatório para exibição
        'ColumnValues "vote_average" between 0 and 10',  # Nota de 0 a 10 (escala da TMDB)
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_discover_tv_tmdb
    # Dados: Lista de séries populares por ano
    # DIFERENÇA: séries usam "name" em vez de "title" na API TMDB
    # ==========================================================================
    "tb_discover_tv_tmdb": [
        'IsComplete "id"',
        'IsUnique "id"',
        'IsComplete "name"',                         # Séries usam "name" (não "title")
        'ColumnValues "vote_average" between 0 and 10',
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_details_movie_tmdb
    # Dados: Detalhes adicionais de filmes (buscados individualmente na API)
    # Ex: {"id": 123, "runtime": 162} → Avatar tem 162 minutos de duração
    # ==========================================================================
    "tb_details_movie_tmdb": [
        'IsComplete "id"',                # ID do filme — obrigatório para o join com discover
        'IsUnique "id"',                  # Cada filme aparece uma vez na tabela de detalhes
        'ColumnValues "runtime" >= 0',    # Duração em minutos — pode ser 0 (não informado),
                                          # mas nunca negativo (indica dado corrompido)
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_details_tv_tmdb
    # Dados: Detalhes adicionais de séries
    # Ex: {"id": 1399, "number_of_seasons": 8, "number_of_episodes": 73}
    # ==========================================================================
    "tb_details_tv_tmdb": [
        'IsComplete "id"',
        'IsUnique "id"',
        'ColumnValues "number_of_seasons" >= 1',   # Série ativa deve ter ao menos 1 temporada
        'ColumnValues "number_of_episodes" >= 1',  # Série deve ter ao menos 1 episódio cadastrado
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_watch_providers_movie_tmdb
    # Dados: Plataformas de streaming disponíveis no Brasil para cada filme
    # Ex: {"id": 123, "provider_type": "flatrate", "provider_id": 8, "provider_name": "Netflix"}
    # ==========================================================================
    "tb_watch_providers_movie_tmdb": [
        'IsComplete "id"',           # ID do filme a que o provider pertence
        'IsComplete "provider_type"', # Tipo: "flatrate" (assinatura), "rent" (aluguel), "buy" (compra)
        'IsComplete "provider_id"',  # ID numérico da plataforma
        'IsComplete "provider_name"', # Nome da plataforma (ex: "Netflix")
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_watch_providers_tv_tmdb
    # Dados: Plataformas disponíveis no Brasil para cada série
    # Mesma estrutura dos watch providers de filmes
    # ==========================================================================
    "tb_watch_providers_tv_tmdb": [
        'IsComplete "id"',
        'IsComplete "provider_type"',
        'IsComplete "provider_id"',
        'IsComplete "provider_name"',
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_watch_providers_ref_movie_tmdb
    # Dados: Lista de referência de todas as plataformas disponíveis (não por filme)
    # Ex: {"provider_id": 8, "provider_name": "Netflix", "logo_path": "/logo.png"}
    # ==========================================================================
    "tb_watch_providers_ref_movie_tmdb": [
        'IsComplete "provider_id"',  # ID único da plataforma (chave de join)
        'IsUnique "provider_id"',    # Cada plataforma aparece uma única vez
        'IsComplete "provider_name"', # Nome obrigatório para exibição
        "RowCount > 0",
    ],

    # ==========================================================================
    # TABELA: tb_watch_providers_ref_tv_tmdb
    # Dados: Lista de referência de plataformas para séries
    # ==========================================================================
    "tb_watch_providers_ref_tv_tmdb": [
        'IsComplete "provider_id"',
        'IsUnique "provider_id"',
        'IsComplete "provider_name"',
        "RowCount > 0",
    ],
}
