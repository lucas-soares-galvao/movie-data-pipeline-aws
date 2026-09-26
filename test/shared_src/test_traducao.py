import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from shared_utils.traducao import (
    get_translate_chars_used_this_month,
    resolve_pt_translation,
    resolve_translate_fn,
    reuse_existing_translation,
    translate_in_parallel,
)


def _sem_consumo_no_mes() -> int:
    """get_chars_used_this_month que devolve sempre 0 — substitui
    get_translate_chars_used_this_month nos testes que não testam o cálculo do orçamento
    em si (a maioria), evitando que resolve_translate_fn(provider="google", ...) sem esse
    parâmetro explícito acabe fazendo uma chamada real ao CloudWatch."""
    return 0

# Texto real observado nas tabelas do dev (name_pt/overview_pt) no lugar da tradução.
GOOGLE_ERROR_PAGE = (
    "Error 500 (Server Error)!!1500.That’s an error.There was an error. "
    "Please try again later.That’s all we know."
)


class TestResolveTranslateFn:
    def test_resolve_google_usa_google_como_primario(self):
        fn = resolve_translate_fn(
            "google", lambda t: f"[G]{t}", lambda t: f"[A]{t}",
            get_chars_used_this_month=_sem_consumo_no_mes,
        )
        assert fn("Hello") == "[G]Hello"

    def test_resolve_aws_usa_aws_como_primario(self):
        fn = resolve_translate_fn("aws", lambda t: f"[G]{t}", lambda t: f"[A]{t}")
        assert fn("Hello") == "[A]Hello"

    def test_provider_invalido_levanta_value_error(self):
        with pytest.raises(ValueError, match="TRANSLATE_PROVIDER inválido"):
            resolve_translate_fn("deepl")

    def test_usa_referencias_locais_informadas_pelo_chamador(self):
        """translate_google/translate_aws são parâmetros (não resolvidos via módulo)
        para que um chamador que faça patch da própria referência local (ex.:
        patch("src.utils.translate_text", ...)) continue funcionando."""
        fn_google = MagicMock(side_effect=lambda t: f"[G]{t}")
        fn_aws = MagicMock(side_effect=lambda t: f"[A]{t}")

        resolve_translate_fn(
            "google", fn_google, fn_aws, get_chars_used_this_month=_sem_consumo_no_mes,
        )("Hello")
        fn_google.assert_called_once_with("Hello")

        resolve_translate_fn("aws", fn_google, fn_aws)("Hello")
        fn_aws.assert_called_once_with("Hello")

    def test_fallback_disparado_quando_primario_falha(self):
        """Primário devolve o próprio texto (sinal de falha) — cai para o fallback."""
        primario = MagicMock(side_effect=lambda t: t)
        fallback = MagicMock(side_effect=lambda t: f"[fallback]{t}")

        fn = resolve_translate_fn("aws", translate_google=fallback, translate_aws=primario)

        assert fn("Hello") == "[fallback]Hello"
        fallback.assert_called_once_with("Hello")

    def test_fallback_nao_disparado_quando_primario_funciona(self):
        primario = MagicMock(side_effect=lambda t: f"[ok]{t}")
        fallback = MagicMock()

        fn = resolve_translate_fn("aws", translate_google=fallback, translate_aws=primario)

        assert fn("Hello") == "[ok]Hello"
        fallback.assert_not_called()

    def test_texto_vazio_nao_dispara_fallback(self):
        primario = MagicMock(side_effect=lambda t: t)
        fallback = MagicMock()

        fn = resolve_translate_fn("aws", translate_google=fallback, translate_aws=primario)

        assert fn("") == ""
        fallback.assert_not_called()

    def test_cap_por_caracteres_bloqueia_excedente(self):
        """provider="google": AWS é o fallback pago — limitado por aws_fallback_max_chars."""
        primario_google = MagicMock(side_effect=lambda t: t)
        fallback_aws = MagicMock(side_effect=lambda t: f"[aws]{t}")

        fn = resolve_translate_fn(
            "google", translate_google=primario_google, translate_aws=fallback_aws,
            aws_fallback_max_chars=5, get_chars_used_this_month=_sem_consumo_no_mes,
        )

        assert fn("Hello") == "[aws]Hello"  # consome os 5 caracteres do orçamento
        assert fn("Hi") == "Hi"  # orçamento esgotado — devolve o texto original sem chamar o fallback
        fallback_aws.assert_called_once_with("Hello")

    def test_orcamento_restante_desconta_consumo_ja_feito_no_mes(self):
        """aws_fallback_max_chars agora é um teto MENSAL: o que resolve_translate_fn
        realmente aplica é o restante, descontado o que get_chars_used_this_month já
        reporta como consumido no mês corrente (ver get_translate_chars_used_this_month)."""
        primario_google = MagicMock(side_effect=lambda t: t)
        fallback_aws = MagicMock(side_effect=lambda t: f"[aws]{t}")

        fn = resolve_translate_fn(
            "google", translate_google=primario_google, translate_aws=fallback_aws,
            aws_fallback_max_chars=10, get_chars_used_this_month=lambda: 8,
        )

        assert fn("Hi") == "[aws]Hi"  # sobraram 2 caracteres do teto de 10 — "Hi" cabe
        assert fn("Hi") == "Hi"  # os 2 caracteres restantes já foram consumidos acima
        fallback_aws.assert_called_once_with("Hi")

    def test_orcamento_ja_esgotado_no_mes_nao_chama_fallback(self):
        """Se o mês já consumiu mais que o teto, o restante é 0 (nunca negativo) — o
        fallback nem chega a ser chamado."""
        primario_google = MagicMock(side_effect=lambda t: t)
        fallback_aws = MagicMock()

        fn = resolve_translate_fn(
            "google", translate_google=primario_google, translate_aws=fallback_aws,
            aws_fallback_max_chars=10, get_chars_used_this_month=lambda: 999,
        )

        assert fn("Hi") == "Hi"
        fallback_aws.assert_not_called()

    def test_cap_nao_se_aplica_quando_aws_e_primario(self):
        """provider="aws": Google é o fallback (grátis) — sem limite de caracteres."""
        primario_aws = MagicMock(side_effect=lambda t: t)  # sempre "falha"
        fallback_google = MagicMock(side_effect=lambda t: f"[google]{t}")

        fn = resolve_translate_fn(
            "aws", translate_google=fallback_google, translate_aws=primario_aws,
            aws_fallback_max_chars=1,  # cap minúsculo — não deve importar, pois aws é o primário
        )

        for texto in ("Hello", "World", "Another long text"):
            assert fn(texto) == f"[google]{texto}"
        assert fallback_google.call_count == 3

    def test_cap_thread_safe_sob_concorrencia(self):
        """O orçamento de caracteres nunca é ultrapassado mesmo com chamadas concorrentes."""
        primario_google = MagicMock(side_effect=lambda t: t)
        fallback_aws = MagicMock(side_effect=lambda t: f"[aws]{t}")

        fn = resolve_translate_fn(
            "google", translate_google=primario_google, translate_aws=fallback_aws,
            aws_fallback_max_chars=10, get_chars_used_this_month=_sem_consumo_no_mes,
        )
        textos = ["ab"] * 20  # 20 x 2 caracteres = 40 caracteres pedidos, orçamento de 10

        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(fn, textos))

        # orçamento de 10 caracteres / textos de 2 caracteres cada = no máximo 5 chamadas ao fallback
        assert fallback_aws.call_count <= 5


