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
Além de digitar, o usuário pode gravar a preferência em áudio pelo widget nativo `st.audio_input`. Ao parar a gravação, o app confirma automaticamente e transcreve por `transcribe_preference()` (`agent.py`) usando Whisper via `litellm` — modelo configurável por `TRANSCRIPTION_MODEL` (padrão: Groq Whisper Large v3 Turbo, rápido e barato), com `language="pt"` fixo. O texto resultante pré-popula o `st.text_area` de preferência, permanecendo totalmente editável antes de clicar em "Recomendar". Visualmente, o bloco de gravação aparece numa única linha logo abaixo do campo de texto: só os botões do gravador nativo (sem waveform, sem fundo/borda ao redor, direto sobre o fundo escuro do app) encolhidos ao próprio conteúdo, com o badge de timer colado logo ao lado, sem label/emoji. Divide espaço com o contador de caracteres (que fica à direita dessa mesma linha) — ordem inversa à do processamento em Python: o áudio ainda roda antes do `text_area` no script (restrição de `session_state`), mas aparece depois na tela, via containers-placeholder criados na ordem visual desejada (`text-area-slot` / `input-footer-row` em `app.py`) e populados fora dessa ordem. Os dois placeholders vivem dentro de um card único (`st.container(key="input-card")`, fundo `#1a1a1a` + borda, `principal.css`) que substitui o fundo que antes era só da textarea — unifica textarea + gravador + contador num painel só, com glow laranja no `:focus-within` do card (não mais `:focus` da textarea) quando o usuário digita. A textarea em si (e o wrapper nativo `stTextAreaRootElement`, que carregava um fundo/borda claros próprios — zerados via CSS) ficam transparentes por dentro do card. Os avisos de transcrição (rate limit, áudio muito longo, erro, vazio, truncado — ver lista abaixo) ficam **fora** desse card, num placeholder próprio (`audio_messages_slot = st.container(key="audio-messages")`) criado logo depois do `input-card` — são feedback sobre uma ação já concluída/rejeitada, não parte do "formulário" em si. Só a mensagem transitória "🎤 Transcrevendo áudio..." continua dentro do card, junto do gravador, por ser um estado em andamento e não um aviso.

- **Confirmação automática e invisível:** o `st.audio_input` nativo não expõe nenhuma forma de cancelar uma gravação **em andamento** (o único botão durante o estado `recording` é "parar", que sempre finaliza e envia o áudio para o backend) — essa limitação foi confirmada inspecionando o bundle JS interno do widget. Por isso existe uma etapa intermediária entre "gravação parou" e "chamar a API de transcrição" (`audio_awaiting_confirmation`/`audio_pending_bytes`), com dois botões internos ("▶️ Usar gravação" / "✕ Cancelar", dentro de `st.container(key="audio-confirm-buttons")`) — mas eles ficam **escondidos via CSS** (`.st-key-audio-confirm-buttons { display: none; }` em `principal.css`) porque o usuário nunca precisa clicar neles à mão: `audio_cancel_recording.js` confirma "Usar gravação" automaticamente assim que os botões aparecem, a menos que o ícone de descarte (abaixo) já tenha sinalizado cancelamento. `audio_widget_seq` é incrementado tanto ao descartar quanto ao confirmar (`use_clicked`) para forçar uma nova instância do `st.audio_input` (troca de `key`) — o único jeito de "esvaziar" visualmente um áudio já gravado, já que o widget não tem API para isso. Sem esse reset também no caminho de sucesso, o widget nativo mantém internamente `recordingUrl` da última gravação e passa a renderizar um segundo botão "▶️ Play" ao lado do de gravar indefinidamente — inofensivo hoje (a caixa nativa acomoda naturalmente qualquer botão extra, ver `principal.css`), mas sem sentido nesse fluxo (a gravação já foi usada), daí o reset.
- **Ícone de descarte durante a gravação:** `static/audio_cancel_recording.js` (injetado por `load_audio_cancel_script()`, mesmo padrão de `contador_caracteres.js`) mostra um ícone ✕ em vermelho ao lado do botão nativo enquanto o estado é `recording`. Como a função interna `cancel()` do gravador não é acessível fora do componente React, o ícone simula "parar" (clica no botão nativo) e arma uma flag em `localStorage`; assim que o botão (escondido) "✕ Cancelar" aparece, o script clica nele automaticamente em vez de confirmar "Usar gravação", descartando o áudio sem nunca chamar `transcribe_preference`. Como os botões de confirmação nunca ficam visíveis, não há nenhum "flash" de UI perceptível ao usuário — só uma pausa breve entre parar e transcrever (ou entre parar e resetar, no caso do descarte). O toolbar nativo do elemento (`data-testid="stElementToolbar"`, com os ícones "Download as WAV"/"Clear recording" que o Streamlit mostra por conta própria assim que a gravação para) também fica escondido via CSS (`principal.css`) pelo mesmo motivo — sem relação com o fluxo de confirmação/descarte, só ruído visual nessa pausa.
- **Limite de duração:** o `st.audio_input` nativo não tem parâmetro de duração máxima — sem intervenção, a pessoa gravaria pelo tempo que quisesse. `static/audio_timer.js` (injetado por `load_audio_timer_script(_MAX_AUDIO_SECONDS)`, mesmo padrão de `contador_caracteres.js`/`window.parent.document`) para a gravação sozinha ao atingir o limite: a cada 250ms, converte o tempo decorrido do timer nativo do widget (hook não documentado `data-testid="stAudioInputWaveformTimeCode"`, formato "MM:SS") pra segundos totais e, se `>= _MAX_AUDIO_SECONDS`, clica no próprio botão nativo `[aria-label="Stop recording"]` — testado de ponta a ponta via Playwright com um device de áudio fake, gravação real interrompida sozinha entre 14s e 16s. Como esse polling de 250ms pode deixar passar um pouquinho além do limite antes de clicar, e como esse auto-stop não coordena com `audio_cancel_recording.js` (que, sem essa checagem, empurraria por padrão o áudio pro fluxo de "Usar gravação"), a duração é validada em Python assim que os bytes chegam em `app.py` — antes de decidir entre o fluxo de confirmação (`audio_awaiting_confirmation`) e a rejeição — usando `_audio_duration_seconds()` (`agent.py`, módulo padrão `wave`, já que `st.audio_input` sempre entrega WAV). Se a duração exceder `_MAX_AUDIO_SECONDS`, o áudio nunca entra no fluxo de confirmação (não é enviado para transcrição) e o aviso "⚠️ Áudio muito longo" aparece de forma imediata, independente de qual script JS tiver parado a gravação. A validação de duração dentro de `transcribe_preference()` (`agent.py`) continua existindo como segunda camada de defesa. O limite é exibido pro usuário como um badge "decorrido / máximo" (ex: `00:07 / 00:15`) à direita do gravador nativo, atualizado em tempo real pelo mesmo script — mesma ressalva de fragilidade a upgrades de versão do Streamlit do contador de caracteres (ver abaixo). O timer nativo do widget continua sendo lido pelo script, mas fica escondido via CSS (`display: none` em `principal.css`) para não duplicar visualmente o mesmo tempo já exibido pelo badge.
- **Degradação graciosa:** qualquer falha na transcrição (provedor indisponível, sem API key configurada, áudio sem fala detectada, áudio muito longo) nunca bloqueia o campo de texto — a pessoa sempre pode digitar manualmente.
- **Rate limiting próprio:** 30 transcrições por hora por IP (`_MAX_TRANSCRIPTIONS_PER_HOUR`), mais generoso que o limite de recomendações porque o custo de Whisper é bem menor que o fluxo LLM+Athena. Usa um histórico de IPs independente (`_audio_ip_history`) do fluxo de recomendação. Ao atingir o limite, a mesma mensagem já reúne o cronômetro MM:SS (`load_countdown_script(_audio_seconds, element_id="audio-countdown")`) e o lembrete de digitar manualmente enquanto isso — `element_id` explícito porque esse countdown pode estar visível ao mesmo tempo que o da busca (rate limits independentes), e os dois usando `id="countdown"` colidiria no DOM
- **Execução assíncrona:** mesmo padrão de `ThreadPoolExecutor` + `Future` + polling (500ms) já usado no botão "Recomendar", com chaves de `session_state` próprias (`transcribing`/`transcription_future`, além de `audio_awaiting_confirmation`/`audio_pending_bytes`/`audio_widget_seq` da etapa de confirmação) para não colidir com o fluxo de busca.
- **Limite de caracteres:** transcrições acima de 150 caracteres (`_MAX_PREFERENCE_CHARS`) são cortadas nesse limite antes de preencher o campo de texto, com aviso "⚠️ Transcrição excedeu 150 caracteres e foi cortada." — necessário porque o `st.text_area` de destino também tem `max_chars=150` e rejeitaria um valor de `session_state` maior que isso.
- **AWS Transcribe foi avaliado e descartado** como alternativa: embora fosse barato de plugar (reaproveitaria o bucket temporário do Athena e a IAM já existentes, sem precisar de secret novo), jobs batch do Transcribe tipicamente levam 15-60+ segundos até completar mesmo para áudios curtos — muito mais lento que os ~1-3s do Whisper via Groq, prejudicando a experiência de "gravar uma frase curta e ver o texto aparecer".

