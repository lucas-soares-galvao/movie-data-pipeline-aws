"""traducao.py — Orquestração de tradução para português: elegibilidade, cache,
paralelismo e escolha do serviço (Google Translate ou AWS Translate)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional

import pandas as pd

from shared_utils.traducao_aws import traduzir_texto_aws
from shared_utils.traducao_google import traduzir_texto

__all__ = [
    "traduzir_texto",
    "traduzir_texto_aws",
    "resolver_traduzir_fn",
    "traduzir_em_paralelo",
    "traduzir_coluna_pendente",
    "reaproveitar_traducao_existente",
    "elegivel_overview_pt",
    "elegivel_tagline_pt",
    "elegivel_keywords_pt",
]

logger = logging.getLogger()


def resolver_traduzir_fn(
    provider: str,
    traduzir_google: Callable[[str], str] = traduzir_texto,
    traduzir_aws: Callable[[str], str] = traduzir_texto_aws,
) -> Callable[[str], str]:
    """
    Resolve o provedor de tradução (`"google"` ou `"aws"`) para a função correspondente.

    Cada caminho do pipeline escolhe um único serviço por execução — sem composição
    de primário+fallback: `glue_details`/`glue_etl` (caminho automático via
    EventBridge) usam `"aws"` por padrão; os backfills manuais (`scripts/`) usam
    `"google"` por padrão, mas podem apontar para `"aws"` para testes pontuais.

    `traduzir_google`/`traduzir_aws` são recebidos como parâmetro (em vez de resolvidos
    aqui dentro) pelo mesmo motivo de `traduzir_em_paralelo`: os chamadores passam suas
    próprias referências locais de `traduzir_texto`/`traduzir_texto_aws` — as mesmas que
    seus testes fazem mock (ex.: `patch("src.utils.traduzir_texto", ...)`). Resolver via
    referência direta ao módulo quebraria esse patch.

    Args:
        provider:        `"google"` (deep_translator, grátis) ou `"aws"` (AWS Translate,
                          pago por caractere).
        traduzir_google: Função a devolver quando `provider="google"`.
        traduzir_aws:    Função a devolver quando `provider="aws"`.

    Returns:
        `traduzir_google` ou `traduzir_aws`, conforme `provider`.

    Raises:
        ValueError: se `provider` não for `"google"` nem `"aws"`.
    """
    try:
        return {"google": traduzir_google, "aws": traduzir_aws}[provider]
    except KeyError:
        raise ValueError(
            f"TRANSLATE_PROVIDER inválido: {provider!r} (esperado 'google' ou 'aws')"
        ) from None


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
    igual à coluna_fonte (tradução que falhou — ver traduzir_texto/traduzir_texto_aws),
    continuam pendentes e são (re)tentados.

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


def reaproveitar_traducao_existente(
    df: pd.DataFrame,
    df_anterior: Optional[pd.DataFrame],
    coluna_fonte: str,
    coluna_destino: str,
    coluna_chave: str = "id",
) -> pd.DataFrame:
    """
    Preenche coluna_destino com a tradução já existente (df_anterior) quando
    coluna_fonte não mudou entre o registro antigo e o novo, para a mesma
    coluna_chave. Evita retraduzir texto idêntico ao da última execução.

    Não sobrescreve valores já preenchidos em coluna_destino neste run (ex.:
    tradução nativa do TMDB, atribuída antes desta chamada) — essa prioridade é
    preservada. A checagem final de "já traduzido" continua em
    traduzir_coluna_pendente ou na máscara de elegibilidade do chamador; esta
    função só fornece o valor de cache para essas checagens localizarem. Se o
    valor reaproveitado for igual à fonte (falha de tradução de um run
    anterior), o chamador vai marcá-lo como pendente e retentar sozinho.

    Compartilhada entre glue_details (coluna_chave="id", default) e glue_etl
    (coluna_chave="iso_3166_1"/"iso_639_1" para a tabela configuration).

    Args:
        df:            DataFrame novo (run atual), com colunas coluna_chave,
                        coluna_fonte e coluna_destino já inicializada (mesmo
                        que com nulos).
        df_anterior:   Registros já persistidos que serão sobrescritos neste
                        run, ou None/vazio se não há histórico.
        coluna_fonte:  Nome da coluna de texto fonte (ex.: "overview_en").
        coluna_destino: Nome da coluna de tradução a (pré-)preencher.
        coluna_chave:  Coluna usada para casar registros antigos e novos
                       (default "id").

    Returns:
        df com coluna_destino atualizada (também modificado in-place).
    """
    if df_anterior is None or df_anterior.empty:
        return df
    colunas_necessarias = {coluna_chave, coluna_fonte, coluna_destino}
    if not colunas_necessarias.issubset(df_anterior.columns):
        # Schema antigo (partição/tabela gravada antes da coluna existir) — nada a reaproveitar.
        return df

    cache = (
        df_anterior[[coluna_chave, coluna_fonte, coluna_destino]]
        .drop_duplicates(subset=coluna_chave, keep="last")
        .set_index(coluna_chave)
    )
    fonte_antiga = df[coluna_chave].map(cache[coluna_fonte])
    destino_antigo = df[coluna_chave].map(cache[coluna_destino])

    destino_novo_vazio = df[coluna_destino].isna() | (df[coluna_destino] == "")
    fonte_valida = df[coluna_fonte].notna() & (df[coluna_fonte] != "")
    destino_antigo_valido = destino_antigo.notna() & (destino_antigo != "")
    fonte_inalterada = fonte_valida & (fonte_antiga == df[coluna_fonte])

    pode_reaproveitar = destino_novo_vazio & destino_antigo_valido & fonte_inalterada
    if pode_reaproveitar.any():
        df.loc[pode_reaproveitar, coluna_destino] = destino_antigo[pode_reaproveitar]
        logger.info(
            f"Reaproveitando tradução existente de {pode_reaproveitar.sum()} registro(s) "
            f"para '{coluna_destino}' (fonte '{coluna_fonte}' inalterada)."
        )
    return df


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
