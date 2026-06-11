"""
agent.py — Agente de IA para recomendação de filmes e séries.

==============================================================================
O QUE ESTE ARQUIVO FAZ?
==============================================================================
Implementa o "cérebro" do FilmBot em 3 passos usando OpenAI + AWS Athena:

  PASSO 1 — Interpretação (OpenAI GPT-4o):
    O usuário digita em linguagem natural: "filmes de terror dos anos 2010".
    O GPT-4o lê isso e decide os filtros SQL:
      genero="Terror", tipo="movie", ano=None (não especificado um ano exato)
    Ele NÃO executa código — apenas devolve os argumentos como JSON.

  PASSO 2 — Consulta real no data lake (AWS Athena):
    Com os filtros extraídos, executamos uma query SQL na tabela SPEC do data lake.
    O Athena retorna títulos reais que passaram pelo pipeline completo de ETL.
    Ex: até 30 filmes de terror ordenados por popularidade.

  PASSO 3 — Formatação das recomendações (OpenAI GPT-4o):
    O GPT-4o recebe os títulos reais e os formata como recomendações personalizadas,
    escolhendo os mais relevantes e explicando o motivo de cada recomendação.
    Responde em JSON estruturado para o app.py renderizar os cards.

POR QUE USAR "FUNCTION CALLING" (TOOL USE)?
  O Function Calling (ou Tool Use) é uma técnica que permite ao GPT-4o
  "chamar funções" de forma estruturada. Em vez de responder em texto livre,
  o modelo devolve um JSON com argumentos específicos que você definiu.

  ANALOGIA: Como pedir a um assistente para preencher um formulário.
    Você diz "quero ver filmes de terror de 2015".
    O assistente não escreve um texto — ele preenche os campos:
    { genero: "Terror", tipo: "movie", ano: 2015 }
    Você então usa esses campos estruturados para fazer a busca real.

  Sem Function Calling, o modelo responderia em texto livre e seria difícil
  extrair os filtros de forma confiável para montar a query SQL.

TECNOLOGIAS UTILIZADAS:
  - openai (Python SDK): acessa o GPT-4o para interpretação e formatação
  - awswrangler (wr.athena.read_sql_query): executa SQL no Athena
  - boto3: cria a sessão AWS com região configurada
  - python-dotenv: carrega variáveis de ambiente do arquivo .env

VARIÁVEIS DE AMBIENTE NECESSÁRIAS (arquivo .env):
  OPENAI_API_KEY     → chave de acesso à API do OpenAI
  AWS_REGION         → região AWS (padrão: "sa-east-1")
  GLUE_DATABASE      → banco no Glue Catalog (padrão: "db_unified_tmdb")
  SPEC_TABLE         → tabela SPEC (padrão: "tb_discover_unified_tmdb")
  ATHENA_S3_OUTPUT   → caminho S3 para resultados temporários do Athena
"""

import os
import json
import boto3
import awswrangler as wr
from openai import OpenAI
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env (na mesma pasta do app).
# No ambiente de produção (Lightsail), o .env é criado pelo script de deploy
# com as variáveis do Terraform output. Em desenvolvimento, o .env é criado manualmente.
load_dotenv()

# Instancia o cliente do OpenAI uma única vez (reutilizado em todas as chamadas).
# api_key é lido da variável de ambiente OPENAI_API_KEY.
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==============================================================================
# DEFINIÇÃO DA TOOL (Function Calling)
# ==============================================================================
# TOOL é um objeto que descreve para o OpenAI a "função" que ele pode "chamar".
# O modelo não executa a função — ele apenas decide quais argumentos usar.
# Nós executamos a função de verdade com os argumentos que o modelo escolheu.
#
# Pense como um formulário que o GPT preenche baseado no pedido do usuário:
#   - genero:      qual gênero filtrar?
#   - tipo:        filme ("movie") ou série ("tv")?
#   - ano:         em qual ano lançado?
#   - nota_minima: qual nota mínima?
#   - limite:      quantos resultados retornar?
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
                    "enum": ["movie", "tv"],  # apenas esses dois valores são válidos
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


# ==============================================================================
# PASSO 2: Consulta real no Athena
# ==============================================================================

