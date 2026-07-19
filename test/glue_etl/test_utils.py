import json
from unittest.mock import MagicMock, patch

import pandas as pd

from src.utils import (
    _add_name_pt_countries,
    _add_name_pt_languages,
    derive_canonical_name,
    get_parameters_glue,
    read_existing_configuration,
    read_from_sor,
    write_parquet_to_sot,
)


# ---------------------------------------------------------------------------
# Helpers compartilhados
# ---------------------------------------------------------------------------


def _make_s3_mock(payload) -> MagicMock:
    """Cria um cliente S3 simulado que retorna `payload` serializado como JSON."""
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode()
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {"Body": body}
    return s3_mock


# ---------------------------------------------------------------------------
# read_from_sor — table_type="discover"
# ---------------------------------------------------------------------------


class TestReadFromSorDiscover:
    def test_calls_wrangler_with_correct_path(self):
        df_mock = pd.DataFrame(
            [{"id": 1, "title": "Film A"}, {"id": 2, "title": "Film B"}]
        )
        with patch("awswrangler.s3.read_json", return_value=df_mock) as mock_read:
            read_from_sor("my-sor", "movie", "discover", year="2023")
            mock_read.assert_called_once_with(
                path="s3://my-sor/tmdb/discover/movie/ano=2023/",
                orient="records",
            )

    def test_adds_year_column(self):
        df_mock = pd.DataFrame([{"id": 1, "title": "Film A"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "discover", year="2023")
            assert "year" in result.columns
            assert result["year"].iloc[0] == "2023"

    def test_year_column_value_matches_arg(self):
        df_mock = pd.DataFrame([{"id": 1}, {"id": 2}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "discover", year="2000")
            assert (result["year"] == "2000").all()

    def test_tv_uses_correct_path(self):
        df_mock = pd.DataFrame([{"id": 10, "name": "Serie A"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock) as mock_read:
            read_from_sor("my-sor", "tv", "discover", year="2022")
            mock_read.assert_called_once_with(
                path="s3://my-sor/tmdb/discover/tv/ano=2022/",
                orient="records",
            )

    def test_overview_idioma_detectado_calculado_a_partir_do_overview(self):
        """overview_idioma_detectado é só diagnóstico (não há tradução no discover —
        o overview já vem pt-BR nativo do TMDB via lambda_api, ver read_from_sor)."""
        df_mock = pd.DataFrame([{"id": 1, "title": "Film A", "overview": "Sinopse"}])
        detect_fn = MagicMock(return_value="pt")
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor(
                "my-sor", "movie", "discover", year="2023", detect_fn=lambda t: detect_fn(t)
            )
        assert result["overview_idioma_detectado"].iloc[0] == "pt"
        detect_fn.assert_called_once_with("Sinopse")

    def test_overview_traduzido_pt_br_derivado_do_idioma_detectado(self):
        """overview_traduzido_pt_br é um booleano puramente derivado de
        overview_idioma_detectado — não há tradução nem chamada de API extra
        no discover (ver read_from_sor)."""
        df_mock = pd.DataFrame([{"id": 1, "title": "Film A", "overview": "Sinopse"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "discover", year="2023", detect_fn=lambda t: "pt")
        assert bool(result["overview_traduzido_pt_br"].iloc[0]) is True

    def test_overview_traduzido_pt_br_false_quando_idioma_nao_e_pt(self):
        df_mock = pd.DataFrame([{"id": 1, "title": "Film A", "overview": "Sinopse"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "discover", year="2023", detect_fn=lambda t: "en")
        assert bool(result["overview_traduzido_pt_br"].iloc[0]) is False

    def test_sem_overview_nao_cria_coluna_de_idioma(self):
        """Guard de schema: se a coluna overview não existir (fixture mínima/legado),
        overview_idioma_detectado e overview_traduzido_pt_br não são criadas."""
        df_mock = pd.DataFrame([{"id": 1, "title": "Film A"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "discover", year="2023")
        assert "overview_idioma_detectado" not in result.columns
        assert "overview_traduzido_pt_br" not in result.columns


# ---------------------------------------------------------------------------
# read_from_sor — table_type="genre"
# ---------------------------------------------------------------------------


class TestReadFromSorGenre:
    def test_movie_reads_correct_s3_key(self):
        s3_mock = _make_s3_mock([{"id": 28, "name": "Ação"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "movie", "genre")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/genre/movie/generos_filmes.json",
            )

    def test_tv_reads_correct_s3_key(self):
        s3_mock = _make_s3_mock([{"id": 10759, "name": "Ação & Aventura"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "tv", "genre")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/genre/tv/generos_series.json",
            )

    def test_returns_dataframe_from_list(self):
        genres = [{"id": 28, "name": "Ação"}, {"id": 12, "name": "Aventura"}]
        s3_mock = _make_s3_mock(genres)
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "genre")
            assert len(result) == 2
            assert list(result.columns) == ["id", "name"]
            assert result["id"].tolist() == [28, 12]


# ---------------------------------------------------------------------------
# read_from_sor — table_type="watch_providers_ref"
# ---------------------------------------------------------------------------


class TestReadFromSorWatchProvidersRef:
    def _make_s3_mock(self, payload) -> MagicMock:
        body = MagicMock()
        body.read.return_value = json.dumps(payload).encode()
        s3_mock = MagicMock()
        s3_mock.get_object.return_value = {"Body": body}
        return s3_mock

    def test_movie_reads_correct_s3_key(self):
        providers = [{"provider_id": 8, "provider_name": "Netflix", "logo_path": "/n.png", "display_priority_br": 1}]
        s3_mock = self._make_s3_mock(providers)
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "movie", "watch_providers_ref")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/watch_providers_ref/movie/watch_providers_ref.json",
            )

    def test_tv_reads_correct_s3_key(self):
        providers = [{"provider_id": 9, "provider_name": "Prime Video", "logo_path": "/p.png", "display_priority_br": 2}]
        s3_mock = self._make_s3_mock(providers)
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "tv", "watch_providers_ref")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/watch_providers_ref/tv/watch_providers_ref.json",
            )

    def test_adds_canonical_name_column(self):
        providers = [{"provider_id": 8, "provider_name": "Netflix Standard with Ads", "logo_path": None, "display_priority_br": None}]
        s3_mock = self._make_s3_mock(providers)
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "watch_providers_ref")
            assert "canonical_name" in result.columns
            assert result["canonical_name"].iloc[0] == "Netflix"

    def test_canonical_name_override_applied(self):
        providers = [{"provider_id": 99, "provider_name": "Paramount Plus", "logo_path": None, "display_priority_br": None}]
        s3_mock = self._make_s3_mock(providers)
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "watch_providers_ref")
            assert result["canonical_name"].iloc[0] == "Paramount+"


# ---------------------------------------------------------------------------
# read_from_sor — table_type="configuration"
# ---------------------------------------------------------------------------


class TestReadFromSorConfiguration:
    def test_movie_reads_languages_s3_key(self):
        s3_mock = _make_s3_mock([{"iso_639_1": "pt", "english_name": "Portuguese"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "movie", "configuration")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/configuration/languages/idiomas.json",
            )

    def test_tv_reads_countries_s3_key(self):
        s3_mock = _make_s3_mock([{"iso_3166_1": "BR", "english_name": "Brazil"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "tv", "configuration")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/configuration/countries/paises.json",
            )

    def test_returns_dataframe_from_list(self):
        s3_mock = _make_s3_mock([{"iso_639_1": "pt"}, {"iso_639_1": "en"}])
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "configuration")
            assert len(result) == 2
            assert "iso_639_1" in result.columns

    def test_tv_countries_recebe_name_pt(self):
        s3_mock = _make_s3_mock([
            {"iso_3166_1": "BR", "english_name": "Brazil", "native_name": "Brasil"},
            {"iso_3166_1": "US", "english_name": "United States", "native_name": "United States"},
        ])
        with (
            patch("boto3.client", return_value=s3_mock),
            patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"),
        ):
            result = read_from_sor("my-sor", "tv", "configuration")
            assert "name_pt" in result.columns
            assert result["name_pt"].iloc[0] == "[PT] Brazil"
            assert result["name_pt"].iloc[1] == "[PT] United States"

    def test_reaproveita_name_pt_quando_english_name_nao_mudou(self):
        """Cache de tradução: english_name idêntico ao já gravado na SOT não é retraduzido."""
        s3_mock = _make_s3_mock([
            {"iso_3166_1": "BR", "english_name": "Brazil", "native_name": "Brasil"},
        ])
        existing_df = pd.DataFrame([
            {"iso_3166_1": "BR", "english_name": "Brazil", "name_pt": "Brasil (cache)"},
        ])
        # langdetect real é pouco confiável para textos curtos (ver conversa sobre
        # a instabilidade do langdetect em textos curtos) — mocka a detecção para
        # exercitar a lógica de cache isoladamente dessa limitação.
        detect_fn = lambda t: "pt" if t == "Brasil (cache)" else "en"  # noqa: E731
        with (
            patch("boto3.client", return_value=s3_mock),
            patch("src.utils.translate_text") as mock_traduzir,
            patch("src.utils.wr.s3.read_parquet", return_value=existing_df),
        ):
            result = read_from_sor(
                "my-sor", "tv", "configuration", s3_bucket_sot="my-sot", table_name="tb_configuration_countries",
                detect_fn=detect_fn,
            )
            assert result["name_pt"].iloc[0] == "Brasil (cache)"
            mock_traduzir.assert_not_called()

    def test_retraduz_quando_english_name_mudou(self):
        s3_mock = _make_s3_mock([
            {"iso_3166_1": "BR", "english_name": "Brazil", "native_name": "Brasil"},
        ])
        existing_df = pd.DataFrame([
            {"iso_3166_1": "BR", "english_name": "Brasil (nome antigo)", "name_pt": "Brasil (cache)"},
        ])
        with (
            patch("boto3.client", return_value=s3_mock),
            patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"),
            patch("src.utils.wr.s3.read_parquet", return_value=existing_df),
        ):
            result = read_from_sor(
                "my-sor", "tv", "configuration", s3_bucket_sot="my-sot", table_name="tb_configuration_countries"
            )
            assert result["name_pt"].iloc[0] == "[PT] Brazil"


class TestAddNamePtCountries:
    def test_traduz_english_name(self):
        df = pd.DataFrame({"english_name": ["Japan", "France"], "native_name": ["日本", "France"]})
        with patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = _add_name_pt_countries(df)
        assert result["name_pt"].iloc[0] == "[PT] Japan"
        assert result["name_pt"].iloc[1] == "[PT] France"

    def test_sem_english_name(self):
        df = pd.DataFrame({"iso_3166_1": ["BR"], "native_name": ["Brasil"]})
        result = _add_name_pt_countries(df)
        assert "name_pt" not in result.columns or result.equals(df)

    def test_english_name_vazio(self):
        df = pd.DataFrame({"english_name": [None, ""]})
        result = _add_name_pt_countries(df)
        assert result["name_pt"].isna().all()

    def test_reaproveita_cache_quando_fonte_identica(self):
        df = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Brazil"]})
        previous_df = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Brazil"], "name_pt": ["Brasil"]})
        with patch("src.utils.translate_text") as mock_traduzir:
            result = _add_name_pt_countries(df, previous_df=previous_df)
        assert result["name_pt"].iloc[0] == "Brasil"
        mock_traduzir.assert_not_called()

    def test_nao_reaproveita_cache_quando_fonte_mudou(self):
        df = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Brazil"]})
        previous_df = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Nome antigo"], "name_pt": ["Brasil"]})
        with patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = _add_name_pt_countries(df, previous_df=previous_df)
        assert result["name_pt"].iloc[0] == "[PT] Brazil"

    def test_idioma_detectado_en_calculado_a_partir_de_english_name(self):
        df = pd.DataFrame({"english_name": ["Japan"]})
        detect_fn = MagicMock(side_effect=lambda t: "en" if t == "Japan" else "pt")
        with patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = _add_name_pt_countries(df, detect_fn=lambda t: detect_fn(t))
        assert result["name_idioma_detectado_en"].iloc[0] == "en"
        detect_fn.assert_any_call("Japan")

    def test_idioma_detectado_pt_e_pt_apos_sucesso(self):
        df = pd.DataFrame({"english_name": ["Japan"]})
        detect_fn = lambda t: "pt" if t.startswith("[PT]") else "en"  # noqa: E731
        with patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = _add_name_pt_countries(df, detect_fn=detect_fn)
        assert result["name_idioma_detectado_pt"].iloc[0] == "pt"

    def test_idioma_detectado_pt_ausente_quando_fonte_ausente(self):
        df = pd.DataFrame({"iso_3166_1": ["BR"], "native_name": ["Brasil"]})
        result = _add_name_pt_countries(df)
        assert "name_idioma_detectado_pt" not in result.columns
        assert "name_tentativas_traducao" not in result.columns

    def test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao(self):
        """Impacto prático baixo (english_name é sempre nome próprio em inglês), mas
        evita o mesmo tipo de desperdício de retradução infinita do glue_details."""
        df = pd.DataFrame({"english_name": ["Nome já em português"]})
        translate_fn = MagicMock(side_effect=lambda t, **kw: f"[PT] {t}")
        with patch("src.utils.translate_text", translate_fn):
            result = _add_name_pt_countries(df, detect_fn=lambda t: "pt")
        assert result["name_pt"].iloc[0] == "Nome já em português"
        assert result["name_idioma_detectado_pt"].iloc[0] == "pt"
        translate_fn.assert_not_called()


# ---------------------------------------------------------------------------
# _add_name_pt_languages
# ---------------------------------------------------------------------------


class TestAddNamePtLanguages:
    def test_traduz_english_name(self):
        df = pd.DataFrame({"english_name": ["English", "French"], "name": ["English", "Français"]})
        with patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = _add_name_pt_languages(df)
        assert result["name_pt"].iloc[0] == "[PT] English"
        assert result["name_pt"].iloc[1] == "[PT] French"

    def test_sem_english_name(self):
        df = pd.DataFrame({"iso_639_1": ["pt"], "name": ["Português"]})
        result = _add_name_pt_languages(df)
        assert "name_pt" not in result.columns or result.equals(df)

    def test_english_name_vazio(self):
        df = pd.DataFrame({"english_name": [None, ""]})
        result = _add_name_pt_languages(df)
        assert result["name_pt"].isna().all()

    def test_reaproveita_cache_quando_fonte_identica(self):
        df = pd.DataFrame({"iso_639_1": ["en"], "english_name": ["English"]})
        previous_df = pd.DataFrame({"iso_639_1": ["en"], "english_name": ["English"], "name_pt": ["Inglês"]})
        # langdetect real é pouco confiável para textos curtos (ver conversa sobre
        # a instabilidade do langdetect em textos curtos) — mocka a detecção para
        # exercitar a lógica de cache isoladamente dessa limitação.
        detect_fn = lambda t: "pt" if t == "Inglês" else "en"  # noqa: E731
        with patch("src.utils.translate_text") as mock_traduzir:
            result = _add_name_pt_languages(df, previous_df=previous_df, detect_fn=detect_fn)
        assert result["name_pt"].iloc[0] == "Inglês"
        mock_traduzir.assert_not_called()

    def test_nao_reaproveita_cache_quando_fonte_mudou(self):
        df = pd.DataFrame({"iso_639_1": ["en"], "english_name": ["English"]})
        previous_df = pd.DataFrame({"iso_639_1": ["en"], "english_name": ["Nome antigo"], "name_pt": ["Inglês"]})
        with patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = _add_name_pt_languages(df, previous_df=previous_df)
        assert result["name_pt"].iloc[0] == "[PT] English"

    def test_idioma_detectado_en_calculado_a_partir_de_english_name(self):
        df = pd.DataFrame({"english_name": ["English"]})
        detect_fn = MagicMock(side_effect=lambda t: "en" if t == "English" else "pt")
        with patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = _add_name_pt_languages(df, detect_fn=lambda t: detect_fn(t))
        assert result["name_idioma_detectado_en"].iloc[0] == "en"
        detect_fn.assert_any_call("English")

    def test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao(self):
        df = pd.DataFrame({"english_name": ["Nome já em português"]})
        translate_fn = MagicMock(side_effect=lambda t, **kw: f"[PT] {t}")
        with patch("src.utils.translate_text", translate_fn):
            result = _add_name_pt_languages(df, detect_fn=lambda t: "pt")
        assert result["name_pt"].iloc[0] == "Nome já em português"
        assert result["name_idioma_detectado_pt"].iloc[0] == "pt"
        translate_fn.assert_not_called()


# ---------------------------------------------------------------------------
# read_existing_configuration
# ---------------------------------------------------------------------------


class TestReadExistingConfiguration:
    def test_retorna_dataframe_lido(self):
        df_mock = pd.DataFrame([{"iso_3166_1": "BR", "english_name": "Brazil", "name_pt": "Brasil"}])
        with patch("src.utils.wr.s3.read_parquet", return_value=df_mock) as mock_read:
            result = read_existing_configuration("my-sot", "tb_configuration_countries")
            mock_read.assert_called_once_with(
                path="s3://my-sot/tmdb/tb_configuration_countries/", dataset=True
            )
            assert result.equals(df_mock)

    def test_retorna_vazio_quando_tabela_nao_existe(self):
        with patch("src.utils.wr.s3.read_parquet", side_effect=Exception("tabela não encontrada")):
            result = read_existing_configuration("my-sot", "tb_configuration_countries")
            assert result.empty


class TestReadFromSorConfigurationLanguages:
    def test_movie_configuration_recebe_name_pt(self):
        payload = [{"iso_639_1": "en", "english_name": "English", "name": "English"}]
        s3_mock = _make_s3_mock(payload)
        with (
            patch("src.utils.boto3.client", return_value=s3_mock),
            patch("src.utils.translate_text", side_effect=lambda t, **kw: f"[PT] {t}"),
        ):
            df = read_from_sor("my-sor", "movie", "configuration")
        assert "name_pt" in df.columns
        assert df["name_pt"].iloc[0] == "[PT] English"


# ---------------------------------------------------------------------------
# read_from_sor — table_type="now_playing"
# ---------------------------------------------------------------------------


class TestReadFromSorNowPlaying:
    def test_reads_correct_s3_path(self):
        df_mock = pd.DataFrame([{"id": 1, "title": "Filme X"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock) as mock_read:
            read_from_sor("my-sor", "movie", "now_playing")
            mock_read.assert_called_once_with(
                path="s3://my-sor/tmdb/now_playing/movie/",
                orient="records",
            )

    def test_deduplicates_by_id(self):
        df_with_dups = pd.DataFrame([
            {"id": 1, "title": "Filme A"},
            {"id": 1, "title": "Filme A duplicado"},
            {"id": 2, "title": "Filme B"},
        ])
        with patch("awswrangler.s3.read_json", return_value=df_with_dups):
            result = read_from_sor("my-sor", "movie", "now_playing")
            assert len(result) == 2
            assert list(result["id"]) == [1, 2]

    def test_returns_dataframe(self):
        df_mock = pd.DataFrame([{"id": 10, "title": "Filme Y", "vote_average": 7.5}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "now_playing")
            assert "id" in result.columns
            assert result["id"].iloc[0] == 10


# ---------------------------------------------------------------------------
# write_parquet_to_sot
# ---------------------------------------------------------------------------


class TestWriteParquetToSot:
    def test_with_partition_cols(self):
        df = pd.DataFrame([{"id": 1, "year": "2023"}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="my-sot",
                table_name="tb_tmdb_discover_movie_dev",
                database="db_tmdb_movie_dev",
                partition_cols=["year"],
            )
            mock_write.assert_called_once_with(
                df=df,
                path="s3://my-sot/tmdb/tb_tmdb_discover_movie_dev/",
                dataset=True,
                partition_cols=["year"],
                mode="overwrite_partitions",
                database="db_tmdb_movie_dev",
                table="tb_tmdb_discover_movie_dev",
            )

    def test_without_partition_cols_defaults_to_none(self):
        df = pd.DataFrame([{"id": 28, "name": "Ação"}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="my-sot",
                table_name="tb_tmdb_genre_movie_dev",
                database="db_tmdb_movie_dev",
            )
            mock_write.assert_called_once_with(
                df=df,
                path="s3://my-sot/tmdb/tb_tmdb_genre_movie_dev/",
                dataset=True,
                partition_cols=None,
                mode="overwrite_partitions",
                database="db_tmdb_movie_dev",
                table="tb_tmdb_genre_movie_dev",
            )

    def test_custom_mode_is_forwarded(self):
        df = pd.DataFrame([{"id": 1}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="my-sot",
                table_name="tb_test",
                database="db_tmdb_movie_dev",
                mode="overwrite",
            )
            _, kwargs = mock_write.call_args
            assert kwargs["mode"] == "overwrite"

    def test_s3_path_uses_table_name(self):
        df = pd.DataFrame([{"id": 1}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="bucket-sot",
                table_name="tb_custom",
                database="db_tmdb_movie_dev",
            )
            _, kwargs = mock_write.call_args
            assert kwargs["path"] == "s3://bucket-sot/tmdb/tb_custom/"


# ---------------------------------------------------------------------------
# derive_canonical_name
# ---------------------------------------------------------------------------


class TestDeriveCanonicalName:
    def test_remove_sufixo_standard_with_ads(self):
        assert derive_canonical_name("Netflix Standard with Ads") == "Netflix"

    def test_remove_sufixo_with_ads(self):
        assert derive_canonical_name("Max with Ads") == "Max"

    def test_remove_sufixo_plus_premium(self):
        # " Plus Premium" é sufixo próprio na lista — remove tudo junto
        assert derive_canonical_name("Disney Plus Premium") == "Disney"

    def test_remove_sufixo_premium_simples(self):
        assert derive_canonical_name("HBO Premium") == "HBO"

    def test_remove_sufixo_amazon_channel(self):
        assert derive_canonical_name("Telecine Amazon Channel") == "Telecine"

    def test_override_paramount_plus(self):
        assert derive_canonical_name("Paramount Plus") == "Paramount+"

    def test_override_claro_video(self):
        assert derive_canonical_name("Claro video") == "Claro Video"

    def test_nome_sem_sufixo_permanece_inalterado(self):
        assert derive_canonical_name("Netflix") == "Netflix"

    def test_plus_premium_tem_prioridade_sobre_premium(self):
        # " Plus Premium" aparece antes de " Premium" na lista, então é removido primeiro
        assert derive_canonical_name("Canal Plus Premium") == "Canal"

    def test_sufixo_amazon_channel_minusculo(self):
        # API retorna "channel" em minúsculo para alguns provedores
        assert derive_canonical_name("Adrenalina Pura Amazon channel") == "Adrenalina Pura"

    def test_paramount_plus_premium(self):
        # " Plus Premium" → "Paramount" → override → "Paramount+"
        assert derive_canonical_name("Paramount Plus Premium") == "Paramount+"

    def test_mgm_plus_amazon_channel(self):
        # " Amazon Channel" → "MGM Plus" → override → "MGM+"
        assert derive_canonical_name("MGM Plus Amazon Channel") == "MGM+"


# ---------------------------------------------------------------------------
# get_resolved_option / get_parameters_glue
# ---------------------------------------------------------------------------


class TestGetParametersGlue:
    def _required(self):
        return {
            "S3_BUCKET_SOR": "sor",
            "S3_BUCKET_SOT": "sot",
            "MEDIA_TYPE": "movie",
            "DATABASE": "db",
            "TABLE_NAME": "tb",
            "TABLE_TYPE": "discover",
            "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
            "GLUE_AGG_JOB_NAME": "agg-job",
            "GLUE_DETAILS_JOB_NAME": "det-job",
        }

    def test_returns_required_args(self):
        with patch("src.utils.get_resolved_option", side_effect=[self._required(), SystemExit(1), SystemExit(1)]):
            result = get_parameters_glue()
        assert result["S3_BUCKET_SOR"] == "sor"
        assert result["TABLE_TYPE"] == "discover"

    def test_includes_year_when_provided(self):
        year_args = {"YEAR": "2024", "END_YEAR": "2025"}
        with patch("src.utils.get_resolved_option", side_effect=[self._required(), year_args, SystemExit(1)]):
            result = get_parameters_glue()
        assert result["YEAR"] == "2024"
        assert result["END_YEAR"] == "2025"

    def test_omits_year_when_not_provided(self):
        def _side_effect(args):
            if "YEAR" in args or "TRANSLATE_PROVIDER" in args:
                raise SystemExit(1)
            return self._required()

        with patch("src.utils.get_resolved_option", side_effect=_side_effect):
            result = get_parameters_glue()
        assert "YEAR" not in result

    def test_defaults_translate_provider_to_google_when_not_provided(self):
        with patch("src.utils.get_resolved_option", side_effect=[self._required(), SystemExit(1), SystemExit(1)]):
            result = get_parameters_glue()
        assert result["TRANSLATE_PROVIDER"] == "google"

    def test_includes_translate_provider_when_provided(self):
        with patch(
            "src.utils.get_resolved_option",
            side_effect=[self._required(), SystemExit(1), {"TRANSLATE_PROVIDER": "google"}],
        ):
            result = get_parameters_glue()
        assert result["TRANSLATE_PROVIDER"] == "google"
