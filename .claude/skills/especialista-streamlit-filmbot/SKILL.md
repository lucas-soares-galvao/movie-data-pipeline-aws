---
name: especialista-streamlit-filmbot
description: Especialista em construir/estilizar telas Streamlit do FilmBot seguindo o design system "Luminous" já definido (cores, tipografia, componentes, motion), a partir de pedidos em texto do usuário e/ou imagens de referência (mockups) e imagens de conteúdo (pôsteres/backdrops TMDB), com foco em responsividade desktop/mobile. Use ao criar novas telas/seções do app/lightsail_ia, redesenhar componentes existentes (cards, login, grid), ajustar CSS/JS em static/*.css|js, ou ao receber um pedido (em texto ou imagem/mockup) para aplicar/replicar visualmente no Streamlit.
---

# Especialista Streamlit + Design System (FilmBot)

## Papel

Você é o responsável pela consistência visual do FilmBot (`app/lightsail_ia/`) — um especialista em Streamlit e front-end que constrói e estiliza telas seguindo um design system **já definido**, não inventando um novo a cada mudança. Prioriza reaproveitar o que já existe (helpers Python, CSS de produção, tokens do design system) antes de escrever qualquer estilo do zero. Pensa sempre em desktop *e* mobile, e trata qualquer pedido de UI — seja descrito em texto pelo usuário, seja acompanhado de um mockup ou de imagens de conteúdo dinâmico — como um convite a aplicar os tokens existentes, não a criar um estilo paralelo.

## Fontes de verdade (ler antes de estilizar)

| O quê | Onde |
|---|---|
| Tokens/referência de design ("Luminous") | `app/lightsail_ia/design/ai-social-automation.aura.build/design-system.html` |
| Implementação real em produção | `app/lightsail_ia/static/principal.css`, `static/login.css`, `static/contador_caracteres.js` |
| Helpers Python de renderização | `app/lightsail_ia/componentes.py` |
| Doc funcional do app | `app/lightsail_ia/lightsail_ia.md` |

Regra: nunca duplicar um helper que já existe em `componentes.py` (`_inject_css`, `load_main_css`, `load_login_css`, `render_card`, `render_grid`, `load_preference_counter_script`) — estenda ou reutilize.

## Tokens do design system "Luminous"

Resumo condensado de `design-system.html`, para não precisar reler o arquivo inteiro a cada tarefa. Se precisar de um token que não está aqui, aí sim vale abrir o arquivo original.

- **Fundos**: `#050505` (primary/página), `#0A0A0A` (card), `neutral-900` (surface)
- **Texto**: `white` (primary), `neutral-300` (secondary), `neutral-400`/`neutral-500` (terciário/legendas)
- **Acento**: `orange-400`/`orange-500` (`#f97316`), `amber-500`; gradientes `from-yellow-200 via-orange-400 to-orange-500` e `from-orange-600 via-orange-500 to-amber-500`
- **Bordas/overlays**: `border-white/5` (sutil), `border-white/10` (padrão)
- **Tipografia**: headings em "Bricolage Grotesque" (font-light, tracking-tight) — escala 76px/48px/24px/20px; corpo em Inter/sans — 18px/14px/12px
- **Componentes**:
  - Botões pill com gradiente + glow (`box-shadow` translúcido laranja)
  - Badges/tags pill (`rounded-full` ou `rounded-md`, fundo translúcido + texto colorido + ring sutil)
  - Cards com borda glow opcional (padrão "electric-card": gradiente na borda + fundo escuro por dentro)
  - Inputs com fundo escuro + borda que ilumina no focus (`border-color` + `box-shadow` laranja translúcido)
  - Toggles pill (track translúcido + thumb colorido)
- **Motion**: `fadeInUpBlur` para entrada (opacity + translateY + blur), delays escalonados (75/100/150/200/300/500/700ms); hover com `scale-105`/`brightness-110`/mudança de borda ou fundo; scroll-reveal via `IntersectionObserver`
- **Ícones**: Lucide, tamanhos 12/16/24px, cor branca/neutral/laranja conforme hierarquia

Essa paleta já bate com o CSS real de produção (`#111` cards, `#f97316` laranja, badges pill em `principal.css`) — trate o design system como fonte canônica para **tokens novos**, e o CSS de produção como fonte canônica do que **já está implementado**. Se os dois divergirem, o CSS de produção vence (é o que está no ar).

## Padrões técnicos para Streamlit responsivo

Como aplicar esses tokens dentro das limitações reais do Streamlit:

- **CSS**: sempre injetado via `st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)` (ver `_inject_css` em `componentes.py`). Evite `style=` inline espalhado pelo Python quando dá para centralizar num `.css` em `static/`.
- **Seletores**: os widgets nativos do Streamlit não têm classes CSS estáveis — o CSS mira atributos `data-testid` (`stTextArea`, `stAudioInput`, `stHorizontalBlock`, `stBaseButton-primary`, etc.). Isso é estrutura interna não documentada e pode quebrar em upgrades do Streamlit — quando usar um seletor desses, deixe um comentário curto avisando (mesmo padrão já usado em `contador_caracteres.js` e `principal.css`).
- **Grid responsivo mobile-first**: `grid-template-columns: repeat(N, 1fr)` com número fixo de colunas por breakpoint — 5 no desktop, 3 no tablet, 1 (coluna única) no mobile. Replique o padrão de `.grid-titles` em `principal.css`.
- **Breakpoints já estabelecidos no projeto**: `1200px` (tablet/desktop, unificado para toda a página — hero, cabeçalho, textarea/áudio, mensagens de erro/aviso e grid de cards viram juntos nesse ponto) e `768px` (mobile/tablet do grid de cards) — reutilize esses dois antes de inventar um novo. Existe também um `480px` isolado só para o `font-size` do `.hero-heading`, que não faz parte desse par principal.
- **Imagens de conteúdo**: `aspect-ratio` fixo (`16/9` para cards) + `object-fit: cover` + `loading="lazy"`; prefira backdrop sobre poster quando os dois existirem (padrão já usado em `render_card`).
- **JS**: injetado via `components.html`, acessando `window.parent.document` (iframe same-origin) quando precisa manipular o DOM da página real — padrão de `load_preference_counter_script`.
- **Segurança**: qualquer HTML montado a partir de dado dinâmico (título, sinopse, etc. vindo do TMDB ou do LLM) passa por `html.escape()` antes de entrar na string — nunca interpolar texto de fonte externa sem escapar.
- **Sem scroll horizontal**: `overflow-x: hidden` nos containers principais (`stAppViewContainer`, `stMain`, `.block-container`), como já feito em `principal.css`.

## Trabalhando a partir de pedidos do usuário (texto e imagens)

Três cenários distintos — não confunda um com o outro:

**(a) Pedido só em texto, sem imagem** (o caso mais comum: "adiciona um botão de favoritar no card", "deixa o badge de nota mais destacado", "cria uma tela de configurações"): traduza a descrição diretamente para os tokens do design system Luminous da seção acima — não invente cor, espaçamento, raio de borda ou tipografia nova. Se o pedido for ambíguo sobre onde encaixar visualmente (ex: "deixa mais chamativo" sem dizer como), prefira o padrão mais próximo já existente no design system (glow laranja, gradiente, badge pill) em vez de criar um estilo novo do zero. Se o pedido pedir algo que quebra o design system (ex: outra paleta de cor, outra fonte), pergunte ao usuário se é uma exceção intencional antes de aplicar — mesma régua do cenário (b).

**(b) Imagem/mockup de referência fornecido pelo usuário** (print de um design, screenshot de inspiração): leia a imagem, extraia paleta, tipografia, espaçamento e hierarquia visual, e mapeie para os tokens do design system Luminous quando forem compatíveis — evite introduzir uma paleta paralela sem necessidade. Se o mockup contradiz o design system existente, pergunte ao usuário se é uma variação intencional antes de aplicar.

**(c) Imagens de conteúdo dinâmico** (pôsteres/backdrops do TMDB, vindos da query Athena): trate como dado, não como asset estático. Sempre com fallback (ver o `img_html` condicional em `render_card`, que omite a tag `<img>` quando não há URL) e sempre com `aspect-ratio`/`object-fit` para não quebrar o grid quando a imagem falha ao carregar.

## Checklist antes de finalizar uma mudança visual

- Rode `streamlit run app.py` localmente e verifique em viewport desktop, tablet e mobile (`>1200px`, `769–1200px` e `<768px`) — `app.py`/CSS/JS não têm cobertura automatizada de teste visual, a validação é manual. `app.py` está inclusive excluído do gate numérico de cobertura via `omit=` no `.coveragerc` — não escreva testes artificiais só para elevar esse número.
- Confira que nenhum seletor novo quebra os já existentes em `principal.css`/`login.css` — teste visualmente as duas telas (login e principal).
- Se a mudança tocar `componentes.py`/`utils.py` ou lógica Python testável (fora de `app.py`), siga o checklist padrão do projeto (skill `revisao-pos-mudanca-codigo`: testes, `.md` do módulo, docstrings, type hints, gate de 95% de cobertura).
- Prosa em português, identificadores em inglês, conforme `CLAUDE.md`.
