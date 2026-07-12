import pandas as pd
from unittest.mock import MagicMock, patch

import src.utils as u


# ---------------------------------------------------------------------------
# Funções auxiliares de extração (enriquecimento TMDB)
# ---------------------------------------------------------------------------


class TestExtrairElenco:
    def test_top_5_por_ordem(self):
        creditos = {"cast": [
            {"name": "Ator C", "order": 2},
            {"name": "Ator A", "order": 0},
            {"name": "Ator B", "order": 1},
            {"name": "Ator D", "order": 3},
            {"name": "Ator E", "order": 4},
            {"name": "Ator F", "order": 5},
        ]}
        assert u._extrair_elenco(creditos) == "Ator A, Ator B, Ator C, Ator D, Ator E"

    def test_menos_que_limite(self):
        creditos = {"cast": [{"name": "Ator A", "order": 0}]}
        assert u._extrair_elenco(creditos) == "Ator A"

    def test_cast_vazio(self):
        assert u._extrair_elenco({"cast": []}) is None

    def test_sem_cast(self):
        assert u._extrair_elenco({}) is None

    def test_limite_customizado(self):
        creditos = {"cast": [
            {"name": f"Ator {i}", "order": i} for i in range(10)
        ]}
        assert u._extrair_elenco(creditos, limite=3) == "Ator 0, Ator 1, Ator 2"


class TestExtrairDiretor:
    def test_diretor_unico(self):
        creditos = {"crew": [
            {"name": "Christopher Nolan", "job": "Director"},
            {"name": "Emma Thomas", "job": "Producer"},
        ]}
        assert u._extrair_diretor(creditos) == "Christopher Nolan"

    def test_multiplos_diretores(self):
        creditos = {"crew": [
            {"name": "Diretor A", "job": "Director"},
            {"name": "Diretor B", "job": "Director"},
        ]}
        assert u._extrair_diretor(creditos) == "Diretor A, Diretor B"

    def test_sem_diretor(self):
        creditos = {"crew": [{"name": "Produtor", "job": "Producer"}]}
        assert u._extrair_diretor(creditos) is None

    def test_crew_vazio(self):
        assert u._extrair_diretor({"crew": []}) is None


class TestExtrairRoteiristas:
    def test_roteirista_unico(self):
        creditos = {"crew": [
            {"name": "Aaron Sorkin", "job": "Screenplay"},
            {"name": "Produtor X", "job": "Producer"},
        ]}
        assert u._extrair_roteiristas(creditos) == "Aaron Sorkin"

    def test_multiplos_roteiristas(self):
        creditos = {"crew": [
            {"name": "Roteirista A", "job": "Screenplay"},
            {"name": "Roteirista B", "job": "Writer"},
        ]}
        assert u._extrair_roteiristas(creditos) == "Roteirista A, Roteirista B"

    def test_deduplica_mesmo_nome(self):
        creditos = {"crew": [
            {"name": "Aaron Sorkin", "job": "Screenplay"},
            {"name": "Aaron Sorkin", "job": "Writer"},
        ]}
        assert u._extrair_roteiristas(creditos) == "Aaron Sorkin"

    def test_sem_roteirista(self):
        creditos = {"crew": [{"name": "Diretor", "job": "Director"}]}
        assert u._extrair_roteiristas(creditos) is None

    def test_crew_vazio(self):
        assert u._extrair_roteiristas({"crew": []}) is None


class TestExtrairCompositor:
    def test_compositor_unico(self):
        creditos = {"crew": [
            {"name": "Hans Zimmer", "job": "Original Music Composer"},
            {"name": "Diretor X", "job": "Director"},
        ]}
        assert u._extrair_compositor(creditos) == "Hans Zimmer"

    def test_multiplos_compositores(self):
        creditos = {"crew": [
            {"name": "Hans Zimmer", "job": "Original Music Composer"},
            {"name": "John Williams", "job": "Original Music Composer"},
        ]}
        assert u._extrair_compositor(creditos) == "Hans Zimmer, John Williams"

    def test_sem_compositor(self):
        creditos = {"crew": [{"name": "Produtor", "job": "Producer"}]}
        assert u._extrair_compositor(creditos) is None

    def test_crew_vazio(self):
        assert u._extrair_compositor({"crew": []}) is None


class TestExtrairKeywords:
    def test_formato_movie(self):
        dados = {"keywords": [{"id": 1, "name": "time travel"}, {"id": 2, "name": "dystopia"}]}
        assert u._extrair_keywords(dados) == "time travel, dystopia"

    def test_formato_tv(self):
        dados = {"results": [{"id": 1, "name": "based on novel"}]}
        assert u._extrair_keywords(dados) == "based on novel"

    def test_vazio(self):
        assert u._extrair_keywords({}) is None

    def test_lista_vazia(self):
        assert u._extrair_keywords({"keywords": []}) is None


class TestExtrairCertificacaoBrMovie:
    def test_encontra_br(self):
        dados = {"results": [
            {"iso_3166_1": "US", "release_dates": [{"certification": "PG-13"}]},
            {"iso_3166_1": "BR", "release_dates": [{"certification": "14"}]},
        ]}
        assert u._extrair_certificacao_br_movie(dados) == "14"

    def test_sem_br(self):
        dados = {"results": [{"iso_3166_1": "US", "release_dates": [{"certification": "R"}]}]}
        assert u._extrair_certificacao_br_movie(dados) is None

    def test_br_sem_certification(self):
        dados = {"results": [{"iso_3166_1": "BR", "release_dates": [{"certification": ""}]}]}
        assert u._extrair_certificacao_br_movie(dados) is None

    def test_vazio(self):
        assert u._extrair_certificacao_br_movie({}) is None


class TestExtrairCertificacaoBrTv:
    def test_encontra_br(self):
        dados = {"results": [
            {"iso_3166_1": "US", "rating": "TV-MA"},
            {"iso_3166_1": "BR", "rating": "16"},
        ]}
        assert u._extrair_certificacao_br_tv(dados) == "16"

    def test_sem_br(self):
        dados = {"results": [{"iso_3166_1": "US", "rating": "TV-14"}]}
        assert u._extrair_certificacao_br_tv(dados) is None

    def test_rating_vazio(self):
        dados = {"results": [{"iso_3166_1": "BR", "rating": ""}]}
        assert u._extrair_certificacao_br_tv(dados) is None


class TestExtrairTrailerUrl:
    def test_trailer_oficial(self):
        videos = {"results": [
            {"type": "Trailer", "site": "YouTube", "official": True, "key": "abc123"},
            {"type": "Trailer", "site": "YouTube", "official": False, "key": "xyz789"},
        ]}
        assert u._extrair_trailer_url(videos) == "https://youtube.com/watch?v=abc123"

    def test_fallback_nao_oficial(self):
        videos = {"results": [
            {"type": "Trailer", "site": "YouTube", "official": False, "key": "xyz789"},
        ]}
        assert u._extrair_trailer_url(videos) == "https://youtube.com/watch?v=xyz789"

    def test_sem_youtube(self):
        videos = {"results": [{"type": "Trailer", "site": "Vimeo", "official": True, "key": "v1"}]}
        assert u._extrair_trailer_url(videos) is None

    def test_sem_trailer(self):
        videos = {"results": [{"type": "Teaser", "site": "YouTube", "official": True, "key": "t1"}]}
        assert u._extrair_trailer_url(videos) is None

    def test_vazio(self):
        assert u._extrair_trailer_url({}) is None


class TestExtrairProdutoras:
    def test_produtoras(self):
        companies = [{"name": "A24"}, {"name": "Pixar"}]
        assert u._extrair_produtoras(companies) == "A24, Pixar"

    def test_lista_vazia(self):
        assert u._extrair_produtoras([]) is None

    def test_none(self):
        assert u._extrair_produtoras(None) is None


class TestExtrairCriadores:
    def test_criadores(self):
        created_by = [{"name": "Vince Gilligan"}, {"name": "Peter Gould"}]
        assert u._extrair_criadores(created_by) == "Vince Gilligan, Peter Gould"

    def test_vazio(self):
        assert u._extrair_criadores([]) is None


