# _setup_athena_mock() simula as 3 etapas do boto3 Athena:
#   start_query_execution → get_query_execution (polling) → get_paginator().paginate()
# O mock precisa dessas 3 chamadas encadeadas porque agent.py as chama em sequência.
#
# _mock_litellm() retorna side_effect=[passo1] porque recomendar() chama
# o LLM uma vez para extrair filtros como JSON (salva em cache).
# Se houver cache hit, a chamada é pulada.

import json
import time

import pytest
from unittest.mock import MagicMock, patch

import agent


TITULO_FAKE = {
    "title": "O Iluminado",
    "media_type": "movie",
    "year": "1980",
    "genre_names": "Terror, Drama",
    "overview": "Um escritor enlouquece num hotel isolado.",
    "vote_average": 8.4,
    "poster_url": "https://example.com/poster.jpg",
    "backdrop_url": None,
    "runtime_minutes": 146,
    "number_of_seasons": None,
    "number_of_episodes": None,
    "episode_runtime_minutes": None,
    "streaming_providers": "Netflix",
    "air_date": "1980-05-23",
    "in_theaters": "false",
    "theater_end_date": None,
}

COLUMNS = [
    "title", "media_type", "year", "air_date", "genre_names", "overview",
    "vote_average", "poster_url", "backdrop_url",
    "runtime_minutes", "number_of_seasons",
    "number_of_episodes", "episode_runtime_minutes",
    "streaming_providers",
    "in_theaters", "theater_end_date",
]


def _setup_athena_mock(mock_boto3, rows_data=None):
    """Configura o mock do boto3 para simular as tres etapas da API do Athena.

    A API nativa do Athena usada por buscar_titulos_spec() requer:
      1. start_query_execution() → inicia a query, retorna QueryExecutionId
      2. get_query_execution()   → polling ate o estado ser SUCCEEDED
      3. get_paginator().paginate() → le os resultados paginados

    Args:
        mock_boto3:  Mock do modulo boto3 injetado via @patch("agent.boto3").
        rows_data:   Lista de dicts com os dados de cada linha a retornar.
                     None ou lista vazia → retorna apenas o header (resultado vazio).

    Returns:
        mock_athena: Mock do client Athena (boto3.client("athena", ...)).
    """
    mock_athena = MagicMock()
    mock_boto3.client.return_value = mock_athena

    mock_athena.start_query_execution.return_value = {"QueryExecutionId": "test-exec-id"}
    mock_athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
    }

    header = {"Data": [{"VarCharValue": col} for col in COLUMNS]}
    if rows_data:
        data_rows = [
            {"Data": [{"VarCharValue": str(row.get(col) or "")} for col in COLUMNS]}
            for row in rows_data
        ]
        page = {"ResultSet": {"Rows": [header] + data_rows}}
    else:
        page = {"ResultSet": {"Rows": [header]}}

    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [page]
    mock_athena.get_paginator.return_value = mock_paginator

    return mock_athena


def _mock_litellm(tool_args: dict):
    """Retorna lista com 1 resposta para o side_effect de litellm.completion."""
    tool_call = MagicMock()
    tool_call.id = "call_test_123"
    tool_call.function.name = "buscar_titulos_spec"
    tool_call.function.arguments = json.dumps(tool_args)

    msg_passo1 = MagicMock()
    msg_passo1.content = None
    msg_passo1.tool_calls = [tool_call]

    usage_mock = MagicMock()
    usage_mock.prompt_tokens = 100
    usage_mock.completion_tokens = 50
    usage_mock.total_tokens = 150

    passo1 = MagicMock()
    passo1.choices = [MagicMock(message=msg_passo1)]
    passo1.usage = usage_mock

    return [passo1]


