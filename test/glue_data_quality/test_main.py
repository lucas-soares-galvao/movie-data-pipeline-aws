"""Testes de integração para app/glue_data_quality/main.py."""

from unittest.mock import MagicMock, patch

import main as m

# Argumentos base devolvidos pelo mock de get_parameters_glue
_BASE_ARGS = {
    "TABLE_NAME": "tb_genre_movie_tmdb",
    "DATABASE": "db_tmdb",
    "S3_BUCKET_DATA_QUALITY": "my-dq-bucket",
    "ENVIRONMENT": "dev",
}


def _run_main(args=None, ruleset="Rules = []", dynamic_frame=None, df_results=None):
    """
    Executa main() com todos os colaboradores simulados.

    Retorna um dicionário com os mocks para que cada teste possa inspecionar
    as chamadas realizadas.
    """
    args = args or _BASE_ARGS
    dynamic_frame = dynamic_frame or MagicMock()
    df_results = df_results or MagicMock()

    sc_mock = MagicMock()
    glue_context_mock = MagicMock()

    # SparkContext e GlueContext são None no conftest (stubs) — precisam ser
    # substituídos por MagicMock para que .getOrCreate() e GlueContext(sc) funcionem.
    with patch.object(m, "SparkContext") as mock_sc_cls, \
         patch.object(m, "GlueContext") as mock_gc_cls, \
         patch.object(m, "get_parameters_glue", return_value=args), \
         patch.object(m, "get_ruleset", return_value=ruleset) as mock_ruleset, \
         patch.object(m, "read_table_from_catalog", return_value=dynamic_frame) as mock_read, \
         patch.object(m, "evaluate_data_quality", return_value=df_results) as mock_eval, \
         patch.object(m, "write_results_to_s3") as mock_write:

        mock_sc_cls.getOrCreate.return_value = sc_mock
        mock_gc_cls.return_value = glue_context_mock

        m.main()

    return {
        "mock_sc_cls": mock_sc_cls,
        "mock_gc_cls": mock_gc_cls,
        "glue_context_mock": glue_context_mock,
        "sc_mock": sc_mock,
        "mock_ruleset": mock_ruleset,
        "mock_read": mock_read,
        "mock_eval": mock_eval,
        "mock_write": mock_write,
    }


# ---------------------------------------------------------------------------
# Criação dos contextos Spark / Glue
# ---------------------------------------------------------------------------

class TestContextCreation:
    def test_creates_spark_context(self):
        """SparkContext.getOrCreate() deve ser chamado para iniciar o Spark."""
        mocks = _run_main()
        mocks["mock_sc_cls"].getOrCreate.assert_called_once()

    def test_creates_glue_context_with_spark_context(self):
        """GlueContext deve ser criado passando o SparkContext como argumento."""
        mocks = _run_main()
        mocks["mock_gc_cls"].assert_called_once_with(mocks["sc_mock"])


# ---------------------------------------------------------------------------
# Chamada de get_ruleset
# ---------------------------------------------------------------------------

class TestGetRulesetCall:
    def test_calls_get_ruleset_with_table_name(self):
        """get_ruleset deve ser chamado com o TABLE_NAME recebido nos args."""
        mocks = _run_main(args={**_BASE_ARGS, "TABLE_NAME": "tb_genre_movie_tmdb"})
        mocks["mock_ruleset"].assert_called_once_with("tb_genre_movie_tmdb")

    def test_calls_get_ruleset_for_discover_table(self):
        """get_ruleset deve funcionar para qualquer nome de tabela nos args."""
        args = {**_BASE_ARGS, "TABLE_NAME": "tb_discover_movie_tmdb"}
        mocks = _run_main(args=args)
        mocks["mock_ruleset"].assert_called_once_with("tb_discover_movie_tmdb")


# ---------------------------------------------------------------------------
# Chamada de read_table_from_catalog
# ---------------------------------------------------------------------------

class TestReadTableFromCatalogCall:
    def test_calls_read_table_with_glue_context(self):
        """read_table_from_catalog deve receber o GlueContext criado no main."""
        mocks = _run_main()
        call_args = mocks["mock_read"].call_args

        assert call_args[0][0] is mocks["glue_context_mock"]

    def test_calls_read_table_with_database(self):
        """read_table_from_catalog deve receber o DATABASE dos args."""
        mocks = _run_main(args={**_BASE_ARGS, "DATABASE": "db_tmdb"})
        _, database, _, _ = mocks["mock_read"].call_args[0]
        assert database == "db_tmdb"

    def test_calls_read_table_with_table_name(self):
        """read_table_from_catalog deve receber o TABLE_NAME dos args."""
        mocks = _run_main(args={**_BASE_ARGS, "TABLE_NAME": "tb_genre_movie_tmdb"})
        _, _, table_name, _ = mocks["mock_read"].call_args[0]
        assert table_name == "tb_genre_movie_tmdb"

    def test_calls_read_table_with_none_year_when_not_in_args(self):
        """read_table_from_catalog deve receber year=None quando YEAR não está nos args
        (tabelas de gênero e configuração não têm partição por ano)."""
        mocks = _run_main()  # _BASE_ARGS não tem YEAR
        _, _, _, year = mocks["mock_read"].call_args[0]
        assert year is None

    def test_calls_read_table_with_year_when_in_args(self):
        """read_table_from_catalog deve receber o ano para aplicar push_down_predicate
        e avaliar apenas a partição recém-escrita, não a tabela inteira."""
        args = {**_BASE_ARGS, "TABLE_NAME": "tb_discover_movie_tmdb", "YEAR": "2002"}
        mocks = _run_main(args=args)
        _, _, _, year = mocks["mock_read"].call_args[0]
        assert year == "2002"