class TestExtrairNetworks:
    def test_networks(self):
        networks = [{"name": "HBO"}, {"name": "Netflix"}]
        assert u._extrair_networks(networks) == "HBO, Netflix"

    def test_vazio(self):
        assert u._extrair_networks([]) is None


class TestExtrairSpokenLanguages:
    def test_prioriza_name_sobre_english_name(self):
        langs = [{"name": "Português", "english_name": "Portuguese"}, {"name": "Français", "english_name": "French"}]
        assert u._extrair_spoken_languages(langs) == "Português, Français"

    def test_fallback_para_english_name(self):
        langs = [{"english_name": "English"}, {"name": "Français", "english_name": "French"}]
        assert u._extrair_spoken_languages(langs) == "English, Français"

    def test_vazio(self):
        assert u._extrair_spoken_languages([]) is None

    def test_none(self):
        assert u._extrair_spoken_languages(None) is None


class TestExtrairSpokenLanguagesIso:
    def test_extrai_codigos_iso(self):
        langs = [{"iso_639_1": "en", "name": "English"}, {"iso_639_1": "fr", "name": "Français"}]
        assert u._extrair_spoken_languages_iso(langs) == ["en", "fr"]

    def test_ignora_sem_iso(self):
        langs = [{"name": "English"}, {"iso_639_1": "fr", "name": "Français"}]
        assert u._extrair_spoken_languages_iso(langs) == ["fr"]

    def test_vazio(self):
        assert u._extrair_spoken_languages_iso([]) is None

    def test_none(self):
        assert u._extrair_spoken_languages_iso(None) is None


class TestExtrairTraducaoPtBr:
    def test_extrai_overview_e_tagline_pt_br(self):
        translations = {"translations": [
            {"iso_639_1": "es", "iso_3166_1": "ES", "data": {"overview": "Sinopsis", "tagline": "Lema"}},
            {"iso_639_1": "pt", "iso_3166_1": "BR", "data": {"overview": "Sinopse BR", "tagline": "Slogan BR"}},
        ]}
        result = u._extrair_traducao_pt_br(translations)
        assert result["overview_pt_tmdb"] == "Sinopse BR"
        assert result["tagline_pt_tmdb"] == "Slogan BR"

    def test_retorna_none_quando_sem_pt_br(self):
        translations = {"translations": [
            {"iso_639_1": "es", "iso_3166_1": "ES", "data": {"overview": "Sinopsis", "tagline": "Lema"}},
        ]}
        result = u._extrair_traducao_pt_br(translations)
        assert result["overview_pt_tmdb"] is None
        assert result["tagline_pt_tmdb"] is None

    def test_retorna_none_quando_translations_vazio(self):
        result = u._extrair_traducao_pt_br({})
        assert result["overview_pt_tmdb"] is None
        assert result["tagline_pt_tmdb"] is None

    def test_ignora_pt_de_portugal(self):
        translations = {"translations": [
            {"iso_639_1": "pt", "iso_3166_1": "PT", "data": {"overview": "Sinopse PT", "tagline": "Slogan PT"}},
        ]}
        result = u._extrair_traducao_pt_br(translations)
        assert result["overview_pt_tmdb"] is None
        assert result["tagline_pt_tmdb"] is None

    def test_ignora_overview_vazio(self):
        translations = {"translations": [
            {"iso_639_1": "pt", "iso_3166_1": "BR", "data": {"overview": "", "tagline": "Slogan BR"}},
        ]}
        result = u._extrair_traducao_pt_br(translations)
        assert result["overview_pt_tmdb"] is None
        assert result["tagline_pt_tmdb"] == "Slogan BR"


class TestAdicionarTraducoesOverviewPt:
    def test_prioriza_tmdb_pt_br(self):
        df = pd.DataFrame({
            "original_language": ["en"],
            "overview_en": ["A great movie"],
            "overview_pt_tmdb": ["Um grande filme"],
        })
        result = u._adicionar_traducoes_pt(df)
        assert result["overview_pt"].iloc[0] == "Um grande filme"

    def test_fallback_para_google_translator(self):
        df = pd.DataFrame({
            "original_language": ["en"],
            "overview_en": ["A great movie"],
            "overview_pt_tmdb": [None],
        })
        with patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = u._adicionar_traducoes_pt(df)
        assert result["overview_pt"].iloc[0] == "[PT] A great movie"

    def test_nao_traduz_quando_idioma_original_ja_e_pt(self):
        df = pd.DataFrame({
            "original_language": ["pt"],
            "overview_en": ["Já em português"],
            "overview_pt_tmdb": [None],
        })
        with patch("src.utils.traduzir_texto") as mock_translate:
            result = u._adicionar_traducoes_pt(df)
        mock_translate.assert_not_called()
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_loga_resumo_de_sucesso(self, caplog):
        df = pd.DataFrame({
            "original_language": ["en"],
            "overview_en": ["A great movie"],
            "overview_pt_tmdb": [None],
        })
        with patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[PT] {t}"):
            with caplog.at_level("INFO"):
                u._adicionar_traducoes_pt(df)
        resumo = [r.message for r in caplog.records if "traduzidos com sucesso" in r.message]
        assert resumo == ["1 registros traduzidos com sucesso (overview_pt)."]

    def test_nao_conta_como_sucesso_quando_traducao_falha_e_mantem_original(self, caplog):
        """traduzir_texto devolve o texto original quando falha após todas as tentativas."""
        df = pd.DataFrame({
            "original_language": ["en"],
            "overview_en": ["Falhou"],
            "overview_pt_tmdb": [None],
        })
        with patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: t):
            with caplog.at_level("INFO"):
                result = u._adicionar_traducoes_pt(df)
        assert result["overview_pt"].iloc[0] == "Falhou"
        resumo = [r.message for r in caplog.records if "traduzidos com sucesso" in r.message]
        assert resumo == ["0 registros traduzidos com sucesso (overview_pt)."]

    def test_retenta_quando_overview_pt_tmdb_igual_a_overview_en(self):
        """Caso de borda: tradução nativa do TMDB idêntica ao texto em inglês é
        reenviada ao Google Translate (mesma regra de retry usada no backfill)."""
        df = pd.DataFrame({
            "original_language": ["en"],
            "overview_en": ["Same text"],
            "overview_pt_tmdb": ["Same text"],
        })
        with patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = u._adicionar_traducoes_pt(df)
        assert result["overview_pt"].iloc[0] == "[PT] Same text"


class TestAdicionarTraducoesKeywordsPt:
    def test_traduz_keywords(self):
        df = pd.DataFrame({"original_language": ["en"], "keywords": ["action, drama"]})
        with patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = u._adicionar_traducoes_keywords_pt(df)
        assert result["keywords_pt"].iloc[0] == "[PT] action, drama"

    def test_nao_traduz_quando_idioma_original_ja_e_pt(self):
        df = pd.DataFrame({"original_language": ["pt"], "keywords": ["ação, drama"]})
        with patch("src.utils.traduzir_texto") as mock_translate:
            result = u._adicionar_traducoes_keywords_pt(df)
        mock_translate.assert_not_called()
        assert pd.isna(result["keywords_pt"].iloc[0])

    def test_nao_traduz_quando_keywords_vazias(self):
        df = pd.DataFrame({"original_language": ["en"], "keywords": [None]})
        result = u._adicionar_traducoes_keywords_pt(df)
        assert pd.isna(result["keywords_pt"].iloc[0])