class TestGetTranslateCharsUsedThisMonth:
    """get_translate_chars_used_this_month soma o CharacterCount (CloudWatch,
    namespace AWS/Translate) de todos os pares de idioma publicados, desde o início do
    mês corrente — ver docstring da função em shared_utils.traducao."""

    def _client_com_pares(self, pares_e_totais: dict[str, int]) -> MagicMock:
        """Monta um client CloudWatch mockado: list_metrics devolve um par por chave de
        pares_e_totais, e get_metric_statistics devolve o total correspondente em Sum."""
        client = MagicMock()
        paginator = MagicMock()
        client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{
            "Metrics": [
                {
                    "Dimensions": [
                        {"Name": "LanguagePair", "Value": pair},
                        {"Name": "Operation", "Value": "TranslateText"},
                    ],
                }
                for pair in pares_e_totais
            ],
        }]

        def _get_metric_statistics(**kwargs):
            pair = next(d["Value"] for d in kwargs["Dimensions"] if d["Name"] == "LanguagePair")
            return {"Datapoints": [{"Sum": pares_e_totais[pair]}]}

        client.get_metric_statistics.side_effect = _get_metric_statistics
        return client

    def test_soma_caracteres_de_todos_os_pares_de_idioma(self):
        client = self._client_com_pares({"en-pt": 100, "es-pt": 50})

        total = get_translate_chars_used_this_month(cloudwatch_client=client)

        assert total == 150

    def test_sem_metricas_publicadas_retorna_zero(self):
        client = self._client_com_pares({})

        assert get_translate_chars_used_this_month(cloudwatch_client=client) == 0

    def test_falha_no_cloudwatch_assume_orcamento_esgotado(self):
        """Sem visibilidade do consumo real, assume o pior caso (orçamento esgotado) em
        vez de assumir consumo zero e arriscar gastar sem controle."""
        client = MagicMock()
        client.get_paginator.side_effect = Exception("ThrottlingException simulada")

        assert get_translate_chars_used_this_month(cloudwatch_client=client) == sys.maxsize

    def test_cria_client_proprio_quando_nao_informado(self):
        """Sem cloudwatch_client explícito, cria um client boto3 na região informada —
        us-east-1 por padrão, mesma região de translate_text_aws (AWS Translate não
        está disponível em sa-east-1)."""
        with patch("shared_utils.traducao.boto3") as mock_boto3:
            mock_client = self._client_com_pares({})
            mock_boto3.client.return_value = mock_client

            get_translate_chars_used_this_month()

            mock_boto3.client.assert_called_once_with("cloudwatch", region_name="us-east-1")


