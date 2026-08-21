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

**Destaque de gênero/provedor nas badges:** `_extract_highlighted_terms()` extrai por regex os valores de `lower(genre_names) LIKE '%valor%'` e `lower(streaming_providers) LIKE '%valor%'` de volta da própria `where_clause` gerada pelo LLM — reaproveita uma decisão que o LLM já tomou no Passo 1, sem chamada extra de LLM. Cláusulas `NOT LIKE` são ignoradas (o usuário não quer aquele valor, não deve ser destacado). O resultado é anexado a cada registro formatado como `highlighted_genres`/`highlighted_providers` e usado por `components.py::_prioritize()` (ver seção "Interface") para colocar o gênero/provedor mencionado primeiro nas badges do card.

O schema informado ao LLM inclui colunas de ficha técnica como `director` e `actor_names` (além de `screenplay`, `music_composer`, `producer`, `cinematographer`, `editor`), permitindo buscas como "filmes do Christopher Nolan" ou "filmes com Tom Hanks" — todos esses campos também são exibidos no card, na seção "Ficha Técnica" (ver seção "Interface").

**Cache de WHERE clauses:** a cláusula WHERE gerada pelo LLM é armazenada em cache em memória (dict no módulo), indexada pelo hash MD5 da preferência normalizada (lowercase + strip). Consultas repetidas (ex: "filmes de terror" digitado duas vezes) reutilizam a cláusula cacheada sem chamar o LLM novamente. TTL de 1 hora — compatível com a frequência de atualização semanal dos dados SPEC. O cache é limpo automaticamente ao reiniciar o processo Streamlit. Como o destaque de gênero/provedor (`_extract_highlighted_terms()`) é derivado da mesma `where_clause` cacheada, um cache hit reproduz exatamente o mesmo destaque de uma chamada fresca ao LLM.

### Etapa 2 — Consulta ao Athena
A cláusula WHERE gerada pelo LLM é validada (`_validate_where()` bloqueia SQL perigoso como DROP, DELETE, INSERT, subqueries) e executada na tabela `tb_tmdb_discover_unified_{env}` (camada SPEC), sem nenhum filtro fixo de qualidade por `vote_count` — a relevância vem só de `ORDER BY popularity DESC` (abaixo) e do pool+sorteio. Isso inclui de graça títulos com `air_date` futuro (ainda não lançados, badge "Em breve" no card — ver seção "Interface"), que nunca tiveram chance de acumular voto; antes existia um filtro fixo `vote_count >= 50` com um bypass explícito só pra esse caso (`vote_count >= 50 OR air_date > CURRENT_DATE`), removido por ser redundante com a ordenação por popularidade — o LLM ainda pode usar `vote_count` na própria `where_clause` quando o pedido do usuário pedir explicitamente por títulos bem votados/consagrados.

**Pool de candidatos + sorteio (variedade entre buscas):** a query busca um pool maior que o `limit` pedido — `min(limit * _CANDIDATE_POOL_MULTIPLIER, _CANDIDATE_POOL_MAX)` títulos, ordenados por popularidade (padrão: multiplicador 3x, teto de 30) — e `search_titles_spec()` sorteia um subconjunto de `limit` títulos desse pool, preservando a ordem de popularidade entre os escolhidos. Sem isso, a mesma pergunta (ou uma parecida, já que o LLM tende a gerar a mesma `where_clause`) sempre devolveria exatamente o mesmo top-N por popularidade — a ordenação fixa da query, não só o cache, é que causava a repetição. Como a Etapa 2 roda em toda busca (mesmo em cache hit do Passo 1 — só a cláusula WHERE é cacheada, não os títulos), a variedade acontece sempre, sem custo adicional de LLM. **Valores conservadores de propósito:** a instância Lightsail de produção tem só 1 GB de RAM (bundle `micro_3_0`) — cada linha a mais do pool aumenta proporcionalmente o payload de boto3 carregado na memória por busca, então o teto fica bem abaixo do que daria pra buscar sem problema numa instância maior.

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
- `upcoming_date` (string formatada conforme acima, `null`/`None` caso contrário) — só preenchido quando
  `air_date` é estritamente futuro (título ainda não lançado, `formatting.py::_is_upcoming()`) — usado pro badge
  "Em breve" (ver seção "Interface")
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

Esta etapa roda em toda busca com resultados, mesmo quando a Etapa 1 tem cache hit: os títulos reais só existem depois da consulta ao Athena, então o motivo não pode ser cacheado junto com a cláusula WHERE.

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

### Interface (`app.py`, `login.py`, `recommendation.py`, `cards.py`, `infrastructure.py`)

`app.py` é só o orquestrador: bootstrap (`infrastructure.py`), chama a tela de login (`login.py`, que interrompe a execução com `st.stop()` se o usuário não estiver autenticado), renderiza o cabeçalho e chama, em sequência, o formulário de preferência/busca assíncrona (`recommendation.py`) e a exibição dos resultados (`cards.py`). É puramente organização de código — a experiência do usuário continua sendo uma tela única (login → formulário → cards no mesmo rerun), sem navegação multipage do Streamlit. `recommendation.py` escreve `titles`/`search_error`/`search_completed` em `st.session_state`; `cards.py` só lê essas chaves, sem import entre os dois. `infrastructure.py` reúne o bootstrap de processo (senha via Secrets Manager, logging CloudWatch) e os utilitários genéricos de rate limiting (IP do cliente, janela deslizante, segundos restantes) usados tanto por `login.py` quanto por `recommendation.py`, cada um com seu próprio dict de histórico.

O CSS (`static/`) acompanha a mesma divisão: `base.css` (transversal), `login.css`, `app.css` (cabeçalho/rodapé), `recommendation.css` e `cards.css`. Cada `load_*_css()` (`components.py`) injeta `base.css` antes do CSS específico da tela — necessário porque duas regras (reset genérico de botão em `base.css` e `.st-key-btn_recomendar` em `recommendation.css`) têm especificidade CSS empatada; sem `base.css` injetado primeiro, o botão "Recomendar" perderia a largura `100%` e voltaria a 140px fixo.

