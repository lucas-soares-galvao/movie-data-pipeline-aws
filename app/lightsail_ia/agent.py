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

  FORMATAÇÃO — Registros formatados pelo Python (formatacao.py):
    Após o Athena retornar os títulos, funções em formatacao.py convertem
    cada registro em campos prontos para o card da interface.

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

VARIÁVEIS OPCIONAIS — fallback automático de LLM:
  LLM_MODEL_FALLBACK → modelo Bedrock usado quando a chamada ao LLM_MODEL falhar
                        por erro de infraestrutura (timeout, 5xx, rate limit,
                        autenticação). Indefinida por padrão = fallback desativado
                        (comportamento atual). Ex: "bedrock/openai.gpt-oss-20b"
  AWS_REGION_BEDROCK → região AWS usada na chamada de fallback (padrão: "us-east-1").
                        Não reaproveita AWS_REGION porque essa fica fixa em
                        "sa-east-1" para Athena/Glue/Secrets Manager.

VARIÁVEIS OPCIONAIS — transcrição de áudio (entrada alternativa por voz):
  TRANSCRIPTION_API_KEY → fallback para dev local (usado quando FILMBOT_SECRET_ARN não
                        está definida; em produção, vem do campo transcription_api_key
                        no secret). Indefinida = transcrição de áudio indisponível
                        (o campo de texto continua funcionando normalmente).
  TRANSCRIPTION_MODEL → modelo de transcrição a usar via litellm
                        (padrão: "groq/whisper-large-v3-turbo")
