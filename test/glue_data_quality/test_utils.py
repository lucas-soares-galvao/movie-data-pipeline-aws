"""Testes unitários para app/glue_data_quality/src/utils.py."""

from unittest.mock import MagicMock, call, patch

import pytest

from src.utils import (
    evaluate_data_quality,
    get_parameters_glue,
    get_ruleset,
    read_table_from_catalog,
    write_results_to_s3,
)


# ---------------------------------------------------------------------------
# get_parameters_glue
# ---------------------------------------------------------------------------

class TestGetParametersGlue:
    # Argumentos que o Glue sempre envia
    _REQUIRED = {
        "TABLE_NAME": "tb_genre_movie_tmdb",
        "DATABASE": "db_tmdb",
        "S3_BUCKET_DATA_QUALITY": "my-dq-bucket",
        "ENVIRONMENT": "dev",
    }

    def test_returns_required_args(self):
        """Os quatro argumentos obrigatórios devem estar no retorno."""
        with patch("src.utils.getResolvedOptions", side_effect=[{**self._REQUIRED}, Exception()]):
            result = get_parameters_glue()

        assert result["TABLE_NAME"] == "tb_genre_movie_tmdb"
        assert result["DATABASE"] == "db_tmdb"
        assert result["S3_BUCKET_DATA_QUALITY"] == "my-dq-bucket"
        assert result["ENVIRONMENT"] == "dev"

    def test_adds_year_when_available(self):
        """YEAR deve ser incluído quando o Glue ETL passar o argumento."""
        year_args = {"YEAR": "2023"}
        with patch("src.utils.getResolvedOptions", side_effect=[{**self._REQUIRED}, year_args]):
            result = get_parameters_glue()

        assert result["YEAR"] == "2023"

    def test_omits_year_when_not_provided(self):
        """YEAR não deve estar no retorno quando o argumento não for enviado."""
        with patch("src.utils.getResolvedOptions", side_effect=[{**self._REQUIRED}, Exception("not found")]):
            result = get_parameters_glue()

        assert "YEAR" not in result

    def test_does_not_raise_when_year_is_missing(self):
        """Ausência de YEAR não pode lançar exceção — é argumento opcional."""
        with patch("src.utils.getResolvedOptions", side_effect=[{**self._REQUIRED}, Exception()]):
            # Não deve lançar nada
            get_parameters_glue()


# ---------------------------------------------------------------------------
# get_ruleset
# ---------------------------------------------------------------------------

class TestGetRuleset:
    def test_starts_with_rules_block(self):
        """O formato DQDL exige que a string comece com 'Rules = ['."""
        result = get_ruleset("tb_genre_movie_tmdb")
        assert result.startswith("Rules = [")

    def test_ends_with_closing_bracket(self):
        """O bloco DQDL deve ser fechado com ']'."""
        result = get_ruleset("tb_genre_movie_tmdb")
        assert result.endswith("]")

    def test_contains_all_rules_from_rulesets_dq(self):
        """Cada regra definida em rulesets_dq deve aparecer na string gerada."""
        from src.rulesets_dq import rulesets_dq

        rules = rulesets_dq["tb_genre_movie_tmdb"]
        result = get_ruleset("tb_genre_movie_tmdb")

        for rule in rules:
            assert rule in result

    def test_raises_key_error_for_unknown_table(self):
        """Tabela sem regras definidas deve lançar KeyError com nome descritivo."""
        with pytest.raises(KeyError, match="tb_nao_existe"):
            get_ruleset("tb_nao_existe")

    def test_rules_separated_by_comma(self):
        """Quando há mais de uma regra, elas devem ser separadas por vírgula."""
        from src.rulesets_dq import rulesets_dq

        rules = rulesets_dq["tb_genre_movie_tmdb"]
        result = get_ruleset("tb_genre_movie_tmdb")

        if len(rules) > 1:
            assert "," in result

    def test_works_for_all_tables_in_rulesets_dq(self):
        """get_ruleset deve funcionar para todas as tabelas cadastradas."""
        from src.rulesets_dq import rulesets_dq

        for table in rulesets_dq:
            result = get_ruleset(table)
            assert result.startswith("Rules = [")


# ---------------------------------------------------------------------------
# read_table_from_catalog
# ---------------------------------------------------------------------------

