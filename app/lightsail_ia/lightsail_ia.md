# lightsail_ia — Aplicativo de Recomendações (FilmBot)

## O que é

O FilmBot é uma interface web construída com Streamlit e hospedada em uma instância AWS Lightsail. O usuário digita o que quer assistir em linguagem natural, e um agente de IA interpreta o pedido, consulta a tabela unificada na camada SPEC via Athena e retorna recomendações personalizadas com pôster, sinopse, avaliação e onde assistir.

## Por que existe

Permite que qualquer pessoa consuma os dados do pipeline sem precisar escrever SQL. O agente de IA atua como intermediário entre o pedido em linguagem natural e a base de dados estruturada.

## Como funciona

O processo de recomendação é dividido em três etapas encadeadas:

### Etapa 1 — Extração de filtros (LLM + Function Calling)
O LLM recebe o texto do usuário e usa *Function Calling* para retornar um JSON estruturado com os filtros extraídos:
```json
{
  "genero": "Terror",
  "tipo": "movie",
  "ano": 1990,
  "nota_minima": 7.0,
  "limite": 10
}
```

### Etapa 2 — Consulta ao Athena
Com os filtros extraídos, monta e executa uma query SQL dinâmica na tabela `tb_tmdb_discover_unified_{env}` (camada SPEC). Filtra por `vote_count ≥ 50`, `vote_average ≥ nota_minima`, `media_type`, `year` e `genre_names LIKE`.

### Etapa 3 — Formatação das recomendações (LLM)
O LLM recebe os resultados reais do Athena e formata como JSON com campos amigáveis:
- `titulo`, `tipo`, `ano`, `generos`
- `sinopse` (traduzida para português quando necessário)
- `nota`, `poster_url`, `backdrop_url`
- `motivo` (por que este título foi recomendado)
- `duracao` (runtime para filmes; temporadas/episódios/duração de ep. para séries; `null` se ausente)
- `data_lancamento` (mês por extenso + ano em PT derivado de `air_date`, ex: `"Julho 2025"`; `null` se ausente)
- `streaming_providers` (onde assistir no Brasil — string com serviços separados por vírgula, ou `null`)
- `in_theaters` (boolean — `true` se o filme estiver atualmente em cartaz nos cinemas)
- `theater_end_date` (string `DD/MM/YYYY` com a data de encerramento no cinema, ou `null`)

### Interface (`app.py`)
- Tema escuro com CSS customizado
- Grid responsivo de cards (largura mínima 260px por coluna, preenche a tela automaticamente)
- Botão "Sair" no cabeçalho para encerrar a sessão autenticada
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
| `agent.py` | `recomendar(user_input)` | Orquestra as 3 etapas: extrair filtros → consultar → formatar |
| `agent.py` | `buscar_titulos_spec(filtros)` | Executa query SQL no Athena com filtros dinâmicos |
| `app.py` | Interface Streamlit | Renderiza cards, gerencia estado e exibe resultados |

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
LLM_API_KEY=sk-... bash infra/scripts/export_env_local.sh

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
| `LLM_MODEL` | Modelo LLM a usar (padrão: `gpt-4o`). Ex: `deepseek/deepseek-chat`, `claude-opus-4-8` |
| `AWS_REGION` | Região AWS para consultas Athena (ex: `sa-east-1`) |
| `AWS_ACCESS_KEY_ID` | Credencial do IAM user `filmbot-agent-{env}` |
| `AWS_SECRET_ACCESS_KEY` | Credencial do IAM user `filmbot-agent-{env}` |
| `ATHENA_S3_OUTPUT` | Bucket temporário para resultados de queries Athena |
| `GLUE_DATABASE` | Nome do banco no Glue Catalog com a tabela SPEC |
| `SPEC_TABLE` | Nome da tabela unificada (ex: `tb_tmdb_discover_unified_prod`) |
| `FILMBOT_PASSWORD` | Senha de acesso à interface Streamlit |

## Tecnologias

- **Streamlit** — framework de interface web em Python
- **litellm** — abstração de chamadas LLM (suporta OpenAI, DeepSeek, Claude, etc.)
- **LLM configurável via `LLM_MODEL`** — padrão `gpt-4o`; suporta qualquer modelo compatível com litellm (OpenAI, DeepSeek, Claude, etc.)
- **boto3** — cliente AWS para consultas Athena (API nativa: start_query_execution / get_paginator)
- **AWS Lightsail** — instância de servidor para hospedar o app