class TestAdicionarTraducoesTaglinePt:
    def test_prioriza_tmdb_pt_br(self):
        df = pd.DataFrame({
            "original_language": ["en"],
            "tagline": ["A great movie"],
            "tagline_pt_tmdb": ["Um grande filme"],
        })
        result = u._adicionar_traducoes_tagline_pt(df)
        assert result["tagline_pt"].iloc[0] == "Um grande filme"

    def test_fallback_para_google_translator(self):
        df = pd.DataFrame({
            "original_language": ["en"],
            "tagline": ["A great movie"],
            "tagline_pt_tmdb": [None],
        })
        with patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = u._adicionar_traducoes_tagline_pt(df)
        assert result["tagline_pt"].iloc[0] == "[PT] A great movie"

    def test_nao_traduz_quando_tudo_vazio(self):
        df = pd.DataFrame({
            "original_language": ["en", "en"],
            "tagline": [None, ""],
            "tagline_pt_tmdb": [None, None],
        })
        result = u._adicionar_traducoes_tagline_pt(df)
        assert result["tagline_pt"].isna().all()

    def test_nao_traduz_quando_idioma_original_ja_e_pt(self):
        df = pd.DataFrame({
            "original_language": ["pt"],
            "tagline": ["Já em português"],
            "tagline_pt_tmdb": [None],
        })
        with patch("src.utils.traduzir_texto") as mock_translate:
            result = u._adicionar_traducoes_tagline_pt(df)
        mock_translate.assert_not_called()
        assert pd.isna(result["tagline_pt"].iloc[0])

    def test_retenta_quando_tagline_pt_tmdb_igual_a_tagline(self):
        """Caso de borda: tradução nativa do TMDB idêntica ao texto em inglês é
        reenviada ao Google Translate (mesma regra de retry usada no backfill)."""
        df = pd.DataFrame({
            "original_language": ["en"],
            "tagline": ["Same text"],
            "tagline_pt_tmdb": ["Same text"],
        })
        with patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[PT] {t}"):
            result = u._adicionar_traducoes_tagline_pt(df)
        assert result["tagline_pt"].iloc[0] == "[PT] Same text"


class TestExtrairPaisesProducaoIso:
    def test_extrai_codigos_iso(self):
        countries = [
            {"iso_3166_1": "US", "name": "United States"},
            {"iso_3166_1": "GB", "name": "United Kingdom"},
        ]
        assert u._extrair_paises_producao_iso(countries) == ["US", "GB"]

    def test_vazio(self):
        assert u._extrair_paises_producao_iso([]) is None

    def test_none(self):
        assert u._extrair_paises_producao_iso(None) is None


class TestExtrairProdutores:
    def test_produtor_unico(self):
        creditos = {"crew": [
            {"name": "Kevin Feige", "job": "Producer"},
            {"name": "Diretor X", "job": "Director"},
        ]}
        assert u._extrair_produtores(creditos) == "Kevin Feige"

    def test_produtor_e_executivo(self):
        creditos = {"crew": [
            {"name": "Kevin Feige", "job": "Producer"},
            {"name": "Victoria Alonso", "job": "Executive Producer"},
        ]}
        assert u._extrair_produtores(creditos) == "Kevin Feige, Victoria Alonso"

    def test_deduplica_mesmo_nome(self):
        creditos = {"crew": [
            {"name": "Kevin Feige", "job": "Producer"},
            {"name": "Kevin Feige", "job": "Executive Producer"},
        ]}
        assert u._extrair_produtores(creditos) == "Kevin Feige"

    def test_limite_top_3(self):
        creditos = {"crew": [
            {"name": f"Produtor {i}", "job": "Producer"} for i in range(5)
        ]}
        assert u._extrair_produtores(creditos) == "Produtor 0, Produtor 1, Produtor 2"

    def test_sem_produtor(self):
        creditos = {"crew": [{"name": "Diretor", "job": "Director"}]}
        assert u._extrair_produtores(creditos) is None

    def test_crew_vazio(self):
        assert u._extrair_produtores({"crew": []}) is None


class TestExtrairCinematografo:
    def test_cinematografo_unico(self):
        creditos = {"crew": [
            {"name": "Roger Deakins", "job": "Director of Photography"},
            {"name": "Diretor X", "job": "Director"},
        ]}
        assert u._extrair_cinematografo(creditos) == "Roger Deakins"

    def test_multiplos_cinematografos(self):
        creditos = {"crew": [
            {"name": "Roger Deakins", "job": "Director of Photography"},
            {"name": "Emmanuel Lubezki", "job": "Director of Photography"},
        ]}
        assert u._extrair_cinematografo(creditos) == "Roger Deakins, Emmanuel Lubezki"

    def test_sem_cinematografo(self):
        creditos = {"crew": [{"name": "Diretor", "job": "Director"}]}
        assert u._extrair_cinematografo(creditos) is None

    def test_crew_vazio(self):
        assert u._extrair_cinematografo({"crew": []}) is None


class TestExtrairMontador:
    def test_montador_unico(self):
        creditos = {"crew": [
            {"name": "Thelma Schoonmaker", "job": "Editor"},
            {"name": "Diretor X", "job": "Director"},
        ]}
        assert u._extrair_montador(creditos) == "Thelma Schoonmaker"

    def test_multiplos_montadores(self):
        creditos = {"crew": [
            {"name": "Thelma Schoonmaker", "job": "Editor"},
            {"name": "Lee Smith", "job": "Editor"},
        ]}
        assert u._extrair_montador(creditos) == "Thelma Schoonmaker, Lee Smith"

    def test_sem_montador(self):
        creditos = {"crew": [{"name": "Diretor", "job": "Director"}]}
        assert u._extrair_montador(creditos) is None

    def test_crew_vazio(self):
        assert u._extrair_montador({"crew": []}) is None


class TestExtrairPaisesProducao:
    def test_paises(self):
        countries = [{"iso_3166_1": "US", "name": "United States"}, {"iso_3166_1": "NZ", "name": "New Zealand"}]
        assert u._extrair_paises_producao(countries) == "United States, New Zealand"

    def test_vazio(self):
        assert u._extrair_paises_producao([]) is None

    def test_none(self):
        assert u._extrair_paises_producao(None) is None


class TestExtrairTitulosRecomendados:
    def test_movie(self):
        recs = {"results": [{"title": "Interstellar"}, {"title": "The Prestige"}]}
        assert u._extrair_titulos_recomendados(recs, "movie") == "Interstellar, The Prestige"

    def test_tv(self):
        recs = {"results": [{"name": "Breaking Bad"}, {"name": "Better Call Saul"}]}
        assert u._extrair_titulos_recomendados(recs, "tv") == "Breaking Bad, Better Call Saul"

    def test_limite(self):
        recs = {"results": [{"title": f"Movie {i}"} for i in range(15)]}
        result = u._extrair_titulos_recomendados(recs, "movie", limite=3)
        assert result == "Movie 0, Movie 1, Movie 2"

    def test_vazio(self):
        assert u._extrair_titulos_recomendados({}, "movie") is None

    def test_results_vazio(self):
        assert u._extrair_titulos_recomendados({"results": []}, "movie") is None


class TestExtrairTitulosSimilares:
    def test_movie(self):
        sim = {"results": [{"title": "Inception"}, {"title": "Tenet"}]}
        assert u._extrair_titulos_similares(sim, "movie") == "Inception, Tenet"

    def test_tv(self):
        sim = {"results": [{"name": "The Wire"}, {"name": "The Sopranos"}]}
        assert u._extrair_titulos_similares(sim, "tv") == "The Wire, The Sopranos"

    def test_vazio(self):
        assert u._extrair_titulos_similares({}, "tv") is None


class TestExtrairIdsRecomendados:
    def test_extrai_ids(self):
        recs = {"results": [{"id": 101, "title": "A"}, {"id": 202, "title": "B"}]}
        assert u._extrair_ids_recomendados(recs) == "101, 202"

    def test_limite(self):
        recs = {"results": [{"id": i, "title": f"M{i}"} for i in range(15)]}
        result = u._extrair_ids_recomendados(recs, limite=3)
        assert result == "0, 1, 2"

    def test_vazio(self):
        assert u._extrair_ids_recomendados({}) is None

    def test_results_vazio(self):
        assert u._extrair_ids_recomendados({"results": []}) is None

    def test_sem_id(self):
        recs = {"results": [{"title": "Sem ID"}]}
        assert u._extrair_ids_recomendados(recs) is None