# ---------------------------------------------------------------------------
# Chamada de evaluate_data_quality
# ---------------------------------------------------------------------------

class TestEvaluateDataQualityCall:
    def test_calls_evaluate_with_glue_context(self):
        """evaluate_data_quality deve receber o GlueContext."""
        mocks = _run_main()
        glue_context_arg = mocks["mock_eval"].call_args[0][0]
        assert glue_context_arg is mocks["glue_context_mock"]

    def test_calls_evaluate_with_dynamic_frame_from_catalog(self):
        """evaluate_data_quality deve receber o DynamicFrame lido do Catalog."""
        dynamic_frame = MagicMock()
        mocks = _run_main(dynamic_frame=dynamic_frame)
        dynamic_frame_arg = mocks["mock_eval"].call_args[0][1]
        assert dynamic_frame_arg is dynamic_frame

    def test_calls_evaluate_with_ruleset(self):
        """evaluate_data_quality deve receber o ruleset retornado por get_ruleset."""
        mocks = _run_main(ruleset='Rules = [\n  RowCount > 0\n]')
        ruleset_arg = mocks["mock_eval"].call_args[0][2]
        assert ruleset_arg == 'Rules = [\n  RowCount > 0\n]'

    def test_calls_evaluate_with_table_name(self):
        """evaluate_data_quality deve receber o TABLE_NAME dos args."""
        mocks = _run_main(args={**_BASE_ARGS, "TABLE_NAME": "tb_genre_movie_tmdb"})
        table_name_arg = mocks["mock_eval"].call_args[0][3]
        assert table_name_arg == "tb_genre_movie_tmdb"

    def test_calls_evaluate_with_database(self):
        """evaluate_data_quality deve receber o DATABASE dos args."""
        mocks = _run_main(args={**_BASE_ARGS, "DATABASE": "db_tmdb"})
        database_arg = mocks["mock_eval"].call_args[0][4]
        assert database_arg == "db_tmdb"

    def test_calls_evaluate_with_none_year_when_not_in_args(self):
        """evaluate_data_quality deve receber year=None quando YEAR não está nos args."""
        mocks = _run_main()  # _BASE_ARGS não tem YEAR
        year_arg = mocks["mock_eval"].call_args[0][5]
        assert year_arg is None

    def test_calls_evaluate_with_year_when_in_args(self):
        """evaluate_data_quality deve receber o ano quando YEAR está nos args."""
        args = {**_BASE_ARGS, "TABLE_NAME": "tb_discover_movie_tmdb", "YEAR": "2002"}
        mocks = _run_main(args=args)
        year_arg = mocks["mock_eval"].call_args[0][5]
        assert year_arg == "2002"


# ---------------------------------------------------------------------------
# Chamada de write_results_to_s3
# ---------------------------------------------------------------------------

class TestWriteResultsToS3Call:
    def test_calls_write_with_df_results(self):
        """write_results_to_s3 deve receber o DataFrame retornado por evaluate."""
        df_results = MagicMock()
        mocks = _run_main(df_results=df_results)

        df_arg = mocks["mock_write"].call_args[0][0]
        assert df_arg is df_results

    def test_calls_write_with_s3_bucket_data_quality(self):
        """write_results_to_s3 deve receber o S3_BUCKET_DATA_QUALITY dos args."""
        args = {**_BASE_ARGS, "S3_BUCKET_DATA_QUALITY": "meu-bucket-dq"}
        mocks = _run_main(args=args)

        bucket_arg = mocks["mock_write"].call_args[0][1]
        assert bucket_arg == "meu-bucket-dq"

    def test_calls_write_with_table_name(self):
        """write_results_to_s3 deve receber o TABLE_NAME dos args."""
        mocks = _run_main(args={**_BASE_ARGS, "TABLE_NAME": "tb_genre_movie_tmdb"})

        table_arg = mocks["mock_write"].call_args[0][2]
        assert table_arg == "tb_genre_movie_tmdb"

    def test_write_is_called_exactly_once(self):
        """write_results_to_s3 deve ser chamado apenas uma vez por execução."""
        mocks = _run_main()
        assert mocks["mock_write"].call_count == 1