class TestValidarWhere:

    def test_aceita_clausula_valida(self):
        resultado = agent._validar_where("media_type = 'movie' AND vote_average >= 7.0")
        assert resultado == "media_type = 'movie' AND vote_average >= 7.0"

    def test_rejeita_ponto_e_virgula(self):
        with pytest.raises(ValueError, match="contém ';'"):
            agent._validar_where("media_type = 'movie'; DROP TABLE x")

    def test_rejeita_drop(self):
        with pytest.raises(ValueError, match="palavra SQL proibida"):
            agent._validar_where("DROP TABLE spec")

    def test_rejeita_delete(self):
        with pytest.raises(ValueError, match="palavra SQL proibida"):
            agent._validar_where("DELETE FROM spec WHERE 1=1")

    def test_rejeita_insert(self):
        with pytest.raises(ValueError, match="palavra SQL proibida"):
            agent._validar_where("1=1 INSERT INTO spec VALUES (1)")

    def test_rejeita_subquery_select(self):
        with pytest.raises(ValueError, match="contém subquery"):
            agent._validar_where("id IN (SELECT id FROM outra_tabela)")

    def test_remove_espacos_nas_pontas(self):
        resultado = agent._validar_where("  media_type = 'movie'  ")
        assert resultado == "media_type = 'movie'"


