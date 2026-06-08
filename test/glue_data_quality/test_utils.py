"""Testes unitários para app/glue_data_quality/src/utils.py."""

from unittest.mock import MagicMock, patch

import pytest

from src.utils import (
    evaluate_data_quality,
    get_parameters_glue,
    get_ruleset,
    notify_failed_outcomes,
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
        "DATABASE_RESULTS": "db_unified_tmdb",
        "S3_BUCKET_DATA_QUALITY": "my-dq-bucket",
        "ENVIRONMENT": "dev",
        "SNS_TOPIC_ARN_DQ_METRICS": "arn:aws:sns:sa-east-1:123456789012:glue-data-quality-metrics-notifications",
    }

    def test_returns_required_args(self):
        """Os argumentos obrigatórios devem estar no retorno."""
        with patch(
            "src.utils.getResolvedOptions",
            side_effect=[{**self._REQUIRED}, SystemExit()],
        ):
            result = get_parameters_glue()

        assert result["TABLE_NAME"] == "tb_genre_movie_tmdb"
        assert result["DATABASE"] == "db_tmdb"
        assert result["DATABASE_RESULTS"] == "db_unified_tmdb"
        assert result["S3_BUCKET_DATA_QUALITY"] == "my-dq-bucket"
        assert result["ENVIRONMENT"] == "dev"

    def test_adds_year_when_available(self):
        """YEAR deve ser incluído quando o Glue ETL passar o argumento."""
        year_args = {"YEAR": "2023"}
        with patch(
            "src.utils.getResolvedOptions",
            side_effect=[{**self._REQUIRED}, year_args],
        ):
            result = get_parameters_glue()

        assert result["YEAR"] == "2023"

    def test_omits_year_when_not_provided(self):
        """YEAR não deve estar no retorno quando o argumento não for enviado."""
        with patch(
            "src.utils.getResolvedOptions",
            side_effect=[{**self._REQUIRED}, SystemExit("not found")],
        ):
            result = get_parameters_glue()

        assert "YEAR" not in result

    def test_does_not_raise_when_year_is_missing(self):
        """Ausência de YEAR não pode lançar exceção — é argumento opcional."""
        with patch(
            "src.utils.getResolvedOptions",
            side_effect=[{**self._REQUIRED}, SystemExit()],
        ):
            get_parameters_glue()

    def test_returns_database_results(self):
        """DATABASE_RESULTS deve estar no retorno como argumento obrigatório."""
        with patch(
            "src.utils.getResolvedOptions",
            side_effect=[{**self._REQUIRED}, SystemExit()],
        ):
            result = get_parameters_glue()

        assert result["DATABASE_RESULTS"] == "db_unified_tmdb"


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

    def test_no_push_down_predicate_when_year_is_none(self):
        """Sem year, push_down_predicate não deve ser passado (tabelas sem partição)."""
        glue_context = MagicMock()
        read_table_from_catalog(
            glue_context, "db_tmdb", "tb_genre_movie_tmdb", year=None
        )

        _, kwargs = glue_context.create_dynamic_frame.from_catalog.call_args
        assert "push_down_predicate" not in kwargs

    def test_push_down_predicate_when_year_is_provided(self):
        """Com year, push_down_predicate deve filtrar apenas a partição informada."""
        glue_context = MagicMock()
        read_table_from_catalog(
            glue_context, "db_tmdb", "tb_discover_movie_tmdb", year="2019"
        )

        _, kwargs = glue_context.create_dynamic_frame.from_catalog.call_args
        assert kwargs["push_down_predicate"] == "year = '2019'"

    def test_push_down_predicate_uses_correct_year_value(self):
        """O predicado deve conter exatamente o ano passado como argumento."""
        glue_context = MagicMock()
        read_table_from_catalog(
            glue_context, "db_tmdb", "tb_discover_tv_tmdb", year="2023"
        )

        _, kwargs = glue_context.create_dynamic_frame.from_catalog.call_args
        assert "2023" in kwargs["push_down_predicate"]


# ---------------------------------------------------------------------------
# evaluate_data_quality
# ---------------------------------------------------------------------------