class TestExtrairIdsSimilares:
    def test_extrai_ids(self):
        sim = {"results": [{"id": 301, "name": "X"}, {"id": 402, "name": "Y"}]}
        assert u._extrair_ids_similares(sim) == "301, 402"

    def test_vazio(self):
        assert u._extrair_ids_similares({}) is None

    def test_sem_id(self):
        sim = {"results": [{"name": "Sem ID"}]}
        assert u._extrair_ids_similares(sim) is None


class TestExtrairTitulosAlternativos:
    def test_movie(self):
        alt = {"titles": [{"title": "Seven"}, {"title": "Se7en"}]}
        assert u._extrair_titulos_alternativos(alt, "movie") == "Seven, Se7en"

    def test_tv(self):
        alt = {"results": [{"title": "La Casa de Papel"}, {"title": "Money Heist"}]}
        assert u._extrair_titulos_alternativos(alt, "tv") == "La Casa de Papel, Money Heist"

    def test_vazio(self):
        assert u._extrair_titulos_alternativos({}, "movie") is None


# ---------------------------------------------------------------------------
# fetch_ids_from_sot
# ---------------------------------------------------------------------------


class TestFetchIdsFromSot:
    def _run(self, year="2025", ids=None, table="tb_tmdb_discover_movie_dev"):
        df = pd.DataFrame({"id": ids or [1, 2]})
        with patch("src.utils.wr.athena.read_sql_query", return_value=df) as mock_athena:
            result = u.fetch_ids_from_sot(
                database="db_tmdb_movie_dev",
                table_discover=table,
                s3_bucket_temp="my-temp",
                year=year,
            )
        return result, mock_athena

    def test_sql_contains_year_equality_filter(self):
        _, mock_athena = self._run(year="2025")
        sql = mock_athena.call_args.kwargs["sql"]
        assert "WHERE year = '2025'" in sql

    def test_returns_list_of_ids(self):
        result, _ = self._run(ids=[1, 2])
        assert result == [1, 2]

    def test_year_filter_uses_passed_year(self):
        _, mock_athena = self._run(year="2000")
        sql = mock_athena.call_args.kwargs["sql"]
        assert "WHERE year = '2000'" in sql

    def test_queries_correct_table(self):
        _, mock_athena = self._run(table="tb_tmdb_discover_tv_dev")
        sql = mock_athena.call_args.kwargs["sql"]
        assert "tb_tmdb_discover_tv_dev" in sql


# ---------------------------------------------------------------------------
# fetch_tmdb_details
# ---------------------------------------------------------------------------


class TestFetchTmdbDetails:
    def test_calls_movie_endpoint(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 1, "runtime": 120}
        with patch("shared_utils.api_client.requests.get", return_value=mock_response) as mock_get:
            u.fetch_tmdb_details("key-123", "movie", 1)
            url = mock_get.call_args[0][0]
            assert "/movie/1" in url

    def test_calls_tv_endpoint(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 10,
            "number_of_seasons": 3,
            "number_of_episodes": 36,
            "episode_run_time": [45],
        }
        with patch("shared_utils.api_client.requests.get", return_value=mock_response) as mock_get:
            u.fetch_tmdb_details("key-123", "tv", 10)
            url = mock_get.call_args[0][0]
            assert "/tv/10" in url

    def test_returns_json_response(self):
        expected = {"id": 1, "runtime": 90}
        mock_response = MagicMock()
        mock_response.json.return_value = expected
        with patch("shared_utils.api_client.requests.get", return_value=mock_response):
            result = u.fetch_tmdb_details("key-123", "movie", 1)
            assert result == expected


# ---------------------------------------------------------------------------
# collect_and_write_details
# ---------------------------------------------------------------------------