class TestReadTableFromCatalog:
    def test_calls_from_catalog_with_correct_args(self):
        """Deve chamar from_catalog passando database e table_name corretos."""
        glue_context = MagicMock()
        read_table_from_catalog(glue_context, "db_tmdb", "tb_genre_movie_tmdb")

        glue_context.create_dynamic_frame.from_catalog.assert_called_once_with(
            database="db_tmdb",
            table_name="tb_genre_movie_tmdb",
        )

    def test_returns_dynamic_frame_from_catalog(self):
        """O retorno deve ser exatamente o DynamicFrame devolvido pelo Glue."""
        glue_context = MagicMock()
        expected = MagicMock()
        glue_context.create_dynamic_frame.from_catalog.return_value = expected

        result = read_table_from_catalog(glue_context, "db_tmdb", "tb_genre_movie_tmdb")

        assert result is expected

    def test_uses_provided_database_name(self):
        """O nome do banco de dados passado deve ser repassado ao Catalog."""
        glue_context = MagicMock()
        read_table_from_catalog(glue_context, "meu_banco", "tb_genre_movie_tmdb")

        _, kwargs = glue_context.create_dynamic_frame.from_catalog.call_args
        assert kwargs["database"] == "meu_banco"

    def test_uses_provided_table_name(self):
        """O nome da tabela passado deve ser repassado ao Catalog."""
        glue_context = MagicMock()
        read_table_from_catalog(glue_context, "db_tmdb", "tb_discover_movie_tmdb")

        _, kwargs = glue_context.create_dynamic_frame.from_catalog.call_args
        assert kwargs["table_name"] == "tb_discover_movie_tmdb"


# ---------------------------------------------------------------------------
# evaluate_data_quality
# ---------------------------------------------------------------------------

class TestEvaluateDataQuality:
    def _make_df_chain(self):
        """
        Cria um Spark DataFrame simulado que suporta o encadeamento:
          df.withColumn(...).withColumn(...)
        Retorna os três mocks: df original, df após 1º withColumn, df após 2º withColumn.
        """
        df_final = MagicMock()
        df_after_source = MagicMock()
        df_after_source.withColumn.return_value = df_final

        df_original = MagicMock()
        df_original.withColumn.return_value = df_after_source

        return df_original, df_after_source, df_final

    def _run(self, table_name="tb_genre_movie_tmdb", ruleset='Rules = [\n  RowCount > 0\n]'):
        """Executa evaluate_data_quality com colaboradores simulados e retorna os mocks."""
        glue_context = MagicMock()
        dynamic_frame = MagicMock()
        df_original, df_after_source, df_final = self._make_df_chain()

        dq_result_mock = MagicMock()
        dq_result_mock.toDF.return_value = df_original
        df_final.count.return_value = 3

        with patch("src.utils.EvaluateDataQuality") as mock_edq, \
             patch("src.utils.lit") as mock_lit, \
             patch("src.utils.current_timestamp") as mock_ts:
            mock_edq.apply.return_value = dq_result_mock

            result = evaluate_data_quality(glue_context, dynamic_frame, ruleset, table_name)

        return {
            "result": result,
            "df_original": df_original,
            "df_after_source": df_after_source,
            "df_final": df_final,
            "mock_edq": mock_edq,
            "mock_lit": mock_lit,
            "mock_ts": mock_ts,
            "dq_result_mock": dq_result_mock,
            "dynamic_frame": dynamic_frame,
        }

    def test_calls_evaluate_data_quality_apply_with_frame_and_ruleset(self):
        """EvaluateDataQuality.apply deve receber o DynamicFrame e o ruleset corretos."""
        mocks = self._run()

        mocks["mock_edq"].apply.assert_called_once()
        call_kwargs = mocks["mock_edq"].apply.call_args[1]
        assert call_kwargs["frame"] is mocks["dynamic_frame"]
        assert call_kwargs["ruleset"] == 'Rules = [\n  RowCount > 0\n]'

    def test_passes_correct_publishing_options(self):
        """As opções de publicação devem ativar métricas e resultados no Glue Studio."""
        mocks = self._run(table_name="tb_genre_movie_tmdb")

        call_kwargs = mocks["mock_edq"].apply.call_args[1]
        opts = call_kwargs["publishing_options"]

        assert opts["dataQualityEvaluationContext"] == "tb_genre_movie_tmdb"
        assert opts["enableDataQualityCloudWatchMetrics"] is True
        assert opts["enableDataQualityResultsPublishing"] is True

    def test_converts_dynamic_frame_to_spark_dataframe(self):
        """toDF() deve ser chamado para converter DynamicFrame em Spark DataFrame."""
        mocks = self._run()
        mocks["dq_result_mock"].toDF.assert_called_once()

    def test_adds_source_table_column(self):
        """A primeira withColumn deve criar a coluna source_table com o nome da tabela."""
        mocks = self._run(table_name="tb_genre_movie_tmdb")

        first_call = mocks["df_original"].withColumn.call_args_list[0]
        column_name = first_call[0][0]
        assert column_name == "source_table"
        mocks["mock_lit"].assert_called_once_with("tb_genre_movie_tmdb")

    def test_adds_evaluated_at_column(self):
        """A segunda withColumn deve criar a coluna evaluated_at com current_timestamp."""
        mocks = self._run()

        second_call = mocks["df_after_source"].withColumn.call_args_list[0]
        column_name = second_call[0][0]
        assert column_name == "evaluated_at"
        mocks["mock_ts"].assert_called_once()

    def test_returns_dataframe_after_both_withcolumn_calls(self):
        """O retorno deve ser o DataFrame após os dois withColumn encadeados."""
        mocks = self._run()
        assert mocks["result"] is mocks["df_final"]