class TestEvaluateDataQuality:
    def _make_chainable_df(self):
        """
        DataFrame mock onde withColumnRenamed e withColumn retornam o próprio mock.
        Permite encadear chamadas ilimitadas sem criar um mock por nível.
        """
        df_mock = MagicMock()
        df_mock.withColumnRenamed.return_value = df_mock
        df_mock.withColumn.return_value = df_mock
        df_mock.drop.return_value = df_mock
        df_mock.count.return_value = 3
        return df_mock

    def _run(
        self,
        table_name="tb_genre_movie_tmdb",
        ruleset="Rules = [\n  RowCount > 0\n]",
        database="db_tmdb",
        year=None,
    ):
        """Executa evaluate_data_quality com colaboradores simulados e retorna os mocks."""
        glue_context = MagicMock()
        dynamic_frame = MagicMock()
        df_mock = self._make_chainable_df()

        dq_result_mock = MagicMock()
        dq_result_mock.toDF.return_value = df_mock

        with (
            patch("src.utils.EvaluateDataQuality") as mock_edq,
            patch("src.utils.DynamicFrame") as mock_dyn,
            patch("src.utils.col") as mock_col,
            patch("src.utils.lit") as mock_lit,
            patch("src.utils.current_timestamp") as mock_ts,
            patch("src.utils.from_utc_timestamp") as mock_utc,
        ):
            mock_edq.apply.return_value = dq_result_mock

            result = evaluate_data_quality(
                glue_context, dynamic_frame, ruleset, table_name, database, year
            )

        return {
            "result": result,
            "df_mock": df_mock,
            "mock_edq": mock_edq,
            "mock_dyn": mock_dyn,
            "mock_col": mock_col,
            "mock_lit": mock_lit,
            "mock_ts": mock_ts,
            "mock_utc": mock_utc,
            "dq_result_mock": dq_result_mock,
            "dynamic_frame": dynamic_frame,
        }

    def test_calls_evaluate_data_quality_apply_with_frame_and_ruleset(self):
        """EvaluateDataQuality.apply deve receber o DynamicFrame e o ruleset corretos."""
        mocks = self._run()

        mocks["mock_edq"].apply.assert_called_once()
        call_kwargs = mocks["mock_edq"].apply.call_args[1]
        assert call_kwargs["frame"] is mocks["dynamic_frame"]
        assert call_kwargs["ruleset"] == "Rules = [\n  RowCount > 0\n]"

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

    def test_renames_rule_column_to_snake_case(self):
        """Coluna 'Rule' do Glue DQ deve ser renomeada para 'rule'."""
        mocks = self._run()
        mocks["df_mock"].withColumnRenamed.assert_any_call("Rule", "rule")

    def test_renames_outcome_column_to_snake_case(self):
        """Coluna 'Outcome' do Glue DQ deve ser renomeada para 'outcome'."""
        mocks = self._run()
        mocks["df_mock"].withColumnRenamed.assert_any_call("Outcome", "outcome")

    def test_renames_failure_reason_column_to_snake_case(self):
        """Coluna 'FailureReason' deve ser renomeada para 'failure_reason'.
        Sem esse rename, o Athena retornaria null em linhas com Outcome=Failed."""
        mocks = self._run()
        mocks["df_mock"].withColumnRenamed.assert_any_call(
            "FailureReason", "failure_reason"
        )

    def test_renames_evaluated_metrics_column_to_snake_case(self):
        """Coluna 'EvaluatedMetrics' do Glue DQ deve ser renomeada para 'evaluated_metrics'."""
        mocks = self._run()
        mocks["df_mock"].withColumnRenamed.assert_any_call(
            "EvaluatedMetrics", "evaluated_metrics"
        )

    def test_adds_partition_column_with_year(self):
        """Coluna partition deve ser preenchida com o ano quando fornecido."""
        mocks = self._run(year="2002")
        mocks["df_mock"].withColumn.assert_any_call(
            "partition", mocks["mock_lit"].return_value.cast.return_value
        )
        mocks["mock_lit"].assert_any_call("2002")

    def test_adds_partition_column_none_when_no_year(self):
        """Coluna partition deve ser None para tabelas sem partição (gêneros, config)."""
        mocks = self._run(year=None)
        mocks["mock_lit"].assert_any_call(None)

    def test_adds_datetime_process_column(self):
        """Coluna datetime_process deve ser adicionada com horário de São Paulo."""
        mocks = self._run()
        mocks["df_mock"].withColumn.assert_any_call(
            "datetime_process", mocks["mock_utc"].return_value
        )
        mocks["mock_utc"].assert_called_once_with(
            mocks["mock_ts"].return_value, "America/Sao_Paulo"
        )
        mocks["mock_ts"].assert_called_once()

    def test_adds_source_database_column(self):
        """Coluna source_database deve ser adicionada com o nome do banco de dados."""
        mocks = self._run(database="db_tmdb")
        mocks["df_mock"].withColumn.assert_any_call(
            "source_database", mocks["mock_lit"].return_value
        )
        mocks["mock_lit"].assert_any_call("db_tmdb")

    def test_adds_source_table_column(self):
        """Coluna source_table deve ser adicionada com o nome da tabela avaliada."""
        mocks = self._run(table_name="tb_genre_movie_tmdb")
        mocks["df_mock"].withColumn.assert_any_call(
            "source_table", mocks["mock_lit"].return_value
        )
        mocks["mock_lit"].assert_any_call("tb_genre_movie_tmdb")

    def test_returns_dataframe_after_all_transformations(self):
        """O retorno deve ser o DataFrame após todos os renames e withColumns."""
        mocks = self._run()
        assert mocks["result"] is mocks["df_mock"]

    def test_filters_dataframe_by_year_before_evaluate_when_year_provided(self):
        """Quando year é fornecido, o DynamicFrame é convertido em DataFrame e filtrado
        por year ANTES de passar ao EvaluateDataQuality, garantindo que apenas os dados
        da partição solicitada sejam avaliados."""
        glue_context = MagicMock()
        dynamic_frame = MagicMock()
        df_source = MagicMock()
        dynamic_frame.toDF.return_value = df_source

        df_mock = self._make_chainable_df()
        dq_result_mock = MagicMock()
        dq_result_mock.toDF.return_value = df_mock

        with (
            patch("src.utils.EvaluateDataQuality") as mock_edq,
            patch("src.utils.DynamicFrame") as mock_dyn,
            patch("src.utils.col") as mock_col,
            patch("src.utils.lit"),
            patch("src.utils.current_timestamp"),
            patch("src.utils.from_utc_timestamp"),
        ):
            mock_edq.apply.return_value = dq_result_mock

            evaluate_data_quality(
                glue_context,
                dynamic_frame,
                "Rules = [\n  RowCount > 0\n]",
                "tb_discover_movie_tmdb",
                "db",
                year="2002",
            )

        mock_col.assert_any_call("year")  # col("year") construiu a expressão
        df_source.filter.assert_called_once()  # filter foi chamado no DataFrame
        # DynamicFrame.fromDF recebe o df filtrado, o glue_context e um nome de frame
        mock_dyn.fromDF.assert_called_once_with(
            df_source.filter.return_value, glue_context, "filtered_frame"
        )

    def test_passes_filtered_dynamic_frame_to_evaluate_when_year_provided(self):
        """EvaluateDataQuality.apply deve receber o DynamicFrame filtrado (não o original)
        quando year é fornecido, assegurando que as regras sejam avaliadas apenas
        nos dados da partição recém-escrita."""
        glue_context = MagicMock()
        dynamic_frame = MagicMock()
        filtered_dynamic_frame = MagicMock()

        df_mock = self._make_chainable_df()
        dq_result_mock = MagicMock()
        dq_result_mock.toDF.return_value = df_mock

        with (
            patch("src.utils.EvaluateDataQuality") as mock_edq,
            patch("src.utils.DynamicFrame") as mock_dyn,
            patch("src.utils.col"),
            patch("src.utils.lit"),
            patch("src.utils.current_timestamp"),
            patch("src.utils.from_utc_timestamp"),
        ):
            mock_edq.apply.return_value = dq_result_mock
            mock_dyn.fromDF.return_value = filtered_dynamic_frame

            evaluate_data_quality(
                glue_context,
                dynamic_frame,
                "Rules = [\n  RowCount > 0\n]",
                "tb_discover_tv_tmdb",
                "db",
                year="2023",
            )

        call_kwargs = mock_edq.apply.call_args[1]
        assert call_kwargs["frame"] is filtered_dynamic_frame

    def test_does_not_filter_when_year_is_none(self):
        """Quando year é None (tabelas sem partição por ano), o DynamicFrame original
        deve ser passado diretamente ao EvaluateDataQuality sem conversão ou filtro."""
        glue_context = MagicMock()
        dynamic_frame = MagicMock()

        df_mock = self._make_chainable_df()
        dq_result_mock = MagicMock()
        dq_result_mock.toDF.return_value = df_mock

        with (
            patch("src.utils.EvaluateDataQuality") as mock_edq,
            patch("src.utils.DynamicFrame") as mock_dyn,
            patch("src.utils.col") as mock_col,
            patch("src.utils.lit"),
            patch("src.utils.current_timestamp"),
            patch("src.utils.from_utc_timestamp"),
        ):
            mock_edq.apply.return_value = dq_result_mock

            evaluate_data_quality(
                glue_context,
                dynamic_frame,
                "Rules = [\n  RowCount > 0\n]",
                "tb_genre_movie_tmdb",
                "db",
                year=None,
            )

        from unittest.mock import call as mock_call

        assert (
            mock_call("year") not in mock_col.call_args_list
        )  # col("year") nunca chamado sem year
        mock_dyn.fromDF.assert_not_called()
        call_kwargs = mock_edq.apply.call_args[1]
        assert call_kwargs["frame"] is dynamic_frame


