# lightsail_ia — Aplicativo de Recomendações (FilmBot)

## O que é

O FilmBot é uma interface web construída com Streamlit e hospedada em uma instância AWS Lightsail. O usuário digita o que quer assistir em linguagem natural, e um agente de IA interpreta o pedido, consulta a tabela unificada na camada SPEC via Athena e retorna recomendações personalizadas com pôster, sinopse, avaliação e onde assistir. O acesso é multiusuário: cada pessoa se cadastra, aguarda aprovação manual de um admin e faz login com e-mail/senha próprios (Cognito User Pool — ver seção "Autenticação e administração").

## Por que existe

Permite que qualquer pessoa consuma os dados do pipeline sem precisar escrever SQL. O agente de IA atua como intermediário entre o pedido em linguagem natural e a base de dados estruturada.

## Como funciona

O processo de recomendação é dividido em três etapas encadeadas:

### Etapa 1 — Geração da cláusula WHERE (LLM + Function Calling, com cache)
O LLM recebe o texto do usuário e o schema completo da tabela SPEC. Usando *Function Calling*, gera a cláusula WHERE do SQL livremente, combinando qualquer coluna disponível:
```json
{
  "where_clause": "media_type = 'movie' AND original_language = 'ko' AND lower(genre_names) LIKE '%terror%' AND vote_average >= 7.0",
  "limit": 8
}
```
Essa abordagem "livre" permite que qualquer combinação de filtros seja usada sem precisar mapear cada pergunta possível no código (ex: idioma, duração, país de origem, temporadas, plataforma de streaming, em cartaz, diretor, elenco). O limite máximo de resultados é 15, mas a descrição do parâmetro `limit` na `TOOL` orienta o LLM a pedir por padrão um valor entre 6 e 9 (`_DEFAULT_RECOMMENDATION_COUNT = 8` é o valor usado quando o LLM omite `limit` de todo) — só um número maior, até o teto, quando o usuário pedir explicitamente mais opções ou uma quantidade específica. Motivo: a Etapa 3 gera um "motivo" (texto) por título recomendado, e geração de texto por LLM é sequencial (token a token) — normalmente a parte mais lenta de qualquer chamada. Recomendar menos títulos por padrão corta quase pela metade esse tempo de geração, sem tirar do usuário a opção de pedir mais.

**Destaque de gênero/provedor nas badges:** `_extract_highlighted_terms()` extrai por regex os valores de `lower(genre_names) LIKE '%valor%'` e `lower(streaming_providers) LIKE '%valor%'` de volta da própria `where_clause` gerada pelo LLM — reaproveita uma decisão que o LLM já tomou no Passo 1, sem chamada extra de LLM. Cláusulas `NOT LIKE` são ignoradas (o usuário não quer aquele valor, não deve ser destacado). O resultado é anexado a cada registro formatado como `highlighted_genres`/`highlighted_providers` e usado por `components.py::_prioritize()` (ver seção "Interface") para colocar o gênero/provedor mencionado primeiro nas badges do card.

O schema informado ao LLM inclui colunas de ficha técnica como `director` e `actor_names` (além de `screenplay`, `music_composer`, `producer`, `cinematographer`, `editor`), permitindo buscas como "filmes do Christopher Nolan" ou "filmes com Tom Hanks" — todos esses campos também são exibidos no card, na seção "Ficha Técnica" (ver seção "Interface").

**Cache de WHERE clauses:** a cláusula WHERE gerada pelo LLM é armazenada em cache em memória (dict no módulo), indexada pelo hash SHA-256 da preferência normalizada (lowercase + strip). Consultas repetidas (ex: "filmes de terror" digitado duas vezes) reutilizam a cláusula cacheada sem chamar o LLM novamente. TTL de 1 hora — compatível com a frequência de atualização semanal dos dados SPEC. O cache é limpo automaticamente ao reiniciar o processo Streamlit. Como o destaque de gênero/provedor (`_extract_highlighted_terms()`) é derivado da mesma `where_clause` cacheada, um cache hit reproduz exatamente o mesmo destaque de uma chamada fresca ao LLM.

**Piso de nota (`vote_average >= 6.0`) com exceção para lançamentos futuros:** o `_SYSTEM_PROMPT` instrui o LLM a incluir `vote_average >= 6.0` por padrão (salvo se o usuário pedir nota diferente), como piso de qualidade para pedidos genéricos ("me recomenda um filme bom"). A exceção: quando o pedido é sobre lançamentos futuros/títulos ainda não estreados (ex: "o que vai estrear", "em breve", filtro por `theatrical_release_date_br`/`air_date` futuro ou `title_status = 'Post Production'`), o LLM é instruído a **não** incluir esse filtro — título não lançado ainda não teve chance de acumular voto, então `vote_average` baixo/zerado o excluiria do resultado mesmo estando bem posicionado por popularidade (ver Etapa 2, título com badge "Em breve").

**Degradação graciosa em JSON inválido:** ocasionalmente o LLM retorna os argumentos da tool call malformados (aspas não escapadas, resposta cortada) — um `json.decoder.JSONDecodeError` já observado em produção. Esse cenário não derruba a recomendação: é tratado como "nenhum filtro extraído" (mesmo caminho de quando o LLM não chama a tool nenhuma), loga um `logger.warning` com os argumentos brutos para diagnóstico, e `recommend()` retorna lista vazia — o usuário vê "não encontramos nada com essa descrição" em vez do erro genérico. A resposta malformada não é cacheada, então uma nova tentativa pode ter sucesso.

### Etapa 2 — Consulta ao Athena
A cláusula WHERE gerada pelo LLM é validada (`_validate_where()` bloqueia SQL perigoso como DROP, DELETE, INSERT, subqueries) e executada na tabela `tb_tmdb_discover_unified_{env}` (camada SPEC), sem nenhum filtro fixo de qualidade por `vote_count` — a relevância vem só de `ORDER BY popularity DESC` (abaixo) e do pool+sorteio. Isso inclui de graça títulos com `air_date` futuro (ainda não lançados, badge "Em breve" no card — ver seção "Interface"), que nunca tiveram chance de acumular voto; antes existia um filtro fixo `vote_count >= 50` com um bypass explícito só pra esse caso (`vote_count >= 50 OR air_date > CURRENT_DATE`), removido por ser redundante com a ordenação por popularidade — o LLM ainda pode usar `vote_count` na própria `where_clause` quando o pedido do usuário pedir explicitamente por títulos bem votados/consagrados.

**Pool de candidatos + sorteio (variedade entre buscas):** a query busca um pool maior que o `limit` pedido — `min(limit * _CANDIDATE_POOL_MULTIPLIER, _CANDIDATE_POOL_MAX)` títulos, ordenados por popularidade (padrão: multiplicador 3x, teto de 30) — e `search_titles_spec()` sorteia um subconjunto de `limit` títulos desse pool, preservando a ordem de popularidade entre os escolhidos. Sem isso, a mesma pergunta (ou uma parecida, já que o LLM tende a gerar a mesma `where_clause`) sempre devolveria exatamente o mesmo top-N por popularidade — a ordenação fixa da query, não só o cache, é que causava a repetição. Como a Etapa 2 roda em toda busca (mesmo em cache hit do Passo 1 — só a cláusula WHERE é cacheada, não os títulos), a variedade acontece sempre, sem custo adicional de LLM. **Valores conservadores de propósito:** a instância Lightsail de produção tem só 1 GB de RAM (bundle `micro_3_0`) — cada linha a mais do pool aumenta proporcionalmente o payload de boto3 carregado na memória por busca, então o teto fica bem abaixo do que daria pra buscar sem problema numa instância maior. Com o `limit` padrão de 8 (Etapa 1), o pool padrão cai de 30 para 24 linhas — efeito colateral positivo da redução de quantidade de recomendações.

**Polling da execução no Athena:** `search_titles_spec()` aguarda a query terminar com `time.sleep(0.3)` entre verificações de status (antes: 1s fixo). Queries do FilmBot levam ~2-5s no Athena; um poll mais frequente reduz a espera "morta" entre a query terminar de verdade e o próximo poll perceber isso (até ~700ms de cauda por request com o intervalo antigo de 1s). Backoff progressivo continua não sendo necessário — o custo de cada poll é mínimo (API leve) mesmo com mais chamadas.

### Etapa 2.5 — Formatação determinística (formatting.py)
Após o Athena retornar os resultados brutos, funções puras em `formatting.py` (`format_record()`) convertem cada registro em campos prontos para o card da interface, sem usar LLM:
- `title` (cópia de `title`), `type` (`"movie"` → `"filme"`, `"tv"` → `"série"`)
- `year` (inteiro), `genres` (lista de strings a partir de `genre_names`)
- `overview` (cópia de `overview` — já vem em pt-BR do pipeline via `COALESCE(overview, overview_pt, overview_en)`)
- `rating` (float), `poster_url`, `backdrop_url`
- `duration` (runtime formatado para filmes: `"2h 26min"`; temporadas/episódios para séries, por extenso — só `min/ep` fica abreviado: `"3 temporadas · 36 episódios · ~45 min/ep"`)
- `release_date` (mês por extenso + ano em PT derivado de `air_date`, ex: `"Maio de 1980"`)
- `streaming_providers` (cópia direta — onde assistir no Brasil), `streaming_provider_logos` (URLs de logo do TMDB, comma-joined e **posicionalmente alinhadas** a `streaming_providers` — item vazio quando aquele provedor não tem logo na origem, ver `glue_agg/src/queries.py`)
- **Formatação adaptativa de data** (`formatting.py::_format_adaptive_date()`, compartilhada por
  `theater_end_date`, `next_episode_date` e `upcoming_date` abaixo): `DD/MM` quando a data está a até
  `_ADAPTIVE_DATE_THRESHOLD_DAYS` (90) dias de hoje, ou "Mês de Ano" (mesmo formato de `release_date`, via
  `_format_release_date()`) quando está mais distante. Critério é só a distância em dias — não olha se cruza o
  ano-calendário — evitando o caso estranho de uma data a 10 meses de distância (mas ainda "esse ano") ganhar dia
  exato enquanto outra a 4 meses (já "ano que vem") não ganhasse. Motivo: dia exato só é confiável/relevante perto
  da data — datas bem mais distantes (lançamento anunciado com muita antecedência, ou próximo episódio depois de
  uma pausa longa de temporada) costumam ter só mês/ano confirmado no TMDB, com o dia sendo um placeholder que
  muda depois. `format_record()` aceita um `today` opcional (repassado a essa função e a `_is_upcoming()`) só pra
  testes determinísticos — em produção nunca é passado
- `in_theaters` (boolean), `theater_end_date` (string formatada conforme acima, ou `null`)
- `next_episode_season_number`/`next_episode_number` (inteiros, apenas séries), `next_episode_date` (string
  formatada conforme acima, derivada de `next_episode_air_date`) — `null`/`None` quando a série não tem episódio
  futuro confirmado
- `upcoming_date` (string formatada conforme acima, `null`/`None` caso contrário) — só preenchido quando a data
  fonte é estritamente futura (título ainda não lançado, `formatting.py::_is_upcoming()`). A fonte prioriza
  `theatrical_release_date_br` (data de estreia teatral BR agendada, extraída de `release_dates` pelo
  `glue_details` — mais precisa que a data global do TMDB), com `air_date` como fallback para título sem essa
  coluna ainda (não enriquecido, ou sem estreia teatral BR cadastrada). Usado pro badge "Em breve" (ver seção
  "Interface")
- `title_status` (cópia direta de `title_status` — o `status` bruto do TMDB já traduzido pra PT-BR na SPEC via
  `CASE`, ver `glue_agg/src/queries.py`: `"Lançado"`, `"Encerrada"`, `"Cancelado"`, `"Em Produção"`,
  `"Planejado"`, `"Pós-Produção"`, `"Rumor"`, `"Piloto"`) — `null`/`None` quando o título ainda não foi
  enriquecido pelo `glue_details` (sem match no LEFT JOIN com `details`). Usado como fallback da `cinema-row`
  quando nenhum dos outros três estados se aplica (ver seção "Interface")
- `cast` (top 5 atores), `director` (filmes e séries), `creators` (apenas séries), `writers` (escritores/roteiristas), `composer` (compositor da trilha sonora), `producer` (produtores/produtores executivos), `cinematographer` (diretor de fotografia) e `editor` (editor/montador) são renderizados no card, na seção "Ficha Técnica" (ver seção "Interface") — um bullet por papel presente
- `tagline` — campo formatado mas atualmente não renderizado por `render_card()` (`components.py`), junto com `collection` e `networks`
- `keywords` (tags temáticas em português), `certification` (classificação indicativa BR: L/10/12/14/16/18)
- `trailer_url` (link do YouTube), `collection` (saga/franquia, apenas filmes)
- `production_companies` (estúdios), `production_countries` (países de produção, diferente de país de origem)
- `networks` (redes originais, apenas séries)
- `rent_buy_providers` (plataformas de aluguel/compra no Brasil), `rent_buy_provider_logos` (mesmo esquema de `streaming_provider_logos` acima)
- `recommended` (títulos recomendados pelo TMDB), `similar` (títulos similares), `alternative_titles` (nomes regionais)

