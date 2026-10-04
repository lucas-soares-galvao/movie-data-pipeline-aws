"""traducao_llm.py — Tradução para português via LLM (OpenRouter, litellm)."""

from __future__ import annotations

import logging
import os
import re

import litellm

from shared_utils.llm_client import load_llm_api_key

logger = logging.getLogger()

# Modelo primário via OpenRouter, mesmo mecanismo de litellm já usado no agente de
# recomendação (app/lightsail_ia/src/agent.py) — reaproveita o par já validado em
# produção. qwen3.8-flash como primário (mais barato por token que o deepseek,
# adequado para uma tarefa estruturada/sem necessidade de raciocínio) e
# deepseek-v4.1-flash como fallback nativo do OpenRouter (acionado dentro da mesma
# chamada via extra_body.models, sem chave adicional).
_LLM_MODEL = os.getenv("TRANSLATE_LLM_MODEL", "openrouter/qwen/qwen3.8-flash")
_LLM_FALLBACK_MODELS = [
    m.strip() for m in os.getenv("TRANSLATE_LLM_FALLBACK_MODELS", "deepseek/deepseek-v4.1-flash").split(",") if m.strip()
]
# Desliga reasoning/thinking tokens (cobrados como output) — desnecessário para uma
# tradução de saída curta e estruturada (mesmo racional de agent.py).
_LLM_EXTRA_BODY: dict[str, object] = {"reasoning": {"enabled": False}}
if _LLM_FALLBACK_MODELS:
    _LLM_EXTRA_BODY["models"] = _LLM_FALLBACK_MODELS
_LLM_NUM_RETRIES = 3
# Textos curtos (overview/tagline/keywords) — bem menor que os 60-90s usados no
# agente, que lida com saída estruturada maior (vários títulos por chamada).
_LLM_TIMEOUT_SECONDS = 20
# overview é o campo mais longo traduzido hoje — teto generoso só pra não truncar
# uma tradução normal, limitando a latência de cauda de uma resposta anormalmente
# verbosa.
_LLM_MAX_TOKENS = 800

# Cache da chave de API, carregada sob demanda (não no import do módulo): nos jobs
# Glue, FILMBOT_SECRET_ARN só é publicada em os.environ dentro de get_parameters_glue()
# (ver app/glue_details e app/glue_etl), chamada de dentro de main() — depois que este
# módulo já foi importado. Carregar no import leria a variável antes de ela existir.
# Lista de 0 ou 1 elemento faz o papel de "ainda não carregado" vs. "carregado como
# None" (None é um valor válido — chave ausente em dev local sem secret configurado).
_llm_api_key_cache: list[str | None] = []


def _get_llm_api_key() -> str | None:
    """Carrega e cacheia a chave de API do LLM na primeira chamada.

    required=False: uma falha pontual ao ler o secret não pode travar a chamada (e
    portanto o job Glue inteiro) — se vier None, a chamada ao LLM falha individualmente
    (capturada em translate_text_llm/detect_language_llm) e devolve o "sem
    tradução"/None de sempre, sem exceção não tratada subindo.
    """
    if not _llm_api_key_cache:
        _llm_api_key_cache.append(load_llm_api_key("llm_api_key", "LLM_API_KEY", required=False))
    return _llm_api_key_cache[0]

_SYSTEM_PROMPT = (
    "Você é um tradutor profissional de inglês para português do Brasil, especializado "
    "em sinopses e metadados de filmes e séries. Traduza o texto do usuário para "
    "português do Brasil. Preserve nomes próprios, títulos de obras, nomes de pessoas "
    "e termos técnicos sem tradução direta. Devolva APENAS o texto traduzido, sem "
    "aspas, sem comentários, sem explicações, sem markdown."
)

# Remove aspas/cercas de markdown que o modelo eventualmente envolva ao redor do
# texto traduzido, mesmo com a instrução explícita de não fazer isso — limpeza
# defensiva, mesmo tipo de tratamento que agent.py já faz para a saída em JSON do
# Passo 3.
_WRAPPING_PATTERN = re.compile(r'^["\'`]+|["\'`]+$')
_CODE_FENCE_PATTERN = re.compile(r"^```[a-zA-Z]*\n?|```$")


def _clean_result(content: str) -> str:
    cleaned = _CODE_FENCE_PATTERN.sub("", content.strip()).strip()
    return _WRAPPING_PATTERN.sub("", cleaned).strip()


def translate_text_llm(text: str) -> str:
    """
    Traduz texto para português via LLM (OpenRouter), com fallback nativo de modelo
    (extra_body.models) se o primário falhar.

    Nunca lança exceção — devolve o texto original em caso de erro, para não
    interromper o job.

    Não há aqui uma forma de detectar "orçamento esgotado" distinta de uma falha de
    chamada comum — esgotamento de crédito no OpenRouter aparece como uma exceção HTTP
    (402/429) igual a qualquer outra falha transitória, e cai no mesmo branch genérico
    abaixo.

    Args:
        text: Texto a ser traduzido (idioma de origem detectado automaticamente pelo
              próprio modelo).

    Returns:
        Texto traduzido para português, ou o texto original se a tradução falhar ou a
        resposta vier vazia/malformada.
    """
    if not text:
        return ""
    try:
        response = litellm.completion(
            model=_LLM_MODEL,
            api_key=_get_llm_api_key(),
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
            num_retries=_LLM_NUM_RETRIES,
            timeout=_LLM_TIMEOUT_SECONDS,
            max_tokens=_LLM_MAX_TOKENS,
            extra_body=_LLM_EXTRA_BODY,
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            logger.debug(f"LLM devolveu tradução vazia para '{text[:80]}'. Mantendo original.")
            return text
        return _clean_result(content)
    # Chamada de API externa, não pode derrubar o job.
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Falha ao traduzir via LLM '{text[:80]}': {exc}")
        return text
