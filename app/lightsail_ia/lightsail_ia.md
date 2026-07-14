# lightsail_ia — Aplicativo de Recomendações (FilmBot)

## O que é

O FilmBot é uma interface web construída com Streamlit e hospedada em uma instância AWS Lightsail. O usuário digita o que quer assistir em linguagem natural, e um agente de IA interpreta o pedido, consulta a tabela unificada na camada SPEC via Athena e retorna recomendações personalizadas com pôster, sinopse, avaliação e onde assistir.

## Por que existe

Permite que qualquer pessoa consuma os dados do pipeline sem precisar escrever SQL. O agente de IA atua como intermediário entre o pedido em linguagem natural e a base de dados estruturada.

## Como funciona

O processo de recomendação é dividido em duas etapas encadeadas:

### Etapa 1 — Geração da cláusula WHERE (LLM + Function Calling, com cache)
O LLM recebe o texto do usuário e o schema completo da tabela SPEC. Usando *Function Calling*, gera a cláusula WHERE do SQL livremente, combinando qualquer coluna disponível:
```json
{
  "where_clause": "media_type = 'movie' AND original_language = 'ko' AND lower(genre_names) LIKE '%terror%' AND vote_average >= 7.0",
  "limit": 10
}
```
Essa abordagem "livre" permite que qualquer combinação de filtros seja usada sem precisar mapear cada pergunta possível no código (ex: idioma, duração, país de origem, temporadas, plataforma de streaming, em cartaz, diretor, elenco). O limite máximo de resultados é 10.

O schema informado ao LLM inclui colunas de ficha técnica como `director` e `actor_names` (além de `screenplay`, `music_composer`, `producer`, `cinematographer`, `editor`), permitindo buscas como "filmes do Christopher Nolan" ou "filmes com Tom Hanks" — mesmo que esses campos não sejam exibidos no card (ver seção "Interface").

**Cache de WHERE clauses:** a cláusula WHERE gerada pelo LLM é armazenada em cache em memória (dict no módulo), indexada pelo hash MD5 da preferência normalizada (lowercase + strip). Consultas repetidas (ex: "filmes de terror" digitado duas vezes) reutilizam a cláusula cacheada sem chamar o LLM novamente. TTL de 1 hora — compatível com a frequência de atualização semanal dos dados SPEC. O cache é limpo automaticamente ao reiniciar o processo Streamlit.

### Etapa 2 — Consulta ao Athena
A cláusula WHERE gerada pelo LLM é validada (`_validate_where()` bloqueia SQL perigoso como DROP, DELETE, INSERT, subqueries) e executada na tabela `tb_tmdb_discover_unified_{env}` (camada SPEC). O filtro fixo `vote_count ≥ 50` é sempre aplicado automaticamente.

### Etapa 2.5 — Formatação determinística (formatacao.py)
Após o Athena retornar os resultados brutos, funções puras em `formatacao.py` (`format_record()`) convertem cada registro em campos prontos para o card da interface, sem usar LLM:
- `title` (cópia de `title`), `type` (`"movie"` → `"filme"`, `"tv"` → `"série"`)
- `year` (inteiro), `genres` (lista de strings a partir de `genre_names`)
- `overview` (cópia de `overview` — já vem em pt-BR do pipeline via `COALESCE(overview, overview_pt, overview_en)`)
- `rating` (float), `poster_url`, `backdrop_url`
- `duration` (runtime formatado para filmes: `"2h 26min"`; temporadas/episódios para séries: `"3 temporadas · 36 eps · ~45 min/ep"`)
- `release_date` (mês por extenso + ano em PT derivado de `air_date`, ex: `"Maio de 1980"`)
- `streaming_providers` (cópia direta — onde assistir no Brasil)
- `in_theaters` (boolean), `theater_end_date` (string `DD/MM/YYYY` ou `null`)
- `tagline`, `cast` (top 5 atores), `director` (filmes e séries) — campos formatados mas atualmente não renderizados por `render_card()` (`componentes.py`), junto com `collection`, `creators`, `networks`, `producer`, `cinematographer`, `editor`
- `writers` (escritores/roteiristas), `composer` (compositor da trilha sonora)
- `producer` (produtores/produtores executivos), `cinematographer` (diretor de fotografia), `editor` (editor/montador)
- `keywords` (tags temáticas em português), `certification` (classificação indicativa BR: L/10/12/14/16/18)
- `trailer_url` (link do YouTube), `collection` (saga/franquia, apenas filmes)
- `production_companies` (estúdios), `production_countries` (países de produção, diferente de país de origem)
- `networks` (redes originais, apenas séries), `creators` (apenas séries)
- `rent_buy_providers` (plataformas de aluguel/compra no Brasil)
- `recommended` (títulos recomendados pelo TMDB), `similar` (títulos similares), `alternative_titles` (nomes regionais)

