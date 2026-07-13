# _setup_athena_mock() simula as 3 etapas do boto3 Athena:
#   start_query_execution → get_query_execution (polling) → get_paginator().paginate()
# O mock precisa dessas 3 chamadas encadeadas porque agent.py as chama em sequência.
#
# _mock_litellm() retorna side_effect=[step1] porque recommend() chama
# o LLM uma vez para extrair filtros como JSON (salva em cache).
# Se houver cache hit, a chamada é pulada.

import json
import logging
import time

import openai
import pytest
from unittest.mock import MagicMock, patch

import agent


FAKE_TITLE = {
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
    "tagline", "actor_names", "director", "screenplay", "music_composer",
    "producer", "cinematographer", "editor",
    "keywords_pt", "certification", "trailer_url", "collection_name",
    "production_companies", "production_countries", "networks", "created_by",
    "streaming_providers", "rent_buy_providers",
    "recommended_titles", "similar_titles", "alternative_titles",
    "in_theaters", "theater_end_date",
]


def _setup_athena_mock(mock_boto3, rows_data=None):
    """Configura o mock do boto3 para simular as tres etapas da API do Athena.

    A API nativa do Athena usada por search_titles_spec() requer:
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
    tool_call.function.name = "search_titles_spec"
    tool_call.function.arguments = json.dumps(tool_args)

    msg_step1 = MagicMock()
    msg_step1.content = None
    msg_step1.tool_calls = [tool_call]

    usage_mock = MagicMock()
    usage_mock.prompt_tokens = 100
    usage_mock.completion_tokens = 50
    usage_mock.total_tokens = 150

    step1 = MagicMock()
    step1.choices = [MagicMock(message=msg_step1)]
    step1.usage = usage_mock

    return [step1]


class TestValidateWhere:

    def test_aceita_clausula_valida(self):
        result = agent._validate_where("media_type = 'movie' AND vote_average >= 7.0")
        assert result == "media_type = 'movie' AND vote_average >= 7.0"

    def test_rejeita_ponto_e_virgula(self):
        with pytest.raises(ValueError, match="contém ';'"):
            agent._validate_where("media_type = 'movie'; DROP TABLE x")

    def test_rejeita_drop(self):
        with pytest.raises(ValueError, match="palavra SQL proibida"):
            agent._validate_where("DROP TABLE spec")

    def test_rejeita_delete(self):
        with pytest.raises(ValueError, match="palavra SQL proibida"):
            agent._validate_where("DELETE FROM spec WHERE 1=1")

    def test_rejeita_insert(self):
        with pytest.raises(ValueError, match="palavra SQL proibida"):
            agent._validate_where("1=1 INSERT INTO spec VALUES (1)")

    def test_rejeita_subquery_select(self):
        with pytest.raises(ValueError, match="contém subquery"):
            agent._validate_where("id IN (SELECT id FROM outra_tabela)")

    def test_remove_espacos_nas_pontas(self):
        result = agent._validate_where("  media_type = 'movie'  ")
        assert result == "media_type = 'movie'"


class TestSearchTitlesSpec:

    def test_retorna_lista_vazia_sem_resultados(self):
        with patch("agent.boto3") as mock_boto3:
            _setup_athena_mock(mock_boto3)
            result = agent.search_titles_spec("vote_average >= 6.0")

        assert result == []

    def test_retorna_registros_como_lista_de_dicts(self):
        with patch("agent.boto3") as mock_boto3:
            _setup_athena_mock(mock_boto3, rows_data=[FAKE_TITLE])
            result = agent.search_titles_spec("vote_average >= 6.0")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["title"] == "O Iluminado"

    def test_filtro_where_incluido_na_query(self):
        where_clause = "media_type = 'movie' AND lower(genre_names) LIKE '%terror%'"
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec(where_clause)

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "media_type = 'movie'" in executed_sql
        assert "lower(genre_names) LIKE '%terror%'" in executed_sql

    def test_vote_count_fixo_sempre_presente(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("media_type = 'movie'")

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "vote_count >= 50" in executed_sql

    def test_filtro_idioma_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("original_language = 'ko'")

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "original_language = 'ko'" in executed_sql

    def test_filtro_duracao_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("runtime_minutes <= 90 AND media_type = 'movie'")

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "runtime_minutes <= 90" in executed_sql

    def test_filtro_temporadas_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("number_of_seasons = 1 AND media_type = 'tv'")

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "number_of_seasons = 1" in executed_sql

    def test_filtro_em_cartaz_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("in_theaters = true AND media_type = 'movie'")

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "in_theaters = true" in executed_sql

    def test_filtro_plataforma_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("lower(streaming_providers) LIKE '%netflix%'")

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "lower(streaming_providers) LIKE '%netflix%'" in executed_sql

    def test_filtro_faixa_de_ano_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("year BETWEEN '2000' AND '2010'")

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "year BETWEEN '2000' AND '2010'" in executed_sql

    def test_limite_aplicado_na_query(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("vote_average >= 6.0", limit=10)

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "LIMIT 10" in executed_sql

    def test_limite_e_limitado_ao_maximo_de_10(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("vote_average >= 6.0", limit=100)

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "LIMIT 10" in executed_sql
        assert "LIMIT 100" not in executed_sql

    def test_limite_minimo_e_1(self):
        with patch("agent.boto3") as mock_boto3:
            mock_athena = _setup_athena_mock(mock_boto3)
            agent.search_titles_spec("vote_average >= 6.0", limit=0)

        executed_sql = mock_athena.start_query_execution.call_args.kwargs["QueryString"]
        assert "LIMIT 1" in executed_sql

    def test_rejeita_where_com_sql_perigoso(self):
        with pytest.raises(ValueError):
            agent.search_titles_spec("1=1; DROP TABLE spec")


class TestRecommend:

    def test_retorna_lista_vazia_se_athena_sem_resultados(self):
        with (
            patch("agent.search_titles_spec", return_value=[]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"where_clause": "media_type = 'movie'"}
            )
            result = agent.recommend("filmes de terror")

        assert result == []

    def test_chama_llm_uma_vez(self):
        with (
            patch("agent.search_titles_spec", return_value=[FAKE_TITLE]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"where_clause": "media_type = 'movie'"}
            )
            agent.recommend("filmes de terror")

        assert mock_completion.call_count == 1

    def test_retorna_lista_de_titulos(self):
        with (
            patch("agent.search_titles_spec", return_value=[FAKE_TITLE]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"where_clause": "media_type = 'movie'"}
            )
            result = agent.recommend("filmes de terror")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["title"] == "O Iluminado"

    def test_passa_filtros_extraidos_pelo_llm_para_athena(self):
        filters = {
            "where_clause": "media_type = 'movie' AND lower(genre_names) LIKE '%terror%' AND vote_average >= 7.0",
            "limit": 5,
        }
        with (
            patch("agent.search_titles_spec", return_value=[FAKE_TITLE]) as mock_search,
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(filters)
            agent.recommend("filmes de terror dos anos 80")

        mock_search.assert_called_once_with(**filters)

    def test_retorna_lista_vazia_se_llm_nao_chama_tool(self):
        msg_no_tool = MagicMock()
        msg_no_tool.content = None
        msg_no_tool.tool_calls = None

        step1_no_tool = MagicMock()
        step1_no_tool.choices = [MagicMock(message=msg_no_tool)]

        with (
            patch("agent.search_titles_spec") as mock_search,
            patch("agent.litellm.completion", return_value=step1_no_tool),
        ):
            result = agent.recommend("filmes de terror")

        assert result == []
        mock_search.assert_not_called()

    def test_retorna_data_lancamento_formatada(self):
        with (
            patch("agent.search_titles_spec", return_value=[FAKE_TITLE]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"where_clause": "media_type = 'movie'"}
            )
            result = agent.recommend("filmes de terror")

        assert "release_date" in result[0]
        assert result[0]["release_date"] == "Maio de 1980"

    def test_campos_formatados_pelo_python(self):
        with (
            patch("agent.search_titles_spec", return_value=[FAKE_TITLE]),
            patch("agent.litellm.completion") as mock_completion,
        ):
            mock_completion.side_effect = _mock_litellm(
                {"where_clause": "media_type = 'movie'"}
            )
            result = agent.recommend("filmes de terror")

        r = result[0]
        assert r["type"] == "filme"
        assert r["year"] == 1980
        assert r["genres"] == ["Terror", "Drama"]
        assert r["overview"] == "Um escritor enlouquece num hotel isolado."
        assert r["rating"] == 8.4
        assert r["duration"] == "2h 26min"
        assert r["streaming_providers"] == "Netflix"
        assert r["in_theaters"] is False


class TestCacheWhere:

    def test_chave_cache_normaliza_entrada(self):
        assert agent._cache_key("  Filmes de Terror  ") == agent._cache_key("filmes de terror")

    def test_salvar_e_buscar_cache(self):
        args = {"where_clause": "media_type = 'movie'"}
        agent._save_cached_where("filmes de terror", args)

        result = agent._get_cached_where("filmes de terror")
        assert result == args

    def test_cache_miss_retorna_none(self):
        assert agent._get_cached_where("consulta inexistente xyz") is None

    def test_cache_expirado_retorna_none(self):
        args = {"where_clause": "media_type = 'movie'"}
        agent._save_cached_where("filmes antigos", args)

        key = agent._cache_key("filmes antigos")
        agent._WHERE_CACHE[key] = (time.time() - agent._CACHE_TTL_SECONDS - 1, args)

        assert agent._get_cached_where("filmes antigos") is None
        assert key not in agent._WHERE_CACHE

    def test_cache_evita_chamada_llm_passo_1(self):
        cached_args = {"where_clause": "media_type = 'movie'"}
        agent._save_cached_where("filmes de terror", cached_args)

        with (
            patch("agent.search_titles_spec", return_value=[FAKE_TITLE]) as mock_search,
            patch("agent.litellm.completion") as mock_completion,
        ):
            result = agent.recommend("filmes de terror")

        assert mock_completion.call_count == 0
        mock_search.assert_called_once_with(**cached_args)
        assert len(result) == 1


class TestFallbackLlm:
    """Fallback automático de LLM: dispara só em falha real da chamada ao provedor
    (openai.APIError e subclasses — a classe-base real usada pelo litellm para erros
    de provedor), nunca em resposta sem tool_calls ou em erro de parsing dos argumentos."""

    def test_fallback_acionado_quando_llm_primario_falha(self):
        primary_error = openai.APIConnectionError(message="timeout", request=None)
        with (
            patch("agent.search_titles_spec", return_value=[FAKE_TITLE]),
            patch("agent.litellm.completion") as mock_completion,
            patch.object(agent, "_LLM_MODEL_FALLBACK", "bedrock/test-model"),
        ):
            mock_completion.side_effect = [
                primary_error,
                *_mock_litellm({"where_clause": "media_type = 'movie'"}),
            ]
            result = agent.recommend("filmes de terror")

        assert len(result) == 1
        assert mock_completion.call_count == 2
        second_call = mock_completion.call_args_list[1].kwargs
        assert second_call["model"] == "bedrock/test-model"
        assert "aws_region_name" in second_call

    def test_sem_fallback_configurado_propaga_erro_primario(self):
        primary_error = openai.APIConnectionError(message="timeout", request=None)
        with (
            patch("agent.litellm.completion") as mock_completion,
            patch.object(agent, "_LLM_MODEL_FALLBACK", None),
        ):
            mock_completion.side_effect = [primary_error]
            with pytest.raises(openai.APIConnectionError):
                agent.recommend("filmes de terror")

        assert mock_completion.call_count == 1

    def test_fallback_tambem_falha_propaga_erro(self):
        primary_error = openai.APIConnectionError(message="timeout", request=None)
        fallback_error = openai.APIConnectionError(message="fallback tambem falhou", request=None)
        with (
            patch("agent.litellm.completion") as mock_completion,
            patch.object(agent, "_LLM_MODEL_FALLBACK", "bedrock/test-model"),
        ):
            mock_completion.side_effect = [primary_error, fallback_error]
            with pytest.raises(openai.APIConnectionError):
                agent.recommend("filmes de terror")

        assert mock_completion.call_count == 2

    def test_resposta_sem_tool_calls_nao_aciona_fallback(self):
        msg_no_tool = MagicMock()
        msg_no_tool.content = None
        msg_no_tool.tool_calls = None
        step1_no_tool = MagicMock()
        step1_no_tool.choices = [MagicMock(message=msg_no_tool)]

        with (
            patch("agent.search_titles_spec") as mock_search,
            patch("agent.litellm.completion", return_value=step1_no_tool) as mock_completion,
            patch.object(agent, "_LLM_MODEL_FALLBACK", "bedrock/test-model"),
        ):
            result = agent.recommend("filmes de terror")

        assert result == []
        mock_search.assert_not_called()
        assert mock_completion.call_count == 1

    def test_json_invalido_no_tool_call_nao_aciona_fallback(self):
        tool_call = MagicMock()
        tool_call.id = "call_test_123"
        tool_call.function.name = "search_titles_spec"
        tool_call.function.arguments = "isso nao eh json valido"

        msg_step1 = MagicMock()
        msg_step1.content = None
        msg_step1.tool_calls = [tool_call]

        step1 = MagicMock()
        step1.choices = [MagicMock(message=msg_step1)]
        step1.usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)

        with (
            patch("agent.litellm.completion", return_value=step1) as mock_completion,
            patch.object(agent, "_LLM_MODEL_FALLBACK", "bedrock/test-model"),
        ):
            with pytest.raises(json.JSONDecodeError):
                agent.recommend("filmes de terror")

        assert mock_completion.call_count == 1

    def test_fallback_usa_regiao_bedrock_configurada(self):
        primary_error = openai.APIConnectionError(message="timeout", request=None)
        with (
            patch("agent.search_titles_spec", return_value=[FAKE_TITLE]),
            patch("agent.litellm.completion") as mock_completion,
            patch.object(agent, "_LLM_MODEL_FALLBACK", "bedrock/test-model"),
            patch.object(agent, "_AWS_REGION_BEDROCK", "us-west-2"),
        ):
            mock_completion.side_effect = [
                primary_error,
                *_mock_litellm({"where_clause": "media_type = 'movie'"}),
            ]
            agent.recommend("filmes de terror")

        second_call = mock_completion.call_args_list[1].kwargs
        assert second_call["aws_region_name"] == "us-west-2"

    def test_fallback_nao_envia_api_key_deepseek(self):
        primary_error = openai.APIConnectionError(message="timeout", request=None)
        with (
            patch("agent.search_titles_spec", return_value=[FAKE_TITLE]),
            patch("agent.litellm.completion") as mock_completion,
            patch.object(agent, "_LLM_MODEL_FALLBACK", "bedrock/test-model"),
        ):
            mock_completion.side_effect = [
                primary_error,
                *_mock_litellm({"where_clause": "media_type = 'movie'"}),
            ]
            agent.recommend("filmes de terror")

        second_call = mock_completion.call_args_list[1].kwargs
        assert "api_key" not in second_call


class TestLogTokenUsage:

    def test_loga_tokens_com_usage(self):
        response = MagicMock()
        response.usage.prompt_tokens = 100
        response.usage.completion_tokens = 50
        response.usage.total_tokens = 150

        with patch("agent.logger") as mock_logger:
            agent._log_token_usage("step1_where", response)

        mock_logger.info.assert_called_once()
        extra = mock_logger.info.call_args.kwargs["extra"]
        assert extra["prompt_tokens"] == 100
        assert extra["completion_tokens"] == 50
        assert extra["step"] == "step1_where"

    def test_nao_loga_sem_usage(self):
        response = MagicMock(spec=[])

        with patch("agent.logger") as mock_logger:
            agent._log_token_usage("step1_where", response)

        mock_logger.info.assert_not_called()

    def test_logger_tem_nivel_info_explicito(self):
        """app.py eleva o root logger para ERROR quando o CloudWatch está
        configurado; sem um nível INFO explícito aqui, esses logs seriam
        suprimidos por herança (ver seção "Observabilidade de tokens" do doc)."""
        assert agent.logger.level == logging.INFO

    def test_loga_modelo_explicito_quando_fornecido(self):
        response = MagicMock()
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 5
        response.usage.total_tokens = 15

        with patch("agent.logger") as mock_logger:
            agent._log_token_usage("step1_where_fallback", response, "bedrock/test-model")

        extra = mock_logger.info.call_args.kwargs["extra"]
        assert extra["step"] == "step1_where_fallback"
        assert extra["model"] == "bedrock/test-model"

    def test_logar_uso_tokens_usa_llm_model_por_padrao(self):
        """Regressão: a chamada de 2 argumentos usada em todo o resto do código/testes
        (sem passar `model`) precisa continuar logando o modelo primário (_LLM_MODEL)."""
        response = MagicMock()
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 5
        response.usage.total_tokens = 15

        with patch("agent.logger") as mock_logger:
            agent._log_token_usage("step1_where", response)

        extra = mock_logger.info.call_args.kwargs["extra"]
        assert extra["model"] == agent._LLM_MODEL


class TestLogLlmFallback:

    def test_loga_fallback_em_warning(self):
        error = openai.APIConnectionError(message="timeout", request=None)

        with (
            patch("agent.logger") as mock_logger,
            patch.object(agent, "_LLM_MODEL_FALLBACK", "bedrock/test-model"),
        ):
            agent._log_llm_fallback("filmes de terror", error)

        mock_logger.warning.assert_called_once()
        extra = mock_logger.warning.call_args.kwargs["extra"]
        assert extra["preference"] == "filmes de terror"
        assert extra["primary_model"] == agent._LLM_MODEL
        assert extra["fallback_model"] == "bedrock/test-model"
        assert "APIConnectionError" in extra["error"]