class TestBuscarTitulosSpec:

    def test_retorna_lista_vazia_sem_resultados(self):
        with patch("agent.boto3") as mock_boto3:
            _setup_athena_mock(mock_boto3)
            resultado = agent.buscar_titulos_spec("vote_average >= 6.0")

        assert resultado == []

    def test_retorna_registros_como_lista_de_dicts(self):
        with patch("agent.boto3") as mock_boto3:
            _setup_athena_mock(mock_boto3, rows_data=[TITULO_FAKE])
            resultado = agent.buscar_titulos_spec("vote_average >= 6.0")

        assert isinstance(resultado, list)
        assert len(resultado) == 1
        assert resultado[0]["title"] == "O Iluminado"

    def test_filtro_where_incluido_na_query(self):
        filtro = "media_type = 'movie' AND lower(genre_names) LIKE '%terror%'"
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec(filtro)

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "media_type = 'movie'" in sql_executado
        assert "lower(genre_names) LIKE '%terror%'" in sql_executado

    def test_vote_count_fixo_sempre_presente(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("media_type = 'movie'")

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "vote_count >= 50" in sql_executado

    def test_filtro_idioma_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("original_language = 'ko'")

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "original_language = 'ko'" in sql_executado

    def test_filtro_duracao_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("runtime_minutes <= 90 AND media_type = 'movie'")

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "runtime_minutes <= 90" in sql_executado

    def test_filtro_temporadas_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("number_of_seasons = 1 AND media_type = 'tv'")

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "number_of_seasons = 1" in sql_executado

    def test_filtro_em_cartaz_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("in_theaters = true AND media_type = 'movie'")

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "in_theaters = true" in sql_executado

    def test_filtro_plataforma_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("lower(streaming_providers) LIKE '%netflix%'")

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "lower(streaming_providers) LIKE '%netflix%'" in sql_executado

    def test_filtro_faixa_de_ano_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("year BETWEEN '2000' AND '2010'")

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "year BETWEEN '2000' AND '2010'" in sql_executado

    def test_limite_aplicado_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("vote_average >= 6.0", limite=10)

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "LIMIT 10" in sql_executado

    def test_limite_e_limitado_ao_maximo_de_10(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("vote_average >= 6.0", limite=100)

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "LIMIT 10" in sql_executado
        assert "LIMIT 100" not in sql_executado

    def test_limite_minimo_e_1(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.buscar_titulos_spec("vote_average >= 6.0", limite=0)

        sql_executado = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "LIMIT 1" in sql_executado

    def test_rejeita_where_com_sql_perigoso(self):
        with pytest.raises(ValueError):
            agent.buscar_titulos_spec("1=1; DROP TABLE spec")


class TestRecomendar:

    def test_retorna_lista_vazia_se_athena_sem_resultados(self):
        with (
            patch("agent.buscar_titulos_spec", return_value=[]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"filtro_where": "media_type = 'movie'"}
            )
            resultado = agent.recomendar("filmes de terror")

        assert resultado == []

    def test_chama_llm_uma_vez(self):
        with (
            patch("agent.buscar_titulos_spec", return_value=[TITULO_FAKE]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"filtro_where": "media_type = 'movie'"}
            )
            agent.recomendar("filmes de terror")

        assert mock_completion.call_count == 1

    def test_retorna_lista_de_titulos(self):
        with (
            patch("agent.buscar_titulos_spec", return_value=[TITULO_FAKE]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"filtro_where": "media_type = 'movie'"}
            )
            resultado = agent.recomendar("filmes de terror")

        assert isinstance(resultado, list)
        assert len(resultado) == 1
        assert resultado[0]["titulo"] == "O Iluminado"

    def test_passa_filtros_extraidos_pelo_llm_para_athena(self):
        filtros = {
            "filtro_where": "media_type = 'movie' AND lower(genre_names) LIKE '%terror%' AND vote_average >= 7.0",
            "limite": 5,
        }
        with (
            patch("agent.buscar_titulos_spec", return_value=[TITULO_FAKE]) as mock_buscar,
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(filtros)
            agent.recomendar("filmes de terror dos anos 80")

        mock_buscar.assert_called_once_with(**filtros)

    def test_retorna_lista_vazia_se_llm_nao_chama_tool(self):
        msg_sem_tool = MagicMock()
        msg_sem_tool.content = None
        msg_sem_tool.tool_calls = None

        passo1_sem_tool = MagicMock()
        passo1_sem_tool.choices = [MagicMock(message=msg_sem_tool)]

        with (
            patch("agent.buscar_titulos_spec") as mock_buscar,
            patch("agent.litellm.completion", return_value=passo1_sem_tool),
        ):
            resultado = agent.recomendar("filmes de terror")

        assert resultado == []
        mock_buscar.assert_not_called()

    def test_retorna_data_lancamento_formatada(self):
        with (
            patch("agent.buscar_titulos_spec", return_value=[TITULO_FAKE]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"filtro_where": "media_type = 'movie'"}
            )
            resultado = agent.recomendar("filmes de terror")

        assert "data_lancamento" in resultado[0]
        assert resultado[0]["data_lancamento"] == "Maio de 1980"

    def test_campos_formatados_pelo_python(self):
        with (
            patch("agent.buscar_titulos_spec", return_value=[TITULO_FAKE]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"filtro_where": "media_type = 'movie'"}
            )
            resultado = agent.recomendar("filmes de terror")

        r = resultado[0]
        assert r["tipo"] == "filme"
        assert r["ano"] == 1980
        assert r["generos"] == ["Terror", "Drama"]
        assert r["sinopse"] == "Um escritor enlouquece num hotel isolado."
        assert r["nota"] == 8.4
        assert r["duracao"] == "2h 26min"
        assert r["streaming_providers"] == "Netflix"
        assert r["in_theaters"] is False


class TestCacheWhere:

    def test_chave_cache_normaliza_entrada(self):
        assert agent._chave_cache("  Filmes de Terror  ") == agent._chave_cache("filmes de terror")

    def test_salvar_e_buscar_cache(self):
        args = {"filtro_where": "media_type = 'movie'"}
        agent._salvar_cache_where("filmes de terror", args)

        resultado = agent._buscar_cache_where("filmes de terror")
        assert resultado == args

    def test_cache_miss_retorna_none(self):
        assert agent._buscar_cache_where("consulta inexistente xyz") is None

    def test_cache_expirado_retorna_none(self):
        args = {"filtro_where": "media_type = 'movie'"}
        agent._salvar_cache_where("filmes antigos", args)

        chave = agent._chave_cache("filmes antigos")
        agent._CACHE_WHERE[chave] = (time.time() - agent._CACHE_TTL_SEGUNDOS - 1, args)

        assert agent._buscar_cache_where("filmes antigos") is None
        assert chave not in agent._CACHE_WHERE

    def test_cache_evita_chamada_llm_passo_1(self):
        args_cached = {"filtro_where": "media_type = 'movie'"}
        agent._salvar_cache_where("filmes de terror", args_cached)

        with (
            patch("agent.buscar_titulos_spec", return_value=[TITULO_FAKE]) as mock_buscar,
            patch("agent.litellm.completion") as mock_completion,
        ):
            resultado = agent.recomendar("filmes de terror")

        assert mock_completion.call_count == 0
        mock_buscar.assert_called_once_with(**args_cached)
        assert len(resultado) == 1


class TestLogarUsoTokens:

    def test_loga_tokens_com_usage(self):
        resposta = MagicMock()
        resposta.usage.prompt_tokens = 100
        resposta.usage.completion_tokens = 50
        resposta.usage.total_tokens = 150

        with patch("agent.logger") as mock_logger:
            agent._logar_uso_tokens("passo_1_where", resposta)

        mock_logger.info.assert_called_once()
        extra = mock_logger.info.call_args.kwargs["extra"]
        assert extra["prompt_tokens"] == 100
        assert extra["completion_tokens"] == 50
        assert extra["etapa"] == "passo_1_where"

    def test_nao_loga_sem_usage(self):
        resposta = MagicMock(spec=[])

        with patch("agent.logger") as mock_logger:
            agent._logar_uso_tokens("passo_1_where", resposta)

        mock_logger.info.assert_not_called()


class TestLimparDuracao:
    def test_retorna_vazio_para_string_vazia(self):
        assert agent.limpar_duracao("") == ""

    def test_remove_null_isolado(self):
        assert agent.limpar_duracao("~null") == ""

    def test_remove_null_no_fim(self):
        assert agent.limpar_duracao("3 temporadas · ~null") == "3 temporadas"

    def test_remove_null_no_inicio(self):
        assert agent.limpar_duracao("~null · 36 eps") == "36 eps"

    def test_remove_multiplos_nulls(self):
        assert agent.limpar_duracao("~null · 36 eps · ~null") == "36 eps"

    def test_preserva_duracao_normal(self):
        assert agent.limpar_duracao("2h 26min") == "2h 26min"

    def test_preserva_duracao_composta(self):
        assert agent.limpar_duracao("3 temporadas · 36 eps · 45min") == "3 temporadas · 36 eps · 45min"

    def test_remove_separadores_vazios(self):
        assert agent.limpar_duracao(" · 36 eps · ") == "36 eps"


class TestFormatarTipo:
    def test_movie_para_filme(self):
        assert agent._formatar_tipo("movie") == "filme"

    def test_tv_para_serie(self):
        assert agent._formatar_tipo("tv") == "série"

    def test_valor_desconhecido(self):
        assert agent._formatar_tipo("outro") == "outro"


class TestFormatarGeneros:
    def test_separa_por_virgula(self):
        assert agent._formatar_generos("Terror, Drama") == ["Terror", "Drama"]

    def test_retorna_lista_vazia_para_none(self):
        assert agent._formatar_generos(None) == []

    def test_retorna_lista_vazia_para_string_vazia(self):
        assert agent._formatar_generos("") == []


class TestFormatarDuracaoTitulo:
    def test_filme_com_duracao(self):
        reg = {"media_type": "movie", "runtime_minutes": 146}
        assert agent._formatar_duracao_titulo(reg) == "2h 26min"

    def test_filme_sem_duracao(self):
        reg = {"media_type": "movie", "runtime_minutes": None}
        assert agent._formatar_duracao_titulo(reg) is None

    def test_filme_menos_de_uma_hora(self):
        reg = {"media_type": "movie", "runtime_minutes": 45}
        assert agent._formatar_duracao_titulo(reg) == "45min"

    def test_serie_completa(self):
        reg = {
            "media_type": "tv",
            "number_of_seasons": 3,
            "number_of_episodes": 36,
            "episode_runtime_minutes": 45,
        }
        assert agent._formatar_duracao_titulo(reg) == "3 temporadas · 36 eps · ~45 min/ep"

    def test_serie_sem_episode_runtime(self):
        reg = {
            "media_type": "tv",
            "number_of_seasons": 2,
            "number_of_episodes": 20,
            "episode_runtime_minutes": None,
        }
        assert agent._formatar_duracao_titulo(reg) == "2 temporadas · 20 eps"

    def test_serie_uma_temporada(self):
        reg = {
            "media_type": "tv",
            "number_of_seasons": 1,
            "number_of_episodes": 10,
            "episode_runtime_minutes": None,
        }
        assert agent._formatar_duracao_titulo(reg) == "1 temporada · 10 eps"

    def test_serie_sem_dados(self):
        reg = {
            "media_type": "tv",
            "number_of_seasons": None,
            "number_of_episodes": None,
            "episode_runtime_minutes": None,
        }
        assert agent._formatar_duracao_titulo(reg) is None


class TestFormatarDataLancamento:
    def test_data_valida(self):
        assert agent._formatar_data_lancamento("1980-05-23") == "Maio de 1980"

    def test_data_none(self):
        assert agent._formatar_data_lancamento(None) is None

    def test_data_vazia(self):
        assert agent._formatar_data_lancamento("") is None

    def test_data_curta(self):
        assert agent._formatar_data_lancamento("1980") is None


class TestFormatarTheaterEndDate:
    def test_em_cartaz_com_data(self):
        assert agent._formatar_theater_end_date("2025-07-15", True) == "15/07/2025"

    def test_fora_de_cartaz(self):
        assert agent._formatar_theater_end_date("2025-07-15", False) is None

    def test_em_cartaz_sem_data(self):
        assert agent._formatar_theater_end_date(None, True) is None


class TestFormatarNota:
    def test_float_valido(self):
        assert agent._formatar_nota(8.4) == 8.4

    def test_string_valida(self):
        assert agent._formatar_nota("7.5") == 7.5

    def test_none(self):
        assert agent._formatar_nota(None) is None

    def test_string_vazia(self):
        assert agent._formatar_nota("") is None


class TestFormatarRegistro:
    def test_registro_completo_filme(self):
        resultado = agent._formatar_registro(TITULO_FAKE)
        assert resultado["titulo"] == "O Iluminado"
        assert resultado["tipo"] == "filme"
        assert resultado["ano"] == 1980
        assert resultado["generos"] == ["Terror", "Drama"]
        assert resultado["sinopse"] == "Um escritor enlouquece num hotel isolado."
        assert resultado["nota"] == 8.4
        assert resultado["poster_url"] == "https://example.com/poster.jpg"
        assert resultado["backdrop_url"] is None
        assert resultado["duracao"] == "2h 26min"
        assert resultado["data_lancamento"] == "Maio de 1980"
        assert resultado["streaming_providers"] == "Netflix"
        assert resultado["in_theaters"] is False
        assert resultado["theater_end_date"] is None

    def test_registro_serie(self):
        serie = {
            "title": "Stranger Things",
            "media_type": "tv",
            "year": "2016",
            "genre_names": "Drama, Ficção Científica",
            "overview": "Um garoto desaparece.",
            "vote_average": "8.6",
            "poster_url": None,
            "backdrop_url": None,
            "runtime_minutes": None,
            "number_of_seasons": "4",
            "number_of_episodes": "34",
            "episode_runtime_minutes": "50",
            "streaming_providers": "Netflix",
            "air_date": "2016-07-15",
            "in_theaters": "false",
            "theater_end_date": None,
        }
        resultado = agent._formatar_registro(serie)
        assert resultado["tipo"] == "série"
        assert resultado["duracao"] == "4 temporadas · 34 eps · ~50 min/ep"