### Entrada alternativa — Transcrição de áudio (Whisper via litellm)
Além de digitar, o usuário pode gravar a preferência em áudio pelo widget nativo `st.audio_input`, exibido como um botão de microfone **embutido no canto inferior direito do `st.text_area`** (visual "composer" único, estilo chat moderno — WhatsApp/ChatGPT/Claude), em vez de uma seção separada. O áudio é transcrito por `transcribe_preference()` (`agent.py`) usando Whisper via `litellm` — modelo configurável por `TRANSCRIPTION_MODEL` (padrão: Groq Whisper Large v3 Turbo, rápido e barato), com `language="pt"` fixo. O texto resultante pré-popula o `st.text_area` de preferência, permanecendo totalmente editável antes de clicar em "Recomendar". O limite de duração é informado apenas no rótulo acessível do widget (`label_visibility="collapsed"`), sem legenda visual — não há mais texto explicando a opção de áudio, o ícone de microfone é autoexplicativo.

- **Ordem visual vs. ordem de execução:** o Streamlit proíbe setar `st.session_state["preference_text"]` depois que o widget `st.text_area` com essa key já rodou no mesmo script run — por isso o áudio precisa ser processado em Python *antes* do `text_area`. `app.py` cria dois `st.empty()` (`text_area_slot`, `status_slot`) logo no início do bloco `st.container(key="composer")`, na ordem em que devem aparecer visualmente (texto, depois as mensagens de status da transcrição); o conteúdo de cada um é preenchido depois (`with slot.container(): ...`), com o áudio ainda processado antes do texto no fluxo do script. `st.empty()` fixa a posição no layout no momento em que é chamado, não quando é preenchido. O `st.audio_input` em si não usa placeholder — como é posicionado via CSS `position: absolute` (ver abaixo), sua posição real no DOM não afeta o resultado visual.
- **Composer via CSS (`static/principal.css`, seletor `.st-key-composer`):** o container `st.container(key="composer")` ganha a classe `st-key-composer` (recurso do parâmetro `key` do Streamlit ≥1.37), usada como âncora `position: relative`. O `[data-testid="stAudioInput"]` é retirado do fluxo normal (`position: absolute`) e ancorado no canto do textarea; a forma de onda e o timer (`stAudioInputWaveSurfer`, `stAudioInputWaveformTimeCode`) são ocultados via CSS, restando só o botão (`stAudioInputActionButton`) visível como ícone. **Atenção:** assim como `contador_caracteres.js`, essa técnica depende de `data-testid`s internos do widget `st.audio_input` que não são API pública documentada do Streamlit e podem mudar em upgrades de versão — validação é manual (`streamlit run app.py`). Durante a gravação ativa, se o widget nativo precisar de mais espaço (forma de onda, se reaparecer em versões futuras), ele pode se sobrepor visualmente ao texto por alguns segundos; não há tratamento especial para esse caso.