"""

import gc
import io
import os
import re
import json
import time
import wave
import logging
import hashlib
import boto3
import litellm
import openai
from dotenv import load_dotenv
from formatacao import format_record

# Carrega as variáveis de ambiente do arquivo .env (na mesma pasta do app).
# No ambiente de produção (Lightsail), o .env é criado pelo script de deploy
# com as variáveis do Terraform output. Em desenvolvimento, o .env é criado manualmente.
load_dotenv()

_LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash")
_LLM_MODEL_FALLBACK = os.getenv("LLM_MODEL_FALLBACK")
_AWS_REGION_BEDROCK = os.getenv("AWS_REGION_BEDROCK", "us-east-1")
_TRANSCRIPTION_MODEL = os.getenv("TRANSCRIPTION_MODEL", "groq/whisper-large-v3-turbo")
_MAX_AUDIO_SECONDS = 20


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


def _log_token_usage(step: str, response: object, model: str | None = None) -> None:
    """Registra no log o consumo de tokens (prompt, completion, total) de uma chamada LLM.

    Args:
        model: modelo que efetivamente respondeu. Default None loga _LLM_MODEL
                (chamada primária); a chamada de fallback passa o modelo real usado.
    """
    usage = getattr(response, "usage", None)
    if not usage:
        return
    logger.info(
        "LLM token usage",
        extra={
            "step": step,
            "model": model or _LLM_MODEL,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    )


def _log_llm_fallback(preference: str, error: Exception) -> None:
    """Registra em WARNING que o fallback de LLM foi acionado (chamada primária falhou).

    Log dedicado (além de _log_token_usage com step="step1_where_fallback") para que
    o acionamento do fallback fique visível mesmo se a chamada de fallback também falhar.
    """
    logger.warning(
        "Fallback de LLM acionado",
        extra={
            "preference": preference,
            "primary_model": _LLM_MODEL,
            "fallback_model": _LLM_MODEL_FALLBACK,
            "error": f"{type(error).__name__}: {error}",
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
                    "description": "Quantidade máxima de resultados (padrão 10, máximo 10)",
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
    "- vote_count (int): número de votos (filtro fixo >= 50 já aplicado; use para exigir mais votos)\n"
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


# ==============================================================================
# PASSO 2: Consulta real no Athena
# ==============================================================================

def search_titles_spec(where_clause: str, limit: int = 10) -> list[dict]:
    """
    Consulta a tabela SPEC no Athena e retorna os títulos que correspondem aos filtros.

    O LLM gera a cláusula WHERE livremente com base no schema da tabela.
    O filtro fixo vote_count >= 50 é sempre aplicado automaticamente para
    garantir qualidade dos dados (exclui títulos com poucos votos).

    Args:
        where_clause: Cláusula WHERE gerada pelo LLM (sem a palavra WHERE).
        limit:        Máximo de títulos retornados. Padrão 10.

    Returns:
        Lista de dicionários, cada um representando um título com todos os campos da SPEC.
    """
    limit = max(1, min(int(limit), 10))
    where_clause = _validate_where(where_clause)

    sql = f"""
        SELECT title, media_type, year, air_date, genre_names, overview,
               vote_average, poster_url, backdrop_url,
               runtime_minutes, number_of_seasons,
               number_of_episodes, episode_runtime_minutes,
               tagline, actor_names, director, screenplay, music_composer,
               producer, cinematographer, editor,
               keywords_pt, certification, trailer_url, collection_name,
               production_companies, production_countries, networks, created_by,
               streaming_providers, rent_buy_providers,
               recommended_titles, similar_titles, alternative_titles,
               in_theaters, theater_end_date
        FROM {os.getenv('SPEC_TABLE', 'tb_tmdb_discover_unified_prod')}
        WHERE vote_count >= 50 AND {where_clause}
        ORDER BY popularity DESC
        LIMIT {int(limit)}
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

    Diferente de _call_llm_step1(), não tem fallback automático de modelo: uma falha
    aqui é tratada pelo chamador (app.py), que deixa o usuário digitar manualmente —
    a transcrição é uma conveniência opcional, nunca um bloqueio para usar o FilmBot.

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
    if duration > _MAX_AUDIO_SECONDS:
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
    """Chama o LLM do Passo 1. Se a chamada primária (_LLM_MODEL) falhar por erro de
    infraestrutura (timeout, 5xx, rate limit, autenticação — openai.APIError e
    subclasses, que é a classe-base real usada pelo litellm para erros de provedor;
    litellm.exceptions.APIError NÃO é essa base, apesar do nome parecido) e
    LLM_MODEL_FALLBACK estiver configurada, tenta uma vez com o modelo de fallback
    (ex: um modelo Bedrock, autenticado via credenciais AWS do IAM user do agente).

    NÃO intercepta ValueError/json.JSONDecodeError — essas ocorrem depois desta função
    retornar (parsing dos tool_calls, em recommend()), então uma resposta primária
    malformada continua se comportando como hoje (propaga o erro), sem acionar fallback.

    Raises:
        openai.APIError (ou subclasse): se a chamada primária falhar sem fallback
            configurado, ou se a chamada de fallback também falhar.
    """
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": preference},
    ]
    try:
        response = litellm.completion(
            model=_LLM_MODEL,
            api_key=_LLM_API_KEY,
            messages=messages,
            tools=[TOOL],
        )
        _log_token_usage("step1_where", response, _LLM_MODEL)
        return response
    except openai.APIError as error:
        if not _LLM_MODEL_FALLBACK:
            raise
        _log_llm_fallback(preference, error)
        response = litellm.completion(
            model=_LLM_MODEL_FALLBACK,
            messages=messages,
            tools=[TOOL],
            aws_region_name=_AWS_REGION_BEDROCK,
        )
        _log_token_usage("step1_where_fallback", response, _LLM_MODEL_FALLBACK)
        return response


# ==============================================================================
# PASSO 1 + 2 + formatação: Orquestração do agente (função principal)
# ==============================================================================

def recommend(preference: str) -> list[dict]:
    """
    Orquestra os 2 passos do agente e retorna uma lista de recomendações.

    Esta é a única função chamada pelo app.py. Ela coordena todo o fluxo:
    LLM extrai filtros → Athena consulta → formatação Python.

    Args:
        preference: Texto em linguagem natural do usuário.
                     Ex: "filmes de terror dos anos 2010"

    Returns:
        Lista de dicionários, cada um com: title, type, year, genres, overview,
        rating, poster_url, backdrop_url, duration, streaming_providers,
        in_theaters, theater_end_date.
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

    # ------------------------------------------------------------------
    # PASSO 2: Consulta o Athena com os filtros (do cache ou do LLM)
    # ------------------------------------------------------------------
    titles_from_spec = search_titles_spec(**args)

    if not titles_from_spec:
        return []  # nenhum título encontrado com esses filtros

    # Formata todos os campos determinísticos via Python (instantâneo)
    return [format_record(r) for r in titles_from_spec]
