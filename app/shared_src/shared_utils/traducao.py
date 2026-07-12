"""traducao.py — Função compartilhada de tradução para português com detecção automática de idioma."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List

import boto3
import pandas as pd
from deep_translator import GoogleTranslator

logger = logging.getLogger()

_MAX_TENTATIVAS = 5
_MAX_TENTATIVAS_SEM_ERRO = 2


def traduzir_texto(texto: str, contexto: str = "") -> str:
    """
    Traduz texto para português via Google Translate, detectando automaticamente
    o idioma de origem (source="auto").

    Faz até _MAX_TENTATIVAS tentativas com backoff entre elas, já que o
    endpoint não-oficial do Google Translate falha esporadicamente sob alto
    volume de chamadas paralelas. Duas formas de falha contam como tentativa
    malsucedida:
      - a chamada lançar exceção — tende a ser transitório (rede, rate limit),
        por isso usa o orçamento completo de _MAX_TENTATIVAS;
      - retornar normalmente um texto idêntico ao original — na maioria das
        vezes indica que não há o que traduzir (nome próprio, termo
        emprestado como "anime"/"hotel"), não bloqueio transitório, por isso
        desiste mais cedo (_MAX_TENTATIVAS_SEM_ERRO).
    Retorna o texto original se todas as tentativas aplicáveis se esgotarem,
    para não interromper o job.

    Args:
        texto:    Texto a ser traduzido (idioma de origem detectado automaticamente).
        contexto: Descrição opcional do item traduzido (usada no log).

    Returns:
        Texto traduzido para português, ou o texto original se a tradução falhar.
    """
    if not texto:
        return ""
    prefixo = f"{contexto} " if contexto else ""
    tentativas_sem_erro = 0
    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        try:
            resultado = GoogleTranslator(source="auto", target="pt").translate(texto)
        except Exception as exc:
            logger.debug(f"Tentativa {tentativa} de traduzir {prefixo}'{texto}' falhou: {exc}")
        else:
            if resultado and resultado != texto:
                return resultado
            tentativas_sem_erro += 1
            logger.debug(
                f"Tentativa {tentativa} de traduzir {prefixo}'{texto:.80}' não lançou erro, mas "
                "devolveu texto idêntico ao original (possível bloqueio/rate-limit silencioso "
                "do Google Translate, ou simplesmente não há o que traduzir)."
            )
            if tentativas_sem_erro >= _MAX_TENTATIVAS_SEM_ERRO:
                logger.debug(
                    f"'{prefixo}{texto:.80}' não mudou em {tentativas_sem_erro} tentativa(s) sem "
                    "erro; provavelmente não há tradução a fazer (nome próprio, termo emprestado). "
                    "Mantendo original."
                )
                return texto
        if tentativa < _MAX_TENTATIVAS:
            time.sleep(tentativa * 2)
    logger.warning(
        f"Falha ao traduzir {prefixo}'{texto:.80}' após {_MAX_TENTATIVAS} tentativas "
        "com erro. Mantendo original."
    )
    return texto


def traduzir_em_paralelo(
    valores: List[str], traduzir_fn: Callable[[str], str], max_workers: int = 10
) -> List[str]:
    """
    Aplica traduzir_fn a cada item de valores em paralelo via ThreadPoolExecutor.

    Recebe a função de tradução como parâmetro (em vez de chamar traduzir_texto
    diretamente) para que os chamadores continuem passando sua própria referência
    local de traduzir_texto — a mesma que seus testes fazem mock.

    Args:
        valores:     Textos a traduzir, na ordem em que devem ser retornados.
        traduzir_fn: Função chamada para cada item (ex.: traduzir_texto).
        max_workers: Número de threads concorrentes.

    Returns:
        Lista de textos traduzidos, na mesma ordem de valores.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(traduzir_fn, valores))


def traduzir_coluna_pendente(
    df: pd.DataFrame,
    coluna_fonte: str,
    coluna_destino: str,
    mask_elegivel: "pd.Series[bool]",
    traduzir_fn: Callable[[str], str],
    max_workers: int = 10,
) -> int:
    """
    Traduz coluna_fonte → coluna_destino para os registros elegíveis ainda pendentes.

    Um registro é considerado "já traduzido" (e não é retraduzido) quando
    coluna_destino está preenchida e é diferente de coluna_fonte — cobre tanto
    tradução nativa do TMDB (glue_details) quanto sucesso em um run anterior
    (backfill). Registros sem coluna_destino, ou cuja coluna_destino ficou
    igual à coluna_fonte (fallback de uma tradução que falhou — ver
    traduzir_texto), continuam pendentes e são (re)tentados.

    traduzir_fn é recebido como parâmetro (em vez de chamar traduzir_texto
    diretamente) para que os chamadores continuem passando sua própria
    referência local — a mesma que seus testes fazem mock.

    Args:
        df:            DataFrame a atualizar (modificado in-place em coluna_destino).
        coluna_fonte:  Nome da coluna com o texto de origem.
        coluna_destino: Nome da coluna a preencher com o texto traduzido.
        mask_elegivel: Máscara booleana dos registros candidatos à tradução.
        traduzir_fn:   Função chamada para cada texto (ex.: traduzir_texto).
        max_workers:   Número de threads concorrentes.

    Returns:
        Quantidade traduzida com sucesso nesta chamada. Sucesso é contado
        comparando cada resultado com o texto original, já que traduzir_fn
        devolve o próprio texto original quando a tradução falha após todas
        as tentativas.
    """
    if coluna_destino not in df.columns:
        df[coluna_destino] = None

    ja_traduzido = (
        df[coluna_destino].notna()
        & (df[coluna_destino] != "")
        & (df[coluna_destino] != df[coluna_fonte])
    )
    mask = mask_elegivel & ~ja_traduzido
    if not mask.any():
        return 0

    valores = df.loc[mask, coluna_fonte].fillna("").tolist()
    traduzidos = traduzir_em_paralelo(valores, traduzir_fn, max_workers=max_workers)
    df.loc[mask, coluna_destino] = traduzidos

    return sum(1 for original, traduzido in zip(valores, traduzidos) if original and traduzido != original)