- **Limite de duração:** áudios com mais de 20 segundos (`_MAX_AUDIO_SECONDS`) são rejeitados **antes** de chamar a API de transcrição — a duração é calculada com o módulo padrão `wave` (sem dependência nova), já que `st.audio_input` sempre entrega WAV. O limite ("máx. 20s") consta apenas no rótulo acessível do botão de microfone (sem legenda visual, ver "Entrada alternativa" acima), além do aviso "⚠️ Áudio muito longo" exibido caso a gravação exceda o limite.
- **Degradação graciosa:** qualquer falha na transcrição (provedor indisponível, sem API key configurada, áudio sem fala detectada, áudio muito longo) nunca bloqueia o campo de texto — a pessoa sempre pode digitar manualmente.
- **Rate limiting próprio:** 30 transcrições por hora por IP (`_MAX_TRANSCRIPTIONS_PER_HOUR`), mais generoso que o limite de recomendações porque o custo de Whisper é bem menor que o fluxo LLM+Athena. Usa um histórico de IPs independente (`_audio_ip_history`) do fluxo de recomendação.
- **Execução assíncrona:** mesmo padrão de `ThreadPoolExecutor` + `Future` + polling (500ms) já usado no botão "Recomendar", com chaves de `session_state` próprias (`transcribing`/`transcription_future`) para não colidir com o fluxo de busca.
- **Limite de caracteres:** transcrições acima de 300 caracteres (`_MAX_PREFERENCE_CHARS`) são cortadas nesse limite antes de preencher o campo de texto, com aviso "⚠️ Transcrição excedeu 300 caracteres e foi cortada." — necessário porque o `st.text_area` de destino também tem `max_chars=300` e rejeitaria um valor de `session_state` maior que isso.
- **AWS Transcribe foi avaliado e descartado** como alternativa: embora fosse barato de plugar (reaproveitaria o bucket temporário do Athena e a IAM já existentes, sem precisar de secret novo), jobs batch do Transcribe tipicamente levam 15-60+ segundos até completar mesmo para áudios curtos — muito mais lento que os ~1-3s do Whisper via Groq, prejudicando a experiência de "gravar uma frase curta e ver o texto aparecer".

### Interface (`app.py`)
- Tema escuro com CSS customizado
- Grid responsivo de cards (largura mínima 260px por coluna, preenche a tela automaticamente)
- Botão "Sair" no cabeçalho para encerrar a sessão autenticada
- **Rate limiting por IP:** máximo de 20 consultas por hora (janela deslizante). O contador é exibido abaixo do campo de texto; ao atingir o limite, o botão "Recomendar" é desabilitado e um countdown dinâmico MM:SS (JavaScript client-side via `st.components.v1.html`) mostra quanto tempo falta em tempo real, decrementando a cada segundo. Ao chegar em 00:00, a página recarrega automaticamente. O histórico de timestamps é mantido em dict no nível do módulo (`_ip_history`), indexado pelo IP do cliente via `X-Forwarded-For` — sobrevive a reloads da página (reseta apenas no restart do processo Streamlit, ex: deploy)
- **Limite de caracteres:** o `st.text_area` da preferência tem `max_chars=300` (`_MAX_PREFERENCE_CHARS`), aplicado tanto à digitação manual (o Streamlit trava a digitação ao atingir o limite) quanto ao texto vindo da transcrição de áudio (truncado antes de preencher o campo — ver seção de transcrição acima). Um contador "N / 300 caracteres" é exibido abaixo da caixa, atualizado em tempo real a cada tecla digitada via `static/contador_caracteres.js` (injetado por `load_preference_counter_script()` em `componentes.py`, mesmo padrão de `_inject_css`/`load_main_css`) — o script acessa o DOM da página (`window.parent.document`) através de um iframe same-origin (`st.components.v1.html`) e observa a textarea pelo hook `data-testid="stTextArea"`, já que o Streamlit não oferece rerun por-tecla nativamente. **Atenção:** por depender de um detalhe interno não documentado do Streamlit, esse contador pode quebrar silenciosamente em upgrades futuros de versão — `app.py` não tem teste automatizado, validação é manual (`streamlit run app.py`)
- Botão "Cancelar" durante a busca: a recomendação roda em thread separada (`ThreadPoolExecutor`) com polling de 500ms, permitindo ao usuário cancelar a qualquer momento sem esperar a resposta completa
- Logging de erros: exceções na busca são registradas via `logging.exception()` e enviadas ao CloudWatch Logs (quando `CLOUDWATCH_LOG_GROUP` está configurada) para diagnóstico em produção
- Cada card exibe:
  - Imagem de fundo (backdrop preferido sobre poster)
  - Título, ano, tipo (filme/série) e badge de classificação indicativa (L/10/12/14/16/18)
  - Badges laranja por gênero
  - Linha com nota (★), duração (⏱), data de lançamento (📅)
  - Badge amarelo 🎬 "Em cartaz até DD/MM/YYYY" (ou "Em cartaz") quando `in_theaters=true`
  - Badges verdes 📺 com as plataformas de streaming disponíveis no Brasil
  - Link clicável ▶ Trailer (quando disponível)
  - Sinopse

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Texto livre do usuário (ex: "filmes de ficção científica dos anos 80") |
| **Leitura** | Athena — tabela `tb_tmdb_discover_unified_{env}` (camada SPEC) |
| **Saída** | Cards de recomendação na interface web |

## Funções principais

