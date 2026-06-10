"""
Agente de recomendação de filmes e séries em 3 passos:
  1. OpenAI lê o texto do usuário e extrai filtros estruturados (gênero, ano, etc.)
  2. AWS Athena executa uma query SQL com esses filtros no data lake
  3. OpenAI recebe os resultados reais e os formata como recomendações em JSON
"""

import json
import os

import boto3
import awswrangler as wr
from openai import OpenAI

TOOL = {
    "type": "function",
    "function": {
        "name": "buscar_titulos_spec",
        "description": "Busca filmes e séries reais da tabela SPEC no data lake AWS.",
        "parameters": {
            "type": "object",
            "properties": {
                "genero": {
                    "type": "string",
                    "description": "Gênero do filme/série (ex: Terror, Ação, Ficção Científica)",
                },
                "tipo": {
                    "type": "string",
                    "enum": ["movie", "tv"],
                    "description": "Filme (movie) ou série (tv)",
                },
                "ano": {
                    "type": "integer",
                    "description": "Ano de lançamento",
                },
                "nota_minima": {
                    "type": "number",
                    "description": "Nota mínima de 0 a 10 (padrão 6.0)",
                },
                "limite": {
                    "type": "integer",
                    "description": "Quantidade máxima de resultados (padrão 30)",
                },
            },
        },
    },
}

_openai_client: OpenAI | None = None


def _buscar_openai_key() -> str:
    secret_arn = os.environ["OPENAI_SECRET_ARN"]
    sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "sa-east-1"))
    response = sm.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])
    return secret["openai_api_key"]


def _get_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=_buscar_openai_key())
    return _openai_client


def buscar_titulos_spec(
    genero: str | None = None,
    tipo: str | None = None,
    ano: int | None = None,
    nota_minima: float = 6.0,
    limite: int = 30,
) -> list[dict]:
    """Consulta a tabela SPEC no Athena e retorna os títulos que batem com os filtros."""
    filtros = ["vote_count >= 50", f"vote_average >= {float(nota_minima)}"]

    if tipo in ("movie", "tv"):
        filtros.append(f"media_type = '{tipo}'")
    if ano:
        filtros.append(f"year = '{int(ano)}'")
    if genero:
        g = genero.replace("'", "")
        filtros.append(f"lower(genre_names) LIKE lower('%{g}%')")

    tabela = os.environ.get("ATHENA_TABLE", "tb_discover_unified_tmdb")
    sql = f"""
        SELECT title, media_type, year, genre_names, overview,
               vote_average, poster_url, backdrop_url,
               runtime_minutes, number_of_seasons,
               number_of_episodes, episode_runtime_minutes,
               streaming_providers
        FROM {tabela}
        WHERE {" AND ".join(filtros)}
        ORDER BY popularity DESC
        LIMIT {int(limite)}
    """

    session = boto3.Session(region_name=os.environ.get("AWS_REGION", "sa-east-1"))
    df = wr.athena.read_sql_query(
        sql=sql,
        database=os.environ.get("ATHENA_DATABASE", "db_unified_tmdb"),
        s3_output=f"s3://{os.environ.get('S3_BUCKET_TEMP', '')}/athena-results/",
        boto3_session=session,
        ctas_approach=False,
    )
    return df.to_dict(orient="records")


def executar_agente(preferencia: str) -> list[dict]:
    """
    Orquestra os 3 passos do agente e retorna uma lista de títulos recomendados.
    Retorna lista vazia se nenhum título for encontrado ou o modelo não responder.
    """
    client = _get_client()

    # PASSO 1: OpenAI analisa o texto do usuário e decide quais filtros usar
    resposta = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um assistente de recomendação de filmes e séries. "
                    "Analise o pedido do usuário e chame a tool com os filtros adequados."
                ),
            },
            {"role": "user", "content": preferencia},
        ],
        tools=[TOOL],
        tool_choice="required",
    )

    # PASSO 2: extrai os argumentos escolhidos pelo OpenAI e consulta o Athena
    tool_call = resposta.choices[0].message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)
    titulos_da_spec = buscar_titulos_spec(**args)

    if not titulos_da_spec:
        return []

    # PASSO 3: OpenAI recebe os títulos reais e gera as recomendações em JSON.
    # A lista de mensagens reconstrói o histórico da conversa: system → usuário →
    # resposta anterior do modelo (com tool call) → resultado da tool.
    # Esse encadeamento é obrigatório pelo protocolo de tool use da API OpenAI.
    resposta_final = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um curador de filmes e séries. Com base nos títulos reais "
                    "fornecidos pela tool, selecione os mais relevantes para o pedido "
                    "do usuário e retorne um JSON com a chave 'titulos'. "
                    "Cada item deve ter: titulo, tipo ('filme' ou 'série'), ano (inteiro), "
                    "generos (lista de strings), sinopse, nota (float ou null), "
                    "poster_url (string ou null), backdrop_url (string ou null), motivo (por que recomenda este título), "
                    "duracao (string formatada ou null), "
                    "streaming_providers (string com nomes dos serviços separados por vírgula, ou null). "
                    "Para filmes, formate duracao a partir de runtime_minutes: ex. '1h 52min'. "
                    "Para séries, formate duracao combinando number_of_seasons, number_of_episodes "
                    "e episode_runtime_minutes: ex. '3 temporadas · 36 eps · ~45 min/ep'. "
                    "Se episode_runtime_minutes for null ou ausente, omita essa parte: ex. '3 temporadas · 36 eps'. "
                    "Se todos os dados de duração forem null, defina duracao como null. "
                    "Copie streaming_providers exatamente como recebido (ex: 'Netflix, Amazon Prime Video'), "
                    "ou null se o campo estiver ausente ou vazio. "
                    "Responda APENAS com o JSON, sem texto extra. "
                    "Responda sempre em português. "
                    "Se a sinopse de algum título estiver em inglês, traduza-a para o português antes de exibir."
                ),
            },
            {"role": "user", "content": preferencia},
            resposta.choices[0].message,
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(titulos_da_spec, ensure_ascii=False, default=str),
            },
        ],
    )

    conteudo = resposta_final.choices[0].message.content or ""
    conteudo = conteudo.strip()
    # O modelo às vezes devolve o JSON envolto em ```json ... ``` mesmo sendo instruído a não fazer isso.
    if conteudo.startswith("```"):
        conteudo = conteudo.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if not conteudo:
        return []
    dados = json.loads(conteudo)
    return dados.get("titulos", [])