- Tema escuro com CSS customizado
- **Sem linha divisória entre blocos** — nem acima de "Encontramos X opções para você!" (`.results-heading`,
  `cards.py`/`cards.css`), nem entre "Consultas restantes"/último card e o rodapé (`.footer`, `app.css`):
  a separação é só espaço, mesmo padrão usado no resto da página (ex. cabeçalho → "O que você quer assistir
  hoje?"). O container `hero-scripts` (`recommendation.py`, só injeta `<script>`s, `display:none`) fica entre
  `hero-actions` e o título dos resultados — mesmo escondido, o wrapper que o Streamlit insere ao redor dele
  continua contando pro `gap:16px` nativo do `stVerticalBlock` da página. Nos três pontos onde a linha existia
  (contador→rodapé sem resultado, contador→título dos resultados, último card→rodapé com resultado), o
  `margin`/`padding` soma 40px — igual ao gap nativo de 16px + `margin-top:24px` de `.hero-heading-wrap`
  (`recommendation.css`) usado entre o cabeçalho e o hero. **`!important` obrigatório em `.results-heading`:**
  o Streamlit injeta CSS próprio por instância (classe autogerada + elemento, ex.
  `.st-emotion-cache-XXXXXX p { margin-top: 0 }`), com especificidade maior que uma classe isolada — sem
  `!important`, o `<p>` do título perde o `margin-top` declarado, independente do valor escrito em `cards.css`
- Grid responsivo de cards: 3 colunas fixas (`repeat(3, 1fr)`) acima de 1200px (breakpoint
  "xl" do Bootstrap, escolhido por convenção), 1 coluna abaixo disso (`≤1200px`, cobrindo
  tanto celular quanto janela de desktop estreita). O breakpoint não é 768px (limite típico
  de "mobile") porque abaixo de ~1200px badges de gênero/provedor com nomes longos ("Amazon
  Prime Video", "Ação & Aventura") costumam não caber numa linha só e quebram pra 2ª/3ª linha
  dentro do próprio card — largura insuficiente pro card, não um efeito colateral entre
  vizinhos da fileira; valor aproximadamente confirmado empiricamente via Playwright com
  nomes reais e longos do catálogo (~373px de card já resolve o caso comum), mas sem folga
  extra pro overhead real do Streamlit, então vale reconferir no app se aparecer wrap bem na
  borda do breakpoint. Mesmo com esse ajuste, o teto máximo de 6
  gêneros/6 provedores simultâneos (caso raro) ainda pode quebrar linha em qualquer largura
  — nomes demais pra caber num card, risco residual aceito conscientemente em vez de
  resolvido com "+N" (exigiria JS pra contar precisamente quantos badges couberam, o que
  esse componente específico não tem — ver bullet da linha de sinopse/trailer mais abaixo).
  No fallback de 1 coluna, `.card` ganha `max-width: 460px` + `.grid-titles { justify-items:
  center }` — sem isso, numa janela larga mas ainda abaixo do breakpoint (ex. 1000px), o
  único card da fileira esticaria pra largura inteira do container, deixando o pôster (16:9,
  `width:100%`) desproporcionalmente grande; em celular real (viewport mais estreito que o
  teto) isso não muda nada, o card já ocupa a largura disponível de qualquer forma. **Alinhamento
  entre os 3 cards da fileira, só no topo:** `.grid-titles` é grid de 3 colunas com
  `align-items: stretch` — isso estica cada card (fundo/borda) até a altura do maior vizinho da
  fileira, sem precisar de nenhum posicionamento explícito de linha/coluna. Só o **topo**
  (pôster, `.card-media`) fica de fato alinhado entre os 3 cards, e isso "de graça":
  `aspect-ratio:16/9` + colunas de largura igual garantem a mesma altura de pôster nos 3 cards.
  Todo o resto do card (título, motivo, meta-line, duração, "Em cartaz", gêneros, provedores,
  Ficha Técnica, Sinopse/Trailer) tem altura livre por card, sem nenhum mecanismo de sincronia
  com os vizinhos — cada um ocupa só o que o próprio conteúdo pede (é justamente nessa faixa que
  o conteúdo mais varia entre títulos, então soltar tudo ali evita vãos vazios). Abaixo do
  breakpoint os cards empilham 1 por linha e esse alinhamento de pôster entre vizinhos deixa de
  fazer sentido (cada card já ocupa a largura toda sozinho) — não precisa de nenhum reset, já que
  nada depende de posicionamento explícito. **Respiro entre seções:** via `margin-top` no início
  de cada seção do card (`.row-reason`, `.meta-line`, `.genres-container`, `.providers-row`,
  `.row-people`, `.row-synopsis` — todas com 16px), não um `gap` uniforme em `.card-body`. Toda
  seção do card, sem exceção, só existe no HTML quando tem conteúdo real (`render_card()`,
  `components.py`) — sem `reason` a `.row-reason` nem é gerada, sem data/tipo/nota/duração a
  `.meta-line` nem é gerada, e assim por diante — então nenhuma seção ausente fica "reservada"
  vazia contribuindo `margin-top` à toa; o respiro sempre vem do primeiro elemento realmente
  presente. `duration-row`/`cinema-row` usam um respiro menor (`margin-top: 4px`) por ficarem
  mais coladas na meta-line, como continuação do mesmo bloco de "fatos rápidos".
- **Largura do rodapé (`render_footer()`):** antes de pesquisar, o rodapé fica com a mesma largura do hero (640px, centralizado, `.footer { max-width: 640px; margin: auto }`). `.grid-titles` (resultados) não tem largura própria — ocupa a largura natural do `block-container`. Quando há resultado na tela, `body:has(.grid-titles) .footer { max-width: none }` destrava o rodapé pra acompanhar essa largura maior, em vez de ficar preso nos 640px do hero. **Respiro acima do rodapé:** padding-top de 16px (estado sem resultado) ou 24px (`body:has(.grid-titles) .footer`, mais `margin-top:16px`) soma 40px de respiro em relação ao conteúdo anterior, igual ao padrão cabeçalho→hero usado no resto da página — ver bullet "Sem linha divisória entre blocos" acima. **Padding vertical simétrico (16px/16px sem resultado, 24px/24px com grid):** o texto fica centralizado dentro da própria caixa do rodapé, em vez do padding-bottom fixo em 8px que existia antes (ajuste a pedido do usuário, comparando com a caixa desenhada visualmente enxuta demais embaixo). **`margin-top: -17px` no estado sem resultado:** o respiro visível de tinta a tinta entre `.query-counter-text` e `.footer` (medido por pixel — screenshot + análise de brilho por linha, Python/Pillow/numpy, não `getBoundingClientRect`, que aqui não reflete o espaço realmente em branco por causa do `padding-top` interno da própria caixa do rodapé + leading de fonte) ficava em ~69px com `margin-top:0`, bem maior que o mesmo respiro cabeçalho→hero (~52px, ver bullet do hero abaixo). `-17px` traz os dois pro mesmo alvo (~52px) — a favor do espaçamento mais compacto entre esses dois pontos, decisão explícita do usuário (preferiu estreitar o gap maior, não alargar o menor). **Só o estado sem resultado foi recalibrado dessa forma** — o estado com grid (`body:has(.grid-titles) .footer`, `margin-top:16px` + `padding-top:24px`) não foi remedido opticamente nesta rodada (precisaria de resultado de busca real/Athena pra medir o respiro contra o último card de verdade, não um `.grid-titles` simulado via DOM) — mantém o valor de caixa antigo, possivelmente com o mesmo desvio óptico do estado sem resultado. **Respiro fixo de 40px entre o rodapé e o fim da página:** `[data-testid="stMain"] .block-container` tem `padding-bottom: 56px !important` — não 40px: o wrapper interno que o Streamlit gera em volta do `st.markdown` do rodapé reporta uma altura ~16px menor que o conteúdo real (mesmo quirk do rodapé do login, ver `margin-top` negativo de `.footer-login` acima), então sem compensar esses 16px o respiro visível medido ficava em 24px em vez de 40px — 56px = 40px pretendido + 16px de compensação, conferido via Playwright (`getBoundingClientRect`) que o respiro visível abaixo do rodapé bate exatamente com o respiro acima dele ("Consultas restantes"/último card → rodapé) nos dois estados. É um valor **fixo**, não proporcional à altura da tela — `[data-testid="stAppViewContainer"] { min-height: 0 }` (topo do arquivo) garante que o container encolhe pro tamanho real do conteúdo em vez de esticar pra 100vh/100dvh (herdado de `base.css`, necessário só na tela de login). Uma tentativa anterior tentou centralizar o rodapé *proporcionalmente* no vão livre da tela (`display:flex` + `min-height:100vh` no `.block-container` + `margin:auto` no rodapé, espelhando `login.css`) — funcionava tecnicamente (confirmado via Playwright), mas o resultado visual era ruim em telas altas: `margin:auto` distribui *todo* o espaço livre da viewport, criando um vão bem maior que qualquer outro espaçamento da página. Descartada em favor do valor fixo
- **Cabeçalho (`st.container(key="header-row")`):** ícone Lucide outline "clapperboard" laranja (`components.py::icon("clapperboard", size=20)`, `.header-icon-badge .icon { color:#f97316 }` vencendo a `.icon` branca de `base.css` por especificidade) dentro de um wrapper (`.header-icon-badge`) do **mesmo tamanho do ícone** (20x20px, sem fundo/borda — era um badge com fundo escuro antes, virou transparente e depois encolheu pro tamanho do ícone: uma caixa maior que o ícone só cria respiro invisível somado ao `gap` do flex, medido via inspeção real do DOM) à esquerda, com título "FilmBot" (28px, `!important` — ver nota abaixo) ao lado dele em `.header-brand` (`gap:4px`) — substitui `st.title`/`st.caption`, que rendem um `<h1>` grande demais pra esse contexto de topo de página, mesmo padrão de markdown customizado já usado em `.login-title`/`.login-subtitle` na tela de login. O subtítulo (`.header-subtitle`, 13px, `!important`) fica **fora** desse flex, como parágrafo solto logo abaixo (largura toda da coluna, não indentado ao lado do ícone, igual `.login-subtitle`) — com `margin-top: -6px` porque mesmo com `margin:0` sobra um respiro visual entre as duas linhas (line-height/leading da fonte de 28px, não margin/padding; medido via `getBoundingClientRect()`, recalibrado de `-3px` pra `-6px` a pedido do usuário pra ficar mais colado, tipo quebra de linha simples — o nudge `top:8px` do botão "Sair", abaixo, continuou com delta `0px` após a mudança, sem precisar de recalibração). **`!important` no `font-size`/`margin` de `.header-title`/`.header-subtitle`:** o Streamlit aplica valores próprios no `<p>` via seletor com especificidade maior que a classe sozinha — sem o `!important`, os valores definidos aqui são ignorados, confirmado via inspeção real do DOM (Playwright). Botão "Sair" (`key="btn_sair"`) estilizado como pill discreto (`#3f3f3f`, cinza neutro). A coluna do título cresce (`flex:1 1 auto`) pra preencher o espaço extra e empurrar a coluna do botão (`flex:0 0 auto`) pra ponta direita — necessário porque a regra genérica "Colunas dos botoes se ajustam ao conteudo" (`base.css`) exclui explicitamente linhas com `<h1>`; sem esse `<h1>` (trocado por markdown), as colunas do header passaram a encolher pro conteúdo, deixando um vão grande entre o botão e a borda direita real do hero — medido via inspeção real do DOM (Playwright). Alinhamento vertical do botão via `align-items:center` no `stHorizontalBlock` mais um nudge fino (`position:relative; top:8px`) — o wrapper interno que o Streamlit gera em volta de `st.markdown` reporta uma altura menor que a dos dois parágrafos reais (título+subtítulo), então o `align-items:center` sozinho centraliza o botão acima do centro visual verdadeiro; compensado diretamente após medir via `getBoundingClientRect()` (delta final: `0px`), já que a causa raiz da altura errada não pôde ser isolada/corrigida via CSS (`height`/`min-height`/`max-height:auto` não tiveram efeito) — recalibrado a cada rodada em que o espaçamento título↔subtítulo mudou, já que a altura total do bloco de texto desloca o centro-alvo. **Wrap natural (sem breakpoint fixo):** `flex-wrap:wrap` + `justify-content:space-between` no `stHorizontalBlock` — o botão fica lado a lado com o ícone+texto enquanto couber (como no desktop, em qualquer largura) e só quebra pra linha de baixo quando o espaço realmente não for suficiente; `justify-content:space-between` resolve o alinhamento nos dois cenários sozinho (título à esquerda/botão à direita quando cabem juntos; botão alinhado à esquerda quando quebra pra própria linha, já que não sobra "outro lado" pra empurrar), e o `gap:12px` do row garante um respiro mínimo tanto na horizontal quanto na vertical (quando quebra) — testado via Playwright em várias larguras (1280px a 320px)
- **Tela de login (`login-card`, `static/css/login.css`):** mesmo ícone "clapperboard" e mesmo estilo de wrapper do cabeçalho principal — `.login-icon-badge` sem fundo/borda, do mesmo tamanho do ícone (18x18px, mesma lógica de `.header-icon-badge` acima) com o ícone laranja (`.login-icon-badge .icon { color:#f97316 }`, que vence a `.icon` branca de `base.css` por especificidade de seletor descendente) dentro de `.login-brand` (`display:flex; gap:4px`, mesmo princípio de `.header-brand`), ao lado do título "FilmBot" (16px, `!important` — mesmo motivo do `.header-title`: o Streamlit força um tamanho nativo próprio no `<p>`, também ~16px nesse caso por coincidência; declarado explicitamente com `!important` em vez de deixado implícito, pra não depender desse comportamento não documentado do Streamlit continuar do mesmo jeito em versões futuras. Chegou a ser testado em 32px — mesmo tamanho do `.header-title` da tela de recomendação — mas voltou a 16px por pedido do usuário, mantendo o tamanho original) — branco (`.login-title`, sem `.accent-gradient-text`, removida do login: reservada só pra "assistir" no hero). Subtítulo (`.login-subtitle`, 14px `!important`, `margin: -2px 0 20px !important`) logo abaixo — o `margin-top` negativo compensa o line-height/leading da fonte do título (mesmo padrão do `.header-subtitle`, recalibrado pro tamanho de 16px), deixando o respiro entre as duas linhas parecido com uma quebra de linha simples. Sem divisor (removido por pedido do usuário — `.login-divider`/`<hr>` não existe mais) — o campo de senha vem direto em seguida. **Créditos do rodapé dentro do card:** `render_login_footer()` é chamado dentro do mesmo `with st.container(key="login-card")` do formulário (não mais depois, fora do card) — os créditos (`.footer-login`) renderizam como último elemento dentro da borda arredondada do card, não soltos embaixo dele. **`margin-top` negativo em `.footer-login` (`-16px`):** mesmo padrão do `.footer` principal acima — entre o botão "Entrar" e este rodapé existe um container invisível de altura zero (injetor de JS de `load_login_button_toggle_script`), e o `gap:16px` do `stVerticalBlock` do card se aplica duas vezes ao redor dele (32px escondidos mesmo com `padding-top` zerado), medido via inspeção real do DOM. **`box-sizing:border-box` em `.login-card`:** sem isso, `width:100%` soma o `padding`/`border` do card por fora (content-box, padrão do navegador), renderizando ~74px mais largo que o container — causa de scroll horizontal em mobile (achado ao investigar reclamação real de usuário em celular). **`min-height:100dvh`** (com fallback `100vh` antes, em `.block-container` aqui e em `stAppViewContainer` de `base.css`): `100vh` em navegador mobile usa a altura máxima da viewport (barra de endereço recolhida), maior que a área visível no load — o `justify-content:center` centralizava contra essa medida inflada e o card ficava deslocado; `100dvh` acompanha a altura visível real (suportado pelos navegadores mobile atuais)
- **Título do hero (`st.container(key="hero-section")`):** "O que você quer **assistir** hoje?" (`.hero-heading`, 40px, `font-weight:300`, a palavra "assistir" em laranja via `.accent-gradient-text`) — `text-wrap: balance` evita que "hoje?" quebre sozinho numa 2ª linha (comportamento padrão do navegador dentro dos ~616px úteis de `.st-key-hero-section`, sem essa propriedade); navegadores sem suporte (fora do Chrome 114+/Firefox 121+/Safari 17.5+) simplesmente ignoram a regra e mantêm a quebra padrão de antes, sem quebrar nada. **`margin-top` de `.hero-heading-wrap` é 8px, calibrado por medição de pixel (não por `getBoundingClientRect`):** o respiro visível de tinta a tinta entre `.header-subtitle` e `.hero-heading` fica em ~52px com esse valor — ver bullet "Largura do rodapé" acima pro racional completo (por que `getBoundingClientRect()` engana aqui — wrapper interno do Streamlit + leading de fonte grande — e por que ~52px foi escolhido como alvo final para os dois respiros, em vez dos ~69px que o outro lado tinha originalmente): decisão explícita do usuário por espaçamento mais compacto. Uma calibração intermediária tinha subido esse `margin-top` pra 25px (bater 69px nos dois, o valor maior) — revertida a pedido do usuário. **`padding:0 !important` no `<h1>`:** o Streamlit aplica um padding próprio (~20px/16px, medido via inspeção real do DOM) em todo `<h1>` renderizado dentro de markdown, com especificidade maior que a classe sozinha — sem o `!important` (tanto no padding quanto no `margin: 0 0 4px` logo abaixo), o respiro entre o heading e "Digite ou grave o seu pedido" (`.hero-subtitle`) ficava ~4x maior que o `margin` declarado sozinho sugeria. Botão "Recomendar" sem emoji no rótulo (só o texto, igual ao estado desabilitado que já não tinha)
- **Rate limiting por IP:** máximo de 15 consultas por hora (janela deslizante). O contador ("Consultas restantes: N/15 por hora") é exibido abaixo do campo de texto, em cinza (`.query-counter-text`); quando restam 3 consultas ou menos, o texto muda para laranja em negrito (`.query-counter-low`, `recommendation.css`) para avisar a pessoa antes de o limite ser atingido. Ao atingir o limite, o botão "Recomendar" é desabilitado e um countdown dinâmico MM:SS mostra quanto tempo falta em tempo real, decrementando a cada segundo — a caixa de aviso vem de `render_feedback()` (renderizada na página real, com CSS de `base.css`) e só o `<span id="countdown">` é atualizado por `static/js/countdown.js` (injetado por `load_countdown_script()`, genérico — reusado também pelo bloqueio de login, ver abaixo), que acessa `window.parent.document` a partir do iframe do `st.components.v1.html` — mesmo padrão de `audio_timer.js`, sem duplicar CSS dentro do iframe. Ao chegar em 00:00, a página recarrega automaticamente. O histórico de timestamps é mantido em dict no nível do módulo (`_ip_history`, `recommendation.py`), indexado pelo IP do cliente via `X-Forwarded-For` — sobrevive a reloads da página (reseta apenas no restart do processo Streamlit, ex: deploy)
- **Mensagens de erro/aviso padronizadas (`render_feedback()`, `components.py`):** todo feedback de erro/aviso do app — senha incorreta no login, os 5 avisos de transcrição, rate limit de busca, erro ao buscar recomendações e busca sem resultado — usa o mesmo componente: uma caixa `.msg-error`/`.msg-warning` com ícone (❌/⚠️) e texto em spans próprios (`.msg-icon`/`.msg-text`, alinhados via flexbox), em vez da mistura anterior de `st.caption()` cru (sem caixa) e `components.html()` com CSS duplicado num iframe. `.msg-error`/`.msg-warning` moram em `base.css`, carregado tanto pela tela de login quanto pela página principal — evita a duplicação que existia antes do CSS acompanhar o split do Python. Erro ao buscar/busca sem resultado (`recommendation.py`, não mais `cards.py`) são renderizados dentro do próprio `st.container(key="hero-actions")`, logo abaixo do bloco de rate limit/contador — não num container à parte lá embaixo (`results-messages`, removido): assim a mensagem aparece perto do botão "Recomendar" quando sozinha, e empilhada junto do aviso de rate limit quando os dois coexistem, em vez de aparecer separada por todo o resto da página. `cards.py` ficou só com a grid de resultados
- **Botão "Recomendar" desabilitado sem texto:** `disabled=_remaining <= 0 or not preference` — além do rate limit, o botão já nasce desabilitado (opacidade 0.5, `.st-key-btn_recomendar button:disabled` em `recommendation.css`) enquanto o campo de preferência estiver vazio, sem precisar clicar pra descobrir que não digitou nada
- **Botão "Entrar" do login desabilitado sem senha, em tempo real:** `disabled=_locked_out or not password` no `st.button(key="btn_entrar")`, com `[data-testid="stButton"] > button:disabled { opacity: 0.5; box-shadow: none }` em `login.css`. Habilita/desabilita a cada tecla digitada no campo de senha — não só no próximo rerun do Streamlit (que só ocorre ao perder o foco/Enter) — via `static/js/login_button_toggle.js` (injetado por `load_login_button_toggle_script(_locked_out)`), mesmo padrão de `contador_caracteres.js`/`window.parent.document` já usado pelo botão "Recomendar"; a flag `locked_out` é passada pro script pro mesmo motivo de `rate_limited` em `contador_caracteres.js` — o JS nunca reabilita um botão que a Python travou por bloqueio de tentativas
- **Bloqueio temporário de login por tentativas incorretas:** após `_MAX_LOGIN_ATTEMPTS` (3) senhas erradas em `_LOGIN_LOCKOUT_SECONDS` (60s), o botão "Entrar" fica desabilitado e a mesma caixa de aviso + countdown do rate limit de busca aparece no lugar da mensagem de erro (`render_feedback("warning", ...)` + `load_countdown_script()`), reaproveitando `events_in_window()`/`seconds_until_available()` (`infrastructure.py`) com uma janela de 60s em vez de 1h. O histórico de tentativas incorretas é mantido em `_login_attempt_history` (`login.py`, mesmo padrão `@st.cache_resource` de `_ip_history`/`_audio_ip_history` em `recommendation.py`, indexado pelo IP via `get_client_ip()`) — como é uma janela deslizante, não há reset explícito: tentativas antigas simplesmente saem da contagem conforme o tempo passa. O bloqueio é reavaliado no servidor a cada rerun (não só via o atributo `disabled` do botão no HTML), então não pode ser burlado manipulando o DOM no navegador — mesmo um clique forjado com `submit=True` durante o bloqueio cai no primeiro `if _locked_out` do fluxo e nunca chega a comparar a senha
- **Limite de caracteres:** o `st.text_area` da preferência tem `max_chars=150` (`_MAX_PREFERENCE_CHARS`), aplicado tanto à digitação manual (o Streamlit trava a digitação ao atingir o limite) quanto ao texto vindo da transcrição de áudio (truncado antes de preencher o campo — ver seção de transcrição acima). Um contador "N / 150 caracteres" é exibido na mesma linha do gravador (abaixo da caixa de texto), alinhado à ponta direita via `margin-left:auto`, atualizado em tempo real a cada tecla digitada via `static/js/contador_caracteres.js` (injetado por `load_preference_counter_script()` em `components.py`, mesmo padrão de `_inject_css`/`load_app_css`) — o script acessa o DOM da página (`window.parent.document`) através de um iframe same-origin (`st.components.v1.html`), observa a textarea pelo hook `data-testid="stTextArea"` (já que o Streamlit não oferece rerun por-tecla nativamente) e anexa o contador como filho de `.st-key-recorder-card`, a mesma linha flex do gravador. **Atenção:** por depender de um detalhe interno não documentado do Streamlit, esse contador pode quebrar silenciosamente em upgrades futuros de versão — `app.py`/`login.py`/`recommendation.py`/`cards.py` não têm teste automatizado, validação é manual (`streamlit run app.py`). Pelo mesmo motivo, `requirements.txt` trava a versão exata do `streamlit` (`==`, não `>=`): local e Lightsail reinstalam as dependências de forma independente a cada deploy (sem lockfile), e uma divergência de versão entre os dois já causou o fundo padrão da textarea (normalmente neutralizado por `[data-testid="stTextAreaRootElement"] { background: transparent !important }` em `recommendation.css`) aparecer num ambiente e não no outro
- **Habilitar/desabilitar "Recomendar" em tempo real:** o mesmo listener de `input` de `contador_caracteres.js` também alterna `button.disabled` do botão "Recomendar" (`.st-key-btn_recomendar button`) a cada tecla — sem isso, o botão só refletiria o campo vazio/preenchido no próximo rerun do Streamlit (que só acontece ao perder o foco do campo ou Ctrl+Enter), não a cada tecla como o contador de caracteres. `load_preference_counter_script(max_chars, rate_limited=_remaining <= 0)` passa a flag `rate_limited` pro script (mesmo mecanismo de template string de `__MAX_CHARS__`): quando `True` (rate limit de consultas atingido), o JS nunca reabilita o botão via digitação — só um rerun (quando o rate limit já não se aplicar) muda esse estado, evitando que o JS destrave um botão que a Python deliberadamente travou por outro motivo
- **Auto-grow da caixa de texto:** a textarea nasce com altura de ~3 linhas e cresce sozinha conforme o texto ultrapassa esse espaço, via `static/js/auto_grow_textarea.js` (injetado por `load_textarea_autogrow_script()`, mesmo padrão de `contador_caracteres.js`/`window.parent.document`/`data-testid="stTextArea"`). Ajusta `textarea.style.height` para `scrollHeight` a cada evento `input` (e uma vez ao carregar, cobrindo o caso de texto pré-preenchido pela transcrição de áudio), com um teto de 200px além do qual a caixa passa a rolar internamente em vez de crescer (rede de segurança para colagem de texto com muitas quebras de linha). Mesma ressalva de dependência de estrutura interna não documentada do contador de caracteres acima.
- Botão "Cancelar" durante a busca: a recomendação roda em thread separada (`ThreadPoolExecutor`) com polling de 500ms, permitindo ao usuário cancelar a qualquer momento sem esperar a resposta completa
- Confirmação de áudio automática e invisível ("▶️ Usar gravação" / "✕ Cancelar", ver seção "Entrada alternativa" acima) — o rate limit de transcrições é resolvido diretamente em Python antes de renderizar os botões (escondidos), sem depender de clique em botão desabilitado
- Logging de erros: exceções na busca são registradas via `logging.exception()` e enviadas ao CloudWatch Logs (quando `CLOUDWATCH_LOG_GROUP` está configurada) para diagnóstico em produção
- Retry automático nas chamadas ao LLM: `_call_llm_step1` e `_call_llm_step3` (`agent.py`) passam `num_retries=_LLM_NUM_RETRIES` (3) para `litellm.completion()`, que reenvia a chamada internamente (via tenacity) quando o provedor responde com `APIError`, `TimeoutError` ou `ServiceUnavailableError` — cobre indisponibilidades transitórias do provedor (ex.: erro 503 "service too busy"), que sem isso já eram tratadas como falha definitiva na primeira tentativa. Se todas as tentativas falharem, a exceção ainda propaga normalmente para `app.py`, que trata como qualquer outro erro de busca (ver item acima). Diferente da transcrição de áudio (que não tem retry nem fallback de modelo, por design — ver seção de transcrição)
- Cada card exibe, de cima para baixo (layout enxuto, poucos rótulos de texto — `components.py::render_card()`).
  Badges de cor são neutros (cinza) por padrão — laranja fica reservado pra nota e pro "Insight do FilmBot", os
  dois pontos que realmente pedem destaque (a Sinopse deixou de ser laranja — ver bullet abaixo). **O layout muda
  conforme há ou não imagem** (`backdrop_url`/`poster_url`):
  - **Imagem** (backdrop preferido sobre poster), quando existe: nota (★, em chip translúcido) e badge de
    classificação indicativa (L/10/12/14/16/18) ficam sobrepostos no canto superior da própria imagem — sobre um
    leve gradiente escuro (scrim) que garante legibilidade em qualquer pôster — em vez de disputar espaço com o
    texto do corpo do card. **Sem imagem**, não há onde sobrepor: os dois caem de volta pra dentro da linha de
    metadados (ver abaixo), como no layout anterior
  - Título
  - Linha única de metadados: ícone outline "info" (`.meta-icon`, mesmo padrão dos ícones de duração/"em cartaz"
    mais abaixo — ver nota geral sobre ícones Lucide no fim deste bullet) seguido de tipo (Filme/Série) · data de
    lançamento (ou ano, quando a data não está disponível) — tipo
    vem **antes** da data, mês sempre abreviado (`Jan`, `Fev`, ... — `formatting.py::_MONTHS`). O link ▶ Trailer
    (quando disponível) mora nessa mesma linha, à esquerda, logo depois do texto de tipo/data, dentro do mesmo
    `<span class="meta-info">` — não na `duration-row` nem do lado direito da linha (as duas alternativas foram
    tentadas antes e descartadas). Ícone e Trailer ficam dentro de `.meta-info` (não como irmãos soltos de
    `.meta-row`) porque `.meta-line` usa `justify-content:space-between` pra separar texto/nota — um filho a mais
    direto do `.meta-row` empurraria pra ponta esquerda/direita, longe do resto do grupo. O ícone só aparece
    quando há tipo/data pra rotular. Se não sobrar nada pra mostrar em lugar nenhum da linha (sem tipo/data, sem
    Trailer, sem nota), a `.meta-line` inteira nem é gerada — meio solto, mesmo padrão das demais seções do card.
    **Com imagem**, o lado direito fica vazio — nota e classificação já foram pra imagem. **Sem imagem**, o lado
    direito volta a ser a nota (★) e a classificação entra junto de tipo/data à esquerda, como antes. Duração
    **não** entra mais nessa linha (ver bullet seguinte) — como ela vive numa linha própria, a combinação
    tipo+data+Trailer aqui é sempre curta o bastante pra caber na largura mínima do card (~355-373px), sem
    precisar de regra condicional por tipo de título (uma tentativa nesse sentido foi cogitada e descartada).
    **Ícones do card**: todos os ícones (meta-line, duração, Trailer, "em cartaz"/calendário, "Onde assistir",
    Sinopse, "Insight do FilmBot", "Ficha Técnica") são ícones outline do conjunto **Lucide**
    (`components.py::icon()`/`ICON_PATHS`, SVG inline 16x16, `stroke="currentColor"` — públicos, sem prefixo `_`,
    porque `app.py` também usa pra montar o badge do ícone do cabeçalho, ver bullet do cabeçalho acima) — trocaram
    os emoji nativos que o card usava antes (ℹ/⏱/🎬/📅/🔜/📄/✨/👥, e o ícone de marca do YouTube em vermelho no
    Trailer), seguindo o conjunto de ícones que o design system "Luminous" já declarava (`.claude/skills/
    especialista-streamlit-filmbot/SKILL.md`). Todos brancos via a classe `.icon` em `base.css`, **com uma
    exceção**: o ícone "lightbulb" do "Insight do FilmBot" é laranja (`#fdba74`, via `.reason-label .icon`,
    mais específico que `.icon` sozinho) — acompanha a cor do rótulo (ver bullet do Insight mais abaixo), em vez
    do branco padrão. Gênero continua sem ícone (removido por pedido do usuário numa rodada anterior)
  - Duração em linha própria (`.duration-row`), logo abaixo da linha de tipo/data, com ou sem imagem — ícone
    outline "clock" + texto, sem Trailer (que mora na meta-line acima, ver bullet anterior). A div só é gerada quando há duração
    pra mostrar; sem duração, nem é gerada (meio solto). Formato depende do tipo (`formatting.py::
    _format_title_duration()`), tudo abreviado: **filme** com 1h ou mais mostra as duas formas —
    `"1h 30min (90min)"`, hora/minuto seguido do total em minutos entre parênteses, pra dar mais peso visual à
    linha (que senão ficaria bem mais curta que a de série) — abaixo de 1h só `"45min"` (o parêntese seria
    redundante, mesmo valor nos dois formatos); **série** mostra `"N temp · M ep · ~K min/ep"`, sempre abreviado e
    sem plural (nunca `temporadas`/`episódios`/`temps`/`eps`)
  - Badge amarelo "Em cartaz até {data}" quando `in_theaters=true`, logo abaixo da duração — informação,
    duração e "em cartaz" ficam agrupados por serem os 3 fatos rápidos/compactos sobre o título (quando, quanto
    dura, ainda tá em cartaz), antes dos campos com mais badges (gênero, provedor a seguir), que ficam mais perto
    do rodapé de ações. **Mesma linha/classe (`cinema-row`/`cinema-badge`)** cobre três estados mutuamente
    exclusivos do título, todos com o mesmo ícone outline "calendar" (antes eram 3 emoji diferentes por estado —
    🎬/📅/🔜 —, unificados num só ícone Lucide, ver nota geral sobre ícones acima): "Em cartaz até {data}"
    (`in_theaters`), "T{temporada} E{episódio} estreia em {data}" quando a série tem
    `next_episode_season_number`/`next_episode_number`/`next_episode_date`
    preenchidos, ou "Em breve · {data}" quando `upcoming_date` está preenchido (título ainda não lançado —
    `air_date` no futuro, ver `formatting.py::_is_upcoming()`). Nos três, `{data}` já vem formatada por
    `_format_adaptive_date()` (bullet "Formatação adaptativa de data" acima) — `DD/MM` perto de hoje, "Mês de
    Ano" quando distante. Os três nunca coexistem no mesmo
    registro (um título não lançado não pode estar em cartaz nem ter próximo episódio de série já no ar), então
    o slot é reaproveitado sem checar `media_type` explicitamente. Prioridade quando mais de um bater ao mesmo
    tempo por inconsistência de dados: em cartaz > próximo episódio > em breve. Sem nenhum dos três, a div nem é
    gerada (meio solto)
  - Badges de gênero, quando há pelo menos um (sem nenhum gênero a div nem é gerada — meio solto, mesmo padrão
    de duration-row/cinema-row/providers-row/row-people/row-synopsis) — máx. 6 visíveis, sem indicador para o
    restante (trunca silenciosamente; cada card quebra linha de forma independente, sem sincronia com os
    vizinhos da fileira, ver bullet do grid acima). Sem ícone (removido por pedido do usuário) —
    `.genres-container` (`display:flex; align-items:flex-start`) hoje só existe pra receber o `margin-top` de
    seção, envolvendo direto o `<span class="genre-badges">` (`display:flex; flex-wrap:wrap; gap:4px`) que
    agrupa os badges. Fundo/borda em cinza neutro mais sutil que o de provedor (dois degraus diferentes da mesma
    escala neutra, sem matiz própria — `.genre`/`.provider-badge` em `cards.css`), único jeito de distinguir
    os dois grupos agora que nenhum tem mais ícone. Todo gênero mencionado explicitamente pelo usuário (ex:
    "filmes de terror e comédia") é priorizado —
    `components.py::_prioritize()` move todos os que baterem para o início da lista antes do corte, então
    nenhum fica de fora se estiver presente no título — e ganha destaque visual (borda + texto laranja, classe
    `.highlighted`, mesmo `#fdba74` do motivo da IA) via `components.py::_matches_highlighted()`
  - "💡 Insight do FilmBot" — motivo da recomendação em destaque (gerado pelo LLM na Etapa 3), com rótulo laranja
    próprio (`.reason-label`) acima do texto em itálico (`.reason`). Sem barra de acento nem fundo/caixa
    colorida atrás do texto (ambos removidos por pedido do usuário) — só o rótulo laranja marca a seção. O
    texto do motivo é neutro, mesmo tom de `.synopsis-text`/`.people-list` (`#d4d4d4`). Vem **depois dos
    gêneros**, não mais logo abaixo do título — junto de "Onde assistir" (bullet seguinte), fecha o bloco "por
    que te recomendei isso · onde assistir" no fim do card, antes das seções colapsáveis. Sem
    `min-height`/`max-height`/toggle — faz parte
    do meio solto do card (ver item do grid, acima), sem sincronia de altura com os vizinhos da fileira, então o
    texto completo sempre aparece direto (motivo raramente varia muito de tamanho: o prompt do LLM,
    `_REASON_SYSTEM_PROMPT` em `agent.py`, pede ~150 caracteres). Sem `reason` (título fora do fluxo de
    recomendação da IA), a div nem é gerada — caso comum, não só borda
  - "Onde assistir" sempre sozinho numa linha própria (com ou sem imagem), quando há pelo menos um provedor —
    sem nenhum provedor a div nem é gerada (meio solto, mesmo padrão de duration-row/cinema-row/row-people/
    row-synopsis). Rótulo em linha própria acima dos badges (`.providers-label-row`), com o ícone outline "tv"
    ao lado do texto (removido numa rodada anterior por ser emoji, reintroduzido nesta como ícone Lucide — ver
    nota geral sobre ícones acima) — mesmo princípio visual do rótulo "💡 Insight do FilmBot" acima. Streaming e
    aluguel/compra
    combinados num único grupo e deduplicados por nome (`components.py::_render_provider_badges()`), sem badge separado
    "Aluguel/Compra". Cada badge mostra a **logo real do TMDB** (`.provider-logo`, ~14px, `streaming_provider_
    logos`/`rent_buy_provider_logos` — colunas já existentes na tabela SPEC, agora selecionadas por `agent.py` e
    mapeadas por `formatting.py::format_record()`) antes do nome, quando disponível; sem logo pra aquele provedor
    (`logo_path` nulo na origem — ver `glue_agg/src/queries.py`), cai de volta pro badge só-texto. Nome e logo são
    pareados **posicionalmente** (`components.py::_parse_provider_logos()` + `zip_longest`) e a **mesma
    deduplicação por nome** que já existia (`name.lower()`) agora carrega a logo junto — garante que uma logo
    nunca duplica quando o mesmo provedor aparece em streaming e aluguel/compra ao mesmo tempo. Mostra até 6
    badges direto, sem badge "+N" (saber exatamente quantos couberam antes de quebrar linha exigiria JS medindo o
    DOM real, risco aceito conscientemente — ver bullet do breakpoint acima): acima do teto de 6, trunca
    silenciosamente, mesmo padrão que gênero já usa. Mesma priorização de `_prioritize()` (todos os provedores
    que baterem, não só o primeiro) e mesmo destaque visual `.highlighted` de gênero garantem que um provedor
    mencionado explicitamente (ex: "animações da Crunchyroll") nunca fica de fora do corte nem passa despercebido
  - "Ficha Técnica" (ícone outline "users", grupo de pessoas — ver nota geral sobre ícones acima), logo
    **acima** da Sinopse: mesmo mecanismo de accordion (checkbox
    hack em CSS, sem JS) da Sinopse abaixo, em linha própria. Faz parte do meio solto do card (ver bullet do grid
    acima), como todo o resto abaixo do pôster. Traz **todos** os campos de elenco/equipe técnica já formatados em
    `formatting.py`: Diretor, Criador(es) (`creators`, só séries — aparece como bullet independente do Diretor,
    sem fallback entre os dois; um título pode mostrar os dois ao mesmo tempo), Elenco (`cast`, top 5 atores),
    Roteiro (`writers`), Trilha sonora (`composer`), Produção (`producer`), Fotografia (`cinematographer`) e
    Montagem (`editor`) — um `<li>` por papel presente, dentro de um `<ul class="people-list">` revelado ao
    expandir. O rótulo de cada papel vai em `<strong>` (branco, mesmo tom do valor — destaque só por peso de
    fonte, não por cor) para escanear rápido quais papéis o título tem. O rótulo da seção ("Ficha Técnica") é
    branco — o laranja fica reservado pra nota e "Insight do FilmBot"; aqui é conteúdo informativo neutro. Ícone
    + texto ficam à esquerda do label e o chevron ⌄ (fechado) / ⌃ (aberto) na ponta direita da linha
    (`justify-content:space-between` + `width:100%` no `<label>`, ver `cards.css`) — antes a seta ficava
    **antes** do texto; foi pro lado oposto pra bater com o mockup mais recente. Se nenhum papel estiver presente,
    a div nem é gerada (meio solto)
  - Sinopse, na última linha do card, também no meio solto (não ancorada em nenhuma borda fixa entre os 3 cards
    da fileira): accordion "Sinopse" (checkbox hack em CSS, já que a grid é renderizada via
    `st.markdown(unsafe_allow_html=True)`, que não executa `<script>` injetado no HTML) recolhido
    por padrão, com o ícone outline "file-text" antes do texto (ver nota geral sobre ícones acima) e o mesmo
    chevron ⌄/⌃ na ponta direita da linha que "Ficha
    Técnica" usa (mesmo motivo — bater com o mockup). O rótulo é **branco**, não mais laranja: o Trailer não
    divide mais essa linha (subiu pra linha de duração/meta-line — ver bullets acima), então não sobrava mais
    motivo pra "Sinopse" reter destaque de cor — o laranja ficou reservado só pra nota e "Insight do FilmBot".
    Clicar no label expande o texto completo da sinopse e troca o chevron pra "⌃", independente do tamanho do
    texto. Sem sinopse, a div nem é gerada nesse card (meio solto)

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
| `agent.py` | `search_titles_spec(where_clause, limit)` | Valida o WHERE gerado pelo LLM, busca um pool de candidatos maior que `limit` (ordenados por popularidade, até `_CANDIDATE_POOL_MAX`) e sorteia um subconjunto de `limit` títulos (máximo 15) preservando a ordem de popularidade entre os escolhidos |
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
| `formatting.py` | `format_record(record)` | Converte um registro bruto do Athena em dict formatado para o card (tipo, gêneros, duração, data, nota, etc.) |
| `formatting.py` | `_format_type()`, `_format_genres()`, `_format_title_duration()`, `_format_release_date()`, `_format_adaptive_date()`, `_is_upcoming()`, `_format_rating()` | Funções puras de formatação de campos individuais |
| `infrastructure.py` | `load_filmbot_password()` | Busca `filmbot_password` no Secrets Manager (via `FILMBOT_SECRET_ARN`) e grava `.streamlit/secrets.toml` (chmod 600) para a autenticação do Streamlit; não faz nada se o arquivo já existir |
| `infrastructure.py` | `setup_cloudwatch_logging()` | `@st.cache_resource` que registra o `CloudWatchLogHandler` no root logger uma única vez por processo — sem isso, cada rerun do Streamlit acumularia um handler novo (vazamento de memória + logs duplicados) |
| `infrastructure.py` | `get_client_ip()` | Obtém o IP do cliente via header `X-Forwarded-For`; confiar no primeiro valor só é seguro porque o Caddy sobrescreve o header (`header_up`) em vez de anexar — ver `deploy/Caddyfile` |
| `infrastructure.py` | `events_in_window(history, ip, window_seconds)` | Conta eventos dentro da janela de tempo informada (janela deslizante) para o IP no histórico informado e limpa registros expirados. Reusada por `login.py` (`_login_attempt_history`, janela de `_LOGIN_LOCKOUT_SECONDS`) e `recommendation.py` (`_ip_history`/`_audio_ip_history`, janela de 1h) |
| `infrastructure.py` | `seconds_until_available(history, ip, window_seconds)` | Calcula quantos segundos faltam até o evento mais antigo do IP expirar, na janela de tempo informada |
| `login.py` | `render_login(client_ip)` | Renderiza a tela de autenticação (CSS, form de senha, bloqueio por `_MAX_LOGIN_ATTEMPTS` tentativas via `_login_attempt_history`); interrompe a execução com `st.stop()` se não autenticado, ou retorna sem efeito se já autenticado |
| `recommendation.py` | `render_recommendation(client_ip)` | Renderiza o formulário de preferência (texto/áudio), transcrição assíncrona, rate limiting de consultas/transcrições (`_ip_history`/`_audio_ip_history`) e dispara/acompanha a busca assíncrona (`ThreadPoolExecutor` + `Future`), escrevendo `titles`/`search_error`/`search_completed` em `st.session_state` |
| `cards.py` | `render_cards()` | Lê `titles`/`search_error`/`search_completed` de `st.session_state` (escritos por `recommendation.py`) e exibe o feedback ou a grid de resultados correspondente |
| `app.py` | Orquestração | Bootstrap, chama `login.render_login()`, renderiza o cabeçalho e chama `recommendation.render_recommendation()` + `cards.render_cards()` em sequência |
| `components.py` | `load_base_css()`, `load_login_css()`, `load_app_css()`, `load_recommendation_css()`, `load_cards_css()`, `load_preference_counter_script()`, `load_audio_cancel_script()`, `load_audio_timer_script()`, `load_textarea_autogrow_script()`, `load_countdown_script()`, `load_login_button_toggle_script()`, `render_card()`, `render_grid()`, `render_feedback()`, `render_footer()`, `render_login_footer()`, `icon()` | Helpers de renderização HTML com escape contra XSS |
| `components.py` | `icon(name, size=16)` | Monta um ícone Lucide inline (`<svg>`, outline, `stroke="currentColor"`) a partir de `ICON_PATHS`. Pública (sem prefixo `_`) porque `app.py` também usa pra montar o badge do ícone do cabeçalho, não só `render_card()` |
| `components.py` | `_matches_highlighted(item, terms)` | Diz se `item` contém (case-insensitive) algum termo da lista `terms` (`highlighted_genres`/`highlighted_providers`). Compartilhada por `_prioritize()` (ordena) e pelo render de badges (decide a classe `.highlighted`), pra garantir que os dois concordem sobre o que é destaque |
| `components.py` | `_prioritize(items, terms)` | Reordena uma lista de badges de texto (gêneros ou nomes de provedores) colocando primeiro **todos** os que contêm algum termo destacado (case-insensitive, via `_matches_highlighted()`), preservando a ordem relativa dentro de cada grupo — não só o primeiro match, se o usuário pediu mais de um termo |
| `components.py` | `_parse_provider_names(names_raw)` | Faz o parsing de um grupo de provedores (streaming ou aluguel/compra) a partir da string comma-joined vinda de `glue_agg` |
| `components.py` | `_parse_provider_logos(logos_raw)` | Faz o parsing da string de logos comma-joined (`streaming_provider_logos`/`rent_buy_provider_logos`), posicionalmente alinhada aos nomes — ao contrário de `_parse_provider_names()`, não filtra entradas vazias, pra não deslocar a posição dos itens seguintes |
| `components.py` | `_render_provider_badges(providers, highlighted)` | Monta os badges de provedor (streaming e aluguel/compra já combinados, pareados nome+logo por `render_card()` e deduplicados por nome), prioriza via `_prioritize()` o(s) provedor(es) mencionado(s) pelo usuário e marca cada um com a classe `.highlighted` (borda + texto laranja). Renderiza a logo real do TMDB (`.provider-logo`) antes do nome quando disponível. Mostra até 6 badges direto, sem toggle — acima do teto trunca silenciosamente (ver seção "Interface") |
| `static/css/base.css` | CSS transversal | Fundo, reset de botão, largura de container (640px), `.icon` base, `.msg-error`/`.msg-warning`, `.time-countdown` — carregado tanto pela tela de login quanto pela página principal, sempre antes dos demais arquivos (ordem de injeção importa, ver `lightsail_ia.md`) |
| `static/css/login.css` | CSS da tela de login | Estilos específicos da tela de autenticação |
| `static/css/app.css` | CSS de cabeçalho/rodapé | Estilos de `.header-*`/`.st-key-btn_sair` e `.footer*` |
| `static/css/recommendation.css` | CSS do formulário de recomendação | Hero, gravador de áudio, botão "Recomendar", contador de consultas, spinner |
| `static/css/cards.css` | CSS do grid de resultados | Estilos do grid, cards e layout responsivo |
| `static/js/contador_caracteres.js` | Script do contador dinâmico do campo de preferência + habilitar/desabilitar "Recomendar" | Observa a textarea via `data-testid="stTextArea"` e atualiza o contador e o `disabled` do botão "Recomendar" a cada tecla digitada (exceto quando `rate_limited`) |
| `static/js/audio_cancel_recording.js` | Script do ícone de descarte da gravação de áudio | Observa `[aria-label="Stop recording"]`; ao clicar no ícone ✕ (vermelho), simula "parar" e auto-confirma o descarte via `localStorage` (ver seção "Entrada alternativa") |
| `static/js/audio_timer.js` | Script do timer decorrido/máximo do gravador de áudio | Atualiza `#audio-timer-badge` para `decorrido / máximo` enquanto `[aria-label="Stop recording"]` existir, lendo `data-testid="stAudioInputWaveformTimeCode"`; fora do estado `recording`, volta a `00:00 / máximo` |
| `static/js/auto_grow_textarea.js` | Script de auto-grow do campo de preferência | Observa a textarea via `data-testid="stTextArea"` e ajusta `style.height` ao `scrollHeight` a cada tecla digitada, com teto de 200px |
| `static/js/countdown.js` | Script de countdown MM:SS genérico (rate limit de busca, rate limit de transcrição e bloqueio temporário de login) | Atualiza o `<span>` de `id` configurável (`element_id`, padrão `"countdown"`, renderizado por `render_feedback()` na página real, via `window.parent.document`) a cada segundo; recarrega a página sozinho ao chegar a 00:00 |
| `static/js/login_button_toggle.js` | Script de habilitar/desabilitar "Entrar" do login | Observa o campo de senha via `data-testid="stTextInput"` e atualiza o `disabled` de `.st-key-btn_entrar button` a cada tecla digitada (exceto quando `lockedOut`) |

## Deploy

### Produção (Lightsail)

O app roda como serviço `systemd` (`filmbot.service`) na instância Lightsail, escutando apenas em `127.0.0.1:8501` (acesso local). O **Caddy** atua como proxy reverso na porta 80. O script `deploy/setup.sh` instala dependências, Caddy e configura ambos os serviços. O Terraform provisiona a instância (portas 22, 80 e 443) e o CI/CD faz o deploy via SSH ao fazer push na branch `main`.

Arquivos de deploy:
- `deploy/filmbot.service` — serviço Streamlit (bind em `127.0.0.1`)
- `deploy/caddy.service` — serviço Caddy (proxy reverso HTTPS)
- `deploy/Caddyfile` — configuração do Caddy (porta 80 → `localhost:8501`); sobrescreve `X-Forwarded-For` com `header_up` para o header sempre refletir o IP real do peer TCP, impedindo que um cliente forje esse valor e burle o rate limit por IP de `recommendation.py`/`login.py`
- `deploy/setup.sh` — bootstrap da instância (Python, Caddy, serviços)

### Desenvolvimento local

A instância Lightsail em si só existe em prod (ver `local.lightsail_prod_enabled` em `infra/locals.tf`), mas o IAM user do agente (`aws_iam_access_key.lightsail_agent`) existe em dev e prod (`local.lightsail_agent_enabled`), justamente para permitir rodar localmente contra dados reais de dev sem misturar credenciais com prod. Para rodar localmente:

```bash
# 1. Gerar o .env com as credenciais do workspace ativo (dev ou prod — requer
#    Terraform inicializado contra o state correspondente)
bash infra/config/export_env_local.sh

# 2. Rodar
cd app/lightsail_ia
pip install -r requirements.txt
streamlit run app.py   # http://localhost:8501
```

Em desenvolvimento local, use `LLM_API_KEY` diretamente no `.env` (fallback quando `FILMBOT_SECRET_ARN` não está definida). Use `.env.example` como referência.

> Rodando contra o state de **dev**: o secret unificado de dev (`AWS_FILMBOT_SECRET_ARN_DEV`) já existe para `tmdb_api_key`/`llm_api_key` (usado por Lambda/backfill), mas pode não ter o campo `filmbot_password` (nem `transcription_api_key`) — adicione manualmente via Secrets Manager antes do login funcionar localmente.

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

`infrastructure.py` eleva o root logger para `ERROR` quando o CloudWatch está configurado (`logging.root.setLevel(logging.ERROR)`), para silenciar bibliotecas ruidosas. Como isso suprimiria por herança os `logger.info(...)` de `_log_token_usage()`, `agent.py` define explicitamente `logger.setLevel(logging.INFO)` no seu próprio logger — garantindo que os logs de tokens continuem passando pelo handler do root independentemente do nível herdado.

**Setup do CloudWatch roda uma única vez por processo (`setup_cloudwatch_logging()`, `infrastructure.py`):** o Streamlit reexecuta o script inteiro a cada rerun (clique em botão, `st.rerun()`, etc.). Sem `@st.cache_resource`, o registro do `CloudWatchLogHandler` no root logger rodaria a cada rerun, acumulando um handler novo por vez (cada um com seu próprio cliente boto3, fila e thread de background do `watchtower`) sem nunca remover os anteriores — vazamento de memória progressivo e cada log duplicado uma vez por handler acumulado (bug real observado em produção: a mesma mensagem repetida dezenas/centenas de vezes no mesmo timestamp, crescendo ao longo da sessão). Mesmo padrão de "roda uma vez por processo" já usado nas factories `@st.cache_resource` de `_ip_history`/`_audio_ip_history` (`recommendation.py`) e `_login_attempt_history` (`login.py`).

## Configuração do Streamlit (`.streamlit/config.toml`)

`minCachedMessageSize = 1000000000` desabilita na prática o `ForwardMsgCache` do Streamlit (mensagens só entram nesse cache se o tamanho for maior que esse valor — nenhuma mensagem deste app chega perto disso). Existe pra evitar o erro "Connection error / Failed to process a Websocket message. Error: Cached ForwardMsg MISS", reproduzido em produção no fluxo entrar → buscar → sair → entrar de novo.

Causa raiz: o `ForwardMsgCache` do Streamlit cacheia mensagens grandes (`global.minCachedMessageSize`, padrão 10 KB) e referencia por hash em vez de reenviar o conteúdo pro cliente — mas a entrada expira no servidor depois de `global.maxCachedMessageAge` (padrão 2) reruns do script sem uso. Telas com trocas drásticas de conteúdo (login ↔ página principal, cada uma com blocos grandes de CSS/HTML via `unsafe_allow_html`) acumulam reruns suficientes entre uma visita e outra pra cair nessa janela, dessincronizando cliente e servidor sobre o que ainda está cacheado. É um bug conhecido do próprio Streamlit (`streamlit/streamlit#11357`, `#11847`), sem correção definitiva do lado deles até a versão fixada aqui (`==1.59.2`) — `minCachedMessageSize = inf` desabilitaria o cache por completo (confirmado em `streamlit/streamlit#1028`), mas um valor finito bem acima de qualquer mensagem real evita depender do parser de TOML aceitar `inf` nesta versão. Não é secreto — `.streamlit/config.toml` vai pro repositório normalmente (só `secrets.toml` é ignorado, ver `.gitignore`).