| Arquivo | Função | Responsabilidade |
|---|---|---|
| `agent.py` | `recommend(user_input)` | Orquestra as etapas: verificar cache → gerar WHERE (LLM) → consultar → formatar (Python) |
| `agent.py` | `search_titles_spec(where_clause, limit)` | Valida o WHERE gerado pelo LLM e executa query SQL no Athena (limite máximo: 10) |
| `agent.py` | `_validate_where(where_clause)` | Valida a cláusula WHERE contra SQL perigoso (DROP, DELETE, INSERT, subqueries, UPDATE, ALTER, CREATE, GRANT, TRUNCATE, EXEC, MERGE, REPLACE, CALL) |
| `agent.py` | `_load_llm_api_key()` | Busca `LLM_API_KEY` no Secrets Manager (via `FILMBOT_SECRET_ARN`) em produção, ou usa `.env` como fallback em desenvolvimento |
| `agent.py` | `_cache_key(preference)` | Calcula o hash MD5 da preferência normalizada (lowercase + strip), usado como chave do cache de WHERE clauses |
| `agent.py` | `_get_cached_where(preference)` | Busca cláusula WHERE cacheada; retorna `None` se ausente ou expirada (TTL 1h) |
| `agent.py` | `_save_cached_where(preference, args)` | Salva cláusula WHERE no cache em memória com timestamp |
| `agent.py` | `_call_llm_step1(preference)` | Chama o LLM (`LLM_MODEL`) para gerar a cláusula WHERE via function calling |
| `agent.py` | `_log_token_usage(step, response)` | Registra `prompt_tokens`, `completion_tokens`, `total_tokens` e `model` (`LLM_MODEL`) da resposta do LLM via `logging.info` (ver observação na seção "Observabilidade de tokens") |
| `agent.py` | `transcribe_preference(audio_bytes)` | Transcreve áudio (WAV) para texto via Whisper (`litellm.transcription`, modelo `TRANSCRIPTION_MODEL`). Rejeita áudios acima de 20s (`AudioMuitoLongoError`) antes de chamar a API. Sem fallback automático de modelo |
| `agent.py` | `_audio_duration_seconds(audio_bytes)` | Calcula a duração de um áudio WAV via módulo padrão `wave` |
| `agent.py` | `_load_transcription_api_key()` | Busca `transcription_api_key` no Secrets Manager (via `FILMBOT_SECRET_ARN`) em produção, ou `TRANSCRIPTION_API_KEY` do `.env` em desenvolvimento; retorna `None` (não quebra o app) se ausente |
| `formatacao.py` | `format_record(record)` | Converte um registro bruto do Athena em dict formatado para o card (tipo, gêneros, duração, data, nota, etc.) |
| `formatacao.py` | `_format_type()`, `_format_genres()`, `_format_title_duration()`, `_format_release_date()`, `_format_theater_end_date()`, `_format_rating()` | Funções puras de formatação de campos individuais |
| `app.py` | `_load_filmbot_password()` | Busca `filmbot_password` no Secrets Manager (via `FILMBOT_SECRET_ARN`) e grava `.streamlit/secrets.toml` (chmod 600) para a autenticação do Streamlit; não faz nada se o arquivo já existir |
| `app.py` | `_create_ip_history()`, `_create_audio_ip_history()` | Factories `@st.cache_resource` que criam os dicts compartilhados `_ip_history` (recomendações) e `_audio_ip_history` (transcrições), garantindo que os históricos de rate limiting sobrevivam a reruns e resetem apenas no restart do processo |
| `app.py` | `_get_client_ip()` | Obtém o IP do cliente via header `X-Forwarded-For` (repassado pelo Caddy) |
| `app.py` | `_queries_in_last_hour(history, ip)` | Conta consultas na última hora (janela deslizante) para o IP no histórico informado e limpa registros expirados. Reusada para recomendações (`_ip_history`) e transcrições (`_audio_ip_history`) |
| `app.py` | `_seconds_until_available(history, ip)` | Calcula quantos segundos faltam até a consulta mais antiga do IP expirar, no histórico informado |
| `app.py` | Interface Streamlit | Orquestra a UI: autenticação, gravação/transcrição de áudio, rate limiting, busca assíncrona e exibição de resultados |
| `componentes.py` | `load_login_css()`, `load_main_css()`, `load_preference_counter_script()`, `render_card()`, `render_grid()`, `render_footer()`, `render_login_footer()` | Helpers de renderização HTML com escape contra XSS |
| `static/login.css` | CSS da tela de login | Estilos específicos da tela de autenticação |
| `static/principal.css` | CSS da página principal | Estilos do grid, cards e layout responsivo |
| `static/contador_caracteres.js` | Script do contador dinâmico do campo de preferência | Observa a textarea via `data-testid="stTextArea"` e atualiza o contador a cada tecla digitada |

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
bash infra/config/export_env_local.sh

