"""
agent.py — Agente de IA para recomendação de filmes e séries.

==============================================================================
O QUE ESTE ARQUIVO FAZ?
==============================================================================
Implementa o "cérebro" do FilmBot em 3 passos usando LLM + AWS Athena:

  PASSO 1 — Interpretação (LLM via litellm):
    O usuário digita em linguagem natural: "filmes coreanos de terror dos anos 2010".
    O LLM conhece o schema da tabela SPEC e gera a cláusula WHERE do SQL:
      "media_type = 'movie' AND original_language = 'ko'
       AND lower(genre_names) LIKE '%terror%'
       AND year BETWEEN '2010' AND '2019'"
    Ele NÃO executa código — apenas devolve a cláusula WHERE como string.

  PASSO 2 — Consulta real no data lake (AWS Athena):
    A cláusula WHERE gerada pelo LLM é validada (segurança) e executada no Athena.
    O filtro fixo vote_count >= 50 é sempre aplicado automaticamente.
    O Athena retorna títulos reais que passaram pelo pipeline completo de ETL.

  PASSO 3 — Formatação das recomendações (LLM via litellm):
    O LLM recebe os títulos reais e os formata como recomendações personalizadas,
    escolhendo os mais relevantes e explicando o motivo de cada recomendação.
    Responde em JSON estruturado para o app.py renderizar os cards.

POR QUE USAR "FUNCTION CALLING" (TOOL USE)?
  O Function Calling (ou Tool Use) é uma técnica que permite ao LLM
  "chamar funções" de forma estruturada. Em vez de responder em texto livre,
  o modelo devolve um JSON com argumentos específicos que você definiu.

  Nesta abordagem "livre", o LLM recebe o schema completo da tabela e gera
  a cláusula WHERE diretamente. Isso permite que qualquer combinação de filtros
  seja usada sem precisar mapear cada pergunta possível no código.

TECNOLOGIAS UTILIZADAS:
  - litellm: interface unificada para múltiplos provedores de LLM (OpenAI, DeepSeek, Claude, etc.)
  - boto3 (Athena API nativa): executa SQL no Athena sem dependências pesadas
  - python-dotenv: carrega variáveis de ambiente do arquivo .env

VARIÁVEIS DE AMBIENTE NECESSÁRIAS (arquivo .env):
  LLM_API_KEY        → chave de acesso à API do provedor LLM em uso
  LLM_MODEL          → modelo LLM a usar (padrão: "deepseek/deepseek-v4-flash"). Exemplos:
                        "deepseek/deepseek-v4-flash" + chave DeepSeek
                        "gpt-4o"                     + chave OpenAI
                        "claude-opus-4-8"            + ANTHROPIC_API_KEY
  AWS_REGION         → região AWS (padrão: "sa-east-1")
  GLUE_DATABASE      → banco no Glue Catalog (padrão: "db_tmdb_unified_prod")
  SPEC_TABLE         → tabela SPEC (padrão: "tb_tmdb_discover_unified_prod")
  ATHENA_S3_OUTPUT   → caminho S3 para resultados temporários do Athena
"""

import gc
import os
import re
import json
import time
import boto3
import litellm
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env (na mesma pasta do app).
# No ambiente de produção (Lightsail), o .env é criado pelo script de deploy
# com as variáveis do Terraform output. Em desenvolvimento, o .env é criado manualmente.
load_dotenv()

_LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash")
_LLM_API_KEY = os.getenv("LLM_API_KEY")

# ==============================================================================
# DEFINIÇÃO DA TOOL (Function Calling)
# ==============================================================================
# TOOL é um objeto que descreve para o LLM a "função" que ele pode "chamar".
# O modelo não executa a função — ele apenas decide quais argumentos usar.
# Nós executamos a função de verdade com os argumentos que o modelo escolheu.
#
# Nesta abordagem "livre", o LLM recebe o schema completo da tabela SPEC
# no system prompt e gera a cláusula WHERE diretamente. Isso permite que
# qualquer combinação de filtros seja usada sem precisar mapear cada pergunta
# possível no código. O parâmetro limite continua estruturado para segurança.
TOOL = {
    "type": "function",
    "function": {
        "name": "buscar_titulos_spec",
        "description": "Busca filmes e séries reais da tabela SPEC no data lake AWS.",
        "parameters": {
            "type": "object",
            "properties": {
                "filtro_where": {
                    "type": "string",
                    "description": (
                        "Cláusula WHERE do SQL (sem a palavra WHERE). "
                        "Use AND para combinar filtros. "
                        "Exemplos: "
                        "\"media_type = 'movie' AND lower(genre_names) LIKE '%terror%'\", "
                        "\"original_language = 'ko' AND year BETWEEN '2010' AND '2019'\", "
                        "\"in_theaters = true AND media_type = 'movie'\", "
                        "\"lower(streaming_providers) LIKE '%netflix%' AND vote_average >= 8.0\", "
                        "\"lower(genre_names) LIKE '%comédia%' AND vote_average >= 7.0\" "
                        "(sem media_type = retorna filmes E séries)"
                    ),
                },
                "limite": {
                    "type": "integer",
                    "description": "Quantidade máxima de resultados (padrão 30, máximo 30)",
                },
            },
            "required": ["filtro_where"],
        },
    },
}

