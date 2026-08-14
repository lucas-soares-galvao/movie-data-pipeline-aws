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
    Sem filtro fixo de qualidade (ex: vote_count) — a ordenação por popularidade
    (ORDER BY popularity DESC) já é o sinal de relevância, e inclui títulos ainda
    não lançados (que nunca tiveram chance de acumular voto).
    O Athena retorna títulos reais que passaram pelo pipeline completo de ETL.
    Em seguida, funções em formatacao.py convertem cada registro em campos
    prontos para o card da interface (sem usar LLM).

  PASSO 3 — Geração do motivo (LLM via litellm):
    O LLM recebe apenas os campos essenciais de cada título já encontrado pelo
    Athena e escreve um motivo curto (1-2 frases) explicando por que aquele
    título específico atende ao pedido do usuário. Responde em JSON, que é
    mesclado por índice aos registros já formatados pelo Python.

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

VARIÁVEIS OPCIONAIS — transcrição de áudio (entrada alternativa por voz):
  TRANSCRIPTION_API_KEY → fallback para dev local (usado quando FILMBOT_SECRET_ARN não
                        está definida; em produção, vem do campo transcription_api_key
                        no secret). Indefinida = transcrição de áudio indisponível
                        (o campo de texto continua funcionando normalmente).
  TRANSCRIPTION_MODEL → modelo de transcrição a usar via litellm
                        (padrão: "groq/whisper-large-v3-turbo")