# 2. Rodar
cd app/lightsail_ia
pip install -r requirements.txt
streamlit run app.py   # http://localhost:8501
```

Em desenvolvimento local, use `LLM_API_KEY` diretamente no `.env` (fallback quando `FILMBOT_SECRET_ARN` não está definida). Use `.env.example` como referência.

## Variáveis de ambiente necessárias

| Variável | Uso |
|---|---|
| `FILMBOT_SECRET_ARN` | ARN do segredo unificado no Secrets Manager (contém `llm_api_key`, `tmdb_api_key`, `filmbot_password` e, opcionalmente, `transcription_api_key`). Em produção, o app busca esses valores do secret em runtime |
| `LLM_API_KEY` | Fallback para desenvolvimento local (usado quando `FILMBOT_SECRET_ARN` não está definida) |
| `TRANSCRIPTION_API_KEY` | *(Opcional)* Fallback para desenvolvimento local da chave de transcrição (usado quando `FILMBOT_SECRET_ARN` não está definida). Indefinida = transcrição de áudio indisponível, sem afetar o restante do app |
| `TRANSCRIPTION_MODEL` | *(Opcional)* Modelo de transcrição via litellm (padrão: `groq/whisper-large-v3-turbo`) |
| `LLM_MODEL` | Modelo LLM a usar (padrão: `deepseek/deepseek-v4-flash`). Ex: `deepseek/deepseek-chat`, `claude-opus-4-8` |
| `AWS_REGION` | Região AWS para consultas Athena (ex: `sa-east-1`) |
| `AWS_ACCESS_KEY_ID` | Credencial do IAM user `filmbot-agent-{env}` |
| `AWS_SECRET_ACCESS_KEY` | Credencial do IAM user `filmbot-agent-{env}` |
| `ATHENA_S3_OUTPUT` | Bucket temporário para resultados de queries Athena |
| `GLUE_DATABASE` | Nome do banco no Glue Catalog com a tabela SPEC |
| `SPEC_TABLE` | Nome da tabela unificada (ex: `tb_tmdb_discover_unified_prod`) |
| `CLOUDWATCH_LOG_GROUP` | Log group do CloudWatch para envio de logs (ex: `/lightsail/tmdb-filmbot-prod`). Injetado automaticamente pelo CI/CD via Terraform output. Se ausente, logs vão apenas para stdout/journald |

## Tecnologias

- **Streamlit** — framework de interface web em Python
- **litellm** — abstração de chamadas LLM (suporta OpenAI, DeepSeek, Claude, etc.)
- **LLM configurável via `LLM_MODEL`** — padrão `deepseek/deepseek-v4-flash`; suporta qualquer modelo compatível com litellm (DeepSeek, OpenAI, Claude, etc.)
- **boto3** — cliente AWS para consultas Athena (API nativa: start_query_execution / get_paginator)
- **watchtower** — handler de logging que envia logs Python diretamente ao CloudWatch Logs via boto3
- **AWS Lightsail** — instância de servidor para hospedar o app

## Observabilidade de tokens

Cada chamada a `litellm.completion()` (etapa 1) registra via `logging.info` os campos `prompt_tokens`, `completion_tokens`, `total_tokens`, `model` e `step` (`_log_token_usage()` em `agent.py`). Esses logs são enviados ao CloudWatch Logs (quando `CLOUDWATCH_LOG_GROUP` está configurada) e podem ser usados para criar métricas de custo e alertas de consumo.

`app.py` eleva o root logger para `ERROR` quando o CloudWatch está configurado (`logging.root.setLevel(logging.ERROR)`), para silenciar bibliotecas ruidosas. Como isso suprimiria por herança os `logger.info(...)` de `_log_token_usage()`, `agent.py` define explicitamente `logger.setLevel(logging.INFO)` no seu próprio logger — garantindo que os logs de tokens continuem passando pelo handler do root independentemente do nível herdado.