### Etapa 3 — Geração do motivo (LLM)
O LLM recebe apenas os campos que ajudam a justificar a recomendação de cada título já encontrado pelo Athena — `id`, `title`, `overview`, `genre_names`, `year`, `vote_average`, `director`, `actor_names`, `streaming_providers`, `certification`, `keywords_pt` — e gera um `reason` curto (1 frase) explicando por que aquele título específico atende ao pedido do usuário, podendo citar diretor/elenco/streaming/classificação/palavras-chave quando fizerem parte do motivo real. Retorna JSON com apenas `id` e `reason` por título (`{"titles": [...]}`), mesclado por índice ao registro já formatado pelo Python. O merge é tolerante a variações de resposta do LLM: aceita `id` como int ou string (converte via `int()`), aceita tanto `{"titles": [...]}` quanto lista direta `[...]`, e degrada para `reason=""` em caso de resposta vazia ou JSON inválido — uma falha aqui nunca derruba a recomendação.

`overview` é truncado a `_MAX_OVERVIEW_CHARS_FOR_LLM` (400 caracteres) antes de entrar no payload — é o campo que mais pesa no tamanho da entrada, e um trecho já dá contexto suficiente pro motivo sem repassar sinopses inteiras.

Esta etapa roda em toda busca com resultados, mesmo quando a Etapa 1 tem cache hit: os títulos reais só existem depois da consulta ao Athena, então o motivo não pode ser cacheado junto com a cláusula WHERE.

### Confiabilidade e latência das chamadas LLM (`timeout`, `max_tokens`, `num_retries`)

As duas chamadas `litellm.completion()` (Etapas 1 e 3) usam:
- `num_retries=3` — configurado deliberadamente após um problema real de indisponibilidade/erro transitório com o provedor DeepSeek. Não é pra remover: tirar isso pra ganhar latência trocaria "às vezes demora mais" por "às vezes quebra de novo".
- `timeout` explícito por tentativa — `_LLM_TIMEOUT_STEP1_SECONDS = 60` e `_LLM_TIMEOUT_STEP3_SECONDS = 90`. Sem isso, o padrão do litellm é 600s (10 minutos) por tentativa: uma chamada travada (não um erro, só sem resposta) ficaria esperando isso antes de sequer entrar no retry. É uma rede de segurança contra travamento, não um redutor de latência do caso normal — os valores são generosos de propósito, pra não abortar uma resposta normal só um pouco lenta (o que dispararia um retry desnecessário e pioraria a latência). Recalibrados a partir dos 10s/15s iniciais depois de estourarem consistentemente (`litellm.Timeout` real, visto via CloudWatch em dev) com `deepseek-v4-pro`, mais lento que o modelo usado quando os valores originais foram definidos (ver `_log_step_latency` abaixo para a instrumentação que permite validar isso com dado real).
- `max_tokens` explícito — `_LLM_MAX_TOKENS_STEP1 = 300` (saída pequena, só `where_clause`+`limit` via tool call) e `_LLM_MAX_TOKENS_STEP3 = 1500` (motivos de até 15 títulos). Generoso o bastante pra nunca truncar uma resposta normal — só dá um teto à latência de cauda de uma resposta anormalmente verbosa.

**Instrumentação de latência por passo:** `_log_step_latency(step, elapsed_seconds)` registra via `logger.info` (mesmo padrão de `_log_token_usage()`) o tempo decorrido de cada etapa — `step1_where`, `step2_athena`, `step3_reasons` — chamada em `recommend()` ao redor de cada uma. Complementa o log de tokens já existente (que mede volume, não tempo) e permite validar com dado real de produção o efeito de mudanças de latência (redução de quantidade de recomendações, polling do Athena, etc.) em vez de depender de suposição.

### Entrada alternativa — Transcrição de áudio (Whisper via litellm)
Além de digitar, o usuário pode gravar a preferência em áudio pelo widget nativo `st.audio_input`. Ao parar a gravação, o app confirma automaticamente e transcreve por `transcribe_preference()` (`agent.py`) usando Whisper via `litellm` — modelo configurável por `TRANSCRIPTION_MODEL` (padrão: Groq Whisper Large v3 Turbo, rápido e barato), com `language="pt"` fixo. O texto resultante pré-popula o `st.text_area` de preferência, permanecendo totalmente editável antes de clicar em "Recomendar". Visualmente, o bloco de gravação aparece numa única linha logo abaixo do campo de texto: só os botões do gravador nativo (sem waveform, sem fundo/borda ao redor, direto sobre o fundo escuro do app) encolhidos ao próprio conteúdo, com o badge de timer colado logo ao lado, sem label/emoji. Divide espaço com o contador de caracteres (que fica à direita dessa mesma linha) — ordem inversa à do processamento em Python: o áudio ainda roda antes do `text_area` no script (restrição de `session_state`), mas aparece depois na tela, via containers-placeholder criados na ordem visual desejada (`text-area-slot` / `input-footer-row` em `recommendation.py`) e populados fora dessa ordem. Os dois placeholders vivem dentro de um card único (`st.container(key="input-card")`, fundo `#1a1a1a` + borda, `recommendation.css`) que substitui o fundo que antes era só da textarea — unifica textarea + gravador + contador num painel só, com glow laranja no `:focus-within` do card (não mais `:focus` da textarea) quando o usuário digita. A textarea em si (e o wrapper nativo `stTextAreaRootElement`, que carregava um fundo/borda claros próprios — zerados via CSS) ficam transparentes por dentro do card. Os avisos de transcrição (rate limit, áudio muito longo, erro, vazio, truncado — ver lista abaixo) ficam **fora** desse card, num placeholder próprio (`audio_messages_slot = st.container(key="audio-messages")`) criado logo depois do `input-card` — são feedback sobre uma ação já concluída/rejeitada, não parte do "formulário" em si. Só a mensagem transitória "🎤 Transcrevendo áudio..." continua dentro do card, junto do gravador, por ser um estado em andamento e não um aviso.

- **Confirmação automática e invisível:** o `st.audio_input` nativo não expõe nenhuma forma de cancelar uma gravação **em andamento** (o único botão durante o estado `recording` é "parar", que sempre finaliza e envia o áudio para o backend) — essa limitação foi confirmada inspecionando o bundle JS interno do widget. Por isso existe uma etapa intermediária entre "gravação parou" e "chamar a API de transcrição" (`audio_awaiting_confirmation`/`audio_pending_bytes`), com dois botões internos ("▶️ Usar gravação" / "✕ Cancelar", dentro de `st.container(key="audio-confirm-buttons")`) — mas eles ficam **escondidos via CSS** (`.st-key-audio-confirm-buttons { display: none; }` em `recommendation.css`) porque o usuário nunca precisa clicar neles à mão: `audio_cancel_recording.js` confirma "Usar gravação" automaticamente assim que os botões aparecem, a menos que o ícone de descarte (abaixo) já tenha sinalizado cancelamento. `audio_widget_seq` é incrementado tanto ao descartar quanto ao confirmar (`use_clicked`) para forçar uma nova instância do `st.audio_input` (troca de `key`) — o único jeito de "esvaziar" visualmente um áudio já gravado, já que o widget não tem API para isso. Sem esse reset também no caminho de sucesso, o widget nativo mantém internamente `recordingUrl` da última gravação e passa a renderizar um segundo botão "▶️ Play" ao lado do de gravar indefinidamente — inofensivo hoje (a caixa nativa acomoda naturalmente qualquer botão extra, ver `recommendation.css`), mas sem sentido nesse fluxo (a gravação já foi usada), daí o reset.
- **Ícone de descarte durante a gravação:** `static/js/audio_cancel_recording.js` (injetado por `load_audio_cancel_script()`, mesmo padrão de `contador_caracteres.js`) mostra um ícone ✕ em vermelho ao lado do botão nativo enquanto o estado é `recording`. Como a função interna `cancel()` do gravador não é acessível fora do componente React, o ícone simula "parar" (clica no botão nativo) e arma uma flag em `localStorage`; assim que o botão (escondido) "✕ Cancelar" aparece, o script clica nele automaticamente em vez de confirmar "Usar gravação", descartando o áudio sem nunca chamar `transcribe_preference`. Como os botões de confirmação nunca ficam visíveis, não há nenhum "flash" de UI perceptível ao usuário — só uma pausa breve entre parar e transcrever (ou entre parar e resetar, no caso do descarte). O toolbar nativo do elemento (`data-testid="stElementToolbar"`, com os ícones "Download as WAV"/"Clear recording" que o Streamlit mostra por conta própria assim que a gravação para) também fica escondido via CSS (`recommendation.css`) pelo mesmo motivo — sem relação com o fluxo de confirmação/descarte, só ruído visual nessa pausa.
- **Limite de duração:** o `st.audio_input` nativo não tem parâmetro de duração máxima — sem intervenção, a pessoa gravaria pelo tempo que quisesse. `static/js/audio_timer.js` (injetado por `load_audio_timer_script(_MAX_AUDIO_SECONDS)`, mesmo padrão de `contador_caracteres.js`/`window.parent.document`) para a gravação sozinha ao atingir o limite: a cada 250ms, converte o tempo decorrido do timer nativo do widget (hook não documentado `data-testid="stAudioInputWaveformTimeCode"`, formato "MM:SS") pra segundos totais e, se `>= _MAX_AUDIO_SECONDS`, clica no próprio botão nativo `[aria-label="Stop recording"]` — testado de ponta a ponta via Playwright com um device de áudio fake, gravação real interrompida sozinha entre 14s e 16s. Como esse polling de 250ms pode deixar passar um pouquinho além do limite antes de clicar, e como esse auto-stop não coordena com `audio_cancel_recording.js` (que, sem essa checagem, empurraria por padrão o áudio pro fluxo de "Usar gravação"), a duração é validada em Python assim que os bytes chegam em `recommendation.py` — antes de decidir entre o fluxo de confirmação (`audio_awaiting_confirmation`) e a rejeição — usando `_audio_duration_seconds()` (`agent.py`, módulo padrão `wave`, já que `st.audio_input` sempre entrega WAV). Se a duração exceder `_MAX_AUDIO_SECONDS`, o áudio nunca entra no fluxo de confirmação (não é enviado para transcrição) e o aviso "⚠️ Áudio muito longo" aparece de forma imediata, independente de qual script JS tiver parado a gravação. A validação de duração dentro de `transcribe_preference()` (`agent.py`) continua existindo como segunda camada de defesa. O limite é exibido pro usuário como um badge "decorrido / máximo" (ex: `00:07 / 00:15`) à direita do gravador nativo, atualizado em tempo real pelo mesmo script — mesma ressalva de fragilidade a upgrades de versão do Streamlit do contador de caracteres (ver abaixo). O timer nativo do widget continua sendo lido pelo script, mas fica escondido via CSS (`display: none` em `recommendation.css`) para não duplicar visualmente o mesmo tempo já exibido pelo badge.
- **Degradação graciosa:** qualquer falha na transcrição (provedor indisponível, sem API key configurada, áudio sem fala detectada, áudio muito longo) nunca bloqueia o campo de texto — a pessoa sempre pode digitar manualmente.
- **Rate limiting próprio:** 30 transcrições por hora por IP (`_MAX_TRANSCRIPTIONS_PER_HOUR`), mais generoso que o limite de recomendações porque o custo de Whisper é bem menor que o fluxo LLM+Athena. Usa um histórico de IPs independente (`_audio_ip_history`) do fluxo de recomendação. Ao atingir o limite, a mesma mensagem já reúne o cronômetro MM:SS (`load_countdown_script(_audio_seconds, element_id="audio-countdown")`) e o lembrete de digitar manualmente enquanto isso — `element_id` explícito porque esse countdown pode estar visível ao mesmo tempo que o da busca (rate limits independentes), e os dois usando `id="countdown"` colidiria no DOM
- **Execução assíncrona:** mesmo padrão de `ThreadPoolExecutor` + `Future` + polling (500ms) já usado no botão "Recomendar", com chaves de `session_state` próprias (`transcribing`/`transcription_future`, além de `audio_awaiting_confirmation`/`audio_pending_bytes`/`audio_widget_seq` da etapa de confirmação) para não colidir com o fluxo de busca.
- **Limite de caracteres:** transcrições acima de 150 caracteres (`_MAX_PREFERENCE_CHARS`) são cortadas nesse limite antes de preencher o campo de texto, com aviso "⚠️ Transcrição excedeu 150 caracteres e foi cortada." — necessário porque o `st.text_area` de destino também tem `max_chars=150` e rejeitaria um valor de `session_state` maior que isso.
- **AWS Transcribe foi avaliado e descartado** como alternativa: embora fosse barato de plugar (reaproveitaria o bucket temporário do Athena e a IAM já existentes, sem precisar de secret novo), jobs batch do Transcribe tipicamente levam 15-60+ segundos até completar mesmo para áudios curtos — muito mais lento que os ~1-3s do Whisper via Groq, prejudicando a experiência de "gravar uma frase curta e ver o texto aparecer".

