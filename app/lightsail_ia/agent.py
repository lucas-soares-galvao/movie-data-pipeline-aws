"""
agent.py — Agente de IA para recomendação de filmes e séries.

==============================================================================
O QUE ESTE ARQUIVO FAZ?
==============================================================================
Implementa o "cérebro" do FilmBot em 2 passos usando LLM + AWS Athena:

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

  FORMATAÇÃO — Registros formatados pelo Python:
    Após o Athena retornar os títulos, funções Python convertem cada registro
    em campos prontos para o card da interface (tipo, gêneros, duração, etc.).

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
  FILMBOT_SECRET_ARN → ARN do segredo unificado no Secrets Manager (produção)
  LLM_API_KEY        → fallback para dev local (usado quando FILMBOT_SECRET_ARN não está definida)
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
import logging
import hashlib
import boto3
import litellm
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env (na mesma pasta do app).
# No ambiente de produção (Lightsail), o .env é criado pelo script de deploy
# com as variáveis do Terraform output. Em desenvolvimento, o .env é criado manualmente.
load_dotenv()

_LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash")


def _carregar_llm_api_key() -> str | None:
    """Busca a LLM_API_KEY do Secrets Manager (produção) ou do .env (desenvolvimento)."""
    secret_arn = os.getenv("FILMBOT_SECRET_ARN")
    if secret_arn:
        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "sa-east-1"))
        response = client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response["SecretString"])
        return secret["llm_api_key"]
    return os.getenv("LLM_API_KEY")


_LLM_API_KEY = _carregar_llm_api_key()

logger = logging.getLogger(__name__)

_CACHE_WHERE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SEGUNDOS = 3600


def _chave_cache(preferencia: str) -> str:
    """Gera hash MD5 da preferência normalizada para uso como chave de cache."""
    normalizada = preferencia.strip().lower()
    return hashlib.md5(normalizada.encode()).hexdigest()


def _buscar_cache_where(preferencia: str) -> dict | None:
    """Verifica se já existe uma cláusula WHERE cacheada para esta preferência.
    Evita chamadas desnecessárias ao LLM quando o mesmo pedido é feito novamente dentro de 1 hora."""
    chave = _chave_cache(preferencia)
    if chave not in _CACHE_WHERE:
        return None
    timestamp, args = _CACHE_WHERE[chave]
    if time.time() - timestamp > _CACHE_TTL_SEGUNDOS:
        del _CACHE_WHERE[chave]
        return None
    logger.info("Cache hit para WHERE clause", extra={"preferencia": preferencia})
    return args


def _salvar_cache_where(preferencia: str, args: dict) -> None:
    """Salva a cláusula WHERE no cache com timestamp atual."""
    chave = _chave_cache(preferencia)
    _CACHE_WHERE[chave] = (time.time(), args)


def _logar_uso_tokens(etapa: str, resposta: object) -> None:
    """Registra no log o consumo de tokens (prompt, completion, total) de uma chamada LLM."""
    usage = getattr(resposta, "usage", None)
    if not usage:
        return
    logger.info(
        "LLM token usage",
        extra={
            "etapa": etapa,
            "modelo": _LLM_MODEL,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    )

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
                    "description": "Quantidade máxima de resultados (padrão 10, máximo 10)",
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
# FORMATAÇÃO DETERMINÍSTICA (Python puro, sem LLM)
# ==============================================================================

_MESES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def _formatar_tipo(media_type: str) -> str:
    """Converte media_type da API ('movie'/'tv') para português ('filme'/'série')."""
    return "filme" if media_type == "movie" else "série" if media_type == "tv" else media_type


def _formatar_generos(genre_names: str | None) -> list[str]:
    """Converte string de gêneros separados por vírgula em lista."""
    if not genre_names:
        return []
    return [g.strip() for g in genre_names.split(",") if g.strip()]


def _formatar_duracao_titulo(registro: dict) -> str | None:
    """Formata duração: '2h 15min' para filmes, '3 temporadas · 24 eps' para séries."""
    if registro.get("media_type") == "movie":
        raw = registro.get("runtime_minutes")
        if not raw:
            return None
        minutos = int(raw)
        horas, resto = divmod(minutos, 60)
        return f"{horas}h {resto}min" if horas else f"{resto}min"

    partes = []
    seasons = registro.get("number_of_seasons")
    episodes = registro.get("number_of_episodes")
    ep_runtime = registro.get("episode_runtime_minutes")
    if seasons:
        n = int(seasons)
        partes.append(f"{n} temporada{'s' if n != 1 else ''}")
    if episodes:
        partes.append(f"{int(episodes)} eps")
    if ep_runtime:
        partes.append(f"~{int(ep_runtime)} min/ep")
    return " · ".join(partes) if partes else None


def _formatar_data_lancamento(air_date: str | None) -> str | None:
    """Converte data ISO 'YYYY-MM-DD' para 'Mês de Ano' em português."""
    if not air_date or len(air_date) < 7:
        return None
    try:
        partes = air_date.split("-")
        ano = int(partes[0])
        mes = int(partes[1])
        return f"{_MESES[mes]} de {ano}"
    except (ValueError, KeyError, IndexError):
        return None


def _formatar_theater_end_date(theater_end_date: str | None, in_theaters: bool) -> str | None:
    """Converte data ISO para 'DD/MM/AAAA' se o título estiver em cartaz."""
    if not in_theaters or not theater_end_date:
        return None
    try:
        ano, mes, dia = theater_end_date.split("-")
        return f"{dia}/{mes}/{ano}"
    except ValueError:
        return None


def _formatar_nota(vote_average: object) -> float | None:
    """Converte nota (str, int ou float) para float, retornando None se inválida."""
    if vote_average is None or vote_average == "":
        return None
    try:
        return float(vote_average)
    except (ValueError, TypeError):
        return None


def _formatar_registro(registro: dict) -> dict:
    """Transforma um registro cru do Athena em dict formatado para o card do app."""
    in_theaters = str(registro.get("in_theaters", "")).lower() == "true"
    return {
        "titulo": registro.get("title", ""),
        "tipo": _formatar_tipo(registro.get("media_type", "")),
        "ano": int(registro["year"]) if registro.get("year") else None,
        "generos": _formatar_generos(registro.get("genre_names")),
        "sinopse": registro.get("overview") or "",
        "nota": _formatar_nota(registro.get("vote_average")),
        "poster_url": registro.get("poster_url") or None,
        "backdrop_url": registro.get("backdrop_url") or None,
        "duracao": _formatar_duracao_titulo(registro),
        "data_lancamento": _formatar_data_lancamento(registro.get("air_date")),
        "streaming_providers": registro.get("streaming_providers") or None,
        "in_theaters": in_theaters,
        "theater_end_date": _formatar_theater_end_date(
            registro.get("theater_end_date"), in_theaters
        ),
    }


# ==============================================================================
# PASSO 2: Consulta real no Athena
# ==============================================================================

def buscar_titulos_spec(filtro_where: str, limite: int = 10) -> list[dict]:
    """
    Consulta a tabela SPEC no Athena e retorna os títulos que correspondem aos filtros.

    O LLM gera a cláusula WHERE livremente com base no schema da tabela.
    O filtro fixo vote_count >= 50 é sempre aplicado automaticamente para
    garantir qualidade dos dados (exclui títulos com poucos votos).

    Args:
        filtro_where: Cláusula WHERE gerada pelo LLM (sem a palavra WHERE).
        limite:       Máximo de títulos retornados. Padrão 10.

    Returns:
        Lista de dicionários, cada um representando um título com todos os campos da SPEC.
    """
    limite = max(1, min(int(limite), 10))
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
        nota, poster_url, backdrop_url, duracao, streaming_providers,
        in_theaters, theater_end_date.
        Retorna lista vazia se nenhum título for encontrado ou o modelo não responder.
    """

    # ------------------------------------------------------------------
    # PASSO 1: LLM analisa o texto e decide os filtros SQL (com cache)
    # ------------------------------------------------------------------
    args_cache = _buscar_cache_where(preferencia)

    if args_cache is not None:
        args = args_cache
    else:
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
        )
        _logar_uso_tokens("passo_1_where", resposta)

        # tool_calls[0]: o modelo pode chamar múltiplas tools, mas definimos apenas uma
        # function.arguments: string JSON com os argumentos que o LLM escolheu
        tool_calls = resposta.choices[0].message.tool_calls or []
        if not tool_calls:
            return []
        tool_call = tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        _salvar_cache_where(preferencia, args)

    # ------------------------------------------------------------------
    # PASSO 2: Consulta o Athena com os filtros (do cache ou do LLM)
    # ------------------------------------------------------------------
    titulos_da_spec = buscar_titulos_spec(**args)

    if not titulos_da_spec:
        return []  # nenhum título encontrado com esses filtros

    # Formata todos os campos determinísticos via Python (instantâneo)
    return [_formatar_registro(r) for r in titulos_da_spec]


def limpar_duracao(raw: str) -> str:
    """Remove fragmentos '~null' e partes vazias da string de duração gerada pelo LLM."""
    limpo = raw.replace("~null", "").strip(" ·")
    return " · ".join(part.strip() for part in limpo.split(" · ") if part.strip())