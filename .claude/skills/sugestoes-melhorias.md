# Skill: Sugestões de Melhorias — proj-eng-dados-filmes-aws

> **Contexto base:** Leia também as skills `estrutura-projeto` e `projeto-filmes-aws` para ter o mapa completo do projeto antes de sugerir qualquer melhoria.

Você atua como um **engenheiro de dados sênior revisando o projeto de um estudante**. Seu objetivo é sugerir melhorias práticas, com exemplos de código direto ao ponto, explicando **por que** cada mudança importa em linguagem simples. Nunca sugira algo que aumente a complexidade sem um ganho claro e compreensível.

---

## Princípios para sugestões neste projeto

1. **Clareza antes de elegância** — o estudante precisa entender o código de ponta a ponta.
2. **Uma coisa de cada vez** — sugerir muitas mudanças juntas paralisa quem está aprendendo.
3. **Mostre o antes e o depois** — sempre apresente o trecho atual e o trecho melhorado.
4. **Explique o "por quê"** — nunca sugira uma mudança sem explicar o problema que ela resolve.
5. **Respeite o que já existe** — o projeto já tem boas práticas (OIDC, mínimo privilégio, quality gates). Destaque isso antes de criticar.

---

## Melhorias em `app/`

### 1. Logging estruturado em vez de `print`

**Problema:** O código usa `print()` para registrar progresso. Em produção na AWS, `print` vai para CloudWatch Logs, mas sem nível de severidade, fica difícil filtrar erros de informações.

**Antes** (`app/glue_etl/src/utils.py`):
```python
print(f"Processed table={table}, partitions={partitions}")
```

**Depois:**
```python
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

logger.info("Tabela processada: table=%s, partitions=%s", table, partitions)
```

**Por quê importa:** Com `logging`, você pode filtrar só erros (`logger.error`) no CloudWatch sem ver todas as mensagens de informação. É a forma padrão usada em projetos reais.

---

### 2. Type hints nas funções

**Problema:** As funções em `src/utils.py` não têm anotações de tipo, o que dificulta entender o que entra e o que sai de cada função.

**Antes** (`app/lambda_api/src/utils.py`):
```python
def get_tmdb_key(secret_arn):
    ...

def generate_monthly_periods(start_year):
    ...
```

**Depois:**
```python
def get_tmdb_key(secret_arn: str) -> str:
    ...

def generate_monthly_periods(start_year: int) -> list[dict]:
    ...
```

**Por quê importa:** Type hints são lidos pelo `mypy` (já configurado no pipeline) e pelo próprio IDE para alertar sobre erros antes de rodar o código. São um forma de documentação que nunca fica desatualizada.

---

### 3. Constante para a URL base da API TMDB

**Problema:** A URL `https://api.themoviedb.org/3/` aparece repetida em três funções diferentes de `lambda_api/src/utils.py`. Se a URL mudar, você precisa alterar em vários lugares.

**Antes:**
```python
def fetch_discover(api_key, period, media_type="movie", max_pages=5):
    url = f"https://api.themoviedb.org/3/discover/{media_type}"
    ...

def fetch_genres(api_key, media_type="movie"):
    url = f"https://api.themoviedb.org/3/genre/{media_type}/list"
    ...
```

**Depois:**
```python
TMDB_BASE_URL = "https://api.themoviedb.org/3"

def fetch_discover(api_key, period, media_type="movie", max_pages=5):
    url = f"{TMDB_BASE_URL}/discover/{media_type}"
    ...

def fetch_genres(api_key, media_type="movie"):
    url = f"{TMDB_BASE_URL}/genre/{media_type}/list"
    ...
```

**Por quê importa:** Constantes no topo do arquivo tornam o código mais fácil de manter. Se a URL mudar, você muda em um só lugar.

---

### 4. Logging de erro explícito na Lambda

**Problema:** Em `lambda_api/main.py`, quando ocorre um `ValueError`, o erro é retornado no corpo da resposta mas não é registrado no CloudWatch como erro.

**Antes:**
```python
    except ValueError as error:
        return {
            "statusCode": 400,
            "body": {"error": str(error)}
        }
```

**Depois:**
```python
import logging
logger = logging.getLogger(__name__)

    except ValueError as error:
        logger.error("Tipo de mídia inválido no evento: %s", error)
        return {
            "statusCode": 400,
            "body": {"error": str(error)}
        }
```

