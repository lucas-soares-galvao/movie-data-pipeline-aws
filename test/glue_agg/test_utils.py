"""
test_utils.py — Testes unitários para app/glue_agg/src/utils.py.

==============================================================================
O QUE ESTE ARQUIVO TESTA?
==============================================================================
Testa cada função utilitária do Glue AGG de forma isolada.

FUNÇÕES TESTADAS:

  run_athena_query()
    Verifica que o SQL gerado contém os elementos obrigatórios:
      - Colunas de imagem com URL completa (https://image.tmdb.org/t/p/...)
      - Aliases poster_url e backdrop_url
      - Referências às tabelas de discover (movie e tv), details e watch_providers
      - Colunas de metadados: overview, air_date, origin_country_name, etc.
    Também verifica os argumentos passados ao awswrangler:
      - database correto (db_unified_tmdb)
      - s3_output com o prefixo correto
      - ctas_approach=True (Athena cria uma tabela temporária para a query)

  traduzir_colunas_en()
    Testa o comportamento de tradução EN→PT seletiva:
      - Traduz title e overview quando original_language == "en"
      - Não altera registros em outros idiomas (pt, es, fr, etc.)
      - Não altera original_title (preserva o título original da TMDB)
      - Fallback: mantém o texto original se a tradução falhar (timeout, etc.)
      - overview vazio ("") não é enviado para tradução (evita chamada desnecessária)

  write_parquet_to_spec()
    Verifica escrita correta na camada SPEC (Gold layer):
      - Caminho S3: s3://<bucket>/<table_name>/
      - partition_cols=["media_type", "year"] (particionamento duplo)
      - mode="overwrite_partitions" (sobrescreve apenas as partições presentes)
      - dataset=True (registra no Glue Catalog automaticamente)
      - database e table corretos no Glue Catalog

  get_resolved_option() / get_parameters_glue()
    Delegação correta para o SDK do Glue (getResolvedOptions).
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from src.utils import get_parameters_glue, get_resolved_option, run_athena_query, traduzir_colunas_en, write_parquet_to_spec


class TestRunAthenaQuery:
    def test_passes_sql_with_image_columns_to_wrangler(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")

            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "AS poster_url" in sql
            assert "AS backdrop_url" in sql
            assert "https://image.tmdb.org/t/p/w342" in sql
            assert "https://image.tmdb.org/t/p/w780" in sql
            assert "tb_discover_movie_tmdb" in sql
            assert "tb_discover_tv_tmdb" in sql
            assert "overview" in sql
            assert "air_date" in sql
            assert "origin_country_name" in sql
            assert "language_name" in sql

    def test_uses_expected_wrangler_execution_args(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")

            mock_read.assert_called_once()
            _, kwargs = mock_read.call_args
            assert kwargs["database"] == "db_unified_tmdb"
            assert kwargs["s3_output"] == "s3://my-temp/athena/glue_agg/"
            assert kwargs["ctas_approach"] is True

    def test_query_contains_details_movie_join(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "tb_details_movie_tmdb" in sql
            assert "runtime_minutes" in sql

    def test_query_contains_details_tv_join(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "tb_details_tv_tmdb" in sql
            assert "number_of_seasons" in sql
            assert "number_of_episodes" in sql
            assert "episode_runtime_minutes" in sql

    def test_query_contains_watch_providers_join(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "tb_watch_providers_movie_tmdb" in sql
            assert "tb_watch_providers_tv_tmdb" in sql
            assert "streaming_providers" in sql


class TestTraduzirColunasEn:
    def _make_df(self, rows):
        return pd.DataFrame(rows)

    def test_traduz_title_e_overview_quando_original_language_en(self):
        df = self._make_df([
            {"original_language": "en", "title": "The Matrix", "overview": "A hacker discovers reality."},
            {"original_language": "pt", "title": "Cidade de Deus", "overview": "Um jovem no Rio de Janeiro."},
        ])
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = lambda texto: f"[PT] {texto}"

        with patch("src.utils.GoogleTranslator", return_value=mock_translator):
            result = traduzir_colunas_en(df)

        assert result.loc[0, "title"] == "[PT] The Matrix"
        assert result.loc[0, "overview"] == "[PT] A hacker discovers reality."
        assert result.loc[1, "title"] == "Cidade de Deus"
        assert result.loc[1, "overview"] == "Um jovem no Rio de Janeiro."

    def test_retorna_df_inalterado_quando_sem_registros_en(self):
        df = self._make_df([
            {"original_language": "pt", "title": "Tropa de Elite", "overview": "Descricao."},
            {"original_language": "es", "title": "Roma", "overview": "Descripcion."},
        ])
        with patch("src.utils.GoogleTranslator") as mock_cls:
            result = traduzir_colunas_en(df)
            mock_cls.assert_not_called()

        pd.testing.assert_frame_equal(result, df)

    def test_nao_altera_original_title(self):
        df = self._make_df([
            {
                "original_language": "en",
                "title": "Inception",
                "original_title": "Inception",
                "overview": "A thief enters dreams.",
            }
        ])
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = lambda texto: f"[PT] {texto}"

        with patch("src.utils.GoogleTranslator", return_value=mock_translator):
            result = traduzir_colunas_en(df)

        assert result.loc[0, "original_title"] == "Inception"

    def test_fallback_mantém_texto_original_em_caso_de_erro(self):
        df = self._make_df([
            {"original_language": "en", "title": "Dune", "overview": "Desert planet."},
        ])
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("timeout")

        with patch("src.utils.GoogleTranslator", return_value=mock_translator):
            result = traduzir_colunas_en(df)

        assert result.loc[0, "title"] == "Dune"
        assert result.loc[0, "overview"] == "Desert planet."

    def test_overview_vazio_nao_chama_translate(self):
        df = self._make_df([
            {"original_language": "en", "title": "Unknown", "overview": ""},
        ])
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "algo"

        with patch("src.utils.GoogleTranslator", return_value=mock_translator):
            result = traduzir_colunas_en(df)

        assert result.loc[0, "overview"] == ""


class TestWriteParquetToSpec:
    def test_constroi_caminho_s3_correto(self):
        df = pd.DataFrame({"col": [1]})
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_spec(df, s3_bucket_spec="my-spec", table_name="tb_unified", database="db_spec")

            _, kwargs = mock_write.call_args
            assert kwargs["path"] == "s3://my-spec/tb_unified/"

    def test_usa_partition_cols_e_mode_corretos(self):
        df = pd.DataFrame({"col": [1]})
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_spec(df, s3_bucket_spec="my-spec", table_name="tb_unified", database="db_spec")

            _, kwargs = mock_write.call_args
            assert kwargs["partition_cols"] == ["media_type", "year"]
            assert kwargs["mode"] == "overwrite_partitions"
            assert kwargs["dataset"] is True

    def test_registra_tabela_no_catalog(self):
        df = pd.DataFrame({"col": [1]})
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_spec(df, s3_bucket_spec="my-spec", table_name="tb_unified", database="db_spec")

            _, kwargs = mock_write.call_args
            assert kwargs["database"] == "db_spec"
            assert kwargs["table"] == "tb_unified"


# ---------------------------------------------------------------------------
# get_resolved_option / get_parameters_glue
# ---------------------------------------------------------------------------


class TestGetResolvedOption:
    def test_delegates_to_getResolvedOptions(self):
        with patch("src.utils.getResolvedOptions", return_value={"TABLE_NAME": "tb_unified"}) as mock_gro:
            result = get_resolved_option(["TABLE_NAME"])
        mock_gro.assert_called_once()
        assert result == {"TABLE_NAME": "tb_unified"}


class TestGetParametersGlue:
    def _required(self):
        return {
            "S3_BUCKET_SPEC": "spec",
            "S3_BUCKET_TEMP": "tmp",
            "DB_MOVIE": "db_movie",
            "DB_TV": "db_tv",
            "DB_UNIFIED": "db_unified",
            "TABLE_NAME": "tb_unified",
        }

    def test_returns_all_required_args(self):
        with patch("src.utils.get_resolved_option", return_value=self._required()):
            result = get_parameters_glue()
        assert result["S3_BUCKET_SPEC"] == "spec"
        assert result["DB_UNIFIED"] == "db_unified"
        assert result["TABLE_NAME"] == "tb_unified"