### Interface (`app.py`)
- Tema escuro com CSS customizado
- Grid responsivo de cards: 3 colunas fixas no desktop (`repeat(3, 1fr)`), 1 coluna no mobile (`≤768px`)
- **Largura do rodapé (`render_footer()`):** antes de pesquisar, o rodapé fica com a mesma largura do hero (640px, centralizado, `.footer { max-width: 640px; margin: auto }`). `.grid-titles` (resultados) não tem largura própria — ocupa a largura natural do `block-container`. Quando há resultado na tela, `body:has(.grid-titles) .footer { max-width: none }` destrava o rodapé pra acompanhar essa largura maior, em vez de ficar preso nos 640px do hero
- **Cabeçalho (`st.container(key="header-row")`):** ícone 🎬 maior (`.header-icon`, 34px) à esquerda, com título "FilmBot" (28px, `!important` — ver nota abaixo) + subtítulo (13px, `!important`) empilhados à direita dele sem nenhuma das duas linhas passar por baixo do ícone (`.header-brand` flex row + `.header-text` flex column, dentro de um único `st.markdown`) — substitui `st.title`/`st.caption`, que rendem um `<h1>` grande demais pra esse contexto de topo de página, mesmo padrão de markdown customizado já usado em `.login-title`/`.login-subtitle` na tela de login. **`!important` no `font-size` de `.header-title`/`.header-subtitle`:** o Streamlit aplica um `font-size` próprio no `<p>` via seletor com especificidade maior que a classe sozinha — sem o `!important`, o valor definido aqui é ignorado e o texto renderiza sempre em 16px, confirmado via inspeção real do DOM (Playwright). Botão "Sair" (`key="btn_sair"`) estilizado como pill discreto (`#3f3f3f`, cinza neutro). A coluna do título cresce (`flex:1 1 auto`) pra preencher o espaço extra e empurrar a coluna do botão (`flex:0 0 auto`) pra ponta direita — necessário porque a regra genérica "Colunas dos botoes se ajustam ao conteudo" (mais acima em `principal.css`) exclui explicitamente linhas com `<h1>`; sem esse `<h1>` (trocado por markdown), as colunas do header passaram a encolher pro conteúdo, deixando um vão grande entre o botão e a borda direita real do hero — medido via inspeção real do DOM (Playwright). Alinhamento vertical do botão via `align-items:center` no `stHorizontalBlock` mais um nudge fino (`position:relative; top:8px`) — o wrapper interno que o Streamlit gera em volta de `st.markdown` reporta uma altura menor que a dos dois parágrafos reais (título+subtítulo), então o `align-items:center` sozinho centraliza o botão ~8px acima do centro visual verdadeiro; compensado diretamente após medir via inspeção real do DOM, já que a causa raiz da altura errada não pôde ser isolada/corrigida via CSS (`height`/`min-height`/`max-height:auto` não tiveram efeito). **Wrap natural (sem breakpoint fixo):** `flex-wrap:wrap` + `justify-content:space-between` no `stHorizontalBlock` — o botão fica lado a lado com o ícone+texto enquanto couber (como no desktop, em qualquer largura) e só quebra pra linha de baixo quando o espaço realmente não for suficiente; `justify-content:space-between` resolve o alinhamento nos dois cenários sozinho (título à esquerda/botão à direita quando cabem juntos; botão alinhado à esquerda quando quebra pra própria linha, já que não sobra "outro lado" pra empurrar), e o `gap:12px` do row garante um respiro mínimo tanto na horizontal quanto na vertical (quando quebra) — testado via Playwright em várias larguras (1280px a 320px)
- **Rate limiting por IP:** máximo de 15 consultas por hora (janela deslizante). O contador ("Consultas restantes: N/15 por hora") é exibido abaixo do campo de texto, em cinza (`.query-counter-text`); quando restam 3 consultas ou menos, o texto muda para laranja em negrito (`.query-counter-low`, `principal.css`) para avisar a pessoa antes de o limite ser atingido. Ao atingir o limite, o botão "Recomendar" é desabilitado e um countdown dinâmico MM:SS mostra quanto tempo falta em tempo real, decrementando a cada segundo — a caixa de aviso vem de `render_feedback()` (renderizada na página real, com CSS de `principal.css`) e só o `<span id="countdown">` é atualizado por `static/countdown.js` (injetado por `load_countdown_script()`, genérico — reusado também pelo bloqueio de login, ver abaixo), que acessa `window.parent.document` a partir do iframe do `st.components.v1.html` — mesmo padrão de `audio_timer.js`, sem duplicar CSS dentro do iframe. Ao chegar em 00:00, a página recarrega automaticamente. O histórico de timestamps é mantido em dict no nível do módulo (`_ip_history`), indexado pelo IP do cliente via `X-Forwarded-For` — sobrevive a reloads da página (reseta apenas no restart do processo Streamlit, ex: deploy)
- **Mensagens de erro/aviso padronizadas (`render_feedback()`, `componentes.py`):** todo feedback de erro/aviso do app — senha incorreta no login, os 5 avisos de transcrição, rate limit de busca, erro ao buscar recomendações e busca sem resultado — usa o mesmo componente: uma caixa `.msg-error`/`.msg-warning` com ícone (❌/⚠️), em vez da mistura anterior de `st.caption()` cru (sem caixa) e `components.html()` com CSS duplicado num iframe. A tela de login duplica `.msg-error`/`.msg-warning` em `login.css` (mesmo motivo de `.accent-gradient-text`: cada tela injeta seu próprio CSS de forma independente). Os blocos de "erro ao buscar"/"sem resultado" — antes soltos fora de qualquer container com largura travada, o que deixava a caixa desproporcional em relação ao resto do hero — agora ficam dentro de `st.container(key="results-messages")`, incluído na mesma regra de `max-width: 640px` de `hero-section`/`hero-actions`/`header-row` (`principal.css`)
- **Botão "Recomendar" desabilitado sem texto:** `disabled=_remaining <= 0 or not preference` — além do rate limit, o botão já nasce desabilitado (opacidade 0.5, `.st-key-btn_recomendar button:disabled` em `principal.css`) enquanto o campo de preferência estiver vazio, sem precisar clicar pra descobrir que não digitou nada
- **Botão "Entrar" do login desabilitado sem senha, em tempo real:** `disabled=_locked_out or not password` no `st.button(key="btn_entrar")`, com `[data-testid="stButton"] > button:disabled { opacity: 0.5; box-shadow: none }` em `login.css`. Habilita/desabilita a cada tecla digitada no campo de senha — não só no próximo rerun do Streamlit (que só ocorre ao perder o foco/Enter) — via `static/login_button_toggle.js` (injetado por `load_login_button_toggle_script(_locked_out)`), mesmo padrão de `contador_caracteres.js`/`window.parent.document` já usado pelo botão "Recomendar"; a flag `locked_out` é passada pro script pro mesmo motivo de `rate_limited` em `contador_caracteres.js` — o JS nunca reabilita um botão que a Python travou por bloqueio de tentativas
- **Bloqueio temporário de login por tentativas incorretas:** após `_MAX_LOGIN_ATTEMPTS` (3) senhas erradas em `_LOGIN_LOCKOUT_SECONDS` (60s), o botão "Entrar" fica desabilitado e a mesma caixa de aviso + countdown do rate limit de busca aparece no lugar da mensagem de erro (`render_feedback("warning", ...)` + `load_countdown_script()`), reaproveitando `_events_in_window()`/`_seconds_until_available()` com uma janela de 60s em vez de 1h. O histórico de tentativas incorretas é mantido em `_login_attempt_history` (mesmo padrão `@st.cache_resource` de `_ip_history`/`_audio_ip_history`, indexado pelo IP via `_get_client_ip()`) — como é uma janela deslizante, não há reset explícito: tentativas antigas simplesmente saem da contagem conforme o tempo passa. O bloqueio é reavaliado no servidor a cada rerun (não só via o atributo `disabled` do botão no HTML), então não pode ser burlado manipulando o DOM no navegador — mesmo um clique forjado com `submit=True` durante o bloqueio cai no primeiro `if _locked_out` do fluxo e nunca chega a comparar a senha
- **Limite de caracteres:** o `st.text_area` da preferência tem `max_chars=150` (`_MAX_PREFERENCE_CHARS`), aplicado tanto à digitação manual (o Streamlit trava a digitação ao atingir o limite) quanto ao texto vindo da transcrição de áudio (truncado antes de preencher o campo — ver seção de transcrição acima). Um contador "N / 150 caracteres" é exibido na mesma linha do gravador (abaixo da caixa de texto), alinhado à ponta direita via `margin-left:auto`, atualizado em tempo real a cada tecla digitada via `static/contador_caracteres.js` (injetado por `load_preference_counter_script()` em `componentes.py`, mesmo padrão de `_inject_css`/`load_main_css`) — o script acessa o DOM da página (`window.parent.document`) através de um iframe same-origin (`st.components.v1.html`), observa a textarea pelo hook `data-testid="stTextArea"` (já que o Streamlit não oferece rerun por-tecla nativamente) e anexa o contador como filho de `.st-key-recorder-card`, a mesma linha flex do gravador. **Atenção:** por depender de um detalhe interno não documentado do Streamlit, esse contador pode quebrar silenciosamente em upgrades futuros de versão — `app.py` não tem teste automatizado, validação é manual (`streamlit run app.py`). Pelo mesmo motivo, `requirements.txt` trava a versão exata do `streamlit` (`==`, não `>=`): local e Lightsail reinstalam as dependências de forma independente a cada deploy (sem lockfile), e uma divergência de versão entre os dois já causou o fundo padrão da textarea (normalmente neutralizado por `[data-testid="stTextAreaRootElement"] { background: transparent !important }` em `principal.css`) aparecer num ambiente e não no outro
- **Habilitar/desabilitar "Recomendar" em tempo real:** o mesmo listener de `input` de `contador_caracteres.js` também alterna `button.disabled` do botão "Recomendar" (`.st-key-btn_recomendar button`) a cada tecla — sem isso, o botão só refletiria o campo vazio/preenchido no próximo rerun do Streamlit (que só acontece ao perder o foco do campo ou Ctrl+Enter), não a cada tecla como o contador de caracteres. `load_preference_counter_script(max_chars, rate_limited=_remaining <= 0)` passa a flag `rate_limited` pro script (mesmo mecanismo de template string de `__MAX_CHARS__`): quando `True` (rate limit de consultas atingido), o JS nunca reabilita o botão via digitação — só um rerun (quando o rate limit já não se aplicar) muda esse estado, evitando que o JS destrave um botão que a Python deliberadamente travou por outro motivo
- **Auto-grow da caixa de texto:** a textarea nasce com altura de ~3 linhas e cresce sozinha conforme o texto ultrapassa esse espaço, via `static/auto_grow_textarea.js` (injetado por `load_textarea_autogrow_script()`, mesmo padrão de `contador_caracteres.js`/`window.parent.document`/`data-testid="stTextArea"`). Ajusta `textarea.style.height` para `scrollHeight` a cada evento `input` (e uma vez ao carregar, cobrindo o caso de texto pré-preenchido pela transcrição de áudio), com um teto de 200px além do qual a caixa passa a rolar internamente em vez de crescer (rede de segurança para colagem de texto com muitas quebras de linha). Mesma ressalva de dependência de estrutura interna não documentada do contador de caracteres acima.
- Botão "Cancelar" durante a busca: a recomendação roda em thread separada (`ThreadPoolExecutor`) com polling de 500ms, permitindo ao usuário cancelar a qualquer momento sem esperar a resposta completa
- Confirmação de áudio automática e invisível ("▶️ Usar gravação" / "✕ Cancelar", ver seção "Entrada alternativa" acima) — o rate limit de transcrições é resolvido diretamente em Python antes de renderizar os botões (escondidos), sem depender de clique em botão desabilitado
- Logging de erros: exceções na busca são registradas via `logging.exception()` e enviadas ao CloudWatch Logs (quando `CLOUDWATCH_LOG_GROUP` está configurada) para diagnóstico em produção
- Retry automático nas chamadas ao LLM: `_call_llm_step1` e `_call_llm_step3` (`agent.py`) passam `num_retries=_LLM_NUM_RETRIES` (3) para `litellm.completion()`, que reenvia a chamada internamente (via tenacity) quando o provedor responde com `APIError`, `TimeoutError` ou `ServiceUnavailableError` — cobre indisponibilidades transitórias do provedor (ex.: erro 503 "service too busy"), que sem isso já eram tratadas como falha definitiva na primeira tentativa. Se todas as tentativas falharem, a exceção ainda propaga normalmente para `app.py`, que trata como qualquer outro erro de busca (ver item acima). Diferente da transcrição de áudio (que não tem retry nem fallback de modelo, por design — ver seção de transcrição)
- Cada card exibe, de cima para baixo (layout enxuto, poucos rótulos de texto — `componentes.py::render_card()`):
  - Imagem de fundo (backdrop preferido sobre poster)
  - Título
  - Motivo da recomendação em destaque (gerado pelo LLM na Etapa 3), logo abaixo do título — itálico,
    com leve realce visual, truncado em 3 linhas no desktop
  - Linha única de metadados: data de lançamento (ou ano, quando a data não está disponível) · tipo
    (filme/série) · badge de classificação indicativa (L/10/12/14/16/18), com a nota (★) alinhada à
    direita
  - Badges laranja por gênero (máx. 3 visíveis, sem indicador para o restante). Um gênero mencionado
    explicitamente pelo usuário (ex: "filmes de terror") é priorizado — `componentes.py::_prioritize()`
    o move para o início da lista antes do corte de 3, então ele nunca fica de fora se estiver presente
    no título
  - Duração/temporadas em linha própria
  - Link ▶ Trailer (quando disponível) e, à direita na mesma linha, os badges de texto dos provedores
    — streaming e aluguel/compra combinados num único grupo e deduplicados por nome
    (`componentes.py::_render_provider_badges()`), sem rótulo "Onde assistir"/"Aluguel/Compra", mas
    com o nome do provedor sempre visível como texto (sem logo — a query em `agent.py` traz apenas
    `streaming_providers`/`rent_buy_providers`, os nomes). Máx. 6 visíveis, sem indicador para o restante, mesma priorização de `_prioritize()`
    para um provedor mencionado explicitamente (ex: "animações da Crunchyroll")
  - Badge amarelo 🎬 "Em cartaz até DD/MM/YYYY" quando `in_theaters=true`
  - Sinopse recolhida por padrão atrás de um accordion "▸ Sinopse" (checkbox hack em CSS, já que
    `st.html` não executa `<script>`) — clicar expande o texto completo e troca a seta para "▾",
    independente do tamanho do texto

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
| `agent.py` | `_call_llm_step1(preference)` | Chama o LLM (`LLM_MODEL`) para gerar a cláusula WHERE via function calling. Retry automático (`num_retries=_LLM_NUM_RETRIES`) em erro transitório do provedor |
| `agent.py` | `_call_llm_step3(preference, titles_for_llm)` | Chama o LLM (`LLM_MODEL`) para gerar o motivo de cada título já encontrado pelo Athena. Retry automático (`num_retries=_LLM_NUM_RETRIES`) em erro transitório do provedor |
| `agent.py` | `_log_token_usage(step, response)` | Registra `prompt_tokens`, `completion_tokens`, `total_tokens` e `model` (`LLM_MODEL`) da resposta do LLM via `logging.info` (ver observação na seção "Observabilidade de tokens") |
| `agent.py` | `transcribe_preference(audio_bytes)` | Transcreve áudio (WAV) para texto via Whisper (`litellm.transcription`, modelo `TRANSCRIPTION_MODEL`). Rejeita áudios acima de 15s (`AudioMuitoLongoError`) antes de chamar a API. Sem fallback automático de modelo |
| `agent.py` | `_audio_duration_seconds(audio_bytes)` | Calcula a duração de um áudio WAV via módulo padrão `wave` |
| `agent.py` | `_load_transcription_api_key()` | Busca `transcription_api_key` no Secrets Manager (via `FILMBOT_SECRET_ARN`) em produção, ou `TRANSCRIPTION_API_KEY` do `.env` em desenvolvimento; retorna `None` (não quebra o app) se ausente |
| `formatacao.py` | `format_record(record)` | Converte um registro bruto do Athena em dict formatado para o card (tipo, gêneros, duração, data, nota, etc.) |
| `formatacao.py` | `_format_type()`, `_format_genres()`, `_format_title_duration()`, `_format_release_date()`, `_format_theater_end_date()`, `_format_rating()` | Funções puras de formatação de campos individuais |
| `app.py` | `_load_filmbot_password()` | Busca `filmbot_password` no Secrets Manager (via `FILMBOT_SECRET_ARN`) e grava `.streamlit/secrets.toml` (chmod 600) para a autenticação do Streamlit; não faz nada se o arquivo já existir |
| `app.py` | `_create_ip_history()`, `_create_audio_ip_history()`, `_create_login_attempt_history()` | Factories `@st.cache_resource` que criam os dicts compartilhados `_ip_history` (recomendações), `_audio_ip_history` (transcrições) e `_login_attempt_history` (tentativas de login incorretas), garantindo que os históricos de rate limiting sobrevivam a reruns e resetem apenas no restart do processo |
| `app.py` | `_get_client_ip()` | Obtém o IP do cliente via header `X-Forwarded-For`; confiar no primeiro valor só é seguro porque o Caddy sobrescreve o header (`header_up`) em vez de anexar — ver `deploy/Caddyfile` |
| `app.py` | `_events_in_window(history, ip, window_seconds)` | Conta eventos dentro da janela de tempo informada (janela deslizante) para o IP no histórico informado e limpa registros expirados. Reusada para recomendações (`_ip_history`, janela de 1h), transcrições (`_audio_ip_history`, janela de 1h) e tentativas de login incorretas (`_login_attempt_history`, janela de `_LOGIN_LOCKOUT_SECONDS`) |
| `app.py` | `_seconds_until_available(history, ip, window_seconds)` | Calcula quantos segundos faltam até o evento mais antigo do IP expirar, na janela de tempo informada |
| `app.py` | Interface Streamlit | Orquestra a UI: autenticação, gravação/transcrição de áudio, rate limiting, busca assíncrona e exibição de resultados |
| `componentes.py` | `load_login_css()`, `load_main_css()`, `load_preference_counter_script()`, `load_audio_cancel_script()`, `load_audio_timer_script()`, `load_textarea_autogrow_script()`, `load_countdown_script()`, `load_login_button_toggle_script()`, `render_card()`, `render_grid()`, `render_feedback()`, `render_footer()`, `render_login_footer()` | Helpers de renderização HTML com escape contra XSS |
| `componentes.py` | `_prioritize(items, terms)` | Reordena uma lista de badges de texto (gêneros ou nomes de provedores) colocando primeiro os que contêm algum termo destacado (case-insensitive), preservando a ordem relativa dentro de cada grupo |
| `componentes.py` | `_parse_provider_names(names_raw)` | Faz o parsing de um grupo de provedores (streaming ou aluguel/compra) a partir da string comma-joined vinda de `glue_agg` |
| `componentes.py` | `_render_provider_badges(names, highlighted)` | Monta os badges de texto de provedor (streaming e aluguel/compra já combinados e deduplicados por `render_card()`), prioriza via `_prioritize()` o provedor mencionado pelo usuário |
| `static/login.css` | CSS da tela de login | Estilos específicos da tela de autenticação |
| `static/principal.css` | CSS da página principal | Estilos do grid, cards e layout responsivo |
| `static/contador_caracteres.js` | Script do contador dinâmico do campo de preferência + habilitar/desabilitar "Recomendar" | Observa a textarea via `data-testid="stTextArea"` e atualiza o contador e o `disabled` do botão "Recomendar" a cada tecla digitada (exceto quando `rate_limited`) |
| `static/audio_cancel_recording.js` | Script do ícone de descarte da gravação de áudio | Observa `[aria-label="Stop recording"]`; ao clicar no ícone ✕ (vermelho), simula "parar" e auto-confirma o descarte via `localStorage` (ver seção "Entrada alternativa") |
| `static/audio_timer.js` | Script do timer decorrido/máximo do gravador de áudio | Atualiza `#audio-timer-badge` para `decorrido / máximo` enquanto `[aria-label="Stop recording"]` existir, lendo `data-testid="stAudioInputWaveformTimeCode"`; fora do estado `recording`, volta a `00:00 / máximo` |
| `static/auto_grow_textarea.js` | Script de auto-grow do campo de preferência | Observa a textarea via `data-testid="stTextArea"` e ajusta `style.height` ao `scrollHeight` a cada tecla digitada, com teto de 200px |
| `static/countdown.js` | Script de countdown MM:SS genérico (rate limit de busca, rate limit de transcrição e bloqueio temporário de login) | Atualiza o `<span>` de `id` configurável (`element_id`, padrão `"countdown"`, renderizado por `render_feedback()` na página real, via `window.parent.document`) a cada segundo; recarrega a página sozinho ao chegar a 00:00 |
| `static/login_button_toggle.js` | Script de habilitar/desabilitar "Entrar" do login | Observa o campo de senha via `data-testid="stTextInput"` e atualiza o `disabled` de `.st-key-btn_entrar button` a cada tecla digitada (exceto quando `lockedOut`) |

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