def buscar_titulos_spec(
    genero: str | None = None,
    tipo: str | None = None,
    ano: int | None = None,
    nota_minima: float = 6.0,
    limite: int = 30,
) -> list[dict]:
    """
    Consulta a tabela SPEC no Athena e retorna os títulos que correspondem aos filtros.

    Esta função é chamada com os argumentos que o GPT-4o escolheu no Passo 1.
    Ela monta dinamicamente a query SQL com os filtros aplicados e executa no Athena.

    FILTROS FIXOS (sempre aplicados):
      - vote_count >= 50: exclui títulos com poucos votos (notas não são confiáveis)
      - vote_average >= nota_minima: exclui títulos mal avaliados

    FILTROS DINÂMICOS (aplicados quando o argumento não é None):
      - media_type = tipo: "movie" ou "tv"
      - year = ano: ano específico de lançamento
      - lower(genre_names) LIKE lower('%genero%'): busca parcial no nome do gênero
        (ex: "terror" encontra "Terror, Mistério")

    Args:
        genero:      Gênero a filtrar (busca parcial, case-insensitive).
        tipo:        "movie" ou "tv". None = ambos.
        ano:         Ano de lançamento. None = todos os anos.
        nota_minima: Nota mínima de 0 a 10. Padrão 6.0.
        limite:      Máximo de títulos retornados. Padrão 30.

    Returns:
        Lista de dicionários, cada um representando um título com todos os campos da SPEC.
    """
    # Começa com os filtros que sempre devem ser aplicados
    filtros = ["vote_count >= 50", f"vote_average >= {float(nota_minima)}"]

    # Adiciona filtros opcionais apenas se o argumento foi fornecido pelo GPT
    if tipo in ("movie", "tv"):
        filtros.append(f"media_type = '{tipo}'")
    if ano:
        filtros.append(f"year = '{int(ano)}'")
    if genero:
        # Remove aspas simples para evitar injeção SQL (o usuário não controla isso,
        # mas o GPT pode incluir aspas ao extrair o gênero do texto do usuário)
        g = genero.replace("'", "")
        # LIKE com % nas duas pontas: busca o gênero em qualquer posição
        # lower() em ambos os lados: busca case-insensitive
        filtros.append(f"lower(genre_names) LIKE lower('%{g}%')")

    # Monta a query SQL com todos os filtros unidos por AND
    sql = f"""
        SELECT title, media_type, year, genre_names, overview,
               vote_average, poster_url, backdrop_url,
               runtime_minutes, number_of_seasons,
               number_of_episodes, episode_runtime_minutes,
               streaming_providers
        FROM {os.getenv('SPEC_TABLE', 'tb_discover_unified_tmdb')}
        WHERE {" AND ".join(filtros)}
        ORDER BY popularity DESC
        LIMIT {int(limite)}
    """

    # Cria a sessão AWS com a região definida na variável de ambiente
    session = boto3.Session(region_name=os.getenv("AWS_REGION", "sa-east-1"))
    df = wr.athena.read_sql_query(
        sql=sql,
        database=os.getenv("GLUE_DATABASE", "db_unified_tmdb"),
        s3_output=os.getenv("ATHENA_S3_OUTPUT"),  # onde salvar os resultados temporários
        boto3_session=session,
        ctas_approach=False,  # query direta (sem criar tabela temporária no S3 via CTAS)
    )
    # Converte o DataFrame Pandas para lista de dicionários — formato fácil de serializar
    # para JSON e passar ao OpenAI no Passo 3
    return df.to_dict(orient="records")


# ==============================================================================
# PASSO 1 + 3: Orquestração do agente (função principal)
# ==============================================================================

def recomendar(preferencia: str) -> list[dict]:
    """
    Orquestra os 3 passos do agente e retorna uma lista de recomendações.

    Esta é a única função chamada pelo app.py. Ela coordena todo o fluxo:
    GPT extrai filtros → Athena consulta → GPT formata recomendações.

    Args:
        preferencia: Texto em linguagem natural do usuário.
                     Ex: "filmes de terror dos anos 2010"

    Returns:
        Lista de dicionários, cada um com: titulo, tipo, ano, generos, sinopse,
        nota, poster_url, backdrop_url, motivo, duracao, streaming_providers.
        Retorna lista vazia se nenhum título for encontrado ou o modelo não responder.
    """

    # ------------------------------------------------------------------
    # PASSO 1: GPT-4o analisa o texto e decide os filtros SQL
    # ------------------------------------------------------------------
    # tool_choice="required" força o modelo a sempre usar a tool definida.
    # Sem isso, o modelo poderia responder em texto livre se não entendesse
    # como usar a tool — o que quebraria o processamento no Passo 2.
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
        tool_choice="required",  # força o uso da tool (não aceita resposta em texto livre)
    )

    # ------------------------------------------------------------------
    # PASSO 2: Extrai os argumentos escolhidos pelo GPT e consulta o Athena
    # ------------------------------------------------------------------
    # tool_calls[0]: o modelo pode chamar múltiplas tools, mas definimos apenas uma
    # function.arguments: string JSON com os argumentos que o GPT escolheu
    tool_call = resposta.choices[0].message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)
    # Executa a consulta real no data lake com os filtros escolhidos pelo GPT
    titulos_da_spec = buscar_titulos_spec(**args)

    if not titulos_da_spec:
        return []  # nenhum título encontrado com esses filtros

    # ------------------------------------------------------------------
    # PASSO 3: GPT-4o formata os títulos reais como recomendações
    # ------------------------------------------------------------------
    # A conversa é reconstruída com o histórico completo para o modelo entender o contexto:
    #   system → mensagem do usuário → resposta anterior do modelo (com tool_call) → resultado da tool
    # Esse encadeamento é obrigatório pelo protocolo de tool use da API OpenAI —
    # sem ele o modelo não sabe que a tool já foi chamada e tenta chamá-la de novo.
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
            # Inclui a mensagem anterior do modelo (com a tool_call) no histórico.
            # Isso é necessário para que o modelo saiba que a tool já foi chamada.
            resposta.choices[0].message,
            {
                "role": "tool",
                "tool_call_id": tool_call.id,  # vincula o resultado à tool_call anterior
                # Serializa a lista de títulos do Athena como JSON para o modelo ler.
                # default=str: converte tipos não-serializáveis (ex: Timestamp) para string.
                "content": json.dumps(titulos_da_spec, ensure_ascii=False, default=str),
            },
        ],
    )

    conteudo = resposta_final.choices[0].message.content or ""
    conteudo = conteudo.strip()

    # O modelo às vezes devolve o JSON envolto em ```json ... ``` mesmo sendo instruído a não
    # fazer isso. Este bloco remove esse envoltório (markdown code fence) antes de parsear.
    # Exemplo de resposta com envoltório:
    #   ```json
    #   {"titulos": [...]}
    #   ```
    if conteudo.startswith("```"):
        conteudo = conteudo.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    if not conteudo:
        return []  # modelo retornou string vazia — não há recomendações

    # Faz o parse do JSON retornado pelo modelo
    dados = json.loads(conteudo)
    # Retorna apenas a lista de títulos (dentro da chave "titulos")
    return dados.get("titulos", [])
