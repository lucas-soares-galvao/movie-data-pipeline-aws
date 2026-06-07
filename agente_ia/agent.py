import os
import json
import boto3
import awswrangler as wr
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── Definição da tool para o OpenAI ──────────────────────────────────────────
# O OpenAI lê isso e decide quais argumentos passar com base no texto do usuário

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


# ── PASSO 2: consulta real no Athena ─────────────────────────────────────────

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

    sql = f"""
        SELECT title, media_type, year, genre_names, overview,
               vote_average, poster_url,
               runtime, number_of_seasons, number_of_episodes
        FROM {os.getenv('SPEC_TABLE', 'tb_discover_unified_tmdb')}
        WHERE {" AND ".join(filtros)}
        ORDER BY popularity DESC
        LIMIT {int(limite)}
    """

    session = boto3.Session(region_name=os.getenv("AWS_REGION", "sa-east-1"))
    df = wr.athena.read_sql_query(
        sql=sql,
        database=os.getenv("GLUE_DATABASE", "db_tmdb"),
        s3_output=os.getenv("ATHENA_S3_OUTPUT"),
        boto3_session=session,
        ctas_approach=False,
    )
    return df.to_dict(orient="records")


# ── Função principal: 3 passos explícitos ────────────────────────────────────

def recomendar(preferencia: str) -> list[dict]:

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
        tool_choice="required",  # força o uso da tool
    )

    # PASSO 2: extrai os argumentos escolhidos pelo OpenAI e consulta o Athena
    tool_call = resposta.choices[0].message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)
    titulos_da_spec = buscar_titulos_spec(**args)

    if not titulos_da_spec:
        return []

    # PASSO 3: OpenAI recebe os títulos reais e gera as recomendações em JSON
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
                    "poster_url (string ou null), motivo (por que recomenda este título), "
                    "duracao (string formatada: '90 min' para filmes; "
                    "'45 min/ep (2 temporadas, 20 episódios)' para séries; null se indisponível). "
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
    if conteudo.startswith("```"):
        conteudo = conteudo.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if not conteudo:
        return []
    dados = json.loads(conteudo)
    return dados.get("titulos", [])