def _traduzir_aws_translate(texto: str, region: str) -> str:
    """
    Traduz texto para português via AWS Translate (detecção automática de idioma),
    usada como fallback quando o Google Translate falha.

    Diferente de traduzir_texto, não implementa retry manual: o AWS Translate é uma
    API oficial (sem o comportamento de bloqueio silencioso do endpoint não-oficial
    do Google Translate) e o cliente boto3 já reaplica retry em erros transitórios
    por padrão. Nunca lança exceção — devolve o texto original em caso de erro, para
    não interromper o job.

    Args:
        texto:  Texto a ser traduzido (idioma de origem detectado automaticamente).
        region: Região AWS do cliente do Translate.

    Returns:
        Texto traduzido para português, ou o texto original se a tradução falhar.
    """
    try:
        cliente = boto3.client("translate", region_name=region)
        resposta = cliente.translate_text(
            Text=texto, SourceLanguageCode="auto", TargetLanguageCode="pt",
        )
        traduzido = resposta.get("TranslatedText", "").strip()
        if traduzido:
            return traduzido
    except Exception as exc:
        logger.warning(f"Falha ao traduzir via AWS Translate '{texto:.80}': {exc}")
    return texto


def criar_traduzir_fn_com_aws_translate(
    traduzir_fn_primario: Callable[[str], str], max_chamadas: int, region: str = "sa-east-1"
) -> Callable[[str], str]:
    """
    Compõe uma função de tradução primária (ex.: traduzir_texto, Google Translate)
    com um fallback via AWS Translate, limitado a max_chamadas chamadas nesta
    execução — o AWS Translate é pago por caractere, diferente do Google Translate.

    traduzir_fn_primario é recebido como parâmetro (em vez de chamar traduzir_texto
    diretamente) pelo mesmo motivo de traduzir_em_paralelo: o chamador passa sua
    própria referência local de traduzir_texto — a mesma que seus testes fazem mock.

    O AWS Translate só é chamado quando traduzir_fn_primario falha (resultado igual
    ao texto original). Com max_chamadas=0, a função devolvida se comporta como
    traduzir_fn_primario puro (fallback desligado). Thread-safe: o contador de
    chamadas é protegido por lock, já que a função é usada dentro de
    ThreadPoolExecutor via traduzir_em_paralelo.

    Args:
        traduzir_fn_primario: Função de tradução tentada primeiro (ex.: traduzir_texto).
        max_chamadas:         Limite de chamadas ao AWS Translate nesta execução.
        region:                Região AWS do cliente do Translate.

    Returns:
        Função de tradução (texto) -> texto traduzido, pronta para ser passada como
        traduzir_fn a traduzir_coluna_pendente/traduzir_em_paralelo.
    """
    chamadas_restantes = [max_chamadas]
    lock = threading.Lock()

    def _traduzir_fn(texto: str) -> str:
        resultado = traduzir_fn_primario(texto)
        if not texto or resultado != texto:
            return resultado
        with lock:
            if chamadas_restantes[0] <= 0:
                return resultado
            chamadas_restantes[0] -= 1
        return _traduzir_aws_translate(texto, region)

    return _traduzir_fn


def elegivel_overview_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de overview: idioma original diferente de pt, com overview_en preenchido."""
    return (
        (df["original_language"] != "pt")
        & df["overview_en"].notna()
        & (df["overview_en"] != "")
    )


def elegivel_tagline_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de tagline: campo preenchido e idioma original diferente de pt."""
    return (
        df["tagline"].notna()
        & (df["tagline"] != "")
        & (df["original_language"] != "pt")
    )


def elegivel_keywords_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de keywords: campo preenchido e idioma original diferente de pt
    (evita reenviar ao Google Translate keywords que já podem estar em português)."""
    return (
        df["keywords"].notna()
        & (df["keywords"] != "")
        & (df["original_language"] != "pt")
    )