class TestCollectAndWriteDetails:
    def _mock_movie_response(self, item_id: int) -> dict:
        return {
            "id": item_id,
            "runtime": 100,
            "release_date": "2023-05-10",
            "title": "Filme A",
            "overview": "Sinopse A",
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "en",
            "tagline": "Uma frase de efeito",
            "status": "Released",
            "belongs_to_collection": {"id": 86311, "name": "The Avengers Collection"},
            "budget": 50000000,
            "revenue": 200000000,
            "production_companies": [{"name": "Studio A"}],
            "production_countries": [{"iso_3166_1": "US", "name": "United States"}],
            "spoken_languages": [{"name": "English", "english_name": "English"}],
            "origin_country": ["US"],
            "credits": {
                "cast": [{"name": "Ator A", "order": 0}, {"name": "Ator B", "order": 1}],
                "crew": [
                    {"name": "Diretor A", "job": "Director"},
                    {"name": "Roteirista A", "job": "Screenplay"},
                    {"name": "Compositor A", "job": "Original Music Composer"},
                    {"name": "Produtor A", "job": "Producer"},
                    {"name": "Foto A", "job": "Director of Photography"},
                    {"name": "Montador A", "job": "Editor"},
                ],
            },
            "keywords": {"keywords": [{"id": 1, "name": "keyword1"}]},
            "release_dates": {"results": [
                {"iso_3166_1": "BR", "release_dates": [{"certification": "12"}]},
            ]},
            "videos": {"results": [
                {"type": "Trailer", "site": "YouTube", "official": True, "key": "abc123"},
            ]},
            "external_ids": {"imdb_id": "tt1234567"},
            "recommendations": {"results": [{"id": 901, "title": "Filme Rec A"}]},
            "similar": {"results": [{"id": 902, "title": "Filme Sim A"}]},
            "alternative_titles": {"titles": [{"title": "Film A Alt"}]},
            "translations": {"translations": [
                {"iso_639_1": "pt", "iso_3166_1": "BR", "data": {
                    "overview": "Sinopse em português do TMDB",
                    "tagline": "Slogan em português do TMDB",
                }},
            ]},
        }

    def _mock_tv_response(self, item_id: int) -> dict:
        return {
            "id": item_id,
            "number_of_seasons": 2,
            "number_of_episodes": 20,
            "episode_run_time": [45],
            "first_air_date": "2022-03-01",
            "name": "Serie A",
            "overview": "Sinopse A",
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "original_language": "en",
            "tagline": "Tagline serie",
            "status": "Returning Series",
            "production_companies": [{"name": "Studio B"}],
            "production_countries": [{"iso_3166_1": "US", "name": "United States"}, {"iso_3166_1": "GB", "name": "United Kingdom"}],
            "spoken_languages": [{"name": "English", "english_name": "English"}, {"name": "Español", "english_name": "Spanish"}],
            "created_by": [{"name": "Criador A"}],
            "networks": [{"name": "HBO"}],
            "in_production": True,
            "last_air_date": "2024-06-15",
            "type": "Scripted",
            "credits": {
                "cast": [{"name": "Ator X", "order": 0}],
                "crew": [
                    {"name": "Diretor TV", "job": "Director"},
                    {"name": "Roteirista TV", "job": "Writer"},
                    {"name": "Compositor TV", "job": "Original Music Composer"},
                    {"name": "Produtor TV", "job": "Executive Producer"},
                    {"name": "Foto TV", "job": "Director of Photography"},
                    {"name": "Montador TV", "job": "Editor"},
                ],
            },
            "keywords": {"results": [{"id": 1, "name": "drama"}]},
            "content_ratings": {"results": [
                {"iso_3166_1": "BR", "rating": "14"},
            ]},
            "videos": {"results": []},
            "external_ids": {"imdb_id": "tt9876543"},
            "recommendations": {"results": [{"id": 903, "name": "Serie Rec A"}]},
            "similar": {"results": [{"id": 904, "name": "Serie Sim A"}]},
            "alternative_titles": {"results": [{"title": "Serie A Alt"}]},
            "translations": {"translations": []},
        }

    def test_movie_prioriza_tmdb_pt_br_para_overview_e_tagline(self):
        """Quando o TMDB tem tradução pt-BR, overview_pt e tagline_pt vêm do TMDB."""
        response = self._mock_movie_response(1)

        with (
            patch("src.utils.fetch_tmdb_details", return_value=response),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: t),
            patch("src.utils._buscar_colecoes_pt_br", return_value={}),
            patch("src.utils.wr.s3.read_parquet", return_value=pd.DataFrame()),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_det", "db")
            df = mock_write.call_args.kwargs["df"]
            assert df["overview_pt"].iloc[0] == "Sinopse em português do TMDB"
            assert df["tagline_pt"].iloc[0] == "Slogan em português do TMDB"

    def test_tv_fallback_google_translator_sem_tmdb_pt_br(self):
        """Quando o TMDB não tem tradução pt-BR, usa GoogleTranslator como fallback."""
        response = self._mock_tv_response(10)

        with (
            patch("src.utils.fetch_tmdb_details", return_value=response),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[GT] {t}"),
            patch("src.utils.wr.s3.read_parquet", return_value=pd.DataFrame()),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [10], "tv", "sot", "tb_det", "db")
            df = mock_write.call_args.kwargs["df"]
            assert df["overview_pt"].iloc[0] == "[GT] Sinopse A"
            assert df["tagline_pt"].iloc[0] == "[GT] Tagline serie"

    def test_movie_writes_runtime_and_year(self):
        ids = [1, 2]
        responses = [self._mock_movie_response(i) for i in ids]

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=responses),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[PT] {t}"),
            patch("src.utils._buscar_colecoes_pt_br", return_value={86311: "Os Vingadores"}),
            patch("src.utils.wr.s3.read_parquet", return_value=pd.DataFrame()),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", ids, "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            df_written = mock_write.call_args.kwargs["df"]

            assert "id" in df_written.columns
            assert "runtime" in df_written.columns
            assert "year" in df_written.columns
            assert "original_language" not in df_written.columns
            assert "overview_pt_tmdb" not in df_written.columns
            assert "tagline_pt_tmdb" not in df_written.columns
            assert "overview_en" in df_written.columns
            assert "overview_pt" in df_written.columns
            assert "poster_path_en" in df_written.columns
            assert "backdrop_path_en" in df_written.columns
            assert "actor_names" in df_written.columns
            assert "director" in df_written.columns
            assert "screenplay" in df_written.columns
            assert "music_composer" in df_written.columns
            assert "keywords" in df_written.columns
            assert "keywords_pt" in df_written.columns
            assert "certification" in df_written.columns
            assert "tagline" in df_written.columns
            assert "tagline_pt" in df_written.columns
            assert "collection_id" in df_written.columns
            assert "collection_name" in df_written.columns
            assert "collection_name_pt" in df_written.columns
            assert "trailer_url" in df_written.columns
            assert "imdb_id" in df_written.columns
            assert "origin_country" in df_written.columns
            assert "producer" in df_written.columns
            assert "cinematographer" in df_written.columns
            assert "editor" in df_written.columns
            assert "production_countries" in df_written.columns
            assert "production_countries_iso" in df_written.columns
            assert df_written["collection_name_pt"].iloc[0] == "Os Vingadores"
            assert df_written["production_countries_iso"].iloc[0] == ["US"]
            assert df_written["recommended_ids"].iloc[0] == "901"
            assert df_written["similar_ids"].iloc[0] == "902"
            assert len(df_written) == 2

    def test_tv_writes_seasons_episodes_runtime(self):
        ids = [10, 20]
        responses = [self._mock_tv_response(i) for i in ids]

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=responses),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[PT] {t}"),
            patch("src.utils.wr.s3.read_parquet", return_value=pd.DataFrame()),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", ids, "tv", "sot", "tb_tmdb_details_tv_dev", "db")
            df_written = mock_write.call_args.kwargs["df"]

            assert "number_of_seasons" in df_written.columns
            assert "number_of_episodes" in df_written.columns
            assert "episode_run_time" in df_written.columns
            assert "title_en" not in df_written.columns
            assert "title_pt" not in df_written.columns
            assert "overview_en" in df_written.columns
            assert "overview_pt" in df_written.columns
            assert "poster_path_en" in df_written.columns
            assert "backdrop_path_en" in df_written.columns
            assert "original_language" not in df_written.columns
            assert "overview_pt_tmdb" not in df_written.columns
            assert "tagline_pt_tmdb" not in df_written.columns
            assert "actor_names" in df_written.columns
            assert "keywords" in df_written.columns
            assert "keywords_pt" in df_written.columns
            assert "tagline" in df_written.columns
            assert "tagline_pt" in df_written.columns
            assert "created_by" in df_written.columns
            assert "networks" in df_written.columns
            assert "trailer_url" in df_written.columns
            assert "imdb_id" in df_written.columns
            assert "producer" in df_written.columns
            assert "cinematographer" in df_written.columns
            assert "editor" in df_written.columns
            assert "production_countries" in df_written.columns
            assert "production_countries_iso" in df_written.columns
            assert "recommended_titles" in df_written.columns
            assert "recommended_ids" in df_written.columns
            assert "similar_titles" in df_written.columns
            assert "similar_ids" in df_written.columns
            assert "alternative_titles" in df_written.columns
            assert df_written["recommended_ids"].iloc[0] == "903"
            assert df_written["similar_ids"].iloc[0] == "904"

    def test_skips_failed_ids_without_raising(self):
        import requests as req_lib

        # side_effect como funcao garante que ID 1 sempre falha e ID 2 sempre
        # tem sucesso, independente da ordem de execucao das threads
        def side_effect(_key, _type, item_id):
            if item_id == 1:
                raise req_lib.RequestException("timeout")
            return {"id": 2, "runtime": 90, "release_date": "2023-01-01"}

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=side_effect),
            patch("src.utils._buscar_colecoes_pt_br", return_value={}),
            patch("src.utils.wr.s3.read_parquet", return_value=pd.DataFrame()),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1, 2], "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            df_written = mock_write.call_args.kwargs["df"]
            assert len(df_written) == 1
            assert df_written.iloc[0]["id"] == 2

    def test_does_not_write_when_all_ids_fail(self):
        import requests as req_lib

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=req_lib.RequestException("err")),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            mock_write.assert_not_called()

    def test_does_not_write_when_all_records_missing_year(self):
        """Titulos sem release_date/first_air_date ficam sem 'year' apos o dropna
        e nao devem chegar ao wr.s3.to_parquet (regressao do EmptyDataFrame)."""
        response = self._mock_movie_response(1)
        response["release_date"] = None
        response["belongs_to_collection"] = None

        with (
            patch("src.utils.fetch_tmdb_details", return_value=response),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: t),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            mock_write.assert_not_called()

    def test_writes_with_year_partition_and_overwrite_mode(self):
        responses = [self._mock_movie_response(1)]

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=responses),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: t),
            patch("src.utils._buscar_colecoes_pt_br", return_value={}),
            patch("src.utils.wr.s3.read_parquet", return_value=pd.DataFrame()),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            assert mock_write.call_args.kwargs["partition_cols"] == ["year"]
            assert mock_write.call_args.kwargs["mode"] == "overwrite_partitions"

    def test_merges_existing_records_not_in_batch(self):
        """Registros existentes cujos IDs nao estao no batch atual sao preservados."""
        existing_df = pd.DataFrame([{
            "id": 99, "runtime": 120, "year": "2023",
            "overview_en": "", "overview_pt": "",
            "poster_path_en": "", "backdrop_path_en": "",
            "dt_processamento": "2023-01-01",
        }])

        with (
            patch("src.utils.fetch_tmdb_details", return_value=self._mock_movie_response(1)),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: t),
            patch("src.utils._buscar_colecoes_pt_br", return_value={}),
            patch("src.utils.wr.s3.read_parquet", return_value=existing_df),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            df_written = mock_write.call_args.kwargs["df"]

            # ID 99 (existente, nao no batch) deve ser preservado junto com o novo ID 1
            assert set(df_written["id"].tolist()) == {1, 99}

    def test_overwrites_id_already_in_batch(self):
        """Se um ID existente esta sendo re-escrito, o registro antigo e substituido."""
        existing_df = pd.DataFrame([{
            "id": 1, "runtime": 999, "year": "2023",
            "overview_en": "", "overview_pt": "",
            "poster_path_en": "", "backdrop_path_en": "",
            "dt_processamento": "2023-01-01",
        }])

        with (
            patch("src.utils.fetch_tmdb_details", return_value=self._mock_movie_response(1)),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: t),
            patch("src.utils._buscar_colecoes_pt_br", return_value={}),
            patch("src.utils.wr.s3.read_parquet", return_value=existing_df),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            df_written = mock_write.call_args.kwargs["df"]

            # Deve haver apenas 1 linha para ID 1 (sem duplicata)
            assert len(df_written[df_written["id"] == 1]) == 1
            # O runtime novo (100) sobrescreve o stale (999)
            assert df_written[df_written["id"] == 1].iloc[0]["runtime"] == 100

    def test_read_parquet_failure_falls_back_to_new_data_only(self):
        """Se read_parquet falhar, a funcao grava apenas os novos registros sem erro."""
        with (
            patch("src.utils.fetch_tmdb_details", return_value=self._mock_movie_response(1)),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: t),
            patch("src.utils._buscar_colecoes_pt_br", return_value={}),
            patch("src.utils.wr.s3.read_parquet", side_effect=Exception("S3 error")),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            df_written = mock_write.call_args.kwargs["df"]
            assert len(df_written) == 1
            assert df_written.iloc[0]["id"] == 1

    def test_nao_retraduz_quando_fonte_nao_mudou(self):
        """Fonte idêntica ao registro existente: reaproveita a tradução sem chamar a API de tradução."""
        existing_df = pd.DataFrame([{
            "id": 10, "year": "2022",
            "overview_en": "Sinopse A", "overview_pt": "Traduzido antes",
            "tagline": "Tagline serie", "tagline_pt": "Tagline traduzida antes",
            "keywords": "drama", "keywords_pt": "Keywords traduzidas antes",
            "dt_processamento": "2024-01-01",
        }])

        with (
            patch("src.utils.fetch_tmdb_details", return_value=self._mock_tv_response(10)),
            patch("src.utils.traduzir_texto") as mock_traduzir,
            patch("src.utils.wr.s3.read_parquet", return_value=existing_df),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [10], "tv", "sot", "tb_tmdb_details_tv_dev", "db")
            df_written = mock_write.call_args.kwargs["df"]

            assert df_written["overview_pt"].iloc[0] == "Traduzido antes"
            assert df_written["tagline_pt"].iloc[0] == "Tagline traduzida antes"
            assert df_written["keywords_pt"].iloc[0] == "Keywords traduzidas antes"
            mock_traduzir.assert_not_called()

    def test_retraduz_apenas_campo_cuja_fonte_mudou(self):
        """Só overview_en mudou: overview_pt é retraduzido, tagline_pt/keywords_pt reaproveitam o cache."""
        existing_df = pd.DataFrame([{
            "id": 10, "year": "2022",
            "overview_en": "Sinopse antiga, diferente", "overview_pt": "Traduzido antes",
            "tagline": "Tagline serie", "tagline_pt": "Tagline traduzida antes",
            "keywords": "drama", "keywords_pt": "Keywords traduzidas antes",
            "dt_processamento": "2024-01-01",
        }])

        with (
            patch("src.utils.fetch_tmdb_details", return_value=self._mock_tv_response(10)),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: f"[GT] {t}"),
            patch("src.utils.wr.s3.read_parquet", return_value=existing_df),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [10], "tv", "sot", "tb_tmdb_details_tv_dev", "db")
            df_written = mock_write.call_args.kwargs["df"]

            assert df_written["overview_pt"].iloc[0] == "[GT] Sinopse A"
            assert df_written["tagline_pt"].iloc[0] == "Tagline traduzida antes"
            assert df_written["keywords_pt"].iloc[0] == "Keywords traduzidas antes"

    def test_traducao_nativa_tmdb_sobrepoe_cache(self):
        """Tradução nativa do TMDB no run atual sobrepõe o cache, mesmo com fonte igual."""
        existing_df = pd.DataFrame([{
            "id": 1, "year": "2023",
            "overview_en": "Sinopse A", "overview_pt": "Cache antigo diferente da nativa",
            "dt_processamento": "2024-01-01",
        }])

        with (
            patch("src.utils.fetch_tmdb_details", return_value=self._mock_movie_response(1)),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: t),
            patch("src.utils._buscar_colecoes_pt_br", return_value={}),
            patch("src.utils.wr.s3.read_parquet", return_value=existing_df),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            df_written = mock_write.call_args.kwargs["df"]

            assert df_written["overview_pt"].iloc[0] == "Sinopse em português do TMDB"

    def test_le_s3_uma_unica_vez_por_particao_year(self):
        """Regressão: a leitura do S3 por partição year deve ser reaproveitada tanto para o
        cache de tradução quanto para o merge final, sem ler a mesma partição duas vezes."""
        with (
            patch("src.utils.fetch_tmdb_details", return_value=self._mock_movie_response(1)),
            patch("src.utils.traduzir_texto", side_effect=lambda t, **kw: t),
            patch("src.utils._buscar_colecoes_pt_br", return_value={}),
            patch("src.utils.wr.s3.read_parquet", return_value=pd.DataFrame()) as mock_read,
            patch("src.utils.wr.s3.to_parquet"),
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_tmdb_details_movie_dev", "db")
            assert mock_read.call_count == 1


# ---------------------------------------------------------------------------
# fetch_tmdb_watch_providers
# ---------------------------------------------------------------------------


class TestFetchTmdbWatchProviders:
    def _make_response(self, br_data: dict) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": {"BR": br_data}}
        return mock_resp

    def test_calls_movie_watch_providers_endpoint(self):
        with patch("shared_utils.api_client.requests.get", return_value=self._make_response({})) as mock_get:
            u.fetch_tmdb_watch_providers("key", "movie", 1)
            url = mock_get.call_args[0][0]
            assert "/movie/1/watch/providers" in url

    def test_calls_tv_watch_providers_endpoint(self):
        with patch("shared_utils.api_client.requests.get", return_value=self._make_response({})) as mock_get:
            u.fetch_tmdb_watch_providers("key", "tv", 10)
            url = mock_get.call_args[0][0]
            assert "/tv/10/watch/providers" in url

    def test_returns_br_section(self):
        br = {"flatrate": [{"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"}]}
        with patch("shared_utils.api_client.requests.get", return_value=self._make_response(br)):
            result = u.fetch_tmdb_watch_providers("key", "movie", 1)
            assert result == br


# ---------------------------------------------------------------------------
# _parse_watch_providers
# ---------------------------------------------------------------------------


class TestParseWatchProviders:
    def test_returns_empty_list_for_empty_br_data(self):
        assert u._parse_watch_providers({}, item_id=1, year="2025") == []

    def test_generates_one_record_per_flatrate_provider(self):
        br = {"flatrate": [
            {"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"},
            {"provider_name": "Prime",   "provider_id": 9, "logo_path": "/p.jpg"},
        ]}
        records = u._parse_watch_providers(br, item_id=1, year="2025")
        assert len(records) == 2
        assert records[0]["provider_type"] == "flatrate"
        assert records[0]["provider_name"] == "Netflix"
        assert records[0]["id"] == 1
        assert records[0]["year"] == "2025"

    def test_generates_records_for_multiple_provider_types(self):
        br = {
            "flatrate": [{"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"}],
            "rent":     [{"provider_name": "Apple",   "provider_id": 2, "logo_path": "/a.jpg"}],
            "buy":      [{"provider_name": "Google",  "provider_id": 3, "logo_path": "/g.jpg"}],
        }
        records = u._parse_watch_providers(br, item_id=5, year="2024")
        types = {r["provider_type"] for r in records}
        assert types == {"flatrate", "rent", "buy"}
        assert len(records) == 3

    def test_ignores_providers_without_name(self):
        br = {"flatrate": [
            {"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"},
            {"provider_id": 99, "logo_path": "/x.jpg"},  # sem provider_name
        ]}
        records = u._parse_watch_providers(br, item_id=1, year="2025")
        assert len(records) == 1
        assert records[0]["provider_name"] == "Netflix"


# ---------------------------------------------------------------------------
# collect_and_write_watch_providers
# ---------------------------------------------------------------------------


class TestCollectAndWriteWatchProviders:
    _BR_DATA = {
        "flatrate": [{"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"}]
    }

    def test_writes_records_with_year_partition(self):
        with (
            patch("src.utils.fetch_tmdb_watch_providers", return_value=self._BR_DATA),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_watch_providers("key", [1], "movie", "sot", "tb_wp_movie", "db", "2025")
            assert mock_write.call_args.kwargs["partition_cols"] == ["year"]

    def test_does_not_write_when_no_providers_found(self):
        with (
            patch("src.utils.fetch_tmdb_watch_providers", return_value={}),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_watch_providers("key", [1], "movie", "sot", "tb_wp_movie", "db", "2025")
            mock_write.assert_not_called()

    def test_skips_failed_ids_without_raising(self):
        import requests as req_lib

        def side_effect(_key, _type, item_id):
            if item_id == 1:
                raise req_lib.RequestException("timeout")
            return self._BR_DATA

        with (
            patch("src.utils.fetch_tmdb_watch_providers", side_effect=side_effect),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_watch_providers("key", [1, 2], "movie", "sot", "tb_wp_movie", "db", "2025")
            df_written = mock_write.call_args.kwargs["df"]
            assert len(df_written) == 1

    def test_passes_year_as_partition_value(self):
        with (
            patch("src.utils.fetch_tmdb_watch_providers", return_value=self._BR_DATA),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_watch_providers("key", [1], "movie", "sot", "tb_wp_movie", "db", "2023")
            df_written = mock_write.call_args.kwargs["df"]
            assert df_written.iloc[0]["year"] == "2023"


# ---------------------------------------------------------------------------
# get_resolved_option / get_parameters_glue
# ---------------------------------------------------------------------------


class TestGetParametersGlue:
    def _required(self):
        return {
            "S3_BUCKET_SOT": "sot",
            "S3_BUCKET_TEMP": "tmp",
            "DATABASE": "db",
            "TABLE_DISCOVER_MOVIE": "tdm",
            "TABLE_DISCOVER_TV": "tdt",
            "TABLE_DETAILS_MOVIE": "det_m",
            "TABLE_DETAILS_TV": "det_tv",
            "TABLE_WATCH_PROVIDERS_MOVIE": "wp_m",
            "TABLE_WATCH_PROVIDERS_TV": "wp_tv",
            "TMDB_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:1:secret:tmdb",
            "GLUE_AGG_JOB_NAME": "agg-job",
            "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
            "MEDIA_TYPE": "movie",
            "YEAR": "2024",
            "END_YEAR": "2025",
        }

    def test_returns_all_required_args(self):
        with patch("src.utils.get_resolved_option", return_value=self._required()):
            result = u.get_parameters_glue()
        assert result["MEDIA_TYPE"] == "movie"
        assert result["YEAR"] == "2024"
        assert result["TMDB_SECRET_ARN"] == "arn:aws:secretsmanager:us-east-1:1:secret:tmdb"


# ---------------------------------------------------------------------------
# fetch_existing_ids_from_details
# ---------------------------------------------------------------------------


class TestFetchExistingIdsFromDetails:
    def _run(self, ids=None, table="tb_tmdb_details_movie_dev", raise_exc=False):
        if raise_exc:
            with patch("src.utils.wr.athena.read_sql_query", side_effect=Exception("err")):
                return u.fetch_existing_ids_from_details(
                    database="db_tmdb_movie_dev",
                    table_details=table,
                    s3_bucket_temp="my-temp",
                ), None
        df = pd.DataFrame({"id": ids if ids is not None else [1, 2]})
        with patch("src.utils.wr.athena.read_sql_query", return_value=df) as mock_athena:
            result = u.fetch_existing_ids_from_details(
                database="db_tmdb_movie_dev",
                table_details=table,
                s3_bucket_temp="my-temp",
            )
        return result, mock_athena

    def test_sql_nao_filtra_por_ano(self):
        """O filtro de year foi removido: IDs existentes em QUALQUER particao sao considerados."""
        _, mock_athena = self._run()
        sql = mock_athena.call_args.kwargs["sql"]
        assert "WHERE year" not in sql

    def test_sql_filtra_mes_atual(self):
        _, mock_athena = self._run()
        sql = mock_athena.call_args.kwargs["sql"]
        assert "date_trunc('month', current_date)" in sql

    def test_retorna_lista_de_ids(self):
        result, _ = self._run(ids=[10, 20, 30])
        assert result == [10, 20, 30]

    def test_retorna_lista_vazia_em_erro(self):
        result, _ = self._run(raise_exc=True)
        assert result == []


# ---------------------------------------------------------------------------
# repair_details_duplicates
# ---------------------------------------------------------------------------


class TestRepairDetailsDuplicates:
    def _run_repair(self, parquet_df=None, s3_exc=None):
        """Helper: executa repair_details_duplicates com mocks configuraveis."""
        if s3_exc:
            with patch("src.utils.wr.s3.read_parquet", side_effect=s3_exc):
                u.repair_details_duplicates(
                    "db_tmdb_movie_dev", "tb_tmdb_details_movie_dev", "sot", "tmp", year="2025"
                )
            return None

        with (
            patch("src.utils.wr.s3.read_parquet", return_value=parquet_df if parquet_df is not None else pd.DataFrame()),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.repair_details_duplicates(
                "db_tmdb_movie_dev", "tb_tmdb_details_movie_dev", "sot", "tmp", year="2025"
            )
        return mock_write

    def test_nao_reescreve_quando_sem_duplicatas(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "runtime": 100, "year": "2025", "dt_processamento": "2025-06-01"},
            {"id": 2, "runtime": 90,  "year": "2025", "dt_processamento": "2025-06-01"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        mock_write.assert_not_called()

    def test_nao_faz_nada_quando_s3_falha(self):
        self._run_repair(s3_exc=Exception("S3 err"))

    def test_nao_reescreve_quando_particao_vazia(self):
        mock_write = self._run_repair(parquet_df=pd.DataFrame())
        mock_write.assert_not_called()

    def test_reescreve_quando_ha_duplicatas(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "runtime": 100, "year": "2025", "dt_processamento": "2025-06-01"},
            {"id": 1, "runtime": 100, "year": "2025", "dt_processamento": "2025-06-02"},
            {"id": 2, "runtime": 90,  "year": "2025", "dt_processamento": "2025-06-01"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        mock_write.assert_called_once()
        df_written = mock_write.call_args.kwargs["df"]
        assert len(df_written) == 2
        assert df_written[df_written["id"] == 1].iloc[0]["dt_processamento"] == "2025-06-02"

    def test_usa_overwrite_partitions(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "runtime": 100, "year": "2025", "dt_processamento": "2025-06-01"},
            {"id": 1, "runtime": 100, "year": "2025", "dt_processamento": "2025-06-02"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        assert mock_write.call_args.kwargs["mode"] == "overwrite_partitions"
        assert mock_write.call_args.kwargs["partition_cols"] == ["year"]


# ---------------------------------------------------------------------------
# repair_discover_duplicates
# ---------------------------------------------------------------------------


class TestRepairDiscoverDuplicates:
    def _run_repair(self, parquet_df=None, s3_exc=None):
        """Helper: executa repair_discover_duplicates com mocks configuraveis."""
        if s3_exc:
            with patch("src.utils.wr.s3.read_parquet", side_effect=s3_exc):
                u.repair_discover_duplicates(
                    "db_tmdb_movie_dev", "tb_tmdb_discover_movie_dev", "sot", year="2025"
                )
            return None

        with (
            patch("src.utils.wr.s3.read_parquet", return_value=parquet_df if parquet_df is not None else pd.DataFrame()),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.repair_discover_duplicates(
                "db_tmdb_movie_dev", "tb_tmdb_discover_movie_dev", "sot", year="2025"
            )
        return mock_write

    def test_nao_reescreve_quando_sem_duplicatas(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "title": "Film A", "popularity": 10.0, "year": "2025"},
            {"id": 2, "title": "Film B", "popularity": 5.0,  "year": "2025"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        mock_write.assert_not_called()

    def test_nao_faz_nada_quando_s3_falha(self):
        self._run_repair(s3_exc=Exception("S3 err"))

    def test_nao_reescreve_quando_particao_vazia(self):
        mock_write = self._run_repair(parquet_df=pd.DataFrame())
        mock_write.assert_not_called()

    def test_reescreve_quando_ha_duplicatas(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "title": "Film A", "popularity": 10.0, "year": "2025"},
            {"id": 1, "title": "Film A", "popularity": 10.0, "year": "2025"},
            {"id": 2, "title": "Film B", "popularity": 5.0,  "year": "2025"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        mock_write.assert_called_once()
        df_written = mock_write.call_args.kwargs["df"]
        assert len(df_written) == 2
        assert set(df_written["id"].tolist()) == {1, 2}

    def test_mantem_registro_mais_popular_quando_ha_duplicatas(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "title": "Film A", "popularity": 5.0,  "year": "2025"},
            {"id": 1, "title": "Film A", "popularity": 20.0, "year": "2025"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        mock_write.assert_called_once()
        df_written = mock_write.call_args.kwargs["df"]
        assert len(df_written) == 1
        assert df_written.iloc[0]["popularity"] == 20.0

    def test_usa_overwrite_partitions(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "title": "Film A", "popularity": 10.0, "year": "2025"},
            {"id": 1, "title": "Film A", "popularity": 10.0, "year": "2025"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        assert mock_write.call_args.kwargs["mode"] == "overwrite_partitions"
        assert mock_write.call_args.kwargs["partition_cols"] == ["year"]


# ---------------------------------------------------------------------------
# repair_watch_providers_duplicates
# ---------------------------------------------------------------------------


class TestRepairWatchProvidersDuplicates:
    def _run_repair(self, parquet_df=None, s3_exc=None):
        """Helper: executa repair_watch_providers_duplicates com mocks configuraveis."""
        if s3_exc:
            with patch("src.utils.wr.s3.read_parquet", side_effect=s3_exc):
                u.repair_watch_providers_duplicates(
                    "db_tmdb_movie_dev", "tb_tmdb_watch_providers_movie_dev", "sot", year="2025"
                )
            return None

        with (
            patch("src.utils.wr.s3.read_parquet", return_value=parquet_df if parquet_df is not None else pd.DataFrame()),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.repair_watch_providers_duplicates(
                "db_tmdb_movie_dev", "tb_tmdb_watch_providers_movie_dev", "sot", year="2025"
            )
        return mock_write

    def test_nao_reescreve_quando_sem_duplicatas(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "provider_type": "flatrate", "provider_id": 8,  "provider_name": "Netflix", "year": "2025", "dt_atualizacao": "2025-06-01"},
            {"id": 1, "provider_type": "flatrate", "provider_id": 9,  "provider_name": "Amazon",  "year": "2025", "dt_atualizacao": "2025-06-01"},
            {"id": 2, "provider_type": "flatrate", "provider_id": 8,  "provider_name": "Netflix", "year": "2025", "dt_atualizacao": "2025-06-01"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        mock_write.assert_not_called()

    def test_nao_faz_nada_quando_s3_falha(self):
        self._run_repair(s3_exc=Exception("S3 err"))

    def test_nao_reescreve_quando_particao_vazia(self):
        mock_write = self._run_repair(parquet_df=pd.DataFrame())
        mock_write.assert_not_called()

    def test_reescreve_quando_ha_duplicatas_pela_chave_composta(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "provider_type": "flatrate", "provider_id": 8, "provider_name": "Netflix", "year": "2025", "dt_atualizacao": "2025-06-01"},
            {"id": 1, "provider_type": "flatrate", "provider_id": 8, "provider_name": "Netflix", "year": "2025", "dt_atualizacao": "2025-06-02"},
            {"id": 1, "provider_type": "flatrate", "provider_id": 9, "provider_name": "Amazon",  "year": "2025", "dt_atualizacao": "2025-06-01"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        mock_write.assert_called_once()
        df_written = mock_write.call_args.kwargs["df"]
        assert len(df_written) == 2
        netflix_row = df_written[(df_written["id"] == 1) & (df_written["provider_id"] == 8)].iloc[0]
        assert netflix_row["dt_atualizacao"] == "2025-06-02"

    def test_dedup_usa_provider_id_nao_provider_name(self):
        """Mesmo provider_id com nomes diferentes (rebranding) e tratado como duplicata."""
        parquet_df = pd.DataFrame([
            {"id": 1, "provider_type": "flatrate", "provider_id": 9, "provider_name": "Amazon Prime Video", "year": "2025", "dt_atualizacao": "2025-01-01"},
            {"id": 1, "provider_type": "flatrate", "provider_id": 9, "provider_name": "Prime Video",        "year": "2025", "dt_atualizacao": "2025-06-01"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        mock_write.assert_called_once()
        df_written = mock_write.call_args.kwargs["df"]
        assert len(df_written) == 1
        assert df_written.iloc[0]["provider_name"] == "Prime Video"

    def test_usa_overwrite_partitions(self):
        parquet_df = pd.DataFrame([
            {"id": 1, "provider_type": "flatrate", "provider_id": 8, "provider_name": "Netflix", "year": "2025", "dt_atualizacao": "2025-06-01"},
            {"id": 1, "provider_type": "flatrate", "provider_id": 8, "provider_name": "Netflix", "year": "2025", "dt_atualizacao": "2025-06-02"},
        ])
        mock_write = self._run_repair(parquet_df=parquet_df)
        assert mock_write.call_args.kwargs["mode"] == "overwrite_partitions"
        assert mock_write.call_args.kwargs["partition_cols"] == ["year"]


# ---------------------------------------------------------------------------
# fetch_ids_stale_watch_providers
# ---------------------------------------------------------------------------


class TestFetchIdsStaleWatchProviders:
    def _run(
        self,
        year="2025",
        ids=None,
        table_discover="tb_tmdb_discover_movie_dev",
        table_wp="tb_tmdb_watch_providers_movie_dev",
        raise_exc=False,
    ):
        if raise_exc:
            with patch("src.utils.wr.athena.read_sql_query", side_effect=Exception("err")):
                return u.fetch_ids_stale_watch_providers(
                    database="db_tmdb_movie_dev",
                    table_discover=table_discover,
                    table_watch_providers=table_wp,
                    s3_bucket_temp="my-temp",
                    year=year,
                ), None
        df = pd.DataFrame({"id": ids if ids is not None else [1, 2]})
        with patch("src.utils.wr.athena.read_sql_query", return_value=df) as mock_athena:
            result = u.fetch_ids_stale_watch_providers(
                database="db_tmdb_movie_dev",
                table_discover=table_discover,
                table_watch_providers=table_wp,
                s3_bucket_temp="my-temp",
                year=year,
            )
        return result, mock_athena

    def test_sql_filtra_pelo_ano(self):
        _, mock_athena = self._run(year="2025")
        sql = mock_athena.call_args.kwargs["sql"]
        assert "d.year = '2025'" in sql

    def test_sql_inclui_condicao_mensal(self):
        _, mock_athena = self._run()
        sql = mock_athena.call_args.kwargs["sql"]
        assert "date_trunc('month', current_date)" in sql

    def test_sql_inclui_join_com_watch_providers(self):
        _, mock_athena = self._run(table_wp="tb_tmdb_watch_providers_movie_dev")
        sql = mock_athena.call_args.kwargs["sql"]
        assert "tb_tmdb_watch_providers_movie_dev" in sql
        assert "LEFT JOIN" in sql.upper()

    def test_retorna_lista_de_ids(self):
        result, _ = self._run(ids=[5, 10])
        assert result == [5, 10]

    def test_retorna_lista_vazia_em_erro(self):
        result, _ = self._run(raise_exc=True)
        assert result == []
