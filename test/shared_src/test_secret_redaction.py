import io
import logging
import traceback

import pytest
import requests
from shared_utils import secret_redaction as sr
from shared_utils.secret_redaction import (
    MASK,
    RedactingFormatter,
    install_log_redaction,
    redact,
    register_secret,
    scrub_exception,
)

# Valor obviamente falso: nunca reusar uma chave que já apareceu num ambiente real.
KEY = "0123456789abcdef0123456789abcdef"
URL = f"https://api.themoviedb.org/3/collection/1786484?api_key={KEY}&language=pt-BR"


def _http_error_real() -> requests.HTTPError:
    """HTTPError como o requests o monta: a mensagem embute a URL completa, com a api_key."""
    response = requests.Response()
    response.status_code = 404
    response.reason = "Not Found"
    response.url = URL
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        return exc
    raise AssertionError("raise_for_status deveria ter levantado")


def _logger_com_saida(formatter: logging.Formatter | None) -> tuple[logging.Logger, io.StringIO, logging.Handler]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    if formatter is not None:
        handler.setFormatter(formatter)
    logger = logging.getLogger(f"teste_redacao_{id(stream)}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger, stream, handler


class TestRedact:
    def test_mascara_api_key_na_url_de_uma_excecao_do_requests(self):
        texto = redact(f"404 Client Error: Not Found for url: {URL}")
        assert KEY not in texto
        assert f"api_key={MASK}&language=pt-BR" in texto

    @pytest.mark.parametrize("nome", ["api_key", "API_KEY", "apikey", "api-key", "access_token", "Access-Token"])
    def test_mascara_variacoes_do_nome_do_parametro(self, nome):
        assert redact(f"GET /x?{nome}={KEY}&a=1") == f"GET /x?{nome}={MASK}&a=1"

    def test_para_o_valor_em_aspas_e_parenteses(self):
        assert redact(f"('api_key={KEY}')") == f"('api_key={MASK}')"

    def test_mascara_bearer_token(self):
        assert redact(f"Authorization: Bearer {KEY}") == f"Authorization: Bearer {MASK}"

    def test_mascara_chave_do_openrouter(self):
        assert redact("erro com sk-or-v1-abcdef0123456789 no header") == f"erro com sk-or-{MASK} no header"

    @pytest.mark.parametrize("prefixo", ["AKIA", "ASIA"])
    def test_mascara_access_key_id_da_aws(self, prefixo):
        assert redact(f"id {prefixo}ABCDEFGHIJKLMNOP fim") == f"id {prefixo}{MASK} fim"

    def test_texto_sem_segredo_fica_inalterado(self):
        texto = "Buscando detalhes de 1800 IDs na API do TMDB com 20 workers..."
        assert redact(texto) == texto


class TestRegisterSecret:
    def test_mascara_o_valor_registrado_em_qualquer_posicao(self):
        register_secret("segredo-sem-padrao-123")
        assert redact("cabecalho x-token: segredo-sem-padrao-123 fim") == f"cabecalho x-token: {MASK} fim"

    def test_mascara_tambem_a_versao_url_encoded(self):
        segredo = "abc/def+ghi==xyz1"
        register_secret(segredo)
        assert redact("url=https://h/p?k=abc%2Fdef%2Bghi%3D%3Dxyz1") == f"url=https://h/p?k={MASK}"
        assert redact(f"raw {segredo}") == f"raw {MASK}"

    def test_ignora_valor_curto_para_nao_mascarar_trechos_comuns(self):
        register_secret("curto")
        assert redact("um texto curto qualquer") == "um texto curto qualquer"

    @pytest.mark.parametrize("valor", [None, 12345678, b"bytes-bytes", ""])
    def test_ignora_o_que_nao_e_string(self, valor):
        register_secret(valor)
        assert sr._secrets == set()

    def test_valor_mais_longo_e_mascarado_antes_do_prefixo_dele(self):
        register_secret("abcdefgh")
        register_secret("abcdefghijkl")
        assert redact("chave abcdefghijkl fim") == f"chave {MASK} fim"


class TestScrubException:
    def test_devolve_a_mesma_excecao_sem_a_chave_na_mensagem(self):
        exc = _http_error_real()
        assert KEY in str(exc)  # sanidade: o requests mesmo embute a chave

        resultado = scrub_exception(exc)

        assert resultado is exc
        assert KEY not in str(exc)
        assert f"api_key={MASK}" in str(exc)

    def test_traceback_nao_contem_a_chave_nem_com_excecao_encadeada(self):
        """O traceback imprime a cadeia (__cause__/__context__): sem cortá-la, a exceção original,
        com a chave, apareceria no log mesmo depois de limpar a mensagem da exceção final."""
        try:
            try:
                raise OSError(f"HTTPSConnectionPool: Max retries exceeded with url: /3/x?api_key={KEY}")
            except OSError as inner:
                raise requests.exceptions.ConnectionError(inner) from inner
        except requests.exceptions.ConnectionError as exc:
            scrub_exception(exc)
            texto = "".join(traceback.format_exception(exc))

        assert KEY not in texto
        assert f"api_key={MASK}" in texto

    def test_nao_mexe_em_argumentos_que_nao_sao_texto(self):
        exc = RuntimeError(404, f"x?api_key={KEY}")
        scrub_exception(exc)
        assert exc.args == (404, f"x?api_key={MASK}")


class TestRedactingFormatter:
    def test_mascara_a_mensagem_preservando_o_formato_interno(self):
        logger, stream, _ = _logger_com_saida(RedactingFormatter(logging.Formatter("%(levelname)s|%(message)s")))
        logger.warning(f"Falha ao buscar coleção 1: 404 for url: {URL}")
        saida = stream.getvalue()
        assert saida.startswith("WARNING|Falha ao buscar coleção 1")
        assert KEY not in saida
        assert f"api_key={MASK}" in saida

    def test_mascara_o_traceback_de_logger_exception(self):
        logger, stream, _ = _logger_com_saida(RedactingFormatter(logging.Formatter("%(message)s")))
        try:
            raise _http_error_real()
        except requests.HTTPError:
            logger.exception("Falha")
        saida = stream.getvalue()
        assert "Traceback" in saida
        assert KEY not in saida

    def test_sem_formatter_interno_usa_o_padrao(self):
        logger, stream, _ = _logger_com_saida(RedactingFormatter())
        logger.info(f"api_key={KEY}")
        assert stream.getvalue().strip() == f"api_key={MASK}"


class TestInstallLogRedaction:
    def test_envolve_o_formatter_do_handler_preservando_o_formato(self):
        logger, stream, handler = _logger_com_saida(logging.Formatter("%(levelname)s|%(message)s"))
        install_log_redaction(logger)
        assert isinstance(handler.formatter, RedactingFormatter)
        logger.warning(f"url {URL}")
        assert stream.getvalue().startswith("WARNING|url https://api.themoviedb.org")
        assert KEY not in stream.getvalue()

    def test_handler_sem_formatter_tambem_e_protegido(self):
        logger, stream, handler = _logger_com_saida(None)
        install_log_redaction(logger)
        assert isinstance(handler.formatter, RedactingFormatter)
        logger.info(f"api_key={KEY}")
        assert KEY not in stream.getvalue()

    def test_e_idempotente(self):
        logger, _, handler = _logger_com_saida(logging.Formatter("%(message)s"))
        install_log_redaction(logger)
        primeiro = handler.formatter
        install_log_redaction(logger)
        assert handler.formatter is primeiro
        assert not isinstance(primeiro._inner, RedactingFormatter)

    def test_sem_argumento_protege_os_handlers_do_logger_raiz(self):
        root = logging.getLogger()
        handler = logging.StreamHandler(io.StringIO())
        root.addHandler(handler)
        try:
            install_log_redaction()
            assert isinstance(handler.formatter, RedactingFormatter)
        finally:
            root.removeHandler(handler)