### Autenticação e administração (`forms.py`, `admin.py`, `infrastructure.py` — Cognito User Pool)

Substituiu a antiga senha única compartilhada. Todo o estado de usuário (identidade, senha, aprovação, grupo admin) mora no Cognito — não existe tabela própria (DynamoDB/RDS) neste app; o Cognito já é o armazenamento persistente e sobrevive ao ciclo de destruição/recriação diária da instância Lightsail (`.github/workflows/lightsail_scheduler.yml`). Recursos provisionados em `infra/lightsail_ia.tf`: `aws_cognito_user_pool.filmbot`, `aws_cognito_user_pool_client.filmbot` (sem client secret — todas as chamadas partem do backend via boto3, nunca do navegador) e `aws_cognito_user_group.admins`.

Cinco telas, alternadas dentro do mesmo `app.py` via `st.session_state["auth_view"]`/`st.session_state["current_view"]` (nunca multipage nativo do Streamlit — evitaria vazar a existência da tela de admin/perfil na sidebar/URL para quem ainda não fez login):

- **Login** (`forms.py::_render_login_form`) — e-mail + senha, valida via `infrastructure.authenticate()` (`AdminInitiateAuth`). Dois botões-link levam a Cadastro/Esqueci a senha.
- **Novo cadastro** (`_render_signup`/`_render_signup_confirm`, controlado por `st.session_state["auth_view"]` indo de `"signup"` → `"signup_confirm"` → `"signup_success"`) — nome/e-mail/senha/confirmar, depois um passo de confirmação de e-mail por código. No desktop, Nome Completo + E-mail + Senha + Confirmar senha ficam todos empilhados numa coluna de ~50% e o painel de requisitos (título "Requisitos da senha" + `render_password_requirements()`, com borda/fundo translúcido) na coluna de ~50% ao lado — replicando exatamente `profile.py::render_password_tab` (mesmo molde de `_render_forgot_password_confirm`, só com 4 campos em vez de 3), via `st.container(key="password-fields-row")` + `st.columns(2, gap="medium")`, mesma CSS de `base.css` (`.st-key-password-fields-row`), sem nada específico do cadastro. Pedido do usuário para o card ficar mais largo (640px) só nesta tela e em "Esqueci a senha" (etapa 2, mesma key `password-fields-row`) — diferente das outras 5 sub-telas de autenticação (440px), que não têm campos suficientes pra parear e ficariam com espaço vazio nos 640px (ver seção "Estilo (CSS)" pra como `forms.css` diferencia as duas larguras via `:has(.st-key-password-fields-row)`, já que todas compartilham a mesma key `"form-card"`). No mobile os pares colapsam empilhados 100%, colapso nativo do `st.columns`, sem CSS de media query. `_render_signup` chama `infrastructure.sign_up()` (só `SignUp` — a conta fica `Enabled=true`, o padrão) e vai para `"signup_confirm"`; o pool tem `auto_verified_attributes = ["email"]` + `verification_message_template` configurados (`infra/lightsail_ia.tf`), então o **próprio `SignUp` já dispara o primeiro código** por e-mail, sem uma chamada explícita de "enviar" (diferente do reset de senha). `_render_signup_confirm` pede o código, chama `infrastructure.confirm_sign_up()` (`ConfirmSignUp` — `UserStatus` vira `CONFIRMED` e `email_verified` fica `true` sozinho, efeito de estar em `auto_verified_attributes` — e só então `AdminDisableUser`) e, com a conta já confirmada e desabilitada, chama `infrastructure.notify_new_signup()` (publica no tópico SNS `filmbot_new_signup`, para o admin saber que há alguém esperando aprovação sem precisar checar o painel periodicamente) antes de ir para `"signup_success"`. Cadastro novo tem, portanto, dois estados pendentes distintos: **aguardando confirmar e-mail** (`UNCONFIRMED`+`Enabled` — Cognito já bloqueia login nativamente nesse estado, `UserNotConfirmedException`, então não precisa desabilitar nesta janela) e **aguardando aprovação do admin** (`CONFIRMED`+`Disabled`, ver bullet "Painel admin" abaixo). A premissa original era que a primeira janela durasse só minutos e por isso não precisasse aparecer no painel — na prática, cadastros abandonados nesse estado (e-mail nunca chegou, código expirou, usuário fechou a aba) ficavam parados por dias, invisíveis nas duas listas do painel (`list_pending_users()`/`list_active_users()` descartam `UNCONFIRMED` cada uma a seu jeito) e sem alerta (`notify_new_signup()` só dispara depois da confirmação). Por isso existe uma terceira função, `list_unconfirmed_users()`, que também aparece no painel — ver bullet "Painel admin" abaixo. Desabilitar a conta só depois do `ConfirmSignUp` (não antes, dentro do próprio `sign_up()`) é o ponto crítico, **na direção oposta do que pareceria intuitivo**: testado empiricamente contra o Cognito real, `ConfirmSignUp` rejeita **qualquer** código — inclusive o certo — com `CodeMismatchException` (mensagem enganosa) quando a conta já está `Disabled`; desabilitar cedo demais quebra a própria confirmação. A tela de confirmação reaproveita integralmente o padrão de rate limit do reset de senha (bullet abaixo): cooldown de reenvio de 60s via `@st.fragment(run_every=1)` (`_signup_code_send_history`, contado a partir do sucesso do `sign_up()` — não de uma ação de "enviar" separada) e lockout de 3 tentativas de código incorreto em 60s via `load_countdown_script`/reload (`_signup_code_attempt_history`), com o mesmo trade-off de UX já aceito no reset (perde o progresso do formulário após 3 tentativas erradas). `authenticate()` retorna `"pending"` tanto para "ainda não confirmou o e-mail" quanto para "conta desabilitada aguardando aprovação" — a tela de login não distingue os dois casos na mensagem. **Retomando um cadastro abandonado:** quem fecha a aba antes de digitar o código tem dois caminhos de volta, ambos passando pela mesma função central, `_start_signup_resume(email, client_ip)`. **Caminho 1 — link dedicado:** o botão "Já iniciei um cadastro e perdi o código" em `_render_signup` leva a uma sub-tela nova, `signup_resume` (`_render_signup_resume_request`), que pede **só o e-mail** — mesmo padrão de "e-mail primeiro" já validado em "Esqueci a senha" (bullet abaixo). **Caminho 2 — reenvio acidental do formulário completo:** reenviar o mesmo formulário de cadastro (nome/e-mail/senha/confirmar) com um e-mail já existente ainda bate em `UsernameExistsException` (`SignUp` do Cognito rejeita qualquer username já existente, mesmo `UNCONFIRMED`, diferente de `ForgotPassword`, que é idempotente) — `_render_signup` captura essa exceção e cai no mesmo `_start_signup_resume()`, descartando a senha que acabou de ser digitada (ver adiante por quê). Nos dois caminhos, `_start_signup_resume()` chama `get_user_status(email)` (mesma função já usada em "Esqueci a senha") e, se `UNCONFIRMED`, reenvia o código (`resend_confirmation_code()`, mesma chamada do botão "Reenviar código" de `_render_signup_confirm`) — reaproveitando o cooldown de 60s já existente (`_signup_code_send_history`/`_RESEND_LOCKOUT_SECONDS`: se um código já saiu há pouco, só redireciona sem reenviar de novo — e busca o nome já gravado no Cognito via `infrastructure.get_unconfirmed_signup_name()` (`ListUsers` filtrado por e-mail, mesmo padrão de `get_user_profile()`), guardando email/nome em `session_state` (`signup_email_confirmed`/`signup_name_confirmed`) mais a flag `signup_resumed`, e retorna `"ok"` (o chamador troca pra `signup_confirm`), `"not_pending"` (e-mail não existe ou já foi confirmado — cada chamador decide a própria mensagem: o link dedicado avisa "Não encontramos um cadastro pendente..."; o formulário completo cai na mensagem genérica "Esse e-mail já está cadastrado.", `_signup_error_message()`) ou `"resend_failed"` (erro real do Cognito ao reenviar). Diferente do desenho anterior, **nome e senha não são mais coletados antes do código, nem na mesma tela em que o código é digitado** — `_render_signup_confirm` continua sendo só o campo código pra todo mundo (retomado ou não); ao suceder `confirm_sign_up()`, se `signup_resumed` for `True`, em vez de ir direto pra `"signup_success"` a função seta `st.session_state["signup_resume_step"] = "details"` e dá `st.rerun()` — no próximo render, `_render_signup_confirm` detecta esse estado logo no topo e delega pra uma segunda função, `_render_signup_resume_details(client_ip, email, name)`, que pede Nome (`value=` pré-preenchido com o nome já gravado, editável — caso tenha sido digitado errado da primeira vez), E-mail (`disabled=True`) e Senha/Confirmar senha (sempre em branco), no mesmo layout de duas colunas (`password-fields-row` + requisitos de senha) do cadastro normal, com um link "← Voltar" que retorna a `signup_resume_step = "code"`. Isso elimina a janela em que uma senha nova ficava em texto plano em `session_state` durante toda a espera do código (podendo durar minutos): agora a senha só existe no request que já a aplica, na tela seguinte. Essa separação em duas telas só é possível aqui porque `ConfirmSignUp` não exige senha nenhuma no request — **diferente de "Esqueci a senha" (bullet abaixo), onde `ConfirmForgotPassword` exige a senha nova no mesmo request do código** (confirmado na doc oficial da API: parâmetro `Password` é obrigatório) e por isso continua sendo uma única tela ali. `infrastructure.notify_new_signup()` também migrou de lugar: agora é chamado sempre logo após `confirm_sign_up()` ter sucesso (antes do `if resumed`), não mais só no caminho não-retomado — semanticamente mais correto, já que o admin precisa saber assim que a conta vira `CONFIRMED`+`Disabled`, independente de quando a pessoa termina de preencher nome/senha na tela seguinte. A aplicação de fato da senha continua deliberadamente adiada para **depois** de `confirm_sign_up()` validar o código: gravar a senha antes disso seria uma janela de account takeover — pedir um reenvio de código é uma ação que qualquer um sabendo o e-mail alheio pode disparar, sem provar posse da caixa de entrada; se a senha fosse gravada nesse instante, um atacante que soubesse o e-mail de alguém com cadastro pendente poderia definir a própria senha ali, e a vítima, ao confirmar o código real recebido por e-mail (achando que está só terminando o próprio cadastro), ativaria a conta com a senha do atacante sem ele nunca precisar ver o código. Por isso `_render_signup_resume_details`, na tela separada, chama `infrastructure.apply_resumed_signup(email, password, name)` com o que foi digitado ali — a posse do código já é a prova de identidade necessária, mesmo racional de `confirm_password_reset()` (bullet abaixo), que troca a senha no mesmo passo em que valida o código de recuperação, sem reautenticação extra. `apply_resumed_signup()` não reaproveita `change_password()`: ele reautentica via `authenticate()` (`AdminInitiateAuth`) antes de trocar a senha, mas nesse ponto a conta já foi desabilitada por `confirm_sign_up()` (aguardando aprovação do admin) e `AdminInitiateAuth` falharia numa conta `Disabled`. Abandonar a tela de dados finais é seguro: a conta já ficou `CONFIRMED`+`Disabled` com a senha **original** do primeiro cadastro ainda válida (nunca foi sobrescrita), então o pior caso é só "não trocou a senha/nome dessa vez", não um lockout.
- **Esqueci a senha** (`_render_forgot_password_request`/`_render_forgot_password_confirm`, controlado por `st.session_state["reset_step"]`) — único fluxo com código: e-mail → **checa se já existe cadastro** (`infrastructure.user_exists()`, `ListUsers` filtrado por `email`) → se não existir, mostra "Esse e-mail ainda não tem cadastro. Crie uma conta para continuar." e não chama o Cognito; se existir, `infrastructure.request_password_reset()` (`ForgotPassword`, o Cognito gera/envia/expira o código sozinho — o envio em si passa pelo trigger `CustomEmailSender` e sai pelo Gmail, ver `app/lambda_cognito_email_sender/lambda_cognito_email_sender.md`) → código + nova senha → `infrastructure.confirm_password_reset()` (`ConfirmForgotPassword`) → tela dedicada `_render_password_reset_success()` (mesmo padrão de `_render_signup_success()`), com a mensagem de sucesso e um botão "Ir para o login →". Essa tela intermediária existe porque a mensagem, se injetada direto no formulário de login (via `session_state.pop()`), some assim que qualquer rerun acontece — inclusive o rerun automático do Streamlit ao sair de um campo de texto alterado sem `st.form` — antes do usuário conseguir lê-la; com a tela própria, a mensagem só desaparece quando o usuário decide avançar. Só funciona se o e-mail estiver marcado como verificado — o que agora acontece no passo de confirmação do próprio cadastro (`confirm_sign_up()`, bullet acima), não mais na aprovação do admin. **Trade-off de segurança consciente:** revelar se um e-mail está cadastrado é um vetor clássico de *user enumeration* — por isso o app client tem `prevent_user_existence_errors = "ENABLED"` (`infra/lightsail_ia.tf`) e `request_password_reset()`/`confirm_password_reset()` continuam sem revelar nada nos próprios erros do Cognito (`except ClientError: pass` em `forms.py`). O check explícito via `user_exists()` foi uma decisão deliberada do projeto (pedido de UX explícito, ciente do risco), e mantém o app consistente com o que o **cadastro** já fazia antes disso: `_signup_error_message()` já revela "Esse e-mail já está cadastrado." via `UsernameExistsException`. Porque `ListUsers` não tem a mesma cota nativa que protege `ForgotPassword`/`ConfirmForgotPassword` no Cognito, o botão **Enviar código** passou a compartilhar o mesmo rate limit de 60s por IP que já existia só no reenvio (`_reset_attempt_history`) — limita tanto o quão rápido alguém varre e-mails quanto quantos códigos reais são disparados. O subtítulo da segunda etapa ainda avisa para checar a pasta de spam (texto da UI do FilmBot) — mitigação que existia enquanto o e-mail saía pelo domínio nativo compartilhado do Cognito; desde a introdução do trigger `CustomEmailSender` (código enviado pelo Gmail, ver `app/lambda_cognito_email_sender/lambda_cognito_email_sender.md`) o aviso tende a ficar cada vez menos necessário, mas foi mantido até validar a deliverability em produção por um tempo. Botão **Reenviar código** (chama `request_password_reset()` de novo, o que invalida o código anterior) com o mesmo cooldown de 60s por IP (`_reset_attempt_history`, mesmo padrão `events_in_window`/`seconds_until_available`/`load_countdown_script` do bloqueio de tentativas de login incorretas, linha abaixo) — evita reenvio repetido em sequência; o teto real de segurança continua sendo a quota do próprio Cognito (5–20 requisições de `ForgotPassword`/`ConfirmForgotPassword` por usuário por hora, não configurável). Diferente do cooldown de login, os dois botões calculam o próprio cooldown (`_send_locked`/`_resend_locked`) dentro de uma função aninhada decorada com `@st.fragment(run_every=1)` (`_send_section`/`_resend_section`, em `_render_forgot_password_request`/`_render_forgot_password_confirm`) — o fragmento reexecuta sozinho 1x/s, recalculando o tempo restante a partir de `_reset_attempt_history` e mandando o `disabled` real pro frontend a cada tick, sem depender de `load_countdown_script()`/JS pra isso. Um rerun de fragmento não é um reload de página, então `session_state` (`auth_view`/`reset_step`) fica intacto — mas, ao contrário do hack de DOM usado antes (que só removia o `disabled` visualmente no navegador sem o backend saber que o cooldown acabou, deixando o clique sem efeito no primeiro reenvio real), o botão fica genuinamente clicável do ponto de vista do Streamlit assim que os 60s passam. Terceiro cooldown, independente dos dois acima: **3 tentativas de código incorreto** (`CodeMismatchException` — não `ExpiredCodeException`/`InvalidPasswordException`, que não são tentativas de adivinhar o código e já têm mensagem própria em `_reset_error_message()`) dentro de 60s desabilita o botão **Redefinir senha** pelo mesmo período (`_code_attempt_history`/`_MAX_CODE_ATTEMPTS`/`_CODE_LOCKOUT_SECONDS`, `_render_forgot_password_confirm`) — mesmo padrão do bloqueio de login (`events_in_window`/`seconds_until_available`/`load_countdown_script`, ver bullet "Bloqueio temporário de login" mais abaixo), não o `@st.fragment(run_every=1)` dos dois cooldowns de envio/reenvio: o bloqueio só precisa ser avaliado no submit (contagem de tentativas reais de decifrar o código), não a cada segundo enquanto o usuário digita. `load_password_requirements_gate_script()` recebe `locked_out=` nesse caso, pra `password_requirements_gate.js` não reabilitar o botão via digitação enquanto o bloqueio estiver ativo (mesmo mecanismo de `locked_out` em `load_form_button_toggle_script`, ver bullet "Senha/confirmar senha/e-mail dinâmicos" mais abaixo). No desktop, `_render_forgot_password_confirm` replica exatamente `profile.py::render_password_tab` (`st.container(key="password-fields-row")` + `st.columns(2, gap="medium")`, mesma key — CSS reaproveitada de `base.css`, sem duplicação): Código de verificação + Nova senha + Confirmar nova senha empilhados numa coluna de ~50%, requisitos da senha (título + `render_password_requirements()`) na outra; no mobile os dois colapsam empilhados 100%, requisitos abaixo dos campos.
- **Painel admin** (`admin.py::render_admin_panel(client_ip)`, chamado por `app.py` quando `st.session_state["is_admin"]` — setado no login via `infrastructure.is_admin()`, que checa o grupo Cognito `admins`) — barra horizontal com ícone ("Usuários"/"Perfil"/"Senha", `profile.py::render_nav_bar`/`render_nav_item`) no topo (`st.container(key="admin-nav")`, um `st.columns(N)` com um item por coluna), com o conteúdo da seção ativa abaixo, centralizado. Título + barra + conteúdo ficam todos dentro de um único `st.container(key="admin-shell")` (640px, `margin: 0 auto`, mesma largura do `profile-shell` da tela solo "Meu Perfil" — sem nenhuma ramificação de largura por seção: antes havia um shell largo de 900px só para "Usuários" e um de 640px para "Perfil"/"Senha", o que fazia a borda esquerda do menu pular de posição ao trocar de aba (bug reportado pelo usuário); com um único wrapper e uma única largura para as 3 seções, isso deixa de ser possível por construção — a tabela ganha scroll horizontal interno (`.st-key-admin-table`, `overflow-x: auto`) quando as colunas não cabem em 640px, em vez de crescer a caixa). **Não é `st.tabs()`** — trocado por um menu de `st.button()` (`admin_active_section` em `st.session_state`) porque o streamlit==1.59.2 travado no projeto não suporta ícone por aba em `st.tabs()` de forma estilizável, e forçar isso via CSS dependeria de comportamento interno não documentado (ver seção "Estilo (CSS)" abaixo). A seção **"Usuários"** é a tabela abaixo; as seções **"Perfil"** e **"Senha"** reaproveitam integralmente `profile.py::render_profile_tab`/`render_password_tab`/`get_own_profile` (mesmas funções usadas pela tela solo "Meu Perfil", ver bullet abaixo) para o próprio admin editar nome/senha sem precisar de uma tela à parte — cada uma dentro do próprio container (`admin-profile-card`/`admin-password-card`), que reaproveita o visual de card escuro de `profile.css` (seletores estendidos, não duplicados), agora preenchendo a largura inteira do shell (640px, igual à caixa da tabela). Seção "Usuários": tabela em DOM real — cabeçalho + uma linha por usuário via `st.columns()`/`st.button()` (`_render_users_table`, `_build_rows()` combinando `list_pending_users()` + `list_active_users()` + `list_unconfirmed_users()`), não mais `st.dataframe`/`column_config.ButtonColumn` (ver "Nona rodada" mais abaixo, nesta mesma seção "Tema claro/escuro dinâmico", sobre por que a troca) — colunas Nome, E-mail, Cadastrado em, Atualizado em, Admin (sim/não — uma chamada `infrastructure.is_admin()` extra por linha), Status (Novo/Ativo/Revogado/Inativo), Último acesso, Aprovar e Revogar (`st.button()` real por linha, key estável por e-mail). **Ordenação da tabela** (`_build_rows()` → `rows.sort(key=infrastructure.admin_table_sort_key, reverse=True)`, `admin.py`; chave pura em `infrastructure.admin_table_sort_key` e testada em `test_infrastructure.py::TestAdminTableSortKey`): cadastros pendentes no topo (fila de ação do admin, motivo de a tela existir), depois ativos e depois inativos; dentro de cada grupo de status, por último acesso mais recente, com quem nunca acessou caindo no fim do próprio grupo (desempatado pelo cadastro mais recente). O grupo de status é o **primeiro** elemento da tupla, então o `reverse=True` único do `sort` já entrega "pending" no topo e "unconfirmed" no fim — o mesmo `reverse` que entrega a descendência das duas datas ISO 8601 (`created_at`/`last_login`, ordenam como texto, sem parsear — ver `infrastructure._parse_user`). Por isso os dois primeiros elementos da tupla são escritos na polaridade da ordem decrescente (`1` para `pending` e `0` para o resto; `True` para quem já acessou e `False` para quem nunca acessou), em vez da ordem crescente "natural": sem essa inversão, o `reverse=True` exigido pelas datas jogaria os pendentes para o fim e os inativos para o topo. A docstring de `admin_table_sort_key` documenta essa dependência explicitamente (a chave isolada não faz sentido sem o `reverse=True` do chamador). **Cadastrado em** e **Atualizado em** (`admin.py::_format_datetime`, mesmo formato
`DD/MM/AAAA HH:MM`) têm fontes diferentes de propósito. **Cadastrado em** vem de
`UserCreateDate`, campo nativo que o Cognito já devolve em todo item de `ListUsers`,
sem depender de atributo custom. **Atualizado em** *não* usa o equivalente nativo
`UserLastModifiedDate` — esse campo reflete **qualquer** alteração na conta, inclusive
o próprio `record_login()` a cada login bem-sucedido (`custom:last_login` é gravado via
`AdminUpdateUserAttributes`, que já conta como uma "atualização" pro Cognito), o que
deixaria a coluna praticamente idêntica a "Último acesso" pra qualquer usuário que já
logou. Em vez disso, "Atualizado em" lê o atributo custom `custom:password_updated_at`
(schema em `infra/lightsail_ia.tf`, mesmo padrão de `custom:last_login`), gravado só por
`infrastructure.record_password_update()` — chamada por `forms.py::_render_forgot_password_confirm`
logo após um `confirm_password_reset()` bem-sucedido (`ConfirmForgotPassword`), o mesmo
padrão `try/except ClientError: pass` (só loga, não trava o fluxo) usado por
`record_login()`. Fica vazio ("Nunca") para quem nunca trocou a senha por esse fluxo.

**Último acesso** (também `admin.py::_format_datetime`) mostra a data/hora (ou "Nunca")
do login mais recente de cada usuário: `forms.py::_render_login_form` grava esse
timestamp (ISO 8601 UTC) no atributo custom `custom:last_login` do Cognito via
`infrastructure.record_login()` logo após um `authenticate()` com retorno `"ok"`,
envolvido em `try/except ClientError: pass` — uma falha ao gravar o timestamp nunca
trava o login. `_parse_user()` lê esse atributo de volta (vazio para quem nunca logou
desde que o atributo existe). O schema do atributo é provisionado em `infra/lightsail_ia.tf` (`aws_cognito_user_pool.filmbot`) — atributos custom podem ser adicionados a um pool já existente sem forçar recriação, mas, uma vez adicionados, não podem ser removidos do schema (decisão permanente, aceitável por ser um campo de baixo risco). A Ação varia por linha: cadastro novo (`Status = Novo` — conta desabilitada, `Enabled=false`, que já confirmou a posse do e-mail via código, `UserStatus=CONFIRMED`; `list_pending_users()` descarta quem ainda não confirmou o e-mail, esses nem aparecem no painel) ganha os dois botões — ✓ **Aprovar** (`infrastructure.approve_signup()`: só `AdminEnableUser` — confirmação e verificação do e-mail já aconteceram no passo de código do próprio usuário, `confirm_sign_up()`, não mais na aprovação — seguido de `infrastructure.notify_user_approved()` se o checkbox do modal estiver marcado, ver bullet "Notificação de aprovação por e-mail" abaixo) e ✕ **Reprovar** (`infrastructure.reject_signup()`: `AdminDeleteUser`, exclui o cadastro por completo — decisão do projeto, sem histórico de reprovados); usuário existente ativo (`Status = Ativo`, `list_active_users()` filtra por `Enabled=true`) ganha só ✕ **Revogar** (`revoke_access()`: `AdminDeleteUser`, mesma decisão de sem histórico usada em `reject_signup()` — revogar exclui a conta por completo, não é reversível pela tela); cadastro que ainda não confirmou o e-mail (`Status = Inativo`, `list_unconfirmed_users()` — `Enabled=true` + `UserStatus=UNCONFIRMED`, ver bullet "Novo cadastro" acima sobre por que essa janela deixou de ficar invisível no painel) ganha só ✕ **Revogar** também, sem **Aprovar** (habilitar não destravaria o login: a conta já está `Enabled`, quem bloqueia é o próprio `UserStatus=UNCONFIRMED` do Cognito — só o próprio usuário confirmando o e-mail resolve isso, nunca o admin). Clicar em Aprovar, Reprovar ou Revogar abre o mesmo **modal de confirmação** (`admin.py::_render_confirm_dialog`, `st.dialog`, primeiro uso desse componente no projeto, largura restrita a 440px via `[data-testid="stDialog"] > div` em `admin.css` — o padrão nativo `width="small"` sozinho ainda permite até 500px) com um checkbox "Notificar por e-mail" — presente nos quatro fluxos (Aprovar, Reprovar, Revogar de um `Ativo` e Revogar de um `Inativo`), com o padrão dependendo do risco de cada um: **marcado por padrão em Aprovar** (quem foi aprovado precisa saber que já pode logar; o padrão seguro é notificar) e **desmarcado por padrão nos outros três** (a instância é pública, então notificar por padrão sinalizaria pra estranhos/spam que o e-mail existe e foi rejeitado/revogado — ver tabela de funções, `notify_user_approved`/`notify_user_rejected`/`notify_user_revoked`) — e botões Cancelar/Confirmar; só ao confirmar é que `approve_signup()`/`reject_signup()`/`revoke_access()` (e o e-mail, se marcado) de fato executam. Revogar um cadastro `Inativo` também chama `reject_signup()` (mesma função do fluxo `Novo` — é a mesma decisão de "sem histórico", não uma ação nova), com a mesma notificação opcional de `notify_user_rejected`. Ao confirmar, o resultado (ação + status do e-mail: enviado com sucesso, não enviado por opção do admin, ou falha ao enviar) é gravado em `st.session_state["admin_action_feedback"]` **antes** do `st.rerun()` que fecha o modal — mesmo racional de `admin_pending_action` (rerun perde variável local) — e exibido uma única vez no topo da aba "Usuários" (`_render_table()`, via `components.py::render_feedback()`, reaproveitada aqui pela primeira vez em `admin.py`), sendo descartado do `session_state` assim que lido. As 3 funções `notify_user_*` retornam `bool` (sucesso do envio) especificamente para alimentar essa mensagem. **Limitação residual aceita:** uma conta ativa desabilitada manualmente fora do app (Console AWS, fora do fluxo de `revoke_access()`, que sempre exclui) fica indistinguível de um cadastro novo genuíno — mesmo `Enabled=false` + `UserStatus=CONFIRMED` — e reaparece no painel como `Novo` em vez de `Revogado`; não há como resolver isso sem um atributo custom novo, fora do escopo desta feature. Os botões usam o parâmetro nativo `icon=` do `st.button` (`:material/check:`/`:material/close:`, sem label) em vez do helper `icon()` de `components.py` (que monta SVG inline via `st.markdown` — não injetável dentro do label de um widget `st.button`).

**Mecânica do modal Reprovar/Revogar — por que existe `admin_pending_action`:** `st.button()` só retorna `True` no rerun imediatamente disparado pelo próprio clique — no rerun seguinte (inclusive o causado pelo clique em "Confirmar"/"Cancelar" dentro do modal) volta a `False` sozinho, mesmo sem o código ler o valor. Por isso `_queue_pending_action` (chamada de dentro de `_render_table_row`, assim que o `if st.button(...)` do botão de Aprovar/Revogar detecta o clique) copia `email`/`name`/`kind` para `st.session_state["admin_pending_action"]` (uma chave comum, que sobrevive a reruns) **antes** do `st.rerun()` — o modal (`_render_confirm_dialog`) lê/age sobre essa chave, não sobre o retorno do botão em si. Mesmo idioma de "flag de ação pendente + payload" já usado por `recommendation.py` no fluxo de confirmação de áudio (`audio_awaiting_confirmation`/`audio_pending_bytes`).

- **Meu Perfil** (`profile.py::render_profile_panel`, chamado por `app.py` quando `st.session_state["current_view"] == "profile"` — botão "Meu Perfil" no cabeçalho, visível só para usuário **não-admin**; admin vê "Painel Admin" no lugar, nunca os dois juntos — desde que o painel admin ganhou as seções "Perfil"/"Senha" (bullet acima), essa exclusão deixou de ser uma limitação: o admin edita o próprio nome/senha por lá. Mesmo visual/posicionamento do botão "Painel Admin" — `.st-key-btn_toggle_admin`/`.st-key-btn_toggle_profile` compartilham a mesma regra em `app.css`) — dentro de `st.container(key="profile-shell")` (640px, `margin: 0 auto`), mesmo padrão de barra horizontal do painel admin: título, depois a barra de navegação no topo (`st.container(key="profile-nav")`, dois itens — "Perfil"/"Senha", `render_nav_bar`/`render_nav_item`) e a seção ativa (`profile_active_section` em `st.session_state`) abaixo, num `st.container(key="profile-card")` que preenche a largura inteira do shell (mesmo estilo visual do card de cadastro, `_render_signup`). `render_profile_tab`/`render_password_tab`/`get_own_profile`/`render_nav_bar`/`render_nav_item` são **públicas** (não mais prefixadas com `_`) justamente porque `admin.py` também as chama — único caso no projeto de funções de tela reaproveitadas por dois módulos de UI diferentes:
  - **`render_nav_bar(scope, sections)`** — monta a barra horizontal: um `st.columns(len(sections))` com um `render_nav_item` por coluna, dentro de `st.container(key=f"{scope}-nav")`. Reaproveitada por `admin.py`/`profile.py` pra não duplicar o loop entre as duas telas.
  - **`render_nav_item(scope, value, icon_name, label)`** — um segmento da barra: `st.button` nativo (`type="primary"` se a seção estiver ativa, senão `"secondary"` — estado em `st.session_state[f"{scope}_active_section"]`, `scope` isola "profile" de "admin" pra não colidir), com o ícone (`components.icon()`, Lucide) numa coluna estreita ao lado (`st.columns([1, 6], gap=None, vertical_alignment="center")`) — o label de `st.button` não renderiza HTML/SVG cru, então o ícone não entra dentro do próprio botão. Ícone e botão vivem em colunas irmãs (2º nível de aninhamento, dentro da coluna que `render_nav_bar` já aloca pra este item — o único aninhamento suportado pelo Streamlit) sem elemento em comum visível além do wrapper da própria linha (`[data-testid="stHorizontalBlock"]`); por isso o destaque do item ativo (fundo + cor do ícone + cor do texto) é resolvido 100% em CSS (`profile.css`) via `:has()` nesse wrapper — em vez de estilizar só o `<button>` (deixaria o ícone de fora do destaque) ou colorir o ícone via `style=` em Python (não funcionava: `.icon { color: #fff }`, em `base.css`, é declarado direto no próprio `<svg>`, e uma declaração direta sempre vence a herdada de um ancestral, mesmo inline).
  - **Seção "Perfil"** (`render_profile_tab`) — Nome Completo (`value=` preenchido, editável, label visível) e E-mail (`value=` preenchido, **`disabled=True`**, label visível), lado a lado (~50%/50%, `st.container(key="profile-fields-row")` + `st.columns(2)`) no desktop e empilhados (100% cada) no mobile — colapso nativo do Streamlit abaixo do próprio breakpoint interno de `st.columns`, sem CSS de media query — e botão `"Salvar Perfil →"` (140px e centralizado horizontalmente no card no desktop, 100% no mobile, `@media (max-width: 768px)` de `profile.css`). **E-mail é sempre somente leitura** — não dá pra trocar e-mail por esta tela; decisão consciente do projeto: quem chega até a tela de perfil já autenticou com e-mail+senha no login, e implementar troca de e-mail exigiria decidir entre reautenticar de novo (redundante nesse racional) ou um fluxo de confirmação por código (o Cognito só confirma o valor **novo** de um atributo, via `VerifyUserAttribute`/`GetUserAttributeVerificationCode` — não existe API pra confirmar o valor **atual** antes de trocar; um fluxo de "confirmar o e-mail antigo antes" exigiria OTP próprio + SES, fora de escopo). Trocar de e-mail ficou fora de escopo desta versão. Handler simples: nome vazio → erro; nome igual ao atual → no-op; senão `infrastructure.update_user_name()` (`AdminUpdateUserAttributes`, sem permissão IAM nova) + mensagem de sucesso — sem reautenticação nenhuma, campo E-mail nunca é submetido (é `disabled`).
  - **Seção "Senha"** (`render_password_tab`) — Senha atual + Nova senha + Confirmar nova senha empilhados numa coluna de ~50% e, na coluna de ~50% ao lado, um painel (borda + fundo translúcido, `align-items: stretch` acompanhando a altura dos 3 campos) com o título "Requisitos da senha" acima de `render_password_requirements()`, no desktop (`st.container(key="password-fields-row")` + `st.columns(2)`) — no mobile os dois colapsam empilhados 100%, requisitos abaixo dos campos, mesmo racional da linha Nome/E-mail acima — e botão `"Salvar Senha →"` (140px e centralizado horizontalmente no card no desktop, 100% no mobile). `infrastructure.change_password()` reautentica com a senha atual internamente e, só se válida, define a nova via `AdminSetUserPassword` (`Permanent=True` — login imediato, sem o estado intermediário `FORCE_CHANGE_PASSWORD`) — única action desta feature que exige permissão IAM (`infra/lightsail_ia.tf`, confirmado na doc oficial: "Amazon Cognito evaluates IAM policies... you must grant yourself the corresponding IAM permission"). 3 tentativas de senha atual incorreta em 60s bloqueiam o botão (`_password_reauth_history`, mesmo padrão `events_in_window`/`seconds_until_available`/`load_countdown_script` do bloqueio de login — histórico compartilhado por IP entre a tela solo e o painel admin, já que é o mesmo dict de módulo). Ao suceder, chama `infrastructure.record_password_update()` (mesma coluna "Atualizado em" do painel admin) e limpa os 3 campos de senha da sessão.
  - Sem os scripts de gate de botão (`load_form_button_toggle_script`/`load_password_requirements_gate_script`) na seção "Perfil" — validação roda só no clique, com mensagem de erro inline (mesmo padrão do painel admin).

**Bootstrap do primeiro admin:** ninguém é admin no início, então ninguém pode aprovar o primeiro admin pela tela normal. Depois que a pessoa se cadastrar normalmente (fica `Unconfirmed`), promover manualmente uma única vez via AWS CLI/console:
```bash
aws cognito-idp admin-confirm-sign-up --user-pool-id <COGNITO_USER_POOL_ID> --username <email>
aws cognito-idp admin-update-user-attributes --user-pool-id <COGNITO_USER_POOL_ID> --username <email> --user-attributes Name=email_verified,Value=true
aws cognito-idp admin-add-user-to-group --user-pool-id <COGNITO_USER_POOL_ID> --username <email> --group-name admins
```
(equivalente ao que `approve_signup()` + `add_to_admins_group()` fazem juntos — sem tela própria no painel porque só acontece uma vez por ambiente).

**Notificação de aprovação por e-mail (Gmail, não SES):** ao confirmar **Aprovar** no modal, `admin.py` chama `infrastructure.approve_signup()` e, se o checkbox "Notificar por e-mail" estiver marcado (marcado por padrão), em seguida `infrastructure.notify_user_approved(email, name)` — envia um e-mail avisando o usuário que o acesso foi liberado, via SMTP de uma conta Gmail dedicada (`filmbot.lsgalvao@gmail.com`, autenticada por uma "senha de app", já que o Gmail não aceita mais login por senha comum via SMTP). Optou-se por Gmail em vez de SES para evitar o passo burocrático de identidade verificada + *production access* do SES. Credenciais (`gmail_sender_email`/`gmail_app_password`) vêm do `FILMBOT_SECRET_ARN` em produção, com fallback `GMAIL_SENDER_EMAIL`/`GMAIL_APP_PASSWORD` para dev local (mesmo padrão de `llm_api_key`). Fire-and-forget: uma falha no envio (credencial errada, Gmail indisponível) só é logada (`logger.error`), nunca propaga — a aprovação em si já aconteceu no Cognito antes dessa chamada. O corpo do e-mail traz o link do FilmBot (`_FILMBOT_URL`, `https://filmbot.lsgalvao.com.br` — mesmo domínio fixo de produção do Caddy/`FILMBOT_DOMAIN`, hardcoded em `infrastructure.py` porque o processo Python nunca precisou da própria URL pública antes), o e-mail cadastrado e um lembrete de que a senha é a mesma já cadastrada no formulário — não gera nem envia uma senha nova. Reprovação e remoção de cadastro não confirmado (`reject_signup()`, nos dois casos) notificam de forma opcional, via o mesmo checkbox "Notificar por e-mail" do modal de confirmação (desmarcado por padrão) — ver bullet acima e `notify_user_rejected`.

**Rate limit de tentativas de login continua sendo por IP, não por conta** (`_login_attempt_history`, `forms.py`) — o Cognito tem bloqueio por tentativa malsucedida nas *Advanced Security Features*, mas são pagas à parte e não foram adotadas; o rate-limit já existente é a única defesa de força bruta.

**Nome cacheado em `session_state` para a saudação da tela de recomendação:** um login bem-sucedido (`forms.py::_render_login_form`) busca `infrastructure.get_user_profile(email)["name"]` uma única vez e grava em `st.session_state["user_name"]`, junto com `user_email`/`is_admin` — evita uma chamada ao Cognito a cada rerun da tela principal só para exibir "Olá, {primeiro nome}" (ver bullet "Título do hero" na seção "Interface"). Falha ao buscar (`ClientError`) cai num fallback `""` (sem saudação), sem travar o login, mesmo racional de `record_login`/`record_password_update` acima. Quando o próprio usuário edita o nome em "Meu Perfil" (`profile.py::render_profile_tab`), o handler também atualiza `session_state["user_name"]` — sem isso, a saudação ficaria com o nome antigo até o próximo login. Não existe atributo `given_name` separado no Cognito: o primeiro nome exibido é sempre `nome_completo.split()[0]`, calculado em `recommendation.py`.

### Interface (`app.py`, `forms.py`, `admin.py`, `profile.py`, `recommendation.py`, `cards.py`, `infrastructure.py`)

`app.py` é só o orquestrador: bootstrap (`infrastructure.py`), chama a tela de login (`forms.py`, que interrompe a execução com `st.stop()` se o usuário não estiver autenticado), renderiza o cabeçalho (botão "Meu Perfil" para não-admin, ou "Painel Admin" para admin — nunca os dois juntos) e chama, em sequência, o formulário de preferência/busca assíncrona (`recommendation.py`) e a exibição dos resultados (`cards.py`) — ou `admin.py::render_admin_panel(client_ip)`/`profile.py::render_profile_panel(client_ip)` no lugar dos dois, conforme `current_view` ("admin"/"profile"). É puramente organização de código — a experiência do usuário continua sendo uma tela única (login → formulário → cards no mesmo rerun), sem navegação multipage do Streamlit. `recommendation.py` escreve `titles`/`search_error`/`search_completed` em `st.session_state`; `cards.py` só lê essas chaves, sem import entre os dois. `infrastructure.py` reúne o bootstrap de processo (senha via Secrets Manager, logging CloudWatch), as chamadas ao Cognito/SNS da autenticação/perfil e os utilitários genéricos de rate limiting (IP do cliente, janela deslizante, segundos restantes) usados por `forms.py`, `profile.py` e `recommendation.py`, cada um com seus próprios dicts de histórico.

`validate_password()` (política de senha do Cognito, mais o teto de 16 caracteres só do app) mora em `components.py` — não em `forms.py`, apesar de ter nascido lá — porque `profile.py` também precisa dela na troca de senha do perfil; mesma política nos 3 lugares que pedem senha nova (cadastro, esqueci senha, perfil).

O CSS (`static/`) acompanha a mesma divisão: `theme.css` (tokens de tema claro/escuro), `base.css` (transversal), `forms.css`, `app.css` (cabeçalho/rodapé), `recommendation.css`, `cards.css`, `admin.css` e `profile.css`. `load_base_css()` (`components.py`) injeta `theme.css` antes de `base.css`, e cada `load_*_css()` injeta `base.css` antes do CSS específico da tela — necessário porque duas regras (reset genérico de botão em `base.css` e `.st-key-btn_recomendar` em `recommendation.css`) têm especificidade CSS empatada; sem `base.css` injetado primeiro, o botão "Recomendar" perderia a largura `100%` e voltaria a 140px fixo. `admin.css` e `profile.css` **passaram a ser injetados juntos** quando `render_admin_panel` chama `load_profile_css()` (as abas "Perfil"/"Senha" do painel admin reaproveitam o CSS de `profile.css`) — `.page-title` continua duplicado entre os dois arquivos de propósito (não colide, mesmo valor), mas os seletores de card/inputs/botões/barra de `profile.css` foram **estendidos** (não duplicados) para também casar com `.st-key-admin-profile-card`/`.st-key-admin-password-card`/`.st-key-admin-nav`, cobrindo o mesmo componente visual nos dois contextos. O shell (`.st-key-profile-shell`/`.st-key-admin-shell`) é uma única regra combinada em `base.css` (não em `profile.css` — CSS usada por 2+ telas mora em `base.css`, ver seção "Estilo (CSS)") — `max-width: 640px; margin: 0 auto` para os dois, sempre, sem exceção por seção ativa: antes existia um `.st-key-admin-outer` (900px) exclusivo do admin, com `.st-key-admin-table`/`.st-key-admin-shell` internos sem centralização própria, porque a seção "Usuários" precisava de mais espaço que 640px — isso foi substituído por dar scroll horizontal interno à própria tabela (`.st-key-admin-table`, `overflow-x: auto`) em vez de alargar a caixa, pra garantir que as 3 seções (tabela/perfil/senha) tenham sempre a mesma largura e o mesmo início/fim horizontal (pedido do usuário). O card de login (`.st-key-form-card`) **não** entra nessa regra compartilhada — fica em `forms.css`, com `max-width: 440px` por padrão e um override pra 640px via `:has()` só nas duas sub-telas com campos pareados (Cadastro, "Esqueci a senha" etapa 2); as outras 5 sub-telas do login ficariam com espaço vazio nos 640px do Perfil/Admin (pedido do usuário, com print da tela de login mostrando o problema).

O nudge vertical fino no ícone da barra (`.st-key-profile-nav`/`.st-key-admin-nav svg.icon`, `top`) é recalibrado por medição objetiva de pixel (screenshot em alta resolução via Playwright + PIL/numpy comparando o centro de tinta real do ícone com o do texto), não por inspeção visual — depende diretamente do `font-size` do botão do menu (ver `profile.css`, valor atual e histórico de recalibração documentados no comentário acima da regra), então precisa ser remedido sempre que esse `font-size` mudar.

- **Tema claro/escuro dinâmico** (`theme.css`, tokens `:root`/`var()` consumidos pelos demais arquivos CSS)
  — resolução em 3 níveis, maior precedência por último: (1) escuro é o padrão histórico do app; (2)
  `prefers-color-scheme` do SO/navegador; (3) escolha manual do usuário no botão sol/lua
  (`theme_toggle_html()`, embutido inline no cabeçalho de cada tela — mesma linha do brand no
  login, agrupado à esquerda com os botões de navegação na página principal; ver "Cabeçalho
  agrupado à esquerda" mais abaixo), persistida via
  `localStorage` e aplicada via atributo `data-theme` em `<html>` — 100% client-side
  (`static/js/theme_toggle.js`, `load_theme_toggle_script()`), sem depender de `session_state`/`st.rerun()`
  do Streamlit para trocar de tema. Paleta clara pragmática: inverte fundo/texto/bordas neutras, mantendo os
  acentos laranja/âmbar e as cores de validação de campo (verde/vermelho) idênticos nos dois temas — com uma
  única exceção deliberada: `--accent-soft-bg`/`--accent-soft-text` (usados só em
  `.st-key-btn_toggle_admin`/`.st-key-btn_toggle_profile`, `app.css`) variam por tema, porque o par original
  (`#fdba74` sobre `rgba(249,115,22,0.15)`) foi calibrado só para fundo escuro e ficava sem contraste em
  fundo claro (bug corrigido). A tabela de usuários do painel admin acompanha o tema normalmente desde a
  reescrita em DOM real (`_render_users_table`, ver "Nona rodada" mais abaixo nesta mesma seção, e
  "Décima quarta rodada" pra migração posterior pra `st.components.v2.component()`) — antes, enquanto
  era `st.dataframe`/`<canvas>`, ficava de fora, sempre escura por decisão deliberada.
  **Elementos nativos do Streamlit fora do alcance do tema custom:** como `.streamlit/config.toml` não fixa
  `[theme]`, qualquer elemento cuja aparência vem do CSS interno do Streamlit (não interceptado por seletor
  nosso) segue `prefers-color-scheme` do navegador de quem acessa, independente da escolha manual no toggle —
  mesma causa raiz documentada em `base.css`/`profile.css` para labels nativos, mas que também afetava
  placeholder de `stTextInput`/`stTextArea` (invisível quando o tema nativo e o custom divergiam — nenhum
  arquivo tinha regra `::placeholder`) e autofill do navegador (Chrome/Edge aplicam sua própria cor de
  fundo/texto via UA stylesheet, ignorada por `background`/`color` normais — corrigido com o truque padrão de
  `box-shadow` inset). Ambos corrigidos em `base.css`, cobrindo as duas telas de uma vez. **Header/toolbar
  nativo do Streamlit** (`stHeader`/`stToolbar`/`stDecoration`) também foi movido de `forms.css` (só cobria o
  login) para `base.css`: sem escondê-lo na tela principal/admin/perfil, seu z-index nativo (bem maior que o
  `z-index:1000` de `.theme-toggle`) cobria visualmente o botão de tema depois do login — o botão nunca saiu
  do DOM, só ficava atrás do header nativo (bug corrigido).
  **Segunda rodada de bugs de modo claro** (screenshots reais pós-login): `.hero-heading` (`<h1>` de verdade,
  `recommendation.css`) precisou de `!important` em `color` — o Streamlit força uma cor própria em todo `<h1>`
  renderizado via markdown (mesmo mecanismo do `!important` já existente ali para `font-weight`/`padding`/
  `margin`), deixando o texto sem acento invisível em modo claro (só "assistir" ficava visível, com cor
  própria em `.accent-gradient-text`, aplicada ao `<span>` e não afetada pela regra do `<h1>` pai — essa por
  si só já funciona sem `!important`, tanto dentro de `<h1>` quanto de `<p>`, ex. `.hero-greeting`).
  `.reason-label`/`.reason-label .icon`/`.genre.highlighted`/`.provider-badge.highlighted` (`cards.css`)
  trocaram o hardcoded `#fdba74` por `--accent-soft-text` (mesmo token da correção do "Painel Admin" acima).
  `.cinema-badge` (`cards.css`) trocou seu par hardcoded de amarelo por `--feedback-warning-bg`/
  `--feedback-warning-text` (já calibrados por tema, usados por `.msg-warning`). `.card`/`article.card`
  (`cards.css`) ganhou borda mais forte (`--overlay-10`, era `-06`) e `box-shadow` — em modo claro
  `--bg-surface`/`--bg-page` são o mesmo branco puro (diferente do escuro, onde já destoam um pouco), então a
  borda fraca sozinha deixava os cards indistinguíveis da página. Botões primários desabilitados
  (`.st-key-btn_recomendar`/`forms.css`/`profile.css`) trocaram `opacity:0.5` (mistura com o que estiver atrás
  — funciona em fundo bem escuro, mas o gradiente pêssego do hero em modo claro é próximo demais do laranja a
  50% de opacidade, apagando o botão) por cores explícitas neutras (`--bg-button-muted`/`--text-faint`, mesma
  família do botão "Sair"), que não dependem do fundo.
  **Terceira rodada:** o `st.button("Recomendar", ...)` do estado "buscando" (`recommendation.py`) não tinha
  `key=` (diferente do idêntico no estado idle, `key="btn_recomendar"`) — sem key, nenhuma regra CSS o
  alcançava, 100% estilo nativo do Streamlit; ganhou a mesma key (seguro, os dois `st.button` são mutuamente
  exclusivos). O `st.caption()` de "🎤 Transcrevendo áudio..." (dentro de `audio-messages`,
  `recommendation.py`) é widget nativo sem wrapper custom (`st.caption` não aceita `class=`) — cor seguia o
  tema nativo do Streamlit; corrigido com `.st-key-audio-messages [data-testid="stCaptionContainer"]` +
  `var(--text-tertiary)` (`recommendation.css`). `.cinema-badge` (`cards.css`) ganhou borda
  (`var(--feedback-warning-border)`, mesmo token de `.msg-warning`) para mais definição contra fundo claro. O
  autofill do navegador (rodada 1, `base.css`) ganhou a variante `input:-webkit-autofill:disabled` — o campo
  "E-mail" do Perfil é sempre `disabled=True`, e um e-mail com autofill salvo pelo navegador para esse campo
  renderiza a combinação autofill+disabled com um estilo próprio do Chromium, fora das 4 variantes já
  cobertas.
  **Quarta rodada:** a correção de contraste do `:disabled` dos botões primários (rodada 2, acima) trocou
  `opacity:0.5` por `--bg-button-muted`/`--text-faint` (cinza neutro) — resolvia o contraste, mas mudava a
  identidade visual do botão sem necessidade (pedido do usuário: só consertar a visibilidade, manter o laranja).
  Revertido para um fundo translúcido explícito (`background: rgba(234,88,12,0.5)` + `color:#fff` sólido, nos
  3 lugares — `.st-key-btn_recomendar`/`forms.css`/`profile.css`) — mesma aparência "laranja apagado" de
  sempre, só sem o texto branco decair junto com o fundo (`opacity` no elemento inteiro afeta texto e fundo
  juntos; `background` translúcido com `color` sólido separa os dois). O fix real de "não aparece" continua
  sendo a `key=` adicionada na terceira rodada — este ajuste só resolve o contraste sem mexer na cor.
  **Campo E-mail do Perfil ainda ilegível em modo claro em produção**, mesmo com a correção de autofill da
  terceira rodada já implantada — investigação aberta, aguardando o usuário testar em aba anônima (sem
  autofill salvo) pra confirmar ou descartar essa hipótese antes de tentar outra correção (2 tentativas
  anteriores não resolveram).
  **Quinta rodada:** revisto de novo — o usuário decidiu que, já que o `:disabled` de `.st-key-btn_recomendar`
  precisa de alguma cor diferente de laranja pra funcionar em modo claro, prefere que seja **idêntico ao botão
  "Sair"** (`.st-key-btn_sair`, `app.css`), não uma variante translúcida de laranja. Ajustado pra usar os
  mesmos tokens exatos (`--bg-button-muted`/`--text-on-muted`) — confirmado via `getComputedStyle` que as
  cores computadas dos dois botões batem exatamente, nos dois temas. Escopo desta mudança é só
  `.st-key-btn_recomendar` (`recommendation.css`) — os `:disabled` genéricos de `forms.css`/`profile.css`
  continuam com o laranja translúcido da quarta rodada, sem reclamação até agora.
  **Sexta rodada — causa raiz real do botão "Recomendar" era JS, não CSS:** o usuário confirmou que o botão
  continuava com a aparência de habilitado mesmo após reiniciar o `streamlit run` local (nunca houve deploy
  envolvido nas rodadas anteriores — presunção incorreta minha). Achado lendo `static/js/
  contador_caracteres.js:49-54,65-68`: esse script roda um `setInterval` a cada 300ms, para sempre, que faz
  `.st-key-btn_recomendar button`.disabled = (campo de texto vazio?) — pensado só pro estado idle, mas
  `load_preference_counter_script()` é chamado incondicionalmente em `recommendation.py` (fora do `if
  searching:`/`else:`), então o script continuava rodando e sobrescrevendo `disabled=True` do Python a cada
  300ms durante a busca (campo não estava vazio) — nenhuma correção de CSS resolveria isso, o navegador nunca
  mantinha o estado `:disabled` tempo suficiente. Corrigido removendo o botão "Recomendar" do DOM por
  completo durante a busca (pedido do próprio usuário, que também é a correção certa: sem o botão,
  `document.querySelector('.st-key-btn_recomendar button')` retorna `null` e o script nem tenta mexer,
  `if (!btn) return`) — só "Cancelar" fica visível. Efeito colateral corrigido: `.st-key-btn_cancelar`
  (`recommendation.css`) deixou de depender de `:has()` sobre um irmão desabilitado (que não existe mais) pra
  ficar vermelho — agora mira a própria key diretamente (única no app).
  **Campo E-mail do Perfil substituído por somente-leitura 100% custom** (`profile.py::render_profile_tab`):
  depois de 3 tentativas de CSS falhas em 2 navegadores (Chrome e Edge) tentando fazer o `st.text_input(
  disabled=True)` funcionar em modo claro, trocado por um `<div>` (`.readonly-field`/`.readonly-field-label`/
  `.readonly-field-value`, `profile.css`) que imita visualmente o par label/input nativo mas não depende de
  nenhum estado `:disabled`/autofill do navegador — elimina a classe inteira do problema em vez de continuar
  adivinhando o seletor certo. Sem mudança de comportamento (segue somente leitura, sem elemento de formulário
  real por trás). CSS morta removida junto (`input:disabled { opacity: 0.55 }`, sem uso desde essa troca).
  **Sétima rodada — modal de confirmação do admin (`_render_confirm_dialog`, `admin.css`):** mesma
  causa-raiz do resto desta seção — `[data-testid="stDialog"] > div` (o card visível) não tinha
  `background`/`border`/texto próprios, herdando o card nativo do Streamlit dissociado do
  `data-theme` do app. Corrigido reaproveitando exatamente os valores do card de login
  (`.st-key-form-card`, `forms.css`): mesmo fundo/borda/sombra. Texto de confirmação
  (`stMarkdownContainer p`), link de e-mail autolinkado (`stMarkdownContainer a`, cor
  `--text-faint` + underline, mesmo padrão de `.footer a`) e label do checkbox "Notificar por
  e-mail" (`stWidgetLabel p`) ganharam cor própria pelo mesmo motivo — sem isso, só recolorir o
  fundo criaria risco real de texto ilegível quando o tema manual diverge do
  `prefers-color-scheme` do navegador. A caixa nativa do checkbox em si ficou de fora (primeiro
  `st.checkbox` do app, sem padrão prévio pra reaproveitar) — risco residual pequeno, mesma classe
  dos outros itens desta seção. O botão "Cancelar" virou outline laranja (fundo transparente,
  borda e texto `#ea580c`, pedido do usuário) — "Confirmar" permanece laranja sólido. Avaliada e
  descartada a possibilidade de a tabela de usuários (`st.dataframe`, ver comentário acima em
  `admin.css`) também acompanhar o tema: `[theme]` no `config.toml` é global (confirmado na doc
  oficial do Streamlit, não existe tema por widget) e reabriria os bugs de contraste já corrigidos
  em componentes nativos; o único mecanismo de JS encontrado é um hack de comunidade não-oficial
  sobre um atributo privado do Streamlit, sem confirmação de que o `<canvas>` do grid realmente
  repinta — mantida sempre escura, decisão reconfirmada.
  **Oitava rodada — dois bugs reais na sétima rodada, achados só ao testar no app de verdade** (o
  harness de verificação inicial só carregava `base.css`+`admin.css`, não a cadeia completa de
  `render_admin_panel`): (1) o texto de "Cancelar"/"Confirmar" saía preto/branco em vez de
  laranja/branco — inspecionado o DOM real (Playwright): o rótulo de um `st.button()` também
  renderiza via `stMarkdownContainer`/`p`, aninhado DENTRO do `<button>`, então a regra de cor do
  texto de confirmação (mesma especificidade da regra de cor dos botões) vencia para esse `<p>`
  por atingi-lo diretamente — `color` só é herdado quando não há declaração explícita batendo no
  próprio elemento. Corrigido com `p:not(button *)`/`a:not(button *)` nas duas regras de texto do
  modal. (2) o indicador visual do checkbox (`<div>` vazio dentro do `<label>`, sem testid próprio,
  irmão de `stWidgetLabel`) aparecia preto sólido mesmo com o card já claro — reproduzido de propósito
  emulando `prefers-color-scheme` do navegador diferente do `data-theme` manual (`color_scheme` do
  Playwright + `localStorage["filmbot-theme"]`), confirmando a mesma causa-raiz nativa desta seção:
  o indicador segue o tema auto-detectado do Streamlit, não o toggle do app. Corrigido com
  `label > div:empty` (isola só o estado DESMARCADO, já que o marcado ganha um `<svg>` filho) +
  `--bg-input`/`--overlay-16`. Estado marcado permanece com o vermelho padrão do Streamlit (fora do
  escopo pedido).
  **Nona rodada — a decisão "tabela sempre escura" da sétima rodada foi revisitada e superada:**
  a causa raiz continuava a mesma (grade em `<canvas>`, glide-data-grid, inalcançável por CSS), mas
  em vez de tentar sincronizar o canvas com o tema (via `[theme]` global ou hack de JS — as duas
  saídas já descartadas na sétima rodada), a tabela foi reconstruída inteiramente como DOM real:
  `_render_users_table`/`_render_table_header`/`_render_table_row` (`admin.py`) montam cabeçalho +
  uma linha por usuário via `st.columns()` com pesos fixos (`_COLUMN_WEIGHTS`), e os botões
  Aprovar/Revogar viram `st.button()` de verdade (key por e-mail) em vez de célula de
  `column_config.ButtonColumn`. `_handle_dataframe_action_click`/`_build_dataframe_action_data`
  somem — o clique é lido inline no próprio `if st.button(...):` de cada linha
  (`_queue_pending_action`), sem precisar reconstruir a leitura de "trigger value" depois. Sendo DOM
  normal, a tabela passa a seguir `theme.css` automaticamente, sem reabrir nenhum dos bugs de
  contraste da sétima rodada (que eram todos de componentes nativos do Streamlit sob `[theme]`
  global — não se aplicam aqui, já que não existe `column_config`/canvas envolvido). O scroll
  horizontal (`.st-key-admin-table`, `overflow-x: auto`) continua existindo do mesmo jeito — só que
  agora via `min-width` forçado no `stHorizontalBlock` (mesma técnica de
  `flex-direction:row!important`/`flex-wrap:nowrap!important` de `.st-key-admin-nav`, só que
  deixando a linha ficar mais larga que o container em vez de espremer). Emoji ✅/❌ mantido como
  label do botão (compacto o bastante pra caber nos 60px da coluna), mas agora estilizado como pill
  colorido de verdade (`--feedback-success-*`/`--feedback-error-*`), não mais um emoji solto dentro
  de uma célula sem CSS.
  **Décima rodada — dois bugs de seletor CSS achados só testando ao vivo (Playwright), não por
  inspeção do código, mais grade completa e centralização de botão:** (1) o comentário que documenta
  os tokens de cor do pill Aprovar/Revogar continha literalmente `--feedback-success-*/--feedback-
  error-*` — o `*/ ` embutido nessa prosa fechava o comentário `/* Botões Aprovar... */` cedo demais,
  e tudo até o próximo `*/` real virava "CSS" inválido descartado pelo navegador, apagando bem a regra
  do botão Aprovar (confirmado via `document.styleSheets`: 24 regras em vez de 25). Corrigido
  inserindo um espaço na sequência. (2) a borda inferior de cada linha usava
  `[class^="st-key-admin-row-"]` (prefixo) quando a classe key real do Streamlit vem no MEIO do
  atributo (`"stVerticalBlock st-key-admin-row-0 st-emotion-cache-..."`, nunca no início) — a regra
  nunca bateu em nada (`getComputedStyle` confirmava `border-bottom: 0px none`). Corrigido pra `*=`
  (substring), mesma técnica já usada nos seletores de `admin_approve_`/`admin_revoke_`. Junto,
  atendendo pedido do usuário de grade completa: `border-right` em cada `stColumn` (exceto o último),
  `border-bottom` mais forte separando cabeçalho do corpo (seletor mira só o `stHorizontalBlock` filho
  direto de `.st-key-admin-table` — o do cabeçalho; as linhas de dado ficam um nível mais fundo,
  dentro do `admin-row-N`, então não batem) e uma moldura externa na caixa toda — todas via
  `var(--overlay-*)`, então já saem pretas/translúcidas no tema claro e brancas/translúcidas no
  escuro, sem regra extra por tema. Também descoberto que os botões Aprovar/Revogar não estavam
  centralizados na própria coluna (ficavam encostados à esquerda): `width:100%` no wrapper
  `[data-testid="stButton"]` sozinho não bastava — a cadeia `stColumn > stVerticalBlock >
  stElementContainer > stButton` perde a largura no `stElementContainer` (fica do tamanho do próprio
  botão em vez de esticar, achado inspecionando a cadeia de ancestrais inteira via
  `getBoundingClientRect`), corrigido forçando `width:100%` nos dois níveis. `align-items:center`
  acrescentado no `stHorizontalBlock` da linha pra centralizar verticalmente por construção (antes
  texto e botão só coincidiam por terem alturas parecidas, ~1px de diferença, nada garantia isso).
  **Décima primeira rodada — grade "desconectada" (linha horizontal cortando no meio da tabela):**
  a borda inferior de cada linha estava no `admin-row-N` (`st.container` externo), mas esse container
  fica com a largura "natural" do shell (~640px) — quem tem o `min-width:1240px` forçado (mesmo
  elemento onde vivem os `stColumn` com `border-right`) é o `stHorizontalBlock` **dentro** dele, um
  nível mais fundo. Confirmado via `getBoundingClientRect`: 638px (admin-row-N) vs. 1240px
  (stHorizontalBlock interno) — a borda parava no meio da tabela, desalinhada dos divisores verticais
  (que já cobriam os 1240px certos). Corrigido movendo `border-bottom`/hover do `admin-row-N` para o
  `stHorizontalBlock` interno (`[class*="st-key-admin-row-"] [data-testid="stHorizontalBlock"]`) —
  mesmo elemento que a borda do cabeçalho já mirava desde o início, por isso aquela nunca teve esse
  problema.
  **Décima segunda rodada — faixas em branco entre cabeçalho/linhas, achado só testando com dados
  reais em produção:** cabeçalho e cada linha são blocos-irmãos dentro de `.st-key-admin-table` (um
  `st.columns()` pro cabeçalho, um `st.container(key=f"admin-row-{idx}")` por linha) — o Streamlit
  insere um `gap` padrão de 16px entre blocos empilhados assim, nunca zerado. Confirmado via
  `getBoundingClientRect`: 16px de vão tanto entre cabeçalho e primeira linha quanto entre linhas
  consecutivas — como a borda de cada linha só cobre a própria caixa (rodada anterior), o gap ficava
  sem nenhuma linha, dando a impressão de registros "soltos" em vez de uma grade conectada. Corrigido
  com `gap: 0 !important` direto em `.st-key-admin-table` — cabeçalho e linhas ficam coladas, com a
  própria borda de cada uma servindo de único separador (mesmo efeito visual de uma tabela HTML normal
  ou do `st.dataframe` antigo). Opacidade das bordas (coluna, linha e cabeçalho) subida de
  `var(--overlay-06)` para `var(--overlay-16)` na mesma rodada — com só 6%, a linha ficava quase
  invisível contra o fundo (creme claro/quase preto no escuro), reforçando a impressão de "sem grade"
  mesmo já com `gap:0`. Padding de `.admin-header-cell`/`.admin-cell` igualado pra 8px nos dois eixos
  (antes 10px vertical × 6px horizontal) — o vertical maior que o horizontal deixava o respiro entre
  linhas visivelmente mais largo que entre colunas, quebrando a sensação de grade uniforme (pedido do
  usuário).
  **Décima terceira rodada — moldura externa invisível e última linha cortada, achados via harness
  isolado (Playwright + dados falsos, sem tocar Cognito real, `render_admin_panel` chamado direto com
  `infrastructure.list_*`/`is_admin` monkeypatchados) comparando com uma imagem de referência trazida
  pelo usuário:** (1) `.st-key-admin-table` tinha `border: 1px solid var(--overlay-08)` mas nenhum
  `background` — capturas de tela nos dois temas mostraram a moldura praticamente invisível contra o
  gradiente de `stAppViewContainer` (a caixa "flutuava" só com os divisores internos visíveis, sem
  ler como cartão), diferente da barra de nav (`.st-key-admin-nav`, profile.css) que já usa o par
  `background:var(--overlay-03)` + `border` pro mesmo efeito. Corrigido replicando esse par
  fundo/borda em `.st-key-admin-table`, e subindo a opacidade da borda de `-08` pra `-16` (igual aos
  divisores internos — com `-08` a moldura saía mais fraca que a própria grade que envolve, invertendo
  a hierarquia visual esperada). (2) A última linha da tabela saía com a base do texto cortada bem na
  curva do `border-radius` quando calhava de ter descendentes mais baixos (ç, ã) — medido via
  `scrollHeight`/`clientHeight`/`getBoundingClientRect`: o content-box da caixa (`overflow-x:auto`, que
  por regra do CSS Overflow promove `overflow-y` pra "auto" também) terminava exatamente no pixel final
  da soma das alturas dos filhos, sem nenhuma folga — qualquer detalhe de rendering de fonte que
  ultrapassasse o content-box da própria célula em 1-2px (comum em glifos com descendente) virava corte
  visível. Corrigido com `padding-bottom: 16px` em `.st-key-admin-table` (confirmado depois do ajuste:
  `scrollHeight == clientHeight`, sem overflow residual). Investigado e descartado como causa: diferença
  de altura entre linhas com botão (~43px) e sem botão (~23px) via `flex-shrink`/`flex-basis` no item —
  sobrepor `flex:0 0 auto !important` inline via JS não mudou a altura renderizada em nada (mesmo valor
  de pixel antes/depois), então o mecanismo real não é o item shrinkar por causa do próprio flex-basis:
  é a falta de folga no content-box mesmo, resolvida só com o padding. Também verificado (e descartado
  como bug real) um caso que parecia divisor ausente entre duas linhas consecutivas sem botão — era
  artefato de reamostragem do crop/zoom do PNG pra inspeção; `getComputedStyle` e varredura pixel a
  pixel no PNG original confirmaram a borda presente e idêntica às demais.
  **Décima quarta rodada — migração de `st.columns()`/`st.button()` pra
  `st.components.v2.component()`:** depois da rodada anterior (bordas corrigidas), avaliado se dava
  pra resolver as mesmas 5 premissas (responsividade, botões, bordas de tabela normal, cor por tema,
  centralização de cabeçalho e células) com uma base estrutural mais sólida que "N `st.columns()`
  empilhados, um flexbox por linha" — que só alinhava cabeçalho e linhas por coincidência de repetir
  o mesmo array de pesos (`_COLUMN_WEIGHTS`) em cada `st.columns()`, sem garantia estrutural nenhuma
  (foi exatamente essa fragilidade que causou os bugs das rodadas 10-13: linha desalinhada, gap de
  16px, altura inconsistente entre linha com/sem botão). Mapeadas três alternativas (`st.dataframe`
  nativo, `streamlit-aggrid`, `st.components.v2`) via doc oficial (WebFetch) e spikes descartáveis
  (Playwright + Streamlit, dados falsos, sem tocar Cognito real):
  - `st.dataframe`/`column_config.ButtonColumn` (Streamlit 1.59.0+, disponível): `pandas.Styler`
    consegue colorir célula de corpo mas **não o cabeçalho** — confirmado emulando
    `color_scheme="light"/"dark"` do Playwright no MESMO Styler: a cor do canvas do cabeçalho mudou
    sozinha, prova de que ele segue só `prefers-color-scheme` do navegador/SO, nunca o `data-theme`
    custom do FilmBot. Sem contorno documentado — descartado.
  - `streamlit-aggrid`: dependência de terceiro nova, tema documentado como "suporte parcial",
    botão exigiria `JsCode` cru em vez de callback limpo, alinhamento de cabeçalho não documentado —
    descartado sem chegar a testar ao vivo (relação custo/incerteza pior que as outras duas rotas).
  - **`st.components.v2.component()`** (Streamlit 1.51.0+, disponível): `<table>` HTML real, sem
    iframe (Shadow DOM, `isolate_styles=True` padrão) — confirmado que Shadow DOM herda CSS custom
    properties da página pai (trocar `data-theme` na página pai via JS puro, sem rerun, mudou a cor
    dentro do componente sozinha), e botão real dispara callback Python via
    `setTriggerValue(key, value)` → `result.key`, inclusive com key dinâmica por linha (`"approve_"
    + email`, testado isolado por e-mail, sem confundir linhas). Escolhida.

  **Achado do spike, não óbvio pela doc oficial:** o exemplo oficial usa
  `document.querySelector(...)` dentro do JS do componente — isso busca no `document` da página
  INTEIRA do Streamlit, não só dentro do Shadow DOM do componente (no teste, pegou por engano o
  botão "Deploy" do próprio Streamlit, e o clique real não disparava nada, sem nenhum erro no
  console). O certo é `component.parentElement.querySelector(...)` (`parentElement` é o
  `ShadowRoot` quando `isolate_styles=True`) — replicado em `admin_table.js`.

  **Achado 2:** `result` do componente reflete só o clique mais recente entre dois `setTriggerValue`
  de chaves diferentes sem rerun no meio (testado: clicar Aprovar da linha 1 e, na mesma sessão sem
  reload, Revogar da linha 2 — só o resultado do Revogar sobrevive em `result`). Não afeta o app real
  porque cada clique já dispara seu próprio rerun e é processado (`_queue_pending_action` +
  `st.rerun()`) antes que outro clique possa acontecer — mesmo padrão de "um clique por vez" que já
  existia com `st.button()`.

  **Mudança de arquivos:** `admin.py::_render_table_header`/`_render_table_row` (a implementação
  `st.columns()`) viraram `_build_table_html`/`_build_table_row_html` (monta o HTML da `<table>`,
  com `<colgroup>` garantindo os mesmos tracks de coluna entre cabeçalho e corpo — `_COLUMN_WEIGHTS`
  agora vira `<col style="width:...px">` literal, não mais pesos proporcionais de `st.columns()`) +
  chamada a `st.components.v2.component(...)`. Todo o CSS da tabela saiu de `admin.css` (que só
  injeta CSS no documento normal do Streamlit, inalcançável pelo Shadow DOM) pra
  `static/css/admin_table.css` novo, passado via `css=` do componente — mesmos tokens
  `var(--overlay-*)`/`var(--text-*)`/`var(--feedback-*)` de antes, incluindo o `padding-bottom:16px`
  da rodada anterior (mesmo bug de content-box sem folga, que também existe aqui já que
  `.admin-table-wrap` ainda usa `overflow-x:auto`). JS novo e estático (sem interpolação Python) em
  `static/js/admin_table.js`. `_build_rows`/`_build_table_data`/`_status_label`/`_format_datetime`/
  `_queue_pending_action`/`_render_confirm_dialog` não mudaram — são lógica pura, independente do
  mecanismo de renderização.
  **Décima quinta rodada — colunas Aprovar/Revogar estreitas e altura sem teto, achados pelo
  usuário testando a versão real (não fake) da migração anterior:** (1) as colunas Aprovar/Revogar
  (60px, herdado da versão `st.columns()`) cortavam o cabeçalho ("APRO…"/"REVO…") — subidas pra
  90px cada (`_COLUMN_WEIGHTS`, admin.py; `min-width` de `admin_table.css` ajustado junto, de 1120
  pra 1180, soma nova dos pesos). Botão já centralizava sozinho (`text-align:center` no
  `<td class="col-center">` já bastava, sem precisar de CSS novo no `<button>`). (2) Pedido do
  usuário: a caixa devia crescer verticalmente sem scroll até um teto de ~5 usuários, só then
  passando a rolar — antes não havia `max-height` nenhum em `.admin-table-wrap`, só
  `overflow-x:auto` (que por regra do CSS Overflow promove `overflow-y` pra "auto" também).
  Investigado antes de corrigir: um harness isolado com 2, 5 e 8 linhas fake não reproduziu
  overflow nenhum sem `max-height` (`scrollHeight == clientHeight` em todos os casos,
  `getBoundingClientRect` confirmando que a caixa só cresce com o conteúdo) — a barra vertical que
  o usuário via na tela real provavelmente é reserva de gutter de scrollbar do navegador dele
  (`overflow-x:auto` promovendo `overflow-y` pra "auto" já torna o elemento um scroll container
  nos dois eixos, e alguns navegadores/SOs reservam espaço de scrollbar mesmo sem conteúdo
  excedente), não confirmável a causa exata sem acesso ao ambiente real do usuário. De qualquer
  forma, implementar o teto pedido resolve os dois cenários possíveis. Medido ao vivo (não
  estimado): cabeçalho ≈35.7px, linha ≈40px cada (`getBoundingClientRect`) →
  `max-height: 256px` (cabeçalho + 5 linhas + `padding-bottom` 16px + borda 2px, com folga pra
  variação de sub-pixel) + `overflow-y: auto` explícito em `.admin-table-wrap`. Validado nos 3
  cenários (harness isolado, `FAKE_ROWS` variável): 5 linhas — `scrollHeight == clientHeight`,
  sem scrollbar, borda fecha rente ao conteúdo; 8 linhas — `scrollHeight` (374px) >
  `clientHeight` (254px), scrollbar aparece, caixa mantém os 256px do teto com cantos
  arredondados intactos (não corta feio).
  **Décima sexta rodada — gap entre o grid de colunas e a borda inferior, causa raiz era a
  scrollbar horizontal reservada, não padding (confirma a suspeita registrada sem certeza na
  rodada anterior):** usuário reportou que a borda inferior do `.admin-table-wrap` não "encostava"
  nas linhas verticais de grade — sobrava uma faixa de fundo liso entre o fim da última linha e a
  borda arredondada. Duas tentativas mexendo em padding não resolveram: (1) mover o
  `padding-bottom:16px` do wrapper (herdado da rodada 13) pra dentro só de `tbody tr:last-child
  td` conectou a borda ao grid, mas deixou a última linha visivelmente mais alta que as demais —
  rejeitado pelo usuário, que pediu altura de célula igual em todas as linhas; (2) remover o
  padding inteiramente, sem repor em lugar nenhum, não mudou o gap em nada — sinal de que padding
  nunca foi a causa raiz. Confirmado via DevTools (screenshot do box model trazido pelo usuário):
  `.admin-table-wrap` mede ~549.6px de largura, bem menor que o `min-w