**Por quê importa:** Sem o `logger.error`, o CloudWatch Alarm de erro da Lambda não detecta esse problema — ele só vê um retorno 400, não uma exceção. Com o log de erro, você consegue criar alarmes baseados em padrões de log.

---

### 5. Separar rulesets por arquivo quando crescer

**Problema atual (ainda não é urgente):** `rulesets_dq.py` tem todos os rulesets em um único dicionário. Quando o projeto crescer (mais tabelas, mais regras), o arquivo vai ficar longo.

**Sugestão para o futuro:** Quando passar de 10 tabelas, considere separar por domínio:
```
src/
├── rulesets/
│   ├── __init__.py        # importa tudo e monta o dict final
│   ├── rulesets_movie.py  # regras de filmes
│   └── rulesets_tv.py     # regras de séries
```

**Por enquanto:** O arquivo atual está adequado para o tamanho do projeto. Não mude antes de precisar.

---

## Melhorias em `infra/`

### 6. Tags nos recursos AWS

**Problema:** Os recursos criados pelo Terraform (S3, Lambda, Glue) não têm tags. Sem tags, é difícil saber quanto cada projeto custa na conta AWS e quem criou cada recurso.

**Onde adicionar** (`infra/locals.tf`):
```hcl
locals {
  common_tags = {
    Project     = "proj-eng-dados-filmes-aws"
    Environment = var.env
    ManagedBy   = "Terraform"
  }
}
```

**Como usar em cada recurso** (ex: `infra/s3.tf`):
```hcl
resource "aws_s3_bucket" "sor" {
  bucket = local.envs.s3_bucket_sor
  tags   = local.common_tags
}
```

**Por quê importa:** Tags são a forma mais simples de controlar custos na AWS. No console de billing você consegue filtrar por `Project = proj-eng-dados-filmes-aws` e ver exatamente quanto esse projeto está custando.

---

### 7. Timeout e número de workers no Glue Job

**Problema:** Glue Jobs sem timeout podem rodar indefinidamente em caso de bug, gerando custo inesperado.

**Onde adicionar** (`infra/glue_etl.tf` e `infra/glue_data_quality.tf`):
```hcl
resource "aws_glue_job" "etl" {
  name     = local.envs.glue_etl_job_name
  timeout  = 30    # minutos — mata o job se passar disso
  
  number_of_workers = 2   # mínimo para G.1X
  worker_type       = "G.1X"
  ...
}
```

**Por quê importa:** Um Glue Job travado sem timeout pode rodar por horas gerando cobranças. Para um projeto pessoal de estudante, isso pode resultar em uma conta AWS inesperada.

---

### 8. Lifecycle rule no S3 para dados antigos

**Problema:** O bucket SOR acumula JSONs brutos da TMDB indefinidamente. Dados com mais de 90 dias raramente precisam ser reprocessados.

**Onde adicionar** (`infra/s3.tf`):
```hcl
resource "aws_s3_bucket_lifecycle_configuration" "sor_lifecycle" {
  bucket = aws_s3_bucket.sor.id

  rule {
    id     = "expire-old-raw-data"
    status = "Enabled"

    filter {
      prefix = "tmdb/"
    }

    expiration {
      days = 90
    }
  }
}
```

**Por quê importa:** Armazenamento S3 é cobrado por GB. Dados que não serão mais usados só geram custo. Para um projeto pessoal, 90 dias é um horizonte seguro — o pipeline sempre pode rebuscar da API se precisar.

---

### 9. Variável de timeout da Lambda

**Problema:** O timeout da Lambda está provavelmente hardcoded ou no default (3 segundos). Para uma Lambda que chama a API do TMDB e depois dispara múltiplos Glue Jobs, 3 segundos é insuficiente.

**Onde configurar** (`infra/variables.tf`):
```hcl
variable "lambda_timeout" {
  description = "Timeout da Lambda em segundos (máximo: 900)"
  type        = number
  default     = 300
}
```

**E em** `infra/lambda_api.tf`:
```hcl
resource "aws_lambda_function" "api" {
  timeout = var.lambda_timeout
  ...
}
```

**Por quê importa:** Se a Lambda atingir o timeout no meio da execução, os dados ficam parcialmente salvos no S3 sem o Glue ETL ter sido disparado — uma inconsistência silenciosa difícil de debugar.

---

## Melhorias em `test/`

### 10. Testar com os dois tipos de mídia (`movie` e `tv`)