# Palavras-chave SQL proibidas na cláusula WHERE gerada pelo LLM.
# O Athena é read-only por natureza, mas essa validação impede que o LLM
# gere cláusulas malformadas ou que fujam do escopo de um filtro SELECT.
_PALAVRAS_PROIBIDAS = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|GRANT|TRUNCATE|EXEC|MERGE|REPLACE|CALL)\b",
    re.IGNORECASE,
)


def _validar_where(filtro_where: str) -> str:
    """Valida a cláusula WHERE gerada pelo LLM e retorna a string sanitizada.

    Raises:
        ValueError: se a cláusula contiver SQL proibido.
    """
    if ";" in filtro_where:
        raise ValueError("Cláusula WHERE inválida: contém ';'")
    if _PALAVRAS_PROIBIDAS.search(filtro_where):
        raise ValueError("Cláusula WHERE inválida: contém palavra SQL proibida")
    if re.search(r"\bSELECT\b", filtro_where, re.IGNORECASE):
        raise ValueError("Cláusula WHERE inválida: contém subquery")
    return filtro_where.strip()


# ==============================================================================
# PASSO 2: Consulta real no Athena
# ==============================================================================

def buscar_titulos_spec(filtro_where: str, limite: int = 30) -> list[dict]:
    """
    Consulta a tabela SPEC no Athena e retorna os títulos que correspondem aos filtros.

    O LLM gera a cláusula WHERE livremente com base no schema da tabela.
    O filtro fixo vote_count >= 50 é sempre aplicado automaticamente para
    garantir qualidade dos dados (exclui títulos com poucos votos).

    Args:
        filtro_where: Cláusula WHERE gerada pelo LLM (sem a palavra WHERE).
        limite:       Máximo de títulos retornados. Padrão 30.

    Returns:
        Lista de dicionários, cada um representando um título com todos os campos da SPEC.
    """
    limite = max(1, min(int(limite), 30))
    filtro_where = _validar_where(filtro_where)

    sql = f"""
        SELECT title, media_type, year, air_date, genre_names, overview,
               vote_average, poster_url, backdrop_url,
               runtime_minutes, number_of_seasons,
               number_of_episodes, episode_runtime_minutes,
               streaming_providers,
               in_theaters, theater_end_date
        FROM {os.getenv('SPEC_TABLE', 'tb_tmdb_discover_unified_prod')}
        WHERE vote_count >= 50 AND {filtro_where}
        ORDER BY popularity DESC
        LIMIT {int(limite)}
    """

    athena = boto3.client("athena", region_name=os.getenv("AWS_REGION", "sa-east-1"))

    # Dispara a query no Athena
    exec_response = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": os.getenv("GLUE_DATABASE", "db_tmdb_unified_prod")},
        ResultConfiguration={"OutputLocation": os.getenv("ATHENA_S3_OUTPUT")},
    )
    execution_id = exec_response["QueryExecutionId"]

    # Aguarda a conclusão (polling simples com backoff fixo de 1 s)
    while True:
        status = athena.get_query_execution(QueryExecutionId=execution_id)
        state = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {state}: {reason}")
        time.sleep(1)

    # Lê os resultados paginados e monta lista de dicionários
    paginator = athena.get_paginator("get_query_results")
    records = []
    columns = None
    for page in paginator.paginate(QueryExecutionId=execution_id):
        rows = page["ResultSet"]["Rows"]
        if columns is None:
            # Primeira linha é o cabeçalho
            columns = [col["VarCharValue"] for col in rows[0]["Data"]]
            rows = rows[1:]
        for row in rows:
            values = [item.get("VarCharValue") for item in row["Data"]]
            records.append(dict(zip(columns, values)))

    # Libera memória dos objetos de resposta do boto3 antes de passar ao LLM
    gc.collect()
    return records


