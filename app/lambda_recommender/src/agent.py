"""
agent.py — Seleciona e justifica recomendações usando a OpenAI API.

Recebe a lista de candidatos do Athena e as preferências do usuário,
e retorna um subconjunto ordenado com um campo recommendation_reason
gerado pelo LLM para cada filme.
"""

import json
import logging
import os

import boto3
import openai

logger = logging.getLogger()
logger.setLevel(logging.INFO)

OPENAI_SECRET_ARN = os.environ["OPENAI_SECRET_ARN"]
MODEL = "gpt-4o-mini"
MAX_TOKENS = 4096


def _get_api_key() -> str:
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=OPENAI_SECRET_ARN)
    secret = json.loads(response["SecretString"])
    return secret["openai_api_key"]


def recommend(preferences: str, movies: list[dict]) -> list[dict]:
    """
    Usa a OpenAI para selecionar os filmes mais relevantes e gerar um
    recommendation_reason em português para cada um.

    Args:
        preferences: Texto livre com as preferências do usuário.
        movies:      Lista de filmes candidatos vindos do Athena.

    Returns:
        Lista de filmes selecionados, cada um com o campo
        recommendation_reason adicionado.
    """
    if not movies:
        return []

    api_key = _get_api_key()
    client = openai.OpenAI(api_key=api_key)

    system_prompt = "Você é um especialista em cinema que responde SOMENTE com JSON válido, sem markdown e sem texto extra."
    user_prompt = f"""O usuário quer: "{preferences}".

Aqui estão os filmes disponíveis no catálogo (JSON):
{json.dumps(movies, ensure_ascii=False, indent=2)}

Selecione entre 5 e 10 filmes que melhor atendam às preferências do usuário.
Responda SOMENTE com um JSON array válido. Cada objeto deve ter exatamente estes campos:
- title (string)
- original_title (string)
- year (número inteiro)
- media_type (string: "movie" ou "tv")
- genre_names (string com os gêneros separados por vírgula)
- vote_average (número decimal)
- language_name (string)
- overview (string — sinopse original, sem alterar)
- recommendation_reason (string — 1 frase em português explicando por que este filme combina com o pedido)

Não inclua nenhum texto fora do JSON. Não use markdown. Retorne apenas o array JSON."""

    logger.info(f"Chamando OpenAI com {len(movies)} candidatos...")
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()
    result = json.loads(raw)
    logger.info(f"OpenAI retornou {len(result)} recomendações.")
    return result