"""

import gc
import hashlib
import io
import json
import logging
import os
import random
import re
import time
import wave

import boto3
import litellm
from dotenv import load_dotenv
from formatacao import format_record

# Carrega as variáveis de ambiente do arquivo .env (na mesma pasta do app).
# No ambiente de produção (Lightsail), o .env é criado pelo script de deploy
# com as variáveis do Terraform output. Em desenvolvimento, o .env é criado manualmente.
load_dotenv()

_LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash")
_LLM_NUM_RETRIES = 3
# Pool de candidatos maior que o limit pedido: search_titles_spec() sorteia um
# subconjunto desse pool a cada busca, para não repetir sempre o mesmo top-N
# por popularidade quando a mesma pergunta (ou uma parecida) é feita de novo.
# Valores conservadores (não maior) de propósito: a instância Lightsail de
# produção tem só 1 GB de RAM (bundle micro_3_0) e cada linha a mais do pool
# aumenta proporcionalmente o payload de boto3 carregado na memória por busca.
_CANDIDATE_POOL_MULTIPLIER = 3
_CANDIDATE_POOL_MAX = 30
_TRANSCRIPTION_MODEL = os.getenv("TRANSCRIPTION_MODEL", "groq/whisper-large-v3-turbo")
_MAX_AUDIO_SECONDS = 15
# Folga só pra rejeição, não pro auto-stop nem pro rótulo mostrado ao usuário
# ("00:00 / 00:15", "máx. 15s"): o auto-stop no cliente corta a gravação assim
# que o tempo decorrido atinge _MAX_AUDIO_SECONDS, mas o áudio resultante mede
# um pouco além disso por jitter do poll de 250ms + arredondamento de
# encoding — medido via inspeção real do log do servidor (15.00s a 15.06s
# num áudio "de 15s"). Sem essa folga, todo áudio que usou o tempo cheio
# (o caso normal, não um abuso) era rejeitado como "muito longo" em vez de
# transcrito — rejeitar só faz sentido pra um áudio claramente fora do limite
# (bypass do auto-stop), não pra esse jitter esperado.
_AUDIO_DURATION_TOLERANCE_SECONDS = 1


def _load_llm_api_key() -> str | None:
    """Busca a LLM_API_KEY do Secrets Manager (produção) ou do .env (desenvolvimento)."""
    secret_arn = os.getenv("FILMBOT_SECRET_ARN")
    if secret_arn:
        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "sa-east-1"))
        response = client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response["SecretString"])
        return secret["llm_api_key"]
    return os.getenv("LLM_API_KEY")


def _load_transcription_api_key() -> str | None:
    """Busca a TRANSCRIPTION_API_KEY do Secrets Manager (produção) ou do .env (desenvolvimento).

    Diferente de _load_llm_api_key(), usa secret.get() em vez de indexação direta:
    transcription_api_key é um campo opcional, adicionado ao secret depois que ele já
    existia em produção. Retornar None em vez de KeyError permite que o app suba
    normalmente antes do operador popular o campo — a transcrição fica apenas
    indisponível (ver transcribe_preference()), sem derrubar o app.
    """
    secret_arn = os.getenv("FILMBOT_SECRET_ARN")
    if secret_arn:
        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "sa-east-1"))
        response = client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response["SecretString"])
        return secret.get("transcription_api_key")
    return os.getenv("TRANSCRIPTION_API_KEY")


_LLM_API_KEY = _load_llm_api_key()
_TRANSCRIPTION_API_KEY = _load_transcription_api_key()


class AudioMuitoLongoError(Exception):
    """Levantado quando o áudio gravado excede _MAX_AUDIO_SECONDS."""

logger = logging.getLogger(__name__)
# Nível explícito: app.py eleva o root logger para ERROR quando o CloudWatch
# está configurado (para silenciar bibliotecas ruidosas), o que suprimiria os
# logs de uso de tokens (INFO) por herança. Definir o nível aqui, no logger
# deste módulo, garante que esses logs continuem passando pelo handler do root.
logger.setLevel(logging.INFO)

_WHERE_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 3600


def _cache_key(preference: str) -> str:
    """Gera hash MD5 da preferência normalizada para uso como chave de cache."""
    normalized = preference.strip().lower()
    return hashlib.md5(normalized.encode()).hexdigest()


def _get_cached_where(preference: str) -> dict | None:
    """Verifica se já existe uma cláusula WHERE cacheada para esta preferência.
    Evita chamadas desnecessárias ao LLM quando o mesmo pedido é feito novamente dentro de 1 hora."""
    key = _cache_key(preference)
    if key not in _WHERE_CACHE:
        return None
    timestamp, args = _WHERE_CACHE[key]
    if time.time() - timestamp > _CACHE_TTL_SECONDS:
        del _WHERE_CACHE[key]
        return None
    logger.info("Cache hit para WHERE clause", extra={"preference": preference})
    return args


def _save_cached_where(preference: str, args: dict) -> None:
    """Salva a cláusula WHERE no cache com timestamp atual."""
    key = _cache_key(preference)
    _WHERE_CACHE[key] = (time.time(), args)


def _log_token_usage(step: str, response: object) -> None:
    """Registra no log o consumo de tokens (prompt, completion, total) de uma chamada LLM."""
    usage = getattr(response, "usage", None)
    if not usage:
        return
    logger.info(
        "LLM token usage",
        extra={
            "step": step,
            "model": _LLM_MODEL,
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
# possível no código. O parâmetro limit continua estruturado para segurança.
TOOL = {
    "type": "function",
    "function": {
        "name": "search_titles_spec",
        "description": "Busca filmes e séries reais da tabela SPEC no data lake AWS.",
        "parameters": {
            "type": "object",
            "properties": {
                "where_clause": {
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
                "limit": {
                    "type": "integer",
                    "description": "Quantidade máxima de resultados (padrão 15, máximo 15)",
                },
            },
            "required": ["where_clause"],
        },
    },
}

# System prompt enviado ao LLM no Passo 1. Define o schema da tabela SPEC e as regras
# de geração da cláusula WHERE. Fica aqui (nível de módulo) para não poluir recommend().
_SYSTEM_PROMPT = (
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
    "- vote_count (int): número de votos (sem filtro automático; use pra exigir mais votos, ex: títulos consagrados/bem avaliados)\n"
    "- popularity (double): score de popularidade do TMDB\n"
    "- origin_country (array<string>): códigos ISO 3166-1 do país de origem (ex: 'US', 'BR', 'KR'). Use contains() para filtrar.\n"
    "- origin_country_name (string): nome do país de origem (ex: 'Brasil', 'United States', '대한민국')\n"
    "- runtime_minutes (int): duração em minutos (apenas filmes, NULL para séries)\n"
    "- number_of_seasons (int): número de temporadas (apenas séries)\n"
    "- number_of_episodes (int): número de episódios (apenas séries)\n"
    "- episode_runtime_minutes (int): duração média por episódio em minutos (apenas séries)\n"
    "- tagline (string): frase curta de efeito do título\n"
    "- title_status (string): estado do título. Filmes: 'Released', 'Post Production'. Séries: 'Returning Series', 'Ended', 'Canceled'\n"
    "- collection_name (string): saga/franquia de filmes (ex: 'Harry Potter Collection', 'Avengers Collection'). Apenas filmes. Use lower() + LIKE.\n"
    "- budget (bigint): orçamento em USD. Apenas filmes. Use > para filtrar alto orçamento.\n"
    "- revenue (bigint): receita de bilheteria em USD. Apenas filmes.\n"
    "- production_companies (string): estúdios produtores (ex: 'A24, Pixar'). Use lower() + LIKE.\n"
    "- production_countries (string): países de produção (ex: 'United States, New Zealand'). Diferente de origin_country (cultural). Use lower() + LIKE para coproduções.\n"
    "- spoken_languages (string): idiomas falados no título (ex: 'English, French'). Use lower() + LIKE.\n"
    "- actor_names (string): top 5 atores/atrizes (ex: 'Tom Hanks, Robin Wright'). Use lower() + LIKE.\n"
    "- director (string): diretor(es) (ex: 'Christopher Nolan'). Filmes e séries. Use lower() + LIKE.\n"
    "- screenplay (string): roteiristas/escritores (ex: 'Aaron Sorkin, Charlie Kaufman'). Filmes e séries. Use lower() + LIKE.\n"
    "- music_composer (string): compositor da trilha sonora (ex: 'Hans Zimmer, John Williams'). Filmes e séries. Use lower() + LIKE.\n"
    "- producer (string): produtor(es) e produtores executivos (ex: 'Kevin Feige, Jerry Bruckheimer'). Filmes e séries. Use lower() + LIKE.\n"
    "- cinematographer (string): diretor de fotografia (ex: 'Roger Deakins, Emmanuel Lubezki'). Filmes e séries. Use lower() + LIKE.\n"
    "- editor (string): montador(a) (ex: 'Thelma Schoonmaker, Lee Smith'). Filmes e séries. Use lower() + LIKE.\n"
    "- keywords_pt (string): tags temáticas em português (ex: 'viagem no tempo, distopia, baseado em romance'). Use lower() + LIKE.\n"
    "- certification (string): classificação indicativa BR (ex: 'L', '10', '12', '14', '16', '18'). Use = para valor exato.\n"
    "- trailer_url (string): link do trailer no YouTube. Não filtrar por este campo.\n"
    "- imdb_id (string): ID do IMDB (ex: 'tt0111161'). Não filtrar por este campo.\n"
    "- created_by (string): criadores de séries (ex: 'Vince Gilligan'). Apenas séries. Use lower() + LIKE.\n"
    "- networks (string): redes de TV originais (ex: 'HBO, Netflix'). Apenas séries. Use lower() + LIKE.\n"
    "- in_production (boolean): se a série ainda está em produção. Apenas séries.\n"
    "- last_air_date (string): data do último episódio exibido (séries). Formato 'YYYY-MM-DD'.\n"
    "- next_episode_air_date (string): data do próximo episódio agendado (séries). Formato 'YYYY-MM-DD'. NULL quando não há episódio futuro confirmado.\n"
    "- next_episode_number (int): número do próximo episódio agendado (séries).\n"
    "- next_episode_season_number (int): número da temporada do próximo episódio agendado (séries). Quando maior que number_of_seasons, indica temporada nova ainda não lançada.\n"
    "- tv_type (string): tipo de série ('Roteirizada', 'Reality Show', 'Documentário', 'Minissérie', 'Notícias', 'Talk Show', 'Vídeo'). Apenas séries.\n"
    "- streaming_providers (string): plataformas de streaming por assinatura no Brasil (ex: 'Netflix, Amazon Prime Video'). Use lower() + LIKE.\n"
    "- rent_buy_providers (string): plataformas de aluguel/compra no Brasil (ex: 'Apple TV, Google Play'). Use lower() + LIKE.\n"
    "- recommended_titles (string): títulos recomendados pelo TMDB (ex: 'Interstellar, The Prestige'). Use lower() + LIKE para encontrar títulos relacionados.\n"
    "- similar_titles (string): títulos similares pelo TMDB. Use lower() + LIKE.\n"
    "- alternative_titles (string): nomes alternativos/regionais do título. Use lower() + LIKE para buscar por nome em outro idioma.\n"
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
)

# System prompt enviado ao LLM no Passo 3. Pede um motivo curto por título, em
# JSON estruturado (menos tokens de completion do que prosa livre). O limite de
# ~90 caracteres mantém o bloco "reason" da UI compacto (card tem min-height/
# max-height de 3 linhas no desktop, com toggle "Ver mais"/"Ver menos" — ver
# principal.css/componentes.py) e controla o custo de tokens de completion.
_REASON_SYSTEM_PROMPT = (
    "Você é um curador de filmes e séries. "
    "Para cada título na lista, escreva um motivo curto (1-2 frases, no máximo "
    "~90 caracteres) explicando por que ele é uma boa recomendação para o "
    "pedido do usuário. "
    "Cite diretor, elenco, plataforma de streaming, classificação indicativa ou "
    "palavras-chave apenas quando fizerem parte do motivo real — não force menção "
    "a um campo que não tenha relação com o pedido. "
    "Retorne APENAS um JSON com a chave 'titles': uma lista de objetos com "
    "'id' (inteiro, índice do título na lista) e 'reason' (string em português). "
    "Não inclua texto fora do JSON."
)

# Palavras-chave SQL proibidas na cláusula WHERE gerada pelo LLM.
# O Athena é read-only por natureza, mas essa validação impede que o LLM
# gere cláusulas malformadas ou que fujam do escopo de um filtro SELECT.
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|GRANT|TRUNCATE|EXEC|MERGE|REPLACE|CALL)\b",
    re.IGNORECASE,
)


def _validate_where(where_clause: str) -> str:
    """Valida a cláusula WHERE gerada pelo LLM e retorna a string sanitizada.

    Raises:
        ValueError: se a cláusula contiver SQL proibido.
    """
    if ";" in where_clause:
        raise ValueError("Cláusula WHERE inválida: contém ';'")
    if _FORBIDDEN_KEYWORDS.search(where_clause):
        raise ValueError("Cláusula WHERE inválida: contém palavra SQL proibida")
    if re.search(r"\bSELECT\b", where_clause, re.IGNORECASE):
        raise ValueError("Cláusula WHERE inválida: contém subquery")
    return where_clause.strip()


# Regex para extrair de volta os valores de gênero/provedor que o LLM já filtrou na
# where_clause (_SYSTEM_PROMPT instrui sempre usar lower(genre_names) LIKE '%valor%' e
# lower(streaming_providers) LIKE '%valor%' para esses dois campos). Reaproveita uma
# decisão que o LLM já tomou no Passo 1 para priorizar as badges do card na Etapa 2.5,
# sem custo extra de tokens/chamadas de LLM.
_HIGHLIGHT_FIELD_PATTERNS = {
    "genres": re.compile(
        r"lower\s*\(\s*genre_names\s*\)\s*(?P<neg>NOT\s+)?LIKE\s*'(?P<val>[^']*)'",
        re.IGNORECASE,
    ),
    "providers": re.compile(
        r"lower\s*\(\s*streaming_providers\s*\)\s*(?P<neg>NOT\s+)?LIKE\s*'(?P<val>[^']*)'",
        re.IGNORECASE,
    ),
}


def _extract_highlighted_terms(where_clause: str) -> dict[str, list[str]]:
    """Extrai os termos de gênero/provedor que o LLM já filtrou na where_clause (Passo 1),
    usados para priorizar as badges correspondentes nos cards (ver componentes.py::_prioritize).

    Cláusulas NOT LIKE são ignoradas: significam que o usuário não quer aquele valor, então
    ele não deve ser destacado.
    """
    result: dict[str, list[str]] = {"genres": [], "providers": []}
    for key, pattern in _HIGHLIGHT_FIELD_PATTERNS.items():
        for match in pattern.finditer(where_clause):
            if match.group("neg"):
                continue
            term = match.group("val").strip("%").strip().lower()
            if term and term not in result[key]:
                result[key].append(term)
    return result


# ==============================================================================
# PASSO 2: Consulta real no Athena
# ==============================================================================

def search_titles_spec(where_clause: str, limit: int = 15) -> list[dict]:
    """
    Consulta a tabela SPEC no Athena e retorna os títulos que correspondem aos filtros.

    O LLM gera a cláusula WHERE livremente com base no schema da tabela. Sem filtro fixo de
    qualidade por vote_count — a relevância vem só do ORDER BY popularity DESC (que já
    naturalmente prioriza títulos com mais dados/reconhecimento) e do pool+sorteio abaixo.
    Isso também inclui títulos com air_date futuro (ainda não lançados, badge "Em breve" no
    card — ver render_card() em componentes.py), que nunca tiveram chance de acumular voto e
    antes ficavam de fora sem um bypass explícito no WHERE.

    Busca um pool de candidatos maior que `limit` (ordenado por popularidade,
    até _CANDIDATE_POOL_MAX) e sorteia um subconjunto de `limit` títulos desse
    pool, preservando a ordem de popularidade entre os escolhidos. Evita que a
    mesma pergunta (ou uma parecida) sempre retorne exatamente os mesmos
    títulos mais populares.

    Args:
        where_clause: Cláusula WHERE gerada pelo LLM (sem a palavra WHERE).
        limit:        Máximo de títulos retornados. Padrão 15.

    Returns:
        Lista de dicionários, cada um representando um título com todos os campos da SPEC.
    """
    limit = max(1, min(int(limit), 15))
    pool_size = min(limit * _CANDIDATE_POOL_MULTIPLIER, _CANDIDATE_POOL_MAX)
    where_clause = _validate_where(where_clause)

    sql = f"""
        SELECT title, media_type, year, air_date, genre_names, overview,
               vote_average, poster_url, backdrop_url,
               runtime_minutes, number_of_seasons,
               number_of_episodes, episode_runtime_minutes,
               next_episode_air_date, next_episode_number, next_episode_season_number,
               tagline, actor_names, director, screenplay, music_composer,
               producer, cinematographer, editor,
               keywords_pt, certification, trailer_url, collection_name,
               production_companies, production_countries, networks, created_by,
               streaming_providers, streaming_provider_logos,
               rent_buy_providers, rent_buy_provider_logos,
               recommended_titles, similar_titles, alternative_titles,
               in_theaters, theater_end_date
        FROM {os.getenv('SPEC_TABLE', 'tb_tmdb_discover_unified_prod')}
        WHERE {where_clause}
        ORDER BY popularity DESC
        LIMIT {pool_size}
    """

    athena = boto3.client("athena", region_name=os.getenv("AWS_REGION", "sa-east-1"))

    # Dispara a query no Athena
    exec_response = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": os.getenv("GLUE_DATABASE", "db_tmdb_unified_prod")},
        ResultConfiguration={"OutputLocation": os.getenv("ATHENA_S3_OUTPUT")},
    )
    execution_id = exec_response["QueryExecutionId"]

    # Aguarda a conclusão com polling de 1s fixo.
    # 1s é suficiente: queries do FilmBot levam ~2-5s no Athena (filtra poucos dados via WHERE).
    # Backoff progressivo não é necessário porque o custo de cada poll é mínimo (API leve).
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

    # Sorteia um subconjunto do pool para variar os títulos entre buscas
    # repetidas ou parecidas. Preserva a ordem por popularidade dentro do
    # subconjunto escolhido — não embaralha o resultado, só troca quais
    # títulos do pool aparecem a cada chamada.
    if len(records) > limit:
        chosen_indices = sorted(random.sample(range(len(records)), limit))
        records = [records[i] for i in chosen_indices]

    # Libera memória dos objetos de resposta do boto3 antes de passar ao LLM
    gc.collect()
    return records


def _audio_duration_seconds(audio_bytes: bytes) -> float:
    """Calcula a duração (em segundos) de um áudio WAV a partir dos bytes brutos.

    O st.audio_input do Streamlit sempre entrega áudio em WAV, então não é
    preciso detectar/converter formato — só ler os frames com o módulo padrão wave.
    """
    with wave.open(io.BytesIO(audio_bytes)) as wav_file:
        return wav_file.getnframes() / float(wav_file.getframerate())


def transcribe_preference(audio_bytes: bytes) -> str:
    """
    Transcreve um áudio gravado pelo usuário para texto em português, usando Whisper
    via litellm (modelo definido por TRANSCRIPTION_MODEL, padrão Groq Whisper Large v3
    Turbo — rápido e barato, com boa qualidade em pt-BR para preferências curtas).

    Uma falha aqui é tratada pelo chamador (app.py), que deixa o usuário digitar
    manualmente — a transcrição é uma conveniência opcional, nunca um bloqueio para
    usar o FilmBot.

    Args:
        audio_bytes: conteúdo binário do áudio gravado (WAV, entregue pelo
                     st.audio_input do Streamlit).

    Returns:
        Texto transcrito e sem espaços nas pontas. String vazia se nenhuma fala foi
        detectada (áudio silencioso/ruído) — o chamador deve distinguir esse caso
        (retorno "") de uma exceção (falha real na chamada ao provedor).

    Raises:
        AudioMuitoLongoError: se o áudio exceder _MAX_AUDIO_SECONDS — levantado antes
            de qualquer chamada à API, para não gastar crédito de transcrição à toa.
        ValueError: se TRANSCRIPTION_API_KEY/transcription_api_key não estiver configurada.
        openai.APIError (ou subclasse): se a chamada ao provedor de transcrição falhar
            (indisponibilidade, timeout, autenticação, formato de áudio inválido, etc.).
    """
    duration = _audio_duration_seconds(audio_bytes)
    # + tolerância (ver comentário em _AUDIO_DURATION_TOLERANCE_SECONDS): mesmo
    # motivo em app.py, na checagem que já deveria ter barrado isso antes
    # daqui — esta é só a rede de segurança redundante.
    if duration > _MAX_AUDIO_SECONDS + _AUDIO_DURATION_TOLERANCE_SECONDS:
        raise AudioMuitoLongoError(
            f"Áudio de {duration:.0f}s excede o limite de {_MAX_AUDIO_SECONDS}s."
        )

    if not _TRANSCRIPTION_API_KEY:
        raise ValueError(
            "TRANSCRIPTION_API_KEY não configurada — transcrição de áudio indisponível."
        )

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "preferencia.wav"  # litellm/OpenAI usam o nome para inferir o formato

    response = litellm.transcription(
        model=_TRANSCRIPTION_MODEL,
        file=audio_file,
        api_key=_TRANSCRIPTION_API_KEY,
        language="pt",
    )
    logger.info(
        "Transcrição de áudio concluída",
        extra={"model": _TRANSCRIPTION_MODEL, "audio_bytes": len(audio_bytes)},
    )
    return (getattr(response, "text", "") or "").strip()


def _call_llm_step1(preference: str) -> object:
    """Chama o LLM do Passo 1 (_LLM_MODEL) para gerar a cláusula WHERE via function calling."""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": preference},
    ]
    response = litellm.completion(
        model=_LLM_MODEL,
        api_key=_LLM_API_KEY,
        messages=messages,
        tools=[TOOL],
        num_retries=_LLM_NUM_RETRIES,
    )
    _log_token_usage("step1_where", response)
    return response


def _call_llm_step3(preference: str, titles_for_llm: list[dict]) -> object:
    """Chama o LLM do Passo 3 (_LLM_MODEL) para gerar o motivo de cada título encontrado."""
    titles_data = json.dumps(titles_for_llm, ensure_ascii=False, default=str)
    response = litellm.completion(
        model=_LLM_MODEL,
        api_key=_LLM_API_KEY,
        messages=[
            {"role": "system", "content": _REASON_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Pedido: {preference}\n\nTítulos encontrados:\n{titles_data}",
            },
        ],
        num_retries=_LLM_NUM_RETRIES,
    )
    _log_token_usage("step3_reasons", response)
    return response


# ==============================================================================
# PASSO 1 + 2 + 3: Orquestração do agente (função principal)
# ==============================================================================

def recommend(preference: str) -> list[dict]:
    """
    Orquestra os 3 passos do agente e retorna uma lista de recomendações.

    Esta é a única função chamada pelo app.py. Ela coordena todo o fluxo:
    LLM extrai filtros → Athena consulta → formatação Python → LLM gera motivos.

    Args:
        preference: Texto em linguagem natural do usuário.
                     Ex: "filmes de terror dos anos 2010"

    Returns:
        Lista de dicionários, cada um com: title, type, year, genres, overview,
        rating, poster_url, backdrop_url, duration, streaming_providers,
        streaming_provider_logos, rent_buy_providers, rent_buy_provider_logos,
        in_theaters, theater_end_date, next_episode_season_number, next_episode_number,
        next_episode_date, reason, highlighted_genres, highlighted_providers.
        Retorna lista vazia se nenhum título for encontrado ou o modelo não responder.
    """

    # ------------------------------------------------------------------
    # PASSO 1: LLM analisa o texto e decide os filtros SQL (com cache)
    # ------------------------------------------------------------------
    cached_args = _get_cached_where(preference)

    if cached_args is not None:
        args = cached_args
    else:
        response = _call_llm_step1(preference)

        # tool_calls[0]: o modelo pode chamar múltiplas tools, mas definimos apenas uma
        # function.arguments: string JSON com os argumentos que o LLM escolheu
        tool_calls = response.choices[0].message.tool_calls or []
        if not tool_calls:
            return []
        tool_call = tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        _save_cached_where(preference, args)

    # Reaproveita os termos de gênero/provedor que o próprio LLM já filtrou na where_clause
    # (cache-hit ou fresca — ambos convergem para o mesmo dict `args`) para priorizar as
    # badges correspondentes nos cards, sem chamada extra ao LLM.
    highlighted_terms = _extract_highlighted_terms(args.get("where_clause", ""))

    # ------------------------------------------------------------------
    # PASSO 2: Consulta o Athena com os filtros (do cache ou do LLM)
    # ------------------------------------------------------------------
    titles_from_spec = search_titles_spec(**args)

    if not titles_from_spec:
        return []  # nenhum título encontrado com esses filtros

    # Formata todos os campos determinísticos via Python (instantâneo)
    formatted_records = [format_record(r) for r in titles_from_spec]
    for record in formatted_records:
        record["highlighted_genres"] = highlighted_terms["genres"]
        record["highlighted_providers"] = highlighted_terms["providers"]

    # ------------------------------------------------------------------
    # PASSO 3: LLM gera apenas o "motivo" de cada recomendação
    # ------------------------------------------------------------------
    # Envia ao LLM só os campos que ajudam a justificar a recomendação — não o
    # registro inteiro (~35 campos). overview domina o tamanho do payload; os
    # demais são strings curtas que cobrem os critérios de filtro mais comuns
    # (diretor, elenco, streaming, classificação, palavras-chave) sem inflar
    # tokens de entrada com campos que não ajudam a explicar a recomendação
    # (produtoras, orçamento, títulos similares etc.).
    titles_for_llm = [
        {
            "id": i,
            "title": r.get("title", ""),
            "overview": r.get("overview", ""),
            "genre_names": r.get("genre_names", ""),
            "year": r.get("year", ""),
            "vote_average": r.get("vote_average", ""),
            "director": r.get("director", ""),
            "actor_names": r.get("actor_names", ""),
            "streaming_providers": r.get("streaming_providers", ""),
            "certification": r.get("certification", ""),
            "keywords_pt": r.get("keywords_pt", ""),
        }
        for i, r in enumerate(titles_from_spec)
    ]

    response = _call_llm_step3(preference, titles_for_llm)
    content = (response.choices[0].message.content or "").strip()

    # Remove blocos de código Markdown (```json ... ```) que o LLM às vezes
    # adiciona ao redor do JSON.
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    if not content:
        for record in formatted_records:
            record["reason"] = ""
        return formatted_records

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        for record in formatted_records:
            record["reason"] = ""
        return formatted_records

    reasons = data if isinstance(data, list) else data.get("titles", [])

    # Merge: adiciona o motivo do LLM ao registro já formatado pelo Python.
    # Tolerante a variações de resposta do LLM: aceita "id" como int ou string.
    reasons_by_id = {}
    for item in reasons:
        if "id" in item:
            try:
                reasons_by_id[int(item["id"])] = item.get("reason", "")
            except (ValueError, TypeError):
                continue
    for i, record in enumerate(formatted_records):
        record["reason"] = reasons_by_id.get(i, "")

    return formatted_records
