import os
from unittest.mock import MagicMock, patch

os.environ.setdefault(
    "TMDB_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123:secret:tmdb-test"
)
os.environ.setdefault("GLUE_ETL_JOB_NAME", "test-glue-etl-job")
os.environ.setdefault("S3_BUCKET_SOR", "test-bucket-sor")

import main  # noqa: E402


EVENTO_MOVIE = {
    "type": "movie",
    "database": "tmdb_db",
    "database_unified": "tmdb_unified_db",
    "table_discover_movie": "discover_movie",
    "table_genre_movie": "genre_movie",
    "table_configuration_languages": "configuration_languages",
    "table_watch_providers_ref_movie": "watch_providers_ref_movie",
}

EVENTO_TV = {
    "type": "tv",
    "database": "tmdb_db",
    "database_unified": "tmdb_unified_db",
    "table_discover_tv": "discover_tv",
    "table_genre_tv": "genre_tv",
    "table_configuration_countries": "configuration_countries",
    "table_watch_providers_ref_tv": "watch_providers_ref_tv",
}

EVENTO_NOW_PLAYING = {
    **EVENTO_MOVIE,
    "table_now_playing_movie": "now_playing_movie",
}


def _run(event, *, year=2025):
    """Executa main.lambda_handler com todos os colaboradores mockados."""
    mock_context = MagicMock()
    with (
        patch("main.trigger_glue_job") as mock_trigger,
        patch("main.collect_now_playing_data") as mock_now_playing,
        patch("main.collect_discover_data") as mock_discover,
        patch("main.collect_watch_providers_ref") as mock_watch_ref,
        patch("main.collect_configuration_data") as mock_config,
        patch("main.collect_genre_data") as mock_genre,
        patch("main.get_api_secret", return_value="api-key-teste"),
        patch("main.boto3"),
        patch("main.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.year = year
        result = main.lambda_handler(event, mock_context)

    return {
        "result": result,
        "mock_trigger": mock_trigger,
        "mock_discover": mock_discover,
        "mock_genre": mock_genre,
        "mock_config": mock_config,
        "mock_watch_ref": mock_watch_ref,
        "mock_now_playing": mock_now_playing,
        "mock_dt": mock_dt,
    }


class TestLambdaHandler:

    def test_retorna_status_200_para_movie(self):
        mocks = _run(EVENTO_MOVIE)
        assert mocks["result"]["statusCode"] == 200
        assert "movie" in mocks["result"]["body"]

    def test_retorna_status_200_para_tv(self):
        mocks = _run(EVENTO_TV)
        assert mocks["result"]["statusCode"] == 200
        assert "tv" in mocks["result"]["body"]

    # --- Secrets Manager ---

    def test_busca_api_key_uma_unica_vez(self):
        with (
            patch("main.trigger_glue_job"),
            patch("main.collect_now_playing_data"),
            patch("main.collect_discover_data"),
            patch("main.collect_watch_providers_ref"),
            patch("main.collect_configuration_data"),
            patch("main.collect_genre_data"),
            patch("main.get_api_secret", return_value="api-key-teste") as mock_get_key,
            patch("main.boto3"),
            patch("main.datetime") as mock_dt,
        ):
            mock_dt.now.return_value.year = 2025
            main.lambda_handler(EVENTO_MOVIE, MagicMock())

        mock_get_key.assert_called_once_with(main.TMDB_SECRET_ARN, "tmdb_api_key")

    # --- collect_genre_data e collect_configuration_data ---

    def test_collect_genre_chamado_com_tipo_movie(self):
        mocks = _run(EVENTO_MOVIE)
        mocks["mock_genre"].assert_called_once()
        _, _, _, content_type = mocks["mock_genre"].call_args[0]
        assert content_type == "movie"

    def test_collect_configuration_chamado_com_tipo_tv(self):
        mocks = _run(EVENTO_TV)
        mocks["mock_config"].assert_called_once()
        _, _, _, content_type = mocks["mock_config"].call_args[0]
        assert content_type == "tv"

    # --- Loop de anos ---

    def test_loop_executa_para_cada_ano(self):
        mocks = _run({**EVENTO_MOVIE, "start_year": 2026}, year=2027)
        assert mocks["mock_discover"].call_count == 2
        assert mocks["mock_trigger"].call_count == 5

    # --- collect_discover_data ---

    def test_collect_discover_usa_folder_correto_para_movie(self):
        mocks = _run(EVENTO_MOVIE, year=2025)
        kwargs = mocks["mock_discover"].call_args[1]
        assert kwargs["folder"] == "tmdb/discover/movie"
        assert kwargs["content_type"] == "movie"

    def test_collect_discover_usa_folder_correto_para_tv(self):
        mocks = _run(EVENTO_TV, year=2025)
        kwargs = mocks["mock_discover"].call_args[1]
        assert kwargs["folder"] == "tmdb/discover/tv"
        assert kwargs["content_type"] == "tv"

    # --- trigger_glue_job ---

    def test_glue_recebe_argumentos_padronizados(self):
        mocks = _run(EVENTO_MOVIE, year=2025)

        chamada_genre = mocks["mock_trigger"].call_args_list[0]
        chamada_config = mocks["mock_trigger"].call_args_list[1]
        chamada_watch_ref = mocks["mock_trigger"].call_args_list[2]
        chamada_disc = mocks["mock_trigger"].call_args_list[3]

        for chamada in (chamada_genre, chamada_config, chamada_watch_ref, chamada_disc):
            assert chamada[1].get("MEDIA_TYPE") == "movie"
            assert chamada[1].get("DATABASE") == "tmdb_db"

        assert chamada_genre[1].get("TABLE_NAME") == "genre_movie"
        assert chamada_config[1].get("TABLE_NAME") == "configuration_languages"
        assert chamada_watch_ref[1].get("TABLE_NAME") == "watch_providers_ref_movie"
        assert chamada_disc[1].get("TABLE_NAME") == "discover_movie"

    def test_glue_acionado_para_genre_e_configuration_sem_year(self):
        """As chamadas do Glue para genre e configuration nao devem receber year."""
        mocks = _run(EVENTO_MOVIE, year=2025)

        assert mocks["mock_trigger"].call_count == 4

        chamada_genre = mocks["mock_trigger"].call_args_list[0]
        assert "YEAR" not in chamada_genre[1]
        assert chamada_genre[1].get("TABLE_TYPE") == "genre"

        chamada_config = mocks["mock_trigger"].call_args_list[1]
        assert "YEAR" not in chamada_config[1]
        assert chamada_config[1].get("TABLE_TYPE") == "configuration"

        chamada_watch_ref = mocks["mock_trigger"].call_args_list[2]
        assert "YEAR" not in chamada_watch_ref[1]
        assert chamada_watch_ref[1].get("TABLE_TYPE") == "watch_providers_ref"

    def test_glue_no_loop_recebe_year_e_table_type_corretos(self):
        """As chamadas do Glue dentro do loop devem receber year e table_type='discover'."""
        mocks = _run({**EVENTO_MOVIE, "start_year": 2025}, year=2026)

        chamada_ano_2025 = mocks["mock_trigger"].call_args_list[3]
        chamada_ano_2026 = mocks["mock_trigger"].call_args_list[4]

        assert chamada_ano_2025[1].get("YEAR") == 2025
        assert chamada_ano_2025[1].get("TABLE_TYPE") == "discover"
        assert chamada_ano_2026[1].get("YEAR") == 2026
        assert chamada_ano_2026[1].get("TABLE_TYPE") == "discover"

    def test_glue_discover_recebe_end_year(self):
        """Todas as chamadas de discover repassam end_year."""
        mocks = _run({**EVENTO_MOVIE, "start_year": 2025}, year=2026)

        for chamada in mocks["mock_trigger"].call_args_list[3:]:
            assert chamada[1].get("END_YEAR") == 2026


class TestSkipWeekly:
    """
    Testa o flag skip_weekly que pula o loop de discover.

    QUANDO USAR skip_weekly:
      O EventBridge tem dois schedules: um semanal (only_discover) e um mensal (skip_weekly).
      skip_weekly=True = "atualizo apenas os dados de referencia (generos, idiomas, paises,
      plataformas de streaming), sem coletar o discover novamente este mes".
      Isso economiza chamadas a API TMDB em execucoes onde os dados de discover nao precisam ser atualizados.
    """

    def test_skip_weekly_nao_chama_collect_discover(self):
        mocks = _run({**EVENTO_MOVIE, "skip_weekly": True}, year=2025)
        mocks["mock_discover"].assert_not_called()

    def test_skip_weekly_ainda_coleta_genre_configuration_watch_providers(self):
        mocks = _run({**EVENTO_MOVIE, "skip_weekly": True}, year=2025)
        mocks["mock_genre"].assert_called_once()
        mocks["mock_config"].assert_called_once()
        mocks["mock_watch_ref"].assert_called_once()

    def test_skip_weekly_glue_acionado_apenas_para_referencias(self):
        mocks = _run({**EVENTO_MOVIE, "skip_weekly": True}, year=2025)
        assert mocks["mock_trigger"].call_count == 3
        table_types = [c[1].get("table_type") for c in mocks["mock_trigger"].call_args_list]
        assert "discover" not in table_types

    def test_skip_weekly_retorna_status_200(self):
        mocks = _run({**EVENTO_MOVIE, "skip_weekly": True}, year=2025)
        assert mocks["result"]["statusCode"] == 200


class TestOnlyDiscover:
    """
    Testa o flag only_discover que pula as coletas de referencia.

    QUANDO USAR only_discover:
      O EventBridge semanal usa only_discover=True. Coleta apenas os filmes/series
      novos do discover sem recoletar generos, idiomas e paises (que raramente
      mudam) — tornando a execucao mais rapida e barata.
    """

    def test_only_discover_pula_genre(self):
        mocks = _run({**EVENTO_MOVIE, "only_discover": True}, year=2025)
        mocks["mock_genre"].assert_not_called()

    def test_only_discover_pula_configuration(self):
        mocks = _run({**EVENTO_MOVIE, "only_discover": True}, year=2025)
        mocks["mock_config"].assert_not_called()

    def test_only_discover_pula_watch_providers_ref(self):
        mocks = _run({**EVENTO_MOVIE, "only_discover": True}, year=2025)
        mocks["mock_watch_ref"].assert_not_called()

    def test_only_discover_executa_loop_normalmente(self):
        mocks = _run({**EVENTO_MOVIE, "only_discover": True}, year=2026)
        assert mocks["mock_discover"].call_count == 1
        assert mocks["mock_trigger"].call_count == 1

    def test_only_discover_retorna_status_200(self):
        mocks = _run({**EVENTO_MOVIE, "only_discover": True}, year=2025)
        assert mocks["result"]["statusCode"] == 200


class TestApenasAnoAnterior:
    """
    Testa o flag apenas_ano_anterior que coleta referencia + discover do ano passado.

    QUANDO USAR apenas_ano_anterior:
      O EventBridge mensal usa apenas_ano_anterior=True. Coleta as tabelas de referencia
      (generos, configuracoes, watch_providers_ref) e roda o discover para current_year - 1.
      Nao coleta now_playing (dados de cinema sao do ano corrente).
    """

    def test_apenas_ano_anterior_coleta_referencia(self):
        mocks = _run({**EVENTO_MOVIE, "apenas_ano_anterior": True}, year=2026)
        mocks["mock_genre"].assert_called_once()
        mocks["mock_config"].assert_called_once()
        mocks["mock_watch_ref"].assert_called_once()

    def test_apenas_ano_anterior_discover_roda_para_ano_passado(self):
        mocks = _run({**EVENTO_MOVIE, "apenas_ano_anterior": True}, year=2026)
        mocks["mock_discover"].assert_called_once()
        kwargs = mocks["mock_discover"].call_args[1]
        assert kwargs["year"] == 2025

    def test_apenas_ano_anterior_nao_coleta_now_playing(self):
        mocks = _run({**EVENTO_NOW_PLAYING, "apenas_ano_anterior": True}, year=2026)
        mocks["mock_now_playing"].assert_not_called()

    def test_apenas_ano_anterior_glue_recebe_end_year_correto(self):
        mocks = _run({**EVENTO_MOVIE, "apenas_ano_anterior": True}, year=2026)
        chamadas_discover = [
            c for c in mocks["mock_trigger"].call_args_list
            if c[1].get("TABLE_TYPE") == "discover"
        ]
        assert len(chamadas_discover) == 1
        assert chamadas_discover[0][1].get("YEAR") == 2025
        assert chamadas_discover[0][1].get("END_YEAR") == 2025

    def test_apenas_ano_anterior_retorna_status_200(self):
        mocks = _run({**EVENTO_MOVIE, "apenas_ano_anterior": True}, year=2026)
        assert mocks["result"]["statusCode"] == 200


class TestNowPlaying:
    """Testa o bloco condicional de coleta de filmes em cartaz."""

    def test_collect_now_playing_chamado_quando_tabela_presente(self):
        mocks = _run(EVENTO_NOW_PLAYING, year=2025)
        mocks["mock_now_playing"].assert_called_once()

    def test_collect_now_playing_nao_chamado_sem_tabela(self):
        mocks = _run(EVENTO_MOVIE, year=2025)
        mocks["mock_now_playing"].assert_not_called()

    def test_glue_acionado_com_table_type_now_playing(self):
        mocks = _run(EVENTO_NOW_PLAYING, year=2025)
        table_types = [c[1].get("TABLE_TYPE") for c in mocks["mock_trigger"].call_args_list]
        assert "now_playing" in table_types
        chamada_now = next(c for c in mocks["mock_trigger"].call_args_list if c[1].get("TABLE_TYPE") == "now_playing")
        assert chamada_now[1].get("TABLE_NAME") == "now_playing_movie"