# ---------------------------------------------------------------------------
# write_results_to_s3
# ---------------------------------------------------------------------------


class TestWriteResultsToS3:
    def _run(self, df_mock=None, bucket="my-dq-bucket", table="tb_genre_movie_tmdb", database="db_tmdb", year=None):
        df_mock = df_mock or MagicMock()
        with patch("src.utils.wr") as mock_wr:
            write_results_to_s3(df_mock, bucket, table, database, year)
        return df_mock, mock_wr

    def test_converts_spark_df_to_pandas(self):
        """O Spark DataFrame deve ser convertido para Pandas antes da escrita."""
        df_mock, _ = self._run()
        df_mock.toPandas.assert_called_once()

    def test_passes_pandas_df_to_wrangler(self):
        """wr.s3.to_parquet deve receber o resultado de df.toPandas()."""
        df_mock, mock_wr = self._run()
        call_kwargs = mock_wr.s3.to_parquet.call_args[1]
        assert call_kwargs["df"] is df_mock.toPandas.return_value

    def test_writes_to_correct_s3_path(self):
        """O Parquet deve ser escrito em s3://<bucket>/tmdb/tb_data_quality_tmdb/."""
        _, mock_wr = self._run(bucket="my-dq-bucket")
        call_kwargs = mock_wr.s3.to_parquet.call_args[1]
        assert call_kwargs["path"] == "s3://my-dq-bucket/tmdb/tb_data_quality_tmdb/"

    def test_s3_path_uses_bucket_name(self):
        """O nome do bucket de Data Quality deve aparecer no caminho S3."""
        _, mock_wr = self._run(bucket="meu-bucket-dq")
        call_kwargs = mock_wr.s3.to_parquet.call_args[1]
        assert "meu-bucket-dq" in call_kwargs["path"]

    def test_s3_path_uses_fixed_output_table_name(self):
        """O nome da tabela de saída deve ser sempre tb_data_quality_tmdb."""
        _, mock_wr = self._run(table="tb_discover_tv_tmdb")
        call_kwargs = mock_wr.s3.to_parquet.call_args[1]
        assert "tb_data_quality_tmdb" in call_kwargs["path"]

    def test_uses_dataset_true(self):
        """dataset=True ativa o registro automático de partições no Glue Catalog."""
        _, mock_wr = self._run()
        call_kwargs = mock_wr.s3.to_parquet.call_args[1]
        assert call_kwargs["dataset"] is True

    def test_registers_table_in_glue_catalog(self):
        """wr.s3.to_parquet deve receber database e table para atualizar o Catalog."""
        _, mock_wr = self._run(database="db_tmdb")
        call_kwargs = mock_wr.s3.to_parquet.call_args[1]
        assert call_kwargs["database"] == "db_tmdb"
        assert call_kwargs["table"] == "tb_data_quality_tmdb"

    def test_partitions_by_source_table(self):
        """partition_cols deve ser ['source_table'] para que o Catalog registre a partição."""
        _, mock_wr = self._run()
        call_kwargs = mock_wr.s3.to_parquet.call_args[1]
        assert call_kwargs["partition_cols"] == ["source_table"]

    def test_uses_overwrite_partitions_mode(self):
        """mode='overwrite_partitions' substitui apenas a partição presente,
        preservando resultados de outras tabelas."""
        _, mock_wr = self._run()
        call_kwargs = mock_wr.s3.to_parquet.call_args[1]
        assert call_kwargs["mode"] == "overwrite_partitions"

    def test_wrangler_called_once(self):
        """wr.s3.to_parquet deve ser chamado exatamente uma vez por execução."""
        _, mock_wr = self._run()
        mock_wr.s3.to_parquet.assert_called_once()