**Problema:** Muitos testes provavelmente testam apenas `movie`. Como a lógica é a mesma para `tv` (com campos diferentes), um bug específico de `tv` pode passar despercebido.

**Antes** (exemplo em `test/lambda_api/test_utils.py`):
```python
def test_extract_media_tables_movie(self):
    event = {"type": "movie", "database": "db_tmdb", ...}
    result = extract_media_tables(event)
    self.assertEqual(result["media_type"], "movie")
```

**Depois (com parametrize):**
```python
import pytest

@pytest.mark.parametrize("media_type,expected_discover", [
    ("movie", "table_discover_movie"),
    ("tv",    "table_discover_tv"),
])
def test_extract_media_tables(media_type, expected_discover):
    event = {"type": media_type, "database": "db_tmdb", expected_discover: "tb_discover"}
    result = extract_media_tables(event)
    assert result["media_type"] == media_type
```

**Por quê importa:** `@pytest.mark.parametrize` executa o mesmo teste com valores diferentes automaticamente. É a forma mais simples de garantir que a lógica funciona para todos os cenários sem duplicar código de teste.

---

### 11. Testar o caminho de erro explicitamente

**Problema:** Os testes provavelmente cobrem o caminho feliz (dados válidos), mas não o caminho de erro (tipo de mídia inválido, API retornando 500, etc.).

**Sugestão** (`test/lambda_api/test_utils.py`):
```python
def test_extract_media_tables_tipo_invalido(self):
    event = {"type": "anime", "database": "db_tmdb"}
    with self.assertRaises(ValueError) as ctx:
        extract_media_tables(event)
    self.assertIn("anime", str(ctx.exception))
```

**E para a retry da API** (`test/lambda_api/test_utils.py`):
```python
@patch("src.utils.requests.get")
def test_request_retry_em_erro_500(self, mock_get):
    mock_get.side_effect = [
        requests.exceptions.HTTPError(response=Mock(status_code=500)),
        requests.exceptions.HTTPError(response=Mock(status_code=500)),
        Mock(status_code=200, json=lambda: {"results": [{"id": 1}]}),
    ]
    result = _request_json_with_retry("http://...", params={})
    self.assertEqual(mock_get.call_count, 3)
```

**Por quê importa:** Testar erros é tão importante quanto testar o sucesso. Em produção, a API do TMDB pode retornar 500 esporadicamente — garantir que o retry funciona dá confiança de que o pipeline vai se recuperar sozinho.

---

### 12. Verificar que todos os rulesets cobrem todas as tabelas do Catalog

**Problema:** `rulesets_dq.py` define regras para cada tabela pelo nome. Se uma nova tabela for criada no Glue Catalog mas esquecer de adicionar o ruleset, o job de DQ vai usar apenas `RowCount > 0` sem avisar.

**Sugestão** (`test/glue_data_quality/test_rulesets_dq.py`):
```python
ALL_CATALOG_TABLES = [
    "tb_discover_movie_tmdb",
    "tb_discover_tv_tmdb",
    "tb_genre_movie_tmdb",
    "tb_genre_tv_tmdb",
    "tb_configuration_languages_tmdb",
    "tb_configuration_countries_tmdb",
]

def test_todas_as_tabelas_tem_ruleset():
    for table in ALL_CATALOG_TABLES:
        assert table in rulesets_dq, f"Tabela '{table}' não tem ruleset definido"
        assert len(rulesets_dq[table]) > 0, f"Ruleset de '{table}' está vazio"
```

**Por quê importa:** Este teste funciona como um contrato: se alguém adicionar uma tabela nova no Catalog sem adicionar o ruleset, o pipeline de testes vai falhar e alertar antes de chegar em produção.

---

## O que NÃO mudar (e por quê)

| O que está bem | Por quê não mudar |
|----------------|-------------------|
| `main.py` delega para `src/utils.py` | Separação clara entre entrada e lógica — padrão correto |
| Autenticação OIDC no CI/CD | Mais seguro que Access Keys — não simplifique isso |
| Backend S3 separado por ambiente | Isolamento real entre dev e prod — não use workspaces |
| `destroy_config.json` como flag | Simples e explícito — não crie lógica complexa aqui |
| `conftest.py` por módulo de teste | Fixtures organizadas por contexto — mantenha assim |
| Timeout de retry com `2 ** attempt` | Backoff exponencial correto para APIs externas |

---

## Como usar esta skill

