# lightsail_ia — Aplicativo de Recomendações (FilmBot)

## O que é

O FilmBot é uma interface web construída com Streamlit e hospedada em uma instância AWS Lightsail. O usuário digita o que quer assistir em linguagem natural, e um agente de IA interpreta o pedido, consulta a tabela unificada na camada SPEC via Athena e retorna recomendações personalizadas com pôster, sinopse, avaliação e onde assistir.

## Por que existe

Permite que qualquer pessoa consuma os dados do pipeline sem precisar escrever SQL. O agente de IA atua como intermediário entre o pedido em linguagem natural e a base de dados estruturada.

## Como funciona

O processo de recomendação é dividido em três etapas encadeadas:

### Etapa 1 — Geração da cláusula WHERE (LLM + Function Calling, com cache)
O LLM recebe o texto do usuário e o schema completo da tabela SPEC. Usando *Function Calling*, gera a cláusula WHERE do SQL livremente, combinando qualquer coluna disponível:
```json
{
  "filtro_where": "media_type = 'movie' AND original_language = 'ko' AND lower(genre_names) LIKE '%terror%' AND vote_average >= 7.0",
  "limite": 10
}
```
Essa abordagem "livre" permite que qualquer combinação de filtros seja usada sem precisar mapear cada pergunta possível no código (ex: idioma, duração, país de origem, temporadas, plataforma de streaming, em cartaz). O limite máximo de resultados é 10.

**Cache de WHERE clauses:** a cláusula WHERE gerada pelo LLM é armazenada em cache em memória (dict no módulo), indexada pelo hash MD5 da preferência normalizada (lowercase + strip). Consultas repetidas (ex: "filmes de terror" digitado duas vezes) reutilizam a cláusula cacheada sem chamar o LLM novamente. TTL de 1 hora — compatível com a frequência de atualização semanal dos dados SPEC. O cache é limpo automaticamente ao reiniciar o processo Streamlit.

### Etapa 2 — Consulta ao Athena
A cláusula WHERE gerada pelo LLM é validada (`_validar_where()` bloqueia SQL perigoso como DROP, DELETE, INSERT, subqueries) e executada na tabela `tb_tmdb_discover_unified_{env}` (camada SPEC). O filtro fixo `vote_count ≥ 50` é sempre aplicado automaticamente.

### Etapa 2.5 — Formatação determinística (Python)
Após o Athena retornar os resultados brutos, funções Python (`_formatar_registro()`) convertem cada registro em campos prontos para o card da interface, sem usar LLM:
- `titulo` (cópia de `title`), `tipo` (`"movie"` → `"filme"`, `"tv"` → `"série"`)
- `ano` (inteiro), `generos` (lista de strings a partir de `genre_names`)
- `sinopse` (cópia de `overview` — já vem em pt-BR do pipeline via `COALESCE(overview, overview_pt, overview_en)`)
- `nota` (float), `poster_url`, `backdrop_url`
- `duracao` (runtime formatado para filmes: `"2h 26min"`; temporadas/episódios para séries: `"3 temporadas · 36 eps · ~45 min/ep"`)
- `data_lancamento` (mês por extenso + ano em PT derivado de `air_date`, ex: `"Maio de 1980"`)
- `streaming_providers` (cópia direta — onde assistir no Brasil)
- `in_theaters` (boolean), `theater_end_date` (string `DD/MM/YYYY` ou `null`)

### Etapa 3 — Geração do motivo (LLM)
O LLM recebe apenas os campos essenciais de cada título (`id`, `title`, `overview`, `genre_names`, `year`, `vote_average`) e gera um `motivo` curto (1-2 frases) explicando por que cada título é relevante para o pedido do usuário. Retorna JSON com apenas `id` e `motivo` por título, que é mesclado ao registro já formatado pelo Python. O merge é tolerante a variações de resposta do LLM: aceita `id` como int ou string (converte via `int()`), e aceita tanto `{"titulos": [...]}` quanto lista direta `[...]`.

### Interface (`app.py`)
- Tema escuro com CSS customizado
- Grid responsivo de cards (largura mínima 260px por coluna, preenche a tela automaticamente)
- Botão "Sair" no cabeçalho para encerrar a sessão autenticada
- Botão "Cancelar" durante a busca: a recomendação roda em thread separada (`ThreadPoolExecutor`) com polling de 500ms, permitindo ao usuário cancelar a qualquer momento sem esperar a resposta completa
- Logging de erros: exceções na busca são registradas via `logging.exception()` e enviadas ao CloudWatch Logs (quando `CLOUDWATCH_LOG_GROUP` está configurada) para diagnóstico em produção
- Cada card exibe:
  - Imagem de fundo (backdrop preferido sobre poster)
  - Título, ano e tipo (filme/série)
  - Badges laranja por gênero
  - Linha com nota (★), duração (⏱), data de lançamento (📅)
  - Badge amarelo 🎬 "Em cartaz até DD/MM/YYYY" (ou "Em cartaz") quando `in_theaters=true`
  - Badges verdes 📺 com as plataformas de streaming disponíveis no Brasil
  - Sinopse e motivo da recomendação

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Texto livre do usuário (ex: "filmes de ficção científica dos anos 80") |
| **Leitura** | Athena — tabela `tb_tmdb_discover_unified_{env}` (camada SPEC) |
| **Saída** | Cards de recomendação na interface web |

## Funções principais