class TestTranslateInParallel:
    def test_traduz_cada_valor_e_preserva_a_ordem(self):
        traduzir_fn = MagicMock(side_effect=lambda t: f"[PT] {t}")
        resultado = translate_in_parallel(["Hello", "World"], traduzir_fn)
        assert resultado == ["[PT] Hello", "[PT] World"]

    def test_lista_vazia_nao_chama_traduzir_fn(self):
        traduzir_fn = MagicMock()
        assert translate_in_parallel([], traduzir_fn) == []
        traduzir_fn.assert_not_called()

    def test_usa_max_workers_informado(self):
        """max_workers é repassado ao ThreadPoolExecutor, não hardcoded."""
        with patch("shared_utils.traducao.ThreadPoolExecutor") as mock_executor_cls:
            mock_executor = mock_executor_cls.return_value.__enter__.return_value
            mock_executor.map.return_value = iter(["ok"])
            translate_in_parallel(["Hello"], MagicMock(), max_workers=3)
        mock_executor_cls.assert_called_once_with(max_workers=3)


class TestReuseExistingTranslation:
    def test_reaproveita_quando_fonte_identica(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": ["Traduzido antes"]})
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert result["overview_pt"].iloc[0] == "Traduzido antes"

    def test_nao_reaproveita_quando_fonte_mudou(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse nova"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse antiga"], "overview_pt": ["Traduzido antes"]})
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_nao_reaproveita_id_novo_sem_historico(self):
        df = pd.DataFrame({"id": [2], "overview_en": ["Sinopse"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": ["Traduzido antes"]})
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_df_anterior_none_nao_quebra(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        result = reuse_existing_translation(df, None, "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_df_anterior_vazio_nao_quebra(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        result = reuse_existing_translation(df, pd.DataFrame(), "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_nao_sobrescreve_destino_ja_preenchido(self):
        """Prioridade da tradução nativa do TMDB (já atribuída ao df novo) é preservada."""
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": ["Tradução nativa TMDB"]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": ["Traduzido antes"]})
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert result["overview_pt"].iloc[0] == "Tradução nativa TMDB"

    def test_ignora_schema_antigo_sem_coluna(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"]})  # sem overview_pt
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_ids_duplicados_no_df_anterior_usa_ultimo(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({
            "id": [1, 1],
            "overview_en": ["Sinopse", "Sinopse"],
            "overview_pt": ["Traducao antiga", "Traducao mais recente"],
        })
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert result["overview_pt"].iloc[0] == "Traducao mais recente"

    def test_coluna_chave_customizada(self):
        """glue_etl usa key_column='iso_3166_1'/'iso_639_1' em vez do default 'id'."""
        df = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Brazil"], "name_pt": [None]})
        df_anterior = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Brazil"], "name_pt": ["Brasil"]})
        result = reuse_existing_translation(
            df, df_anterior, "english_name", "name_pt", key_column="iso_3166_1"
        )
        assert result["name_pt"].iloc[0] == "Brasil"

    def test_coluna_chave_customizada_nao_reaproveita_quando_ausente_no_anterior(self):
        df = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Brazil"], "name_pt": [None]})
        df_anterior = pd.DataFrame({"iso_3166_1": ["US"], "english_name": ["United States"], "name_pt": ["Estados Unidos"]})
        result = reuse_existing_translation(
            df, df_anterior, "english_name", "name_pt", key_column="iso_3166_1"
        )
        assert pd.isna(result["name_pt"].iloc[0])

    def test_reuse_existing_translation_ainda_reaproveita_pagina_de_erro_do_cache(self):
        """Contrato documentado: o cache não filtra — quem descarta é resolve_pt_translation."""
        novo = pd.DataFrame({"iso": ["ja"], "english_name": ["Japanese"], "name_pt": [None]})
        anterior = pd.DataFrame({"iso": ["ja"], "english_name": ["Japanese"], "name_pt": [GOOGLE_ERROR_PAGE]})

        resultado = reuse_existing_translation(novo, anterior, "english_name", "name_pt", key_column="iso")

        assert resultado["name_pt"].iloc[0] == GOOGLE_ERROR_PAGE


class TestResolvePtTranslation:
    def _detect_fn(self, mapping):
        return lambda t: mapping.get(t)

    def test_traduz_registros_elegiveis_pendentes(self):
        df = pd.DataFrame({"overview_en": ["Hello", "World"], "overview_pt": [None, None]})
        def detect_fn(t):
            return "en"
        traduzir_fn = MagicMock(side_effect=lambda t: f"[PT] {t}")

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 2
        assert df["overview_pt"].tolist() == ["[PT] Hello", "[PT] World"]

    def test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_tradutor(self):
        df = pd.DataFrame({"overview_en": ["Já em português"], "overview_pt": [None]})
        def detect_fn(t):
            return "pt"
        traduzir_fn = MagicMock()

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 0
        assert df["overview_pt"].iloc[0] == "Já em português"
        assert df["overview_idioma_pt"].iloc[0] == "pt"
        assert df["overview_tentativas"].iloc[0] == 0
        traduzir_fn.assert_not_called()

    def test_elegibilidade_usa_idioma_do_destino_nao_diff_de_string(self):
        """Um destino que difere da fonte mas cujo idioma detectado não é 'pt'
        (ex.: mistradução silenciosa) continua elegível — diferente da antiga
        heurística de string-diff, que consideraria isso 'já traduzido'."""
        df = pd.DataFrame({
            "overview_en": ["Hello"],
            "overview_pt": ["Bonjour"],  # traduziu errado, pra francês
            "overview_idioma_en": ["en"],
        })
        detect_fn = self._detect_fn({"Hello": "en", "Bonjour": "fr", "Olá": "pt"})
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 1
        assert df["overview_pt"].iloc[0] == "Olá"
        assert df["overview_idioma_pt"].iloc[0] == "pt"

    def test_nao_retraduz_quando_idioma_pt_ja_confirmado(self):
        df = pd.DataFrame({
            "overview_en": ["Hello"],
            "overview_pt": ["Olá"],
            "overview_idioma_pt": ["pt"],
        })
        traduzir_fn = MagicMock()

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn,
        )

        assert sucesso == 0
        traduzir_fn.assert_not_called()

    def test_redetecta_idioma_pt_so_nas_linhas_recem_traduzidas(self):
        """A detecção feita antes da tradução (sobre o valor antigo/vazio de
        overview_pt) fica obsoleta para as linhas traduzidas nesta execução — só
        essas devem ser redetectadas a partir do novo valor."""
        df = pd.DataFrame({
            "overview_en": ["Hello", "World"],
            "overview_pt": [None, None],
            "overview_idioma_pt": [None, "en"],  # linha 2: já detectado antes (não-pt)
        })
        detect_fn = self._detect_fn({"Hello": "en", "World": "en", "Olá": "pt", "Mundo": "pt"})
        traduzir_fn = MagicMock(side_effect=lambda t: {"Hello": "Olá", "World": "Mundo"}[t])

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 2
        assert df["overview_idioma_pt"].tolist() == ["pt", "pt"]

    def test_incrementa_tentativas_para_linhas_elegiveis(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        def detect_fn(t):
            return "en"
        traduzir_fn = MagicMock(side_effect=lambda t: t)  # tradução "falha" (devolve igual)

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert df["overview_tentativas"].iloc[0] == 1

    def test_copia_direta_nao_incrementa_tentativas(self):
        df = pd.DataFrame({"overview_en": ["Já em português"], "overview_pt": [None]})
        def detect_fn(t):
            return "pt"
        traduzir_fn = MagicMock()

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert df["overview_tentativas"].iloc[0] == 0

    def test_esgota_tentativas_e_para_de_reenviar_ao_tradutor(self):
        """Conteúdo genuinamente não traduzível (nome próprio, termo curto) nunca
        teria idioma_pt == 'pt' — sem o teto, seria retentado para sempre."""
        df = pd.DataFrame({
            "overview_en": ["Iron Man"],
            "overview_pt": ["Iron Man"],
            "overview_idioma_pt": ["en"],
            "overview_tentativas": [3],
        })
        traduzir_fn = MagicMock()

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn, max_attempts=3,
        )

        assert sucesso == 0
        traduzir_fn.assert_not_called()
        assert df["overview_tentativas"].iloc[0] == 3

    def test_descarta_pagina_de_erro_do_google_e_retraduz(self):
        """Página de erro gravada como tradução (versões antigas de translate_text) é
        tratada como destino vazio: limpa, zera o idioma detectado e retraduz."""
        df = pd.DataFrame({
            "overview_en": ["Hello"],
            "overview_pt": [GOOGLE_ERROR_PAGE],
            "overview_idioma_pt": ["en"],
            "overview_tentativas": [1],
        })
        detect_fn = self._detect_fn({"Hello": "en", "Olá": "pt"})
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 1
        assert df["overview_pt"].iloc[0] == "Olá"
        assert df["overview_idioma_pt"].iloc[0] == "pt"
        assert df["overview_tentativas"].iloc[0] == 1  # zerado e incrementado pela nova tentativa

    def test_pagina_de_erro_com_tentativas_esgotadas_volta_a_ser_elegivel(self):
        """O ponto do auto-reparo: sem zerar o contador, a linha que já bateu o teto de
        tentativas ficaria com o texto de erro para sempre."""
        df = pd.DataFrame({
            "overview_en": ["Hello"],
            "overview_pt": [GOOGLE_ERROR_PAGE],
            "overview_idioma_pt": ["en"],
            "overview_tentativas": [3],
        })
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", self._detect_fn({"Hello": "en", "Olá": "pt"}), traduzir_fn,
            max_attempts=3,
        )

        traduzir_fn.assert_called_once_with("Hello")
        assert sucesso == 1
        assert df["overview_pt"].iloc[0] == "Olá"

    def test_pagina_de_erro_que_falha_de_novo_fica_vazia_e_nao_com_o_texto_de_erro(self):
        """Se a retradução também falhar (tradutor devolve o original), o destino fica com
        o original em inglês — nunca de volta com a página de erro."""
        df = pd.DataFrame({
            "overview_en": ["Hello"],
            "overview_pt": [GOOGLE_ERROR_PAGE],
        })
        traduzir_fn = MagicMock(side_effect=lambda t: t)

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn,
        )

        assert sucesso == 0
        assert df["overview_pt"].iloc[0] == "Hello"

    def test_nao_toca_em_destinos_que_nao_sao_pagina_de_erro(self):
        df = pd.DataFrame({
            "overview_en": ["Hello", "World"],
            "overview_pt": ["Olá", GOOGLE_ERROR_PAGE],
            "overview_idioma_pt": ["pt", "en"],
            "overview_tentativas": [2, 3],
        })
        traduzir_fn = MagicMock(side_effect=lambda t: "Mundo")

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", self._detect_fn({"Hello": "en", "World": "en", "Mundo": "pt"}),
            traduzir_fn,
        )

        traduzir_fn.assert_called_once_with("World")
        assert df["overview_pt"].tolist() == ["Olá", "Mundo"]
        assert df["overview_tentativas"].tolist() == [2, 1]

    def test_loga_quantidade_de_paginas_de_erro_descartadas(self, caplog):
        import logging
        df = pd.DataFrame({
            "overview_en": ["a", "b"],
            "overview_pt": [GOOGLE_ERROR_PAGE, GOOGLE_ERROR_PAGE],
        })

        with caplog.at_level(logging.INFO):
            resolve_pt_translation(
                df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
                "overview_tentativas", lambda t: "en", MagicMock(side_effect=lambda t: t),
            )

        assert "2 valor(es) de 'overview_pt'" in caplog.text

    def test_sem_pagina_de_erro_nao_loga_descarte(self, caplog):
        import logging
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": ["Olá"]})

        with caplog.at_level(logging.INFO):
            resolve_pt_translation(
                df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
                "overview_tentativas", lambda t: "pt", MagicMock(),
            )

        assert "página de erro" not in caplog.text

    def test_cria_coluna_tentativas_como_zero_quando_ausente(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        def detect_fn(t):
            return "en"
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert "overview_tentativas" in df.columns

    def test_only_missing_nao_recalcula_idioma_en_ja_preenchido(self):
        df = pd.DataFrame({
            "overview_en": ["Hello"],
            "overview_pt": ["Olá"],
            "overview_idioma_en": ["antigo"],
            "overview_idioma_pt": ["pt"],
        })
        detect_fn = MagicMock()

        resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, MagicMock(),
        )

        assert df["overview_idioma_en"].iloc[0] == "antigo"
        detect_fn.assert_not_called()

    def test_usa_max_workers_informado(self):
        with patch("shared_utils.traducao.translate_in_parallel") as mock_paralelo:
            mock_paralelo.return_value = ["Olá"]
            df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
            resolve_pt_translation(
                df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
                "overview_tentativas", lambda t: "en", MagicMock(), max_workers=3,
            )
        assert mock_paralelo.call_args.kwargs["max_workers"] == 3

    def test_precisa_traducao_column_none_nao_cria_coluna(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn,
        )

        assert "overview_needs_translation" not in df.columns

    def test_precisa_traducao_true_quando_resultado_ainda_nao_e_pt(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        traduzir_fn = MagicMock(side_effect=lambda t: t)  # tradução "falha" (devolve igual)

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn,
            needs_translation_column="overview_needs_translation",
        )

        assert df["overview_needs_translation"].tolist() == [True]

    def test_precisa_traducao_false_quando_resultado_ja_e_pt(self):
        df = pd.DataFrame({"overview_en": ["Já em português"], "overview_pt": [None]})
        traduzir_fn = MagicMock()

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "pt", traduzir_fn,
            needs_translation_column="overview_needs_translation",
        )

        assert df["overview_needs_translation"].tolist() == [False]

    def test_precisa_traducao_false_quando_fonte_vazia(self):
        df = pd.DataFrame({"overview_en": [None], "overview_pt": [None]})
        traduzir_fn = MagicMock()

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: None, traduzir_fn,
            needs_translation_column="overview_needs_translation",
        )

        assert df["overview_needs_translation"].tolist() == [False]

    def test_loga_resumo_agregado_de_falhas_de_traducao(self, caplog):
        """Falhas de tradução não devem ser logadas uma a uma (isso fica em DEBUG
        dentro de translate_text/translate_text_aws) — só o resumo agregado
        (falhas / elegíveis) aparece aqui, em INFO."""
        import logging
        df = pd.DataFrame({"overview_en": ["Hello", "World"], "overview_pt": [None, None]})
        def detect_fn(t):
            return "en"
        # "Hello" traduz com sucesso; "World" "falha" (tradutor devolve o próprio texto).
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá" if t == "Hello" else t)

        with caplog.at_level(logging.INFO):
            df, sucesso = resolve_pt_translation(
                df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
                "overview_tentativas", detect_fn, traduzir_fn,
            )

        assert sucesso == 1
        assert "1 falha" in caplog.text
        assert "2 elegível" in caplog.text

    def test_precisa_traducao_continua_true_mesmo_com_tentativas_esgotadas(self):
        """Diferente da elegibilidade (que para de tentar), a coluna de estado
        continua True: o campo ainda não está em português, mesmo que o pipeline
        já tenha desistido de reenviar essa linha ao tradutor."""
        df = pd.DataFrame({
            "overview_en": ["Iron Man"],
            "overview_pt": ["Iron Man"],
            "overview_idioma_pt": ["en"],
            "overview_tentativas": [3],
        })
        traduzir_fn = MagicMock()

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn, max_attempts=3,
            needs_translation_column="overview_needs_translation",
        )

        assert sucesso == 0
        traduzir_fn.assert_not_called()
        assert df["overview_needs_translation"].tolist() == [True]
