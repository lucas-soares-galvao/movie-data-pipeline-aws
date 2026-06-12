# lightsail_ia — Aplicativo de Recomendações (FilmBot)

## O que é

O FilmBot é uma interface web construída com Streamlit e hospedada em uma instância AWS Lightsail. O usuário digita o que quer assistir em linguagem natural, e um agente de IA (GPT-4o) interpreta o pedido, consulta a tabela unificada na camada SPEC via Athena e retorna recomendações personalizadas com pôster, sinopse, avaliação e onde assistir.

## Por que existe

Permite que qualquer pessoa consuma os dados do pipeline sem precisar escrever SQL. O agente de IA atua como intermediário entre o pedido em linguagem natural e a base de dados estruturada.

## Como funciona

O processo de recomendação é dividido em três etapas encadeadas:

### Etapa 1 — Extração de filtros (GPT-4o + Function Calling)
O GPT-4o recebe o texto do usuário e usa *Function Calling* para retornar um JSON estruturado com os filtros extraídos:
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
Com os filtros extraídos, monta e executa uma query SQL dinâmica na tabela `tb_discover_unified_tmdb` (camada SPEC). Filtra por `vote_count ≥ 50`, `vote_average ≥ nota_minima`, `media_type`, `year` e `genre_names LIKE`.

### Etapa 3 — Formatação das recomendações (GPT-4o)
O GPT-4o recebe os resultados reais do Athena e formata como JSON com campos amigáveis:
- `titulo`, `tipo`, `ano`, `generos`
- `sinopse` (traduzida)
- `nota`, `poster_url`, `backdrop_url`
- `motivo` (por que este título foi recomendado)
- `duracao` (runtime para filmes, temporadas/episódios para séries)
- `streaming_providers` (onde assistir no Brasil)

### Interface (`app.py`)
- Tema escuro com CSS customizado
- Grid de 4 colunas com cards por título
- Badges coloridos para gêneros e plataformas de streaming
- Linha de metadados com nota, duração e ano

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Texto livre do usuário (ex: "filmes de ficção científica dos anos 80") |
| **Leitura** | Athena — tabela `tb_discover_unified_tmdb` (camada SPEC) |
| **Saída** | Cards de recomendação na interface web |

## Funções principais

| Arquivo | Função | Responsabilidade |
|---|---|---|
| `agent.py` | `recomendar(user_input)` | Orquestra as 3 etapas: extrair filtros → consultar → formatar |
| `agent.py` | `buscar_titulos_spec(filtros)` | Executa query SQL no Athena com filtros dinâmicos |
| `app.py` | Interface Streamlit | Renderiza cards, gerencia estado e exibe resultados |

## Deploy

### Produção (Lightsail)

O app roda como serviço `systemd` (`filmbot.service`) na instância Lightsail. O script `deploy/setup.sh` instala dependências e configura o serviço. O Terraform provisiona a instância (portas 8501 e 22) e o CI/CD faz o deploy via SSH ao fazer push na branch `main`.

### Desenvolvimento local

Em dev, a instância Lightsail está desabilitada (`lightsail_enabled = false`). Para rodar localmente:

```bash
# 1. Gerar o .env com as credenciais da conta dev (requer Terraform inicializado)
OPENAI_API_KEY=sk-... bash infra/scripts/export_env_local.sh

# 2. Rodar
cd app/lightsail_ia
pip install -r requirements.txt
streamlit run app.py   # http://localhost:8501
```

Use `.env.example` como referência para as variáveis necessárias.

## Variáveis de ambiente necessárias

| Variável | Uso |
|---|---|
| `OPENAI_API_KEY` | Chave da API OpenAI para o GPT-4o |
| `AWS_REGION` | Região AWS para consultas Athena (ex: `sa-east-1`) |
| `AWS_ACCESS_KEY_ID` | Credencial do IAM user `filmbot-agent-{env}` |
| `AWS_SECRET_ACCESS_KEY` | Credencial do IAM user `filmbot-agent-{env}` |
| `ATHENA_S3_OUTPUT` | Bucket temporário para resultados de queries Athena |
| `GLUE_DATABASE` | Nome do banco no Glue Catalog com a tabela SPEC |
| `SPEC_TABLE` | Nome da tabela unificada (ex: `tb_discover_unified_tmdb`) |
| `FILMBOT_PASSWORD` | Senha de acesso à interface Streamlit |

## Tecnologias

- **Streamlit** — framework de interface web em Python
- **litellm** — abstração de chamadas LLM (suporta OpenAI, DeepSeek, Claude, etc.)
- **OpenAI GPT-4o** — modelo padrão para extração de filtros e formatação de recomendações
- **boto3** — cliente AWS para consultas Athena (API nativa: start_query_execution / get_paginator)
- **AWS Lightsail** — instância de servidor para hospedar o app