# ---------------------------------------------------------------------------
# write_results_to_s3
# ---------------------------------------------------------------------------

class TestWriteResultsToS3:
    def test_uses_append_mode(self):
        """O modo 'append' deve ser usado para não apagar resultados de outras tabelas."""
        df_mock = MagicMock()
        write_results_to_s3(df_mock, "my-dq-bucket", "tb_genre_movie_tmdb")

        df_mock.write.mode.assert_called_once_with("append")

    def test_partitions_by_source_table(self):
        """Os dados devem ser particionados pela coluna source_table."""
        df_mock = MagicMock()
        write_results_to_s3(df_mock, "my-dq-bucket", "tb_genre_movie_tmdb")

        df_mock.write.mode.return_value.partitionBy.assert_called_once_with("source_table")

    def test_writes_parquet_to_correct_s3_path(self):
        """O Parquet deve ser escrito em s3://<bucket>/tmdb/tb_data_quality_tmdb/."""
        df_mock = MagicMock()
        write_results_to_s3(df_mock, "my-dq-bucket", "tb_genre_movie_tmdb")

        parquet_call = df_mock.write.mode.return_value.partitionBy.return_value.parquet
        parquet_call.assert_called_once_with("s3://my-dq-bucket/tmdb/tb_data_quality_tmdb/")

    def test_s3_path_uses_fixed_output_table_name(self):
        """O nome da tabela de saída deve ser sempre tb_data_quality_tmdb."""
        df_mock = MagicMock()
        write_results_to_s3(df_mock, "bucket-dq", "tb_discover_tv_tmdb")

        parquet_path = (
            df_mock.write.mode.return_value.partitionBy.return_value.parquet.call_args[0][0]
        )
        assert "tb_data_quality_tmdb" in parquet_path

    def test_s3_path_uses_bucket_name(self):
        """O nome do bucket de Data Quality deve aparecer no caminho S3."""
        df_mock = MagicMock()
        write_results_to_s3(df_mock, "meu-bucket-dq", "tb_genre_tv_tmdb")

        parquet_path = (
            df_mock.write.mode.return_value.partitionBy.return_value.parquet.call_args[0][0]
        )
        assert "meu-bucket-dq" in parquet_path

    def test_chained_write_operations_are_called_in_order(self):
        """mode → partitionBy → parquet devem ser chamados nesta ordem."""
        df_mock = MagicMock()
        write_results_to_s3(df_mock, "my-dq-bucket", "tb_genre_movie_tmdb")

        # Verifica que o encadeamento completo foi executado
        after_mode = df_mock.write.mode.return_value
        after_partition = after_mode.partitionBy.return_value
        after_partition.parquet.assert_called_once()