| Arquivo | Função | Responsabilidade |
|---|---|---|
| `agent.py` | `recomendar(user_input)` | Orquestra as etapas: verificar cache → gerar WHERE (LLM) → consultar → formatar (Python) → gerar motivo (LLM) |
| `agent.py` | `buscar_titulos_spec(filtro_where, limite)` | Valida o WHERE gerado pelo LLM e executa query SQL no Athena (limite máximo: 10) |
| `agent.py` | `_validar_where(filtro_where)` | Valida a cláusula WHERE contra SQL perigoso (DROP, DELETE, INSERT, subqueries) |
| `agent.py` | `_buscar_cache_where(preferencia)` | Busca cláusula WHERE cacheada; retorna `None` se ausente ou expirada (TTL 1h) |
| `agent.py` | `_salvar_cache_where(preferencia, args)` | Salva cláusula WHERE no cache em memória com timestamp |
| `agent.py` | `_logar_uso_tokens(etapa, resposta)` | Registra `prompt_tokens`, `completion_tokens` e `total_tokens` da resposta do LLM via `logging.info` |
| `agent.py` | `_formatar_registro(registro)` | Converte um registro bruto do Athena em dict formatado para o card (tipo, gêneros, duração, data, nota, etc.) |
| `agent.py` | `limpar_duracao(raw)` | Remove fragmentos `~null` de strings de duração (legado — novas durações são formatadas por `_formatar_duracao_titulo`) |
| `app.py` | Interface Streamlit | Orquestra a UI: autenticação, busca assíncrona e exibição de resultados |
| `componentes.py` | `carregar_css()`, `renderizar_card()`, `renderizar_grid()`, `renderizar_rodape()` | Helpers de renderização HTML com escape contra XSS |
| `static/estilos.css` | CSS consolidado | Estilos do login e página principal (grid, cards, responsivo) |

## Deploy

### Produção (Lightsail)

O app roda como serviço `systemd` (`filmbot.service`) na instância Lightsail, escutando apenas em `127.0.0.1:8501` (acesso local). O **Caddy** atua como proxy reverso na porta 80. O script `deploy/setup.sh` instala dependências, Caddy e configura ambos os serviços. O Terraform provisiona a instância (portas 22, 80 e 443) e o CI/CD faz o deploy via SSH ao fazer push na branch `main`.

Arquivos de deploy:
- `deploy/filmbot.service` — serviço Streamlit (bind em `127.0.0.1`)
- `deploy/caddy.service` — serviço Caddy (proxy reverso HTTPS)
- `deploy/Caddyfile` — configuração do Caddy (porta 80 → `localhost:8501`)
- `deploy/setup.sh` — bootstrap da instância (Python, Caddy, serviços)

### Desenvolvimento local

Em dev, a instância Lightsail está desabilitada (`lightsail_enabled = false`). Para rodar localmente:

```bash
# 1. Gerar o .env com as credenciais da conta dev (requer Terraform inicializado)
LLM_API_KEY=sk-... bash infra/config/export_env_local.sh

# 2. Rodar
cd app/lightsail_ia
pip install -r requirements.txt
streamlit run app.py   # http://localhost:8501
```

Use `.env.example` como referência para as variáveis necessárias.

## Variáveis de ambiente necessárias

| Variável | Uso |
|---|---|
| `LLM_API_KEY` | Chave de API do provedor LLM em uso |
| `LLM_MODEL` | Modelo LLM a usar (padrão: `deepseek/deepseek-v4-flash`). Ex: `deepseek/deepseek-chat`, `claude-opus-4-8` |
| `AWS_REGION` | Região AWS para consultas Athena (ex: `sa-east-1`) |
| `AWS_ACCESS_KEY_ID` | Credencial do IAM user `filmbot-agent-{env}` |
| `AWS_SECRET_ACCESS_KEY` | Credencial do IAM user `filmbot-agent-{env}` |
| `ATHENA_S3_OUTPUT` | Bucket temporário para resultados de queries Athena |
| `GLUE_DATABASE` | Nome do banco no Glue Catalog com a tabela SPEC |
| `SPEC_TABLE` | Nome da tabela unificada (ex: `tb_tmdb_discover_unified_prod`) |
| `FILMBOT_PASSWORD` | Senha de acesso à interface Streamlit |
| `CLOUDWATCH_LOG_GROUP` | Log group do CloudWatch para envio de logs (ex: `/lightsail/tmdb-filmbot-prod`). Injetado automaticamente pelo CI/CD via Terraform output. Se ausente, logs vão apenas para stdout/journald |

## Tecnologias

- **Streamlit** — framework de interface web em Python
- **litellm** — abstração de chamadas LLM (suporta OpenAI, DeepSeek, Claude, etc.)
- **LLM configurável via `LLM_MODEL`** — padrão `deepseek/deepseek-v4-flash`; suporta qualquer modelo compatível com litellm (DeepSeek, OpenAI, Claude, etc.)
- **boto3** — cliente AWS para consultas Athena (API nativa: start_query_execution / get_paginator)
- **watchtower** — handler de logging que envia logs Python diretamente ao CloudWatch Logs via boto3
- **AWS Lightsail** — instância de servidor para hospedar o app

## Observabilidade de tokens

Cada chamada a `litellm.completion()` (etapas 1 e 3) registra via `logging.info` os campos `prompt_tokens`, `completion_tokens`, `total_tokens`, `modelo` e `etapa`. Esses logs são enviados ao CloudWatch Logs (quando `CLOUDWATCH_LOG_GROUP` está configurada) e podem ser usados para criar métricas de custo e alertas de consumo.