Quando o usuário pedir sugestões de melhoria, siga este roteiro:

1. **Identifique a área** (app, infra ou test) e o arquivo específico.
2. **Mostre o código atual** do arquivo relevante.
3. **Explique o problema** em uma frase simples.
4. **Proponha o código melhorado** com diff claro (antes/depois).
5. **Explique o ganho** em termos que um estudante entenda (custo, debug, manutenção).
6. **Pergunte se quer implementar** antes de alterar qualquer arquivo.

Nunca sugira mais de 2 melhorias por resposta — foco e profundidade valem mais que quantidade.

---

## Regra obrigatória: ao aplicar melhoria em `app/`, atualizar `test/` junto

Toda vez que uma melhoria for **aplicada** em qualquer arquivo de `app/`, o ciclo completo é:

```
1. Aplica a mudança em app/<modulo>/src/utils.py  (ou main.py)
2. Roda os testes existentes para verificar que nada quebrou
3. Atualiza ou cria testes em test/<modulo>/ para cobrir a mudança
4. Roda os testes novamente para confirmar cobertura
```

### Mapeamento `app/` → `test/`

| Arquivo alterado em `app/` | Arquivo de teste correspondente em `test/` |
|----------------------------|--------------------------------------------|
| `app/lambda_api/main.py` | `test/lambda_api/test_main.py` |
| `app/lambda_api/src/utils.py` | `test/lambda_api/test_utils.py` |
| `app/glue_etl/main.py` | `test/glue_etl/test_main.py` |
| `app/glue_etl/src/utils.py` | `test/glue_etl/test_utils.py` |
| `app/glue_data_quality/main.py` | `test/glue_data_quality/test_utils.py` |
| `app/glue_data_quality/src/utils.py` | `test/glue_data_quality/test_utils.py` |
| `app/glue_data_quality/src/rulesets_dq.py` | `test/glue_data_quality/test_rulesets_dq.py` |

### O que atualizar nos testes para cada tipo de melhoria

**Se adicionou logging (`logger.info` / `logger.error`):**
- Verifique se o teste existente ainda passa (logging não quebra testes).
- Adicione um caso que confirma que o logger é chamado no caminho de erro:
```python
@patch("app.lambda_api.src.utils.logger")
def test_logger_chamado_em_erro(self, mock_logger):
    # força o erro
    result = lambda_handler({"type": "invalido"}, {})
    mock_logger.error.assert_called_once()
```

**Se adicionou/alterou uma constante (ex: `TMDB_BASE_URL`):**
- Verifique que os testes de `fetch_*` que mockam `requests.get` continuam passando.
- Não é necessário criar teste para a constante em si — o teste da função já a exercita.

**Se adicionou type hints:**
- Type hints não mudam o comportamento em runtime — os testes existentes já os cobrem.
- Nenhuma atualização de teste necessária; o `mypy` valida os tipos no pipeline.

**Se adicionou validação de entrada ou novo `raise`:**
- Crie um teste de caminho de erro explicitamente:
```python
def test_funcao_levanta_value_error_para_entrada_invalida(self):
    with self.assertRaises(ValueError):
        funcao_alterada(entrada_invalida)
```

**Se extraiu lógica para uma nova função:**
- Crie um teste unitário dedicado para a nova função.
- Verifique que o teste da função original ainda passa (ela agora delega para a nova).

### Como rodar os testes localmente após a mudança

```bash
# Rodar apenas os testes do módulo alterado (mais rápido durante desenvolvimento)
pytest test/lambda_api/ -v

# Rodar com cobertura para verificar o gate de 70%
pytest --cov=app --cov-report=term-missing --cov-fail-under=70

# Verificar apenas o arquivo específico
pytest test/lambda_api/test_utils.py -v
```

### Ordem de execução ao aplicar uma melhoria

```
[1] Lê o arquivo atual em app/<modulo>/src/utils.py
[2] Lê o arquivo de teste atual em test/<modulo>/test_utils.py
[3] Aplica a melhoria em app/
[4] Roda: pytest test/<modulo>/ -v  → todos devem continuar passando
[5] Atualiza test/<modulo>/test_utils.py com casos para a mudança
[6] Roda: pytest test/<modulo>/ -v  → novos testes devem passar
[7] Roda: pytest --cov=app --cov-fail-under=70  → gate de cobertura mantido
```

Nunca entregue uma melhoria em `app/` sem completar todos os 7 passos acima.