# ---------------------------------------------------------------------------
# notify_failed_outcomes
# ---------------------------------------------------------------------------


class TestNotifyFailedOutcomes:
    _SNS_ARN = "arn:aws:sns:sa-east-1:123456789012:glue-data-quality-failure-notifications"

    def _make_row(self, rule: str, failure_reason: str):
        row = MagicMock()
        row.__getitem__ = lambda self, key: {"rule": rule, "failure_reason": failure_reason}[key]
        return row

    def _make_df(self, failed_rows: list):
        """Cria um Spark DataFrame mock com a lista de linhas em failed_rows."""
        df = MagicMock()
        failed_df = MagicMock()
        failed_df.count.return_value = len(failed_rows)
        failed_df.select.return_value.collect.return_value = failed_rows
        df.filter.return_value = failed_df
        return df, failed_df

    def test_does_not_publish_when_all_rules_pass(self):
        """Quando nenhuma regra falha, sns.publish não deve ser chamado."""
        df, _ = self._make_df([])
        with patch("src.utils.boto3") as mock_boto3:
            notify_failed_outcomes(df, "tb_genre_movie_tmdb", self._SNS_ARN, "dev")
            mock_boto3.client.return_value.publish.assert_not_called()

    def test_publishes_when_any_rule_fails(self):
        """Quando ao menos uma regra falha, sns.publish deve ser chamado uma vez."""
        row = self._make_row('IsComplete "id"', "Column id has null values")
        df, _ = self._make_df([row])
        with patch("src.utils.boto3") as mock_boto3:
            notify_failed_outcomes(df, "tb_genre_movie_tmdb", self._SNS_ARN, "dev")
            mock_boto3.client.return_value.publish.assert_called_once()

    def test_subject_contains_environment_uppercased(self):
        """O subject do e-mail deve conter o ambiente em maiúsculas."""
        row = self._make_row("RowCount > 0", "Row count is 0")
        df, _ = self._make_df([row])
        with patch("src.utils.boto3") as mock_boto3:
            notify_failed_outcomes(df, "tb_discover_movie_tmdb", self._SNS_ARN, "dev")
            call_kwargs = mock_boto3.client.return_value.publish.call_args[1]
            assert "DEV" in call_kwargs["Subject"]

    def test_message_contains_table_name(self):
        """O corpo do e-mail deve indicar qual tabela teve métricas com falha."""
        row = self._make_row("RowCount > 0", "Row count is 0")
        df, _ = self._make_df([row])
        with patch("src.utils.boto3") as mock_boto3:
            notify_failed_outcomes(df, "tb_genre_tv_tmdb", self._SNS_ARN, "prod")
            call_kwargs = mock_boto3.client.return_value.publish.call_args[1]
            assert "tb_genre_tv_tmdb" in call_kwargs["Message"]

    def test_message_contains_failed_rule(self):
        """O corpo do e-mail deve listar a regra que falhou."""
        row = self._make_row('IsUnique "id"', "Duplicate values found")
        df, _ = self._make_df([row])
        with patch("src.utils.boto3") as mock_boto3:
            notify_failed_outcomes(df, "tb_genre_movie_tmdb", self._SNS_ARN, "dev")
            call_kwargs = mock_boto3.client.return_value.publish.call_args[1]
            assert 'IsUnique "id"' in call_kwargs["Message"]

    def test_message_contains_failure_reason(self):
        """O corpo do e-mail deve incluir o motivo da falha de cada regra."""
        row = self._make_row('IsComplete "id"', "Column id has null values")
        df, _ = self._make_df([row])
        with patch("src.utils.boto3") as mock_boto3:
            notify_failed_outcomes(df, "tb_genre_movie_tmdb", self._SNS_ARN, "dev")
            call_kwargs = mock_boto3.client.return_value.publish.call_args[1]
            assert "Column id has null values" in call_kwargs["Message"]

    def test_publishes_to_correct_topic_arn(self):
        """sns.publish deve usar o ARN do tópico recebido como parâmetro."""
        row = self._make_row("RowCount > 0", "Row count is 0")
        df, _ = self._make_df([row])
        with patch("src.utils.boto3") as mock_boto3:
            notify_failed_outcomes(df, "tb_genre_movie_tmdb", self._SNS_ARN, "dev")
            call_kwargs = mock_boto3.client.return_value.publish.call_args[1]
            assert call_kwargs["TopicArn"] == self._SNS_ARN

    def test_message_lists_all_failed_rules(self):
        """Quando múltiplas regras falham, todas devem aparecer no corpo do e-mail."""
        rows = [
            self._make_row('IsComplete "id"', "Null values found"),
            self._make_row("RowCount > 0", "Row count is 0"),
        ]
        df, _ = self._make_df(rows)
        with patch("src.utils.boto3") as mock_boto3:
            notify_failed_outcomes(df, "tb_discover_tv_tmdb", self._SNS_ARN, "dev")
            call_kwargs = mock_boto3.client.return_value.publish.call_args[1]
            assert 'IsComplete "id"' in call_kwargs["Message"]
            assert "RowCount > 0" in call_kwargs["Message"]
