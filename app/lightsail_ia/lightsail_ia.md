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
  "where_clause": "media_type = 'movie' AND original_language = 'ko' AND lower(genre_names) LIKE '%terror%' AND vote_average >= 7.0",
  "limit": 15
}
```
Essa abordagem "livre" permite que qualquer combinação de filtros seja usada sem precisar mapear cada pergunta possível no código (ex: idioma, duração, país de origem, temporadas, plataforma de streaming, em cartaz, diretor, elenco). O limite máximo de resultados é 15.

**Destaque de gênero/provedor nas badges:** `_extract_highlighted_terms()` extrai por regex os valores de `lower(genre_names) LIKE '%valor%'` e `lower(streaming_providers) LIKE '%valor%'` de volta da própria `where_clause` gerada pelo LLM — reaproveita uma decisão que o LLM já tomou no Passo 1, sem chamada extra de LLM. Cláusulas `NOT LIKE` são ignoradas (o usuário não quer aquele valor, não deve ser destacado). O resultado é anexado a cada registro formatado como `highlighted_genres`/`highlighted_providers` e usado por `componentes.py::_prioritize()` (ver seção "Interface") para colocar o gênero/provedor mencionado primeiro nas badges do card.

O schema informado ao LLM inclui colunas de ficha técnica como `director` e `actor_names` (além de `screenplay`, `music_composer`, `producer`, `cinematographer`, `editor`), permitindo buscas como "filmes do Christopher Nolan" ou "filmes com Tom Hanks" — mesmo que esses campos não sejam exibidos no card (ver seção "Interface").

**Cache de WHERE clauses:** a cláusula WHERE gerada pelo LLM é armazenada em cache em memória (dict no módulo), indexada pelo hash MD5 da preferência normalizada (lowercase + strip). Consultas repetidas (ex: "filmes de terror" digitado duas vezes) reutilizam a cláusula cacheada sem chamar o LLM novamente. TTL de 1 hora — compatível com a frequência de atualização semanal dos dados SPEC. O cache é limpo automaticamente ao reiniciar o processo Streamlit. Como o destaque de gênero/provedor (`_extract_highlighted_terms()`) é derivado da mesma `where_clause` cacheada, um cache hit reproduz exatamente o mesmo destaque de uma chamada fresca ao LLM.

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

### Etapa 3 — Geração do motivo (LLM)
O LLM recebe apenas os campos que ajudam a justificar a recomendação de cada título já encontrado pelo Athena — `id`, `title`, `overview`, `genre_names`, `year`, `vote_average`, `director`, `actor_names`, `streaming_providers`, `certification`, `keywords_pt` — e gera um `reason` curto (1-2 frases) explicando por que aquele título específico atende ao pedido do usuário, podendo citar diretor/elenco/streaming/classificação/palavras-chave quando fizerem parte do motivo real. Retorna JSON com apenas `id` e `reason` por título (`{"titles": [...]}`), mesclado por índice ao registro já formatado pelo Python. O merge é tolerante a variações de resposta do LLM: aceita `id` como int ou string (converte via `int()`), aceita tanto `{"titles": [...]}` quanto lista direta `[...]`, e degrada para `reason=""` em caso de resposta vazia ou JSON inválido — uma falha aqui nunca derruba a recomendação.

Esta etapa roda em toda busca com resultados, mesmo quando a Etapa 1 tem cache hit: os títulos reais só existem depois da consulta ao Athena, então o motivo não pode ser cacheado junto com a cláusula WHERE.

### Entrada alternativa — Transcrição de áudio (Whisper via litellm)
Além de digitar, o usuário pode gravar a preferência em áudio pelo widget nativo `st.audio_input`. Ao parar a gravação, o app confirma automaticamente e transcreve por `transcribe_preference()` (`agent.py`) usando Whisper via `litellm` — modelo configurável por `TRANSCRIPTION_MODEL` (padrão: Groq Whisper Large v3 Turbo, rápido e barato), com `language="pt"` fixo. O texto resultante pré-popula o `st.text_area` de preferência, permanecendo totalmente editável antes de clicar em "Recomendar".

- **Confirmação automática e invisível:** o `st.audio_input` nativo não expõe nenhuma forma de cancelar uma gravação **em andamento** (o único botão durante o estado `recording` é "parar", que sempre finaliza e envia o áudio para o backend) — essa limitação foi confirmada inspecionando o bundle JS interno do widget. Por isso existe uma etapa intermediária entre "gravação parou" e "chamar a API de transcrição" (`audio_awaiting_confirmation`/`audio_pending_bytes`), com dois botões internos ("▶️ Usar gravação" / "✕ Cancelar", dentro de `st.container(key="audio-confirm-buttons")`) — mas eles ficam **escondidos via CSS** (`.st-key-audio-confirm-buttons { display: none; }` em `principal.css`) porque o usuário nunca precisa clicar neles à mão: `audio_cancel_recording.js` confirma "Usar gravação" automaticamente assim que os botões aparecem, a menos que o ícone de descarte (abaixo) já tenha sinalizado cancelamento. Ao descartar, `audio_widget_seq` é incrementado para forçar uma nova instância do `st.audio_input` (troca de `key`) — o único jeito de "esvaziar" visualmente um áudio já gravado, já que o widget não tem API para isso.
- **Ícone de descarte durante a gravação:** `static/audio_cancel_recording.js` (injetado por `load_audio_cancel_script()`, mesmo padrão de `contador_caracteres.js`) mostra um ícone 🗑 ao lado do botão nativo enquanto o estado é `recording`. Como a função interna `cancel()` do gravador não é acessível fora do componente React, o ícone simula "parar" (clica no botão nativo) e arma uma flag em `localStorage`; assim que o botão (escondido) "✕ Cancelar" aparece, o script clica nele automaticamente em vez de confirmar "Usar gravação", descartando o áudio sem nunca chamar `transcribe_preference`. Como os botões de confirmação nunca ficam visíveis, não há nenhum "flash" de UI perceptível ao usuário — só uma pausa breve entre parar e transcrever (ou entre parar e resetar, no caso do descarte).
- **Limite de duração:** áudios com mais de 15 segundos (`_MAX_AUDIO_SECONDS`) são rejeitados **antes** de chamar a API de transcrição — a duração é calculada com o módulo padrão `wave` (sem dependência nova), já que `st.audio_input` sempre entrega WAV. O limite é exibido para o usuário na legenda acima do gravador ("máx. 15s"), além do aviso "⚠️ Áudio muito longo" exibido caso a gravação exceda o limite.
- **Degradação graciosa:** qualquer falha na transcrição (provedor indisponível, sem API key configurada, áudio sem fala detectada, áudio muito longo) nunca bloqueia o campo de texto — a pessoa sempre pode digitar manualmente.
- **Rate limiting próprio:** 30 transcrições por hora por IP (`_MAX_TRANSCRIPTIONS_PER_HOUR`), mais generoso que o limite de recomendações porque o custo de Whisper é bem menor que o fluxo LLM+Athena. Usa um histórico de IPs independente (`_audio_ip_history`) do fluxo de recomendação.
- **Execução assíncrona:** mesmo padrão de `ThreadPoolExecutor` + `Future` + polling (500ms) já usado no botão "Recomendar", com chaves de `session_state` próprias (`transcribing`/`transcription_future`, além de `audio_awaiting_confirmation`/`audio_pending_bytes`/`audio_widget_seq` da etapa de confirmação) para não colidir com o fluxo de busca.
- **Limite de caracteres:** transcrições acima de 150 caracteres (`_MAX_PREFERENCE_CHARS`) são cortadas nesse limite antes de preencher o campo de texto, com aviso "⚠️ Transcrição excedeu 150 caracteres e foi cortada." — necessário porque o `st.text_area` de destino também tem `max_chars=150` e rejeitaria um valor de `session_state` maior que isso.
- **AWS Transcribe foi avaliado e descartado** como alternativa: embora fosse barato de plugar (reaproveitaria o bucket temporário do Athena e a IAM já existentes, sem precisar de secret novo), jobs batch do Transcribe tipicamente levam 15-60+ segundos até completar mesmo para áudios curtos — muito mais lento que os ~1-3s do Whisper via Groq, prejudicando a experiência de "gravar uma frase curta e ver o texto aparecer".

### Interface (`app.py`)
- Tema escuro com CSS customizado
- Grid responsivo de cards: 3 colunas fixas no desktop (`repeat(3, 1fr)`), 1 coluna no mobile (`≤768px`)
- Botão "Sair" no cabeçalho para encerrar a sessão autenticada
- **Rate limiting por IP:** máximo de 15 consultas por hora (janela deslizante). O contador é exibido abaixo do campo de texto; ao atingir o limite, o botão "Recomendar" é desabilitado e um countdown dinâmico MM:SS (JavaScript client-side via `st.components.v1.html`) mostra quanto tempo falta em tempo real, decrementando a cada segundo. Ao chegar em 00:00, a página recarrega automaticamente. O histórico de timestamps é mantido em dict no nível do módulo (`_ip_history`), indexado pelo IP do cliente via `X-Forwarded-For` — sobrevive a reloads da página (reseta apenas no restart do processo Streamlit, ex: deploy)
- **Limite de caracteres:** o `st.text_area` da preferência tem `max_chars=150` (`_MAX_PREFERENCE_CHARS`), aplicado tanto à digitação manual (o Streamlit trava a digitação ao atingir o limite) quanto ao texto vindo da transcrição de áudio (truncado antes de preencher o campo — ver seção de transcrição acima). Um contador "N / 150 caracteres" é exibido abaixo da caixa, atualizado em tempo real a cada tecla digitada via `static/contador_caracteres.js` (injetado por `load_preference_counter_script()` em `componentes.py`, mesmo padrão de `_inject_css`/`load_main_css`) — o script acessa o DOM da página (`window.parent.document`) através de um iframe same-origin (`st.components.v1.html`) e observa a textarea pelo hook `data-testid="stTextArea"`, já que o Streamlit não oferece rerun por-tecla nativamente. **Atenção:** por depender de um detalhe interno não documentado do Streamlit, esse contador pode quebrar silenciosamente em upgrades futuros de versão — `app.py` não tem teste automatizado, validação é manual (`streamlit run app.py`)
- **Auto-grow da caixa de texto:** a textarea nasce com altura de ~3 linhas e cresce sozinha conforme o texto ultrapassa esse espaço, via `static/auto_grow_textarea.js` (injetado por `load_textarea_autogrow_script()`, mesmo padrão de `contador_caracteres.js`/`window.parent.document`/`data-testid="stTextArea"`). Ajusta `textarea.style.height` para `scrollHeight` a cada evento `input` (e uma vez ao carregar, cobrindo o caso de texto pré-preenchido pela transcrição de áudio), com um teto de 200px além do qual a caixa passa a rolar internamente em vez de crescer (rede de segurança para colagem de texto com muitas quebras de linha). Mesma ressalva de dependência de estrutura interna não documentada do contador de caracteres acima.
- Botão "Cancelar" durante a busca: a recomendação roda em thread separada (`ThreadPoolExecutor`) com polling de 500ms, permitindo ao usuário cancelar a qualquer momento sem esperar a resposta completa
- Confirmação de áudio automática e invisível ("▶️ Usar gravação" / "✕ Cancelar", ver seção "Entrada alternativa" acima) — o rate limit de transcrições é resolvido diretamente em Python antes de renderizar os botões (escondidos), sem depender de clique em botão desabilitado
- Logging de erros: exceções na busca são registradas via `logging.exception()` e enviadas ao CloudWatch Logs (quando `CLOUDWATCH_LOG_GROUP` está configurada) para diagnóstico em produção
- Cada card exibe:
  - Imagem de fundo (backdrop preferido sobre poster)
  - Título, ano, tipo (filme/série) e badge de classificação indicativa (L/10/12/14/16/18)
  - Badges laranja por gênero (máx. 6 visíveis, sem indicador para o restante). Um gênero mencionado
    explicitamente pelo usuário (ex: "filmes de terror") é priorizado — `componentes.py::_prioritize()`
    o move para o início da lista antes do corte de 6, então ele nunca fica de fora se estiver presente
    no título
  - Onde assistir: rótulo + badges verdes 📺 com as plataformas de streaming no Brasil (máx. 6
    visíveis, sem indicador para o restante), seguido do badge amarelo 🎬 "Em cartaz até DD/MM/YYYY" quando
    `in_theaters=true`. Mesma priorização de `_prioritize()` para um provedor mencionado explicitamente
    (ex: "animações da Crunchyroll")
  - Linha compacta de "vitals": nota (★), data de lançamento (📅) e link ▶ Trailer (quando disponível),
    separados por "·"
  - Linha própria com a duração (⏱), logo abaixo
  - Sinopse e motivo da recomendação (gerado pelo LLM na Etapa 3, truncado em 3 linhas no desktop)

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Texto livre do usuário (ex: "filmes de ficção científica dos anos 80") |
| **Leitura** | Athena — tabela `tb_tmdb_discover_unified_{env}` (camada SPEC) |
| **Saída** | Cards de recomendação na interface web |

## Funções principais

| Arquivo | Função | Responsabilidade |
|---|---|---|
| `agent.py` | `recommend(user_input)` | Orquestra as etapas: verificar cache → gerar WHERE (LLM) → consultar → formatar (Python) → gerar motivo (LLM) |
| `agent.py` | `search_titles_spec(where_clause, limit)` | Valida o WHERE gerado pelo LLM e executa query SQL no Athena (limite máximo: 15) |
| `agent.py` | `_validate_where(where_clause)` | Valida a cláusula WHERE contra SQL perigoso (DROP, DELETE, INSERT, subqueries, UPDATE, ALTER, CREATE, GRANT, TRUNCATE, EXEC, MERGE, REPLACE, CALL) |
| `agent.py` | `_extract_highlighted_terms(where_clause)` | Extrai por regex os valores de `lower(genre_names) LIKE '%valor%'`/`lower(streaming_providers) LIKE '%valor%'` da where_clause gerada pelo LLM (ignora `NOT LIKE`), para priorizar as badges correspondentes nos cards sem chamada extra de LLM |
| `agent.py` | `_load_llm_api_key()` | Busca `LLM_API_KEY` no Secrets Manager (via `FILMBOT_SECRET_ARN`) em produção, ou usa `.env` como fallback em desenvolvimento |
| `agent.py` | `_cache_key(preference)` | Calcula o hash MD5 da preferência normalizada (lowercase + strip), usado como chave do cache de WHERE clauses |
| `agent.py` | `_get_cached_where(preference)` | Busca cláusula WHERE cacheada; retorna `None` se ausente ou expirada (TTL 1h) |
| `agent.py` | `_save_cached_where(preference, args)` | Salva cláusula WHERE no cache em memória com timestamp |
| `agent.py` | `_call_llm_step1(preference)` | Chama o LLM (`LLM_MODEL`) para gerar a cláusula WHERE via function calling |
| `agent.py` | `_call_llm_step3(preference, titles_for_llm)` | Chama o LLM (`LLM_MODEL`) para gerar o motivo de cada título já encontrado pelo Athena |
| `agent.py` | `_log_token_usage(step, response)` | Registra `prompt_tokens`, `completion_tokens`, `total_tokens` e `model` (`LLM_MODEL`) da resposta do LLM via `logging.info` (ver observação na seção "Observabilidade de tokens") |
| `agent.py` | `transcribe_preference(audio_bytes)` | Transcreve áudio (WAV) para texto via Whisper (`litellm.transcription`, modelo `TRANSCRIPTION_MODEL`). Rejeita áudios acima de 20s (`AudioMuitoLongoError`) antes de chamar a API. Sem fallback automático de modelo |
| `agent.py` | `_audio_duration_seconds(audio_bytes)` | Calcula a duração de um áudio WAV via módulo padrão `wave` |
| `agent.py` | `_load_transcription_api_key()` | Busca `transcription_api_key` no Secrets Manager (via `FILMBOT_SECRET_ARN`) em produção, ou `TRANSCRIPTION_API_KEY` do `.env` em desenvolvimento; retorna `None` (não quebra o app) se ausente |
| `formatacao.py` | `format_record(record)` | Converte um registro bruto do Athena em dict formatado para o card (tipo, gêneros, duração, data, nota, etc.) |
| `formatacao.py` | `_format_type()`, `_format_genres()`, `_format_title_duration()`, `_format_release_date()`, `_format_theater_end_date()`, `_format_rating()` | Funções puras de formatação de campos individuais |
| `app.py` | `_load_filmbot_password()` | Busca `filmbot_password` no Secrets Manager (via `FILMBOT_SECRET_ARN`) e grava `.streamlit/secrets.toml` (chmod 600) para a autenticação do Streamlit; não faz nada se o arquivo já existir |
| `app.py` | `_create_ip_history()`, `_create_audio_ip_history()` | Factories `@st.cache_resource` que criam os dicts compartilhados `_ip_history` (recomendações) e `_audio_ip_history` (transcrições), garantindo que os históricos de rate limiting sobrevivam a reruns e resetem apenas no restart do processo |
| `app.py` | `_get_client_ip()` | Obtém o IP do cliente via header `X-Forwarded-For`; confiar no primeiro valor só é seguro porque o Caddy sobrescreve o header (`header_up`) em vez de anexar — ver `deploy/Caddyfile` |
| `app.py` | `_queries_in_last_hour(history, ip)` | Conta consultas na última hora (janela deslizante) para o IP no histórico informado e limpa registros expirados. Reusada para recomendações (`_ip_history`) e transcrições (`_audio_ip_history`) |
| `app.py` | `_seconds_until_available(history, ip)` | Calcula quantos segundos faltam até a consulta mais antiga do IP expirar, no histórico informado |
| `app.py` | Interface Streamlit | Orquestra a UI: autenticação, gravação/transcrição de áudio, rate limiting, busca assíncrona e exibição de resultados |
| `componentes.py` | `load_login_css()`, `load_main_css()`, `load_preference_counter_script()`, `load_audio_cancel_script()`, `load_textarea_autogrow_script()`, `render_card()`, `render_grid()`, `render_footer()`, `render_login_footer()` | Helpers de renderização HTML com escape contra XSS |
| `componentes.py` | `_prioritize(items, terms)` | Reordena uma lista de badges (gêneros ou provedores) colocando primeiro as que contêm algum termo destacado (case-insensitive), preservando a ordem relativa dentro de cada grupo |
| `static/login.css` | CSS da tela de login | Estilos específicos da tela de autenticação |
| `static/principal.css` | CSS da página principal | Estilos do grid, cards e layout responsivo |
| `static/contador_caracteres.js` | Script do contador dinâmico do campo de preferência | Observa a textarea via `data-testid="stTextArea"` e atualiza o contador a cada tecla digitada |
| `static/audio_cancel_recording.js` | Script do ícone de descarte da gravação de áudio | Observa `[aria-label="Stop recording"]`; ao clicar no ícone 🗑, simula "parar" e auto-confirma o descarte via `localStorage` (ver seção "Entrada alternativa") |
| `static/auto_grow_textarea.js` | Script de auto-grow do campo de preferência | Observa a textarea via `data-testid="stTextArea"` e ajusta `style.height` ao `scrollHeight` a cada tecla digitada, com teto de 200px |

## Deploy

### Produção (Lightsail)

O app roda como serviço `systemd` (`filmbot.service`) na instância Lightsail, escutando apenas em `127.0.0.1:8501` (acesso local). O **Caddy** atua como proxy reverso na porta 80. O script `deploy/setup.sh` instala dependências, Caddy e configura ambos os serviços. O Terraform provisiona a instância (portas 22, 80 e 443) e o CI/CD faz o deploy via SSH ao fazer push na branch `main`.

Arquivos de deploy:
- `deploy/filmbot.service` — serviço Streamlit (bind em `127.0.0.1`)
- `deploy/caddy.service` — serviço Caddy (proxy reverso HTTPS)
- `deploy/Caddyfile` — configuração do Caddy (porta 80 → `localhost:8501`); sobrescreve `X-Forwarded-For` com `header_up` para o header sempre refletir o IP real do peer TCP, impedindo que um cliente forje esse valor e burle o rate limit por IP de `app.py`
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

Cada chamada a `litellm.completion()` (etapas 1 e 3) registra via `logging.info` os campos `prompt_tokens`, `completion_tokens`, `total_tokens`, `model` e `step` (`_log_token_usage()` em `agent.py`). Esses logs são enviados ao CloudWatch Logs (quando `CLOUDWATCH_LOG_GROUP` está configurada) e podem ser usados para criar métricas de custo e alertas de consumo.

`app.py` eleva o root logger para `ERROR` quando o CloudWatch está configurado (`logging.root.setLevel(logging.ERROR)`), para silenciar bibliotecas ruidosas. Como isso suprimiria por herança os `logger.info(...)` de `_log_token_usage()`, `agent.py` define explicitamente `logger.setLevel(logging.INFO)` no seu próprio logger — garantindo que os logs de tokens continuem passando pelo handler do root independentemente do nível herdado.