# ==============================================================================
# PASSO 1 + 3: Orquestração do agente (função principal)
# ==============================================================================

def recomendar(preferencia: str) -> list[dict]:
    """
    Orquestra os 3 passos do agente e retorna uma lista de recomendações.

    Esta é a única função chamada pelo app.py. Ela coordena todo o fluxo:
    LLM extrai filtros → Athena consulta → LLM formata recomendações.

    Args:
        preferencia: Texto em linguagem natural do usuário.
                     Ex: "filmes de terror dos anos 2010"

    Returns:
        Lista de dicionários, cada um com: titulo, tipo, ano, generos, sinopse,
        nota, poster_url, backdrop_url, motivo, duracao, streaming_providers,
        in_theaters, theater_end_date.
        Retorna lista vazia se nenhum título for encontrado ou o modelo não responder.
    """

    # ------------------------------------------------------------------
    # PASSO 1: LLM analisa o texto e decide os filtros SQL
    # ------------------------------------------------------------------
    # tool_choice="required" força o modelo a sempre usar a tool definida.
    # Sem isso, o modelo poderia responder em texto livre se não entendesse
    # como usar a tool — o que quebraria o processamento no Passo 2.
    resposta = litellm.completion(
        model=_LLM_MODEL,
        api_key=_LLM_API_KEY,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um assistente de recomendação de filmes e séries. "
                    "Analise o pedido do usuário e gere a cláusula WHERE do SQL para filtrar a tabela SPEC.\n\n"
                    "SCHEMA DA TABELA SPEC (colunas disponíveis para filtro):\n"
                    "- media_type (string): 'movie' ou 'tv'\n"
                    "- title (string): título em português\n"
                    "- original_title (string): título original (ex: 'The Shining', 'Parasita')\n"
                    "- overview (string): sinopse do título. Use lower() + LIKE para buscar por palavra-chave.\n"
                    "- original_language (string): código ISO 639-1 do idioma original (ex: 'en', 'ko', 'ja', 'pt', 'es', 'fr')\n"
                    "- language_name (string): nome do idioma em inglês (ex: 'English', 'Korean', 'Japanese')\n"
                    "- genre_names (string): gêneros separados por vírgula (ex: 'Terror, Drama'). Use lower() + LIKE para buscar.\n"
                    "- year (string): ano de lançamento. Use BETWEEN para faixas, = para ano exato.\n"
                    "- air_date (string): data de lançamento no formato 'YYYY-MM-DD'\n"
                    "- vote_average (double): nota média de 0 a 10\n"
                    "- vote_count (int): número de votos (filtro fixo >= 50 já aplicado; use para exigir mais votos)\n"
                    "- popularity (double): score de popularidade do TMDB\n"
                    "- origin_country (array<string>): códigos ISO 3166-1 do país de origem (ex: 'US', 'BR', 'KR'). Use contains() para filtrar.\n"
                    "- origin_country_name (string): nome do país de origem (ex: 'Brasil', 'United States', '대한민국')\n"
                    "- runtime_minutes (int): duração em minutos (apenas filmes, NULL para séries)\n"
                    "- number_of_seasons (int): número de temporadas (apenas séries)\n"
                    "- number_of_episodes (int): número de episódios (apenas séries)\n"
                    "- episode_runtime_minutes (int): duração média por episódio em minutos (apenas séries)\n"
                    "- streaming_providers (string): plataformas de streaming no Brasil (ex: 'Netflix, Amazon Prime Video'). Use lower() + LIKE.\n"
                    "- in_theaters (boolean): true se está em cartaz nos cinemas\n"
                    "- theater_start_date (string): data de estreia nos cinemas ('YYYY-MM-DD')\n"
                    "- theater_end_date (string): data de saída dos cinemas ('YYYY-MM-DD')\n"
                    "- adult (boolean): true se é conteúdo adulto\n\n"
                    "REGRAS:\n"
                    "- Gere APENAS a cláusula WHERE (sem a palavra WHERE), usando AND para combinar filtros.\n"
                    "- Para textos, use lower() + LIKE: lower(genre_names) LIKE '%terror%'\n"
                    "- Para idioma, use original_language com código ISO: original_language = 'ko' (coreano), 'ja' (japonês), 'en' (inglês), 'pt' (português)\n"
                    "- Sempre inclua vote_average >= 6.0 salvo se o usuário pedir nota diferente.\n"
                    "- Se o usuário pedir APENAS filmes, use media_type = 'movie'. Se pedir APENAS séries, use media_type = 'tv'. "
                    "Se pedir ambos ('filmes e séries', 'filmes ou séries') ou não especificar o tipo, NÃO inclua filtro de media_type.\n"
                    "- Nunca use SELECT, INSERT, UPDATE, DELETE ou outros comandos — apenas expressões de filtro."
                ),
            },
            {"role": "user", "content": preferencia},
        ],
        tools=[TOOL],
        tool_choice="required",  # força o uso da tool (não aceita resposta em texto livre)
    )

    # ------------------------------------------------------------------
    # PASSO 2: Extrai os argumentos escolhidos pelo LLM e consulta o Athena
    # ------------------------------------------------------------------
    # tool_calls[0]: o modelo pode chamar múltiplas tools, mas definimos apenas uma
    # function.arguments: string JSON com os argumentos que o LLM escolheu
    tool_calls = resposta.choices[0].message.tool_calls or []
    if not tool_calls:
        return []  # modelo não chamou a tool — não há filtros para consultar
    tool_call = tool_calls[0]
    args = json.loads(tool_call.function.arguments)
    # Executa a consulta real no data lake com os filtros escolhidos pelo LLM
    titulos_da_spec = buscar_titulos_spec(**args)

    if not titulos_da_spec:
        return []  # nenhum título encontrado com esses filtros

    # ------------------------------------------------------------------
    # PASSO 3: LLM formata os títulos reais como recomendações
    # ------------------------------------------------------------------
    # A conversa é reconstruída com o histórico completo para o modelo entender o contexto:
    #   system → mensagem do usuário → resposta anterior do modelo (com tool_call) → resultado da tool
    # Esse encadeamento é obrigatório pelo protocolo de tool use —
    # sem ele o modelo não sabe que a tool já foi chamada e tenta chamá-la de novo.
    # A mensagem do assistente é convertida para dict explicitamente para garantir
    # compatibilidade entre provedores (LiteLLM, OpenAI, DeepSeek, etc.).
    resposta_final = litellm.completion(
        model=_LLM_MODEL,
        api_key=_LLM_API_KEY,
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
                    "data_lancamento (string com mês por extenso em português e ano, ex: 'Julho 2025', "
                    "extraído do campo air_date no formato 'YYYY-MM-DD'; se air_date for null ou vazio, defina como null), "
                    "streaming_providers (string com nomes dos serviços separados por vírgula, ou null). "
                    "Para filmes, formate duracao a partir de runtime_minutes: ex. '1h 52min'. "
                    "Para séries, formate duracao combinando number_of_seasons, number_of_episodes "
                    "e episode_runtime_minutes: ex. '3 temporadas · 36 eps · ~45 min/ep'. "
                    "Se episode_runtime_minutes for null ou ausente, omita essa parte: ex. '3 temporadas · 36 eps'. "
                    "Se todos os dados de duração forem null, defina duracao como null. "
                    "Copie streaming_providers exatamente como recebido (ex: 'Netflix, Amazon Prime Video'), "
                    "ou null se o campo estiver ausente ou vazio. "
                    "in_theaters: booleano (true/false) copiado do campo in_theaters; use false se ausente. "
                    "theater_end_date: string no formato 'DD/MM/YYYY' convertida a partir do campo theater_end_date "
                    "(formato 'YYYY-MM-DD'), ou null se o campo estiver ausente, vazio ou in_theaters for false. "
                    "Responda APENAS com o JSON, sem texto extra. "
                    "Responda sempre em português. "
                    "Se a sinopse de algum título estiver em inglês, traduza-a para o português antes de exibir."
                ),
            },
            {"role": "user", "content": preferencia},
            # Inclui a mensagem anterior do modelo (com a tool_call) no histórico.
            # Convertido para dict para compatibilidade entre provedores via LiteLLM.
            {
                "role": "assistant",
                "content": resposta.choices[0].message.content,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                ],
            },
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


def limpar_duracao(raw: str) -> str:
    """Remove fragmentos '~null' e partes vazias da string de duração gerada pelo LLM."""
    limpo = raw.replace("~null", "").strip(" ·")
    return " · ".join(part.strip() for part in limpo.split(" · ") if part.strip())