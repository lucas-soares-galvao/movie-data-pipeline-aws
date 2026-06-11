"""
utils.py — Funções Auxiliares da Lambda API

==============================================================================
POR QUE SEPARAR EM utils.py?
==============================================================================
O arquivo main.py cuida do "fluxo geral" (orquestração).
Este arquivo cuida dos "detalhes de implementação":
  - Como fazer uma requisição HTTP com retry
  - Como buscar uma senha no Secrets Manager
  - Como salvar um arquivo no S3
  - Como disparar um job Glue

Separar assim tem três vantagens:
1. Testabilidade: cada função pode ser testada isoladamente (mockar só o boto3)
2. Legibilidade: main.py fica limpo, utils.py tem os detalhes
3. Reutilização: funções como get_tmdb_api_key() são usadas por outros jobs também
"""

import json
import logging
import random
import time

import boto3
import requests
from requests.exceptions import ConnectionError, Timeout

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Máximo de páginas coletadas por ano da API TMDB.
# O TMDB suporta até 500 páginas, mas 100 (= 2.000 títulos) é suficiente
# para cobrir os lançamentos mais relevantes por ano sem exceder o timeout da Lambda.
MAX_PAGES = 100

# Códigos HTTP que indicam problema TEMPORÁRIO no servidor — vale tentar novamente.
# 429 = "Too Many Requests" (ultrapassou o rate limit da API)
# 5xx = erros internos do servidor TMDB (normalmente transitórios)
# Diferente de 401 (chave inválida) ou 404 (recurso não existe) — esses são erros
# permanentes que não melhoram com retry.
_TMDB_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _tmdb_get(url: str, params: dict, max_retries: int = 3) -> dict:
    """
    Executa uma requisição HTTP GET para a API do TMDB com retry automático.

    O QUE É RETRY COM BACKOFF EXPONENCIAL?
    Se a API retornar erro temporário (como rate limit), em vez de desistir
    imediatamente, a função tenta novamente após aguardar um tempo crescente:
    - 1ª falha: espera ~1 segundo
    - 2ª falha: espera ~2 segundos
    - 3ª falha: espera ~4 segundos (e lança exceção se ainda falhar)

    "Exponencial" porque o tempo dobra a cada tentativa: 2^0=1, 2^1=2, 2^2=4.
    O "+random.uniform(0,1)" adiciona um valor aleatório entre 0 e 1 segundo
    para evitar que múltiplos processos façam retry ao mesmo tempo (fenômeno
    chamado "thundering herd").

    Para erro 429 com cabeçalho "Retry-After", usa o tempo indicado pelo TMDB.

    Args:
        url:         URL completa do endpoint TMDB
        params:      Dicionário de parâmetros da query string
        max_retries: Número máximo de tentativas antes de lançar exceção

    Returns:
        Dicionário Python com o corpo da resposta JSON do TMDB
    """
    for attempt in range(max_retries):
        is_last_attempt = attempt == max_retries - 1
        try:
            # timeout=30 evita que a Lambda fique presa esperando por uma resposta
            # que nunca chega (servidor travado, rede lenta, etc.)
            response = requests.get(url, params=params, timeout=30)

            if response.status_code in _TMDB_TRANSIENT_STATUS:
                if is_last_attempt:
                    logger.error(
                        f"HTTP {response.status_code} após {max_retries} tentativas. "
                        f"Todas as tentativas esgotadas para {url}."
                    )
                    # raise_for_status() converte o código de erro HTTP em uma exceção Python.
                    # Ex: status 429 → lança requests.exceptions.HTTPError
                    response.raise_for_status()

                # Para 429, o TMDB informa no header Retry-After quantos segundos esperar.
                # Para outros erros transitórios, usa backoff exponencial calculado.
                if response.status_code == 429 and "Retry-After" in response.headers:
                    wait = int(response.headers["Retry-After"]) + random.uniform(0, 1)
                else:
                    wait = (2 ** attempt) + random.uniform(0, 1)

                logger.warning(
                    f"HTTP {response.status_code} (tentativa {attempt + 1}/{max_retries}). "
                    f"Aguardando {wait:.1f}s..."
                )
                time.sleep(wait)
                continue  # Volta ao início do loop para tentar novamente

            # Se o código HTTP não é transiente, lança exceção para qualquer erro 4xx/5xx.
            # Ex: 401 (API key inválida), 404 (endpoint não existe) → falha imediata.
            response.raise_for_status()
            return response.json()

        except (ConnectionError, Timeout) as e:
            # Erros de rede (sem conexão, timeout) também merecem retry.
            if is_last_attempt:
                logger.error(
                    f"Erro de conexão após {max_retries} tentativas: {e}. "
                    f"Todas as tentativas esgotadas para {url}."
                )
                raise
            wait = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(
                f"Erro de conexão (tentativa {attempt + 1}/{max_retries}): {e}. "
                f"Aguardando {wait:.1f}s..."
            )
            time.sleep(wait)


# ==============================================================================
# SECRETS MANAGER — Busca Segura de Credenciais
# ==============================================================================


def get_tmdb_api_key(secret_arn: str) -> str:
    """
    Busca a chave de API do TMDB armazenada no AWS Secrets Manager.

    POR QUE USAR SECRETS MANAGER EM VEZ DE VARIÁVEL DE AMBIENTE?
    Variáveis de ambiente podem ser lidas por qualquer pessoa com acesso ao console AWS.
    O Secrets Manager criptografa o valor e registra cada acesso em logs de auditoria.
    Além disso, a rotação automática de chaves é possível sem redeploy da Lambda.

    FORMATO DO SEGREDO:
    O segredo deve ser um JSON com a chave "tmdb_api_key":
    {"tmdb_api_key": "abc123xyz..."}

    Args:
        secret_arn: ARN completo do segredo. Ex: arn:aws:secretsmanager:sa-east-1:123456:secret:tmdb-key

    Returns:
        A chave de API do TMDB como string
    """
    client = boto3.client("secretsmanager")
    # get_secret_value retorna um dicionário; o valor está em "SecretString"
    response = client.get_secret_value(SecretId=secret_arn)
    # json.loads converte a string JSON em dicionário Python
    secret = json.loads(response["SecretString"])
    return secret["tmdb_api_key"]


# ==============================================================================
# API TMDB — Chamadas Paginadas (Discover)
# ==============================================================================


def fetch_tmdb_data(api_key: str, content_type: str, year: int, page: int) -> dict:
    """
    Busca UMA página de resultados da API TMDB (discover de filmes ou séries).

    O QUE É O ENDPOINT "DISCOVER"?
    O endpoint /discover permite filtrar títulos por múltiplos critérios.
    Aqui usamos: ordenado por popularidade decrescente, filtrado por ano.

    PAGINAÇÃO:
    O TMDB retorna 20 resultados por página. Para pegar mais, incrementamos a página.
    Cada chamada retorna "total_pages" para saber quando parar.

    PARÂMETROS ENVIADOS À API:
    - api_key:             Autenticação
    - language: "pt-BR"   Títulos e descrições em português do Brasil
    - sort_by:  "popularity.desc" → Mais populares primeiro
    - page:                Número da página solicitada
    - primary_release_year (movie) ou first_air_date_year (tv): Filtro por ano

    Args:
        api_key:      Chave de autenticação da API TMDB
        content_type: "movie" para filmes, "tv" para séries
        year:         Ano de lançamento para filtrar
        page:         Página a buscar (1 a 500 — limite do TMDB)

    Returns:
        Dicionário com: page, results (lista de 20 títulos), total_pages, total_results
    """
    if content_type == "movie":
        url = "https://api.themoviedb.org/3/discover/movie"
    else:
        url = "https://api.themoviedb.org/3/discover/tv"

    params = {
        "api_key": api_key,
        "language": "pt-BR",
        "sort_by": "popularity.desc",
        "page": page,
    }

    # O parâmetro de filtro por ano tem nome diferente para cada tipo de conteúdo:
    # filmes usam "primary_release_year", séries usam "first_air_date_year"
    if content_type == "movie":
        params["primary_release_year"] = year
    else:
        params["first_air_date_year"] = year

    return _tmdb_get(url, params)


# ==============================================================================
# S3 — Persistência de Dados Brutos
# ==============================================================================


def save_to_s3(s3_client, bucket: str, data: dict, s3_key: str) -> None:
    """
    Serializa um dicionário Python para JSON e salva no S3.

    POR QUE SALVAR CADA PÁGINA COMO UM ARQUIVO SEPARADO?
    1. Idempotência: se a Lambda falhar no meio, os arquivos já salvos não precisam
       ser coletados novamente — o reprocessamento recomeça de onde parou.
    2. Paralelismo: o Glue ETL pode processar múltiplos arquivos em paralelo.
    3. Rastreabilidade: é possível inspecionar cada página individualmente para debug.

    Args:
        s3_client: Cliente boto3 já instanciado (evita criar nova conexão a cada chamada)
        bucket:    Nome do bucket S3 destino (ex: "lsg-sa-east-1-bucket-sor-prod")
        data:      Dados Python a serializar (dict ou list)
        s3_key:    Caminho do arquivo no bucket (ex: "tmdb/discover/movie/ano=2024/pagina_001.json")
    """
    # ensure_ascii=False preserva caracteres UTF-8 como acentos (ã, é, ç)
    # sem isso, "Ação" seria salvo como "ção" — ilegível para humanos
    body = json.dumps(data, ensure_ascii=False)

    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(f"Arquivo salvo: s3://{bucket}/{s3_key}")


# ==============================================================================
# GLUE ETL — Disparo de Jobs de Processamento
# ==============================================================================


def trigger_glue_job(
    glue_client,
    job_name: str,
    glue_catalog_args: dict,
    table_type: str,
    table_name: str,
    year: int = None,
    end_year: int = None,
) -> str:
    """
    Inicia uma execução do job Glue ETL com os argumentos dinâmicos desta coleta.

    COMO FUNCIONA O DISPARO DO GLUE?
    start_job_run() chama o Glue para iniciar o job em segundo plano.
    A Lambda NÃO espera o job terminar — ela dispara e continua para o próximo ano.
    Isso permite paralelismo: múltiplas execuções do Glue ETL rodando ao mesmo tempo
    (uma para cada ano coletado), cada uma com seus próprios argumentos.

    TIPOS DE TABELA (table_type):
    - "genre"            → Processa tabela de gêneros (sem partição por ano)
    - "configuration"    → Processa tabela de idiomas/países (sem partição por ano)
    - "watch_providers_ref" → Processa lista de plataformas (sem partição por ano)
    - "discover"         → Processa lista de títulos do ano (particionado por ano)

    O job Glue usa o TABLE_TYPE para saber: como ler os dados, como estruturar
    o Parquet, quais colunas são chave de partição, e se deve disparar jobs downstream.

    Args:
        glue_client:       Cliente boto3 do Glue (compartilhado entre chamadas)
        job_name:          Nome do job registrado na AWS (ex: "glue-etl-prod")
        glue_catalog_args: Dict com MEDIA_TYPE, DATABASE, DATABASE_UNIFIED
        table_type:        "genre", "configuration", "watch_providers_ref" ou "discover"
        table_name:        Nome da tabela no Glue Catalog para registrar os dados
        year:              Ano dos dados (apenas para discover)
        end_year:          Último ano do ciclo (para o Details saber quando disparar o AGG)

    Returns:
        JobRunId: ID único desta execução (útil para consultar status no console AWS)
    """
    # O Glue exige que argumentos customizados tenham o prefixo "--"
    # Ex: "--TABLE_TYPE": "discover" → no job Python: getResolvedOptions(args, ["TABLE_TYPE"])
    arguments = {
        "--TABLE_TYPE": table_type,
        "--TABLE_NAME": table_name,
    }

    # Argumentos opcionais — só adicionados quando relevantes
    if year is not None:
        arguments["--YEAR"] = str(year)
    if end_year is not None:
        arguments["--END_YEAR"] = str(end_year)

    # Adiciona os argumentos base (MEDIA_TYPE, DATABASE, etc.) com prefixo "--"
    for key, value in glue_catalog_args.items():
        arguments[f"--{key.upper()}"] = str(value)

    response = glue_client.start_job_run(
        JobName=job_name,
        Arguments=arguments,
    )
    run_id = response["JobRunId"]

    if year is not None:
        logger.info(
            f"Job Glue '{job_name}' iniciado para '{table_type}' do ano {year}. RunId: {run_id}"
        )
    else:
        logger.info(
            f"Job Glue '{job_name}' iniciado para '{table_type}'. RunId: {run_id}"
        )
    return run_id


# ==============================================================================
# API TMDB — Dados de Referência (sem paginação)
# ==============================================================================


def fetch_tmdb_reference(api_key: str, endpoint: str, params: dict = None) -> dict:
    """
    Busca dados de referência do TMDB — endpoints que retornam lista simples, sem paginação.

    Usado para:
    - /genre/movie/list      → Lista de gêneros de filmes
    - /genre/tv/list         → Lista de gêneros de séries
    - /configuration/languages → Lista de idiomas suportados
    - /configuration/countries → Lista de países suportados
    - /watch/providers/movie → Lista de plataformas de streaming para filmes

    Diferente do discover (que pagina), esses endpoints retornam tudo de uma vez.

    Args:
        api_key:  Chave de API TMDB
        endpoint: Caminho a partir da base URL (ex: "/genre/movie/list")
        params:   Parâmetros opcionais (ex: {"language": "pt-BR"})

    Returns:
        Dicionário com o corpo da resposta JSON
    """
    base_url = "https://api.themoviedb.org/3"
    url = f"{base_url}{endpoint}"

    query = {"api_key": api_key}
    if params:
        # dict.update() mescla os parâmetros extras com o api_key
        query.update(params)

    return _tmdb_get(url, query)


def collect_genre_data(api_key: str, s3_client, bucket: str, content_type: str) -> None:
    """
    Coleta a lista completa de gêneros do TMDB e salva no S3.

    EXEMPLO DE DADO RETORNADO:
    [{"id": 28, "name": "Ação"}, {"id": 12, "name": "Aventura"}, ...]

    Este dado é uma tabela de referência estática — usada para enriquecer
    os títulos do discover com os nomes dos gêneros (o discover só retorna IDs).

    Mapeamento de endpoint por tipo:
    - movie → /genre/movie/list → tmdb/genre/movie/generos_filmes.json
    - tv    → /genre/tv/list   → tmdb/genre/tv/generos_series.json
    """
    if content_type == "movie":
        logger.info("Coletando referência: /genre/movie/list")
        data = fetch_tmdb_reference(api_key, "/genre/movie/list", {"language": "pt-BR"})
        save_to_s3(
            s3_client, bucket, data["genres"], "tmdb/genre/movie/generos_filmes.json"
        )
    else:
        logger.info("Coletando referência: /genre/tv/list")
        data = fetch_tmdb_reference(api_key, "/genre/tv/list", {"language": "pt-BR"})
        save_to_s3(
            s3_client, bucket, data["genres"], "tmdb/genre/tv/generos_series.json"
        )


def collect_configuration_data(
    api_key: str, s3_client, bucket: str, content_type: str
) -> None:
    """
    Coleta dados de configuração do TMDB (idiomas para filmes, países para séries).

    EXEMPLO DE DADO DE IDIOMAS:
    [{"iso_639_1": "pt", "english_name": "Portuguese", "name": "Português"}, ...]

    EXEMPLO DE DADO DE PAÍSES:
    [{"iso_3166_1": "BR", "english_name": "Brazil", "native_name": "Brasil"}, ...]

    Esses dados são usados para traduzir códigos de idioma/país em nomes legíveis
    na camada de agregação (Glue AGG).

    Mapeamento:
    - movie → /configuration/languages → tmdb/configuration/languages/idiomas.json
    - tv    → /configuration/countries → tmdb/configuration/countries/paises.json
    """
    if content_type == "movie":
        logger.info("Coletando referência: /configuration/languages")
        data = fetch_tmdb_reference(api_key, "/configuration/languages")
        save_to_s3(s3_client, bucket, data, "tmdb/configuration/languages/idiomas.json")
    else:
        logger.info("Coletando referência: /configuration/countries")
        data = fetch_tmdb_reference(
            api_key, "/configuration/countries", {"language": "pt-BR"}
        )
        save_to_s3(s3_client, bucket, data, "tmdb/configuration/countries/paises.json")


def collect_watch_providers_ref(
    api_key: str, s3_client, bucket: str, content_type: str
) -> None:
    """
    Coleta a lista de plataformas de streaming disponíveis no Brasil (BR).

    EXEMPLO DE DADO RETORNADO (após extração):
    [
      {"provider_id": 8,   "provider_name": "Netflix",      "display_priority_br": 1},
      {"provider_id": 119, "provider_name": "Amazon Prime", "display_priority_br": 2},
      ...
    ]

    "display_priority_br" indica a ordem de exibição no Brasil:
    menor número = plataforma mais relevante/popular no Brasil.

    Esta tabela de referência é cruzada com os dados de watch_providers dos títulos
    para exibir os nomes das plataformas (Netflix, Prime) em vez de só IDs numéricos.

    Mapeamento:
    - movie → /watch/providers/movie → tmdb/watch_providers_ref/movie/watch_providers_ref.json
    - tv    → /watch/providers/tv   → tmdb/watch_providers_ref/tv/watch_providers_ref.json
    """
    logger.info(f"Coletando referência: /watch/providers/{content_type}")
    data = fetch_tmdb_reference(
        api_key,
        f"/watch/providers/{content_type}",
        {"watch_region": "BR"},  # Filtra apenas plataformas disponíveis no Brasil
    )

    # Extrai apenas os campos necessários de cada plataforma
    # "p.get(campo)" é equivalente a p[campo] mas retorna None em vez de KeyError se não existir
    providers = [
        {
            "provider_id":         p["provider_id"],
            "provider_name":       p["provider_name"],
            "logo_path":           p.get("logo_path"),
            "display_priority_br": p.get("display_priorities", {}).get("BR"),
        }
        for p in data.get("results", [])
    ]

    s3_key = f"tmdb/watch_providers_ref/{content_type}/watch_providers_ref.json"
    save_to_s3(s3_client, bucket, providers, s3_key)


# ==============================================================================
# COLETA DE DISCOVER — Paginação Completa por Ano
# ==============================================================================


def collect_discover_data(
    api_key: str, s3_client, bucket: str, content_type: str, folder: str, year: int
) -> None:
    """
    Coleta TODAS as páginas disponíveis de discover para um ano específico.

    ESTRATÉGIA DE PAGINAÇÃO:
    1. Solicita a página 1
    2. O TMDB retorna "total_pages" no response
    3. Se a página atual é maior que total_pages, para
    4. Caso contrário, solicita a próxima página
    5. Repete até MAX_PAGES (100) ou até não haver mais páginas

    EXEMPLO DE ARQUIVOS GERADOS NO S3:
    tmdb/discover/movie/ano=2024/pagina_001.json  ← 20 filmes
    tmdb/discover/movie/ano=2024/pagina_002.json  ← próximos 20 filmes
    ...
    tmdb/discover/movie/ano=2024/pagina_087.json  ← últimos filmes de 2024

    O formato "pagina_{page:03d}" garante ordenação correta no S3:
    "pagina_001" < "pagina_002" < ... < "pagina_100" (padding com zeros)

    Args:
        api_key:       Chave de API TMDB
        s3_client:     Cliente boto3 S3
        bucket:        Nome do bucket SOR
        content_type:  "movie" ou "tv"
        folder:        Pasta base no S3 (ex: "tmdb/discover/movie")
        year:          Ano de lançamento/estreia para filtrar
    """
    logger.info(f"Coletando {folder} do ano {year}...")

    for page in range(1, MAX_PAGES + 1):
        data = fetch_tmdb_data(api_key, content_type, year, page)

        # total_pages informa quantas páginas realmente existem para este filtro.
        # Ex: filmes de 2024 podem ter 250 páginas; filmes de 1950 podem ter apenas 5.
        total_pages = data.get("total_pages", 0)
        if page > total_pages:
            logger.info(
                f"{folder}/{year}: {total_pages} página(s) disponível(is). Encerrando na página {page - 1}."
            )
            break

        # Salva apenas o array "results" (lista de títulos), descartando metadados de paginação.
        # O Glue ETL não precisa saber que eram 50 páginas totais — ele só precisa dos títulos.
        s3_key = f"{folder}/ano={year}/pagina_{page:03d}.json"
        save_to_s3(s3_client, bucket, data["results"], s3_key)
