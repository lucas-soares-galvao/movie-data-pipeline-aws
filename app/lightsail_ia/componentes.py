"""componentes.py — Funções auxiliares de renderização para o FilmBot."""

import html
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_CERTIFICATION_DESCRIPTIONS = {
    "L": "Livre para todas as idades",
    "10": "Não recomendado para menores de 10 anos",
    "12": "Não recomendado para menores de 12 anos",
    "14": "Não recomendado para menores de 14 anos",
    "16": "Não recomendado para menores de 16 anos",
    "18": "Não recomendado para menores de 18 anos",
}

_MAX_VISIBLE_GENRES = 6
_MAX_VISIBLE_PROVIDER_BADGES = 6

_YT_IMG = (
    '<img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJyZWQiPjxwYXRoIGQ9Ik0yMy40OTggNi4xODZhMy4wMTYgMy4wMTYgMCAwIDAtMi4xMjItMi4xMzZDMTkuNTA1IDMuNTQ2IDEyIDMuNTQ2IDEyIDMuNTQ2cy03LjUwNSAwLTkuMzc3LjUwNEEzLjAxNyAzLjAxNyAwIDAgMCAuNTAyIDYuMTg2QzAgOC4wNyAwIDEyIDAgMTJzMCAzLjkzLjUwMiA1LjgxNGEzLjAxNiAzLjAxNiAwIDAgMCAyLjEyMiAyLjEzNmMxLjg3MS41MDQgOS4zNzYuNTA0IDkuMzc2LjUwNHM3LjUwNSAwIDkuMzc3LS41MDRhMy4wMTUgMy4wMTUgMCAwIDAgMi4xMjItMi4xMzZDMjQgMTUuOTMgMjQgMTIgMjQgMTJzMC0zLjkzLS41MDItNS44MTR6TTkuNTQ1IDE1LjU2OFY4LjQzMkwxNS44MTggMTJsLTYuMjczIDMuNTY4eiIvPjwvc3ZnPg=="'
    ' width="20" height="20" alt="YouTube" style="display:inline-block;vertical-align:middle;" />'
)


def _inject_css(file_name: str) -> None:
    """Lê um arquivo CSS e injeta na página via st.markdown."""
    path = Path(__file__).parent / "static" / file_name
    css = path.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def load_login_css() -> None:
    """Injeta os estilos da tela de login."""
    _inject_css("login.css")


def load_main_css() -> None:
    """Injeta os estilos da página principal."""
    _inject_css("principal.css")


def load_preference_counter_script(max_chars: int, rate_limited: bool = False) -> None:
    """Injeta o script do contador dinâmico de caracteres e do habilitar/desabilitar do botão "Recomendar"."""
    path = Path(__file__).parent / "static" / "contador_caracteres.js"
    script = (
        path.read_text(encoding="utf-8")
        .replace("__MAX_CHARS__", str(max_chars))
        .replace("__RATE_LIMITED__", "true" if rate_limited else "false")
    )
    components.html(f"<script>{script}</script>", height=0)


def load_audio_cancel_script() -> None:
    """Injeta o script do ícone de descarte durante a gravação de áudio."""
    path = Path(__file__).parent / "static" / "audio_cancel_recording.js"
    script = path.read_text(encoding="utf-8")
    components.html(f"<script>{script}</script>", height=0)


def load_audio_timer_script(max_seconds: int) -> None:
    """Injeta o script do timer decorrido/máximo do gravador, que também para a gravação sozinha ao atingir max_seconds."""
    path = Path(__file__).parent / "static" / "audio_timer.js"
    script = path.read_text(encoding="utf-8").replace("__MAX_SECONDS__", str(max_seconds))
    components.html(f"<script>{script}</script>", height=0)


def load_textarea_autogrow_script() -> None:
    """Injeta o script que ajusta a altura do campo de preferência ao conteúdo digitado."""
    path = Path(__file__).parent / "static" / "auto_grow_textarea.js"
    script = path.read_text(encoding="utf-8")
    components.html(f"<script>{script}</script>", height=0)


def load_countdown_script(seconds: int, element_id: str = "countdown") -> None:
    """Injeta o script de countdown MM:SS genérico (rate limit de busca, rate limit de
    transcrição e bloqueio temporário de login), que recarrega a página sozinho ao chegar
    a 00:00. `element_id` mira o `<span>` a atualizar — necessário quando mais de um
    countdown pode estar visível na mesma página ao mesmo tempo (busca e transcrição),
    para não colidir em `id="countdown"` duplicado no DOM."""
    path = Path(__file__).parent / "static" / "countdown.js"
    script = (
        path.read_text(encoding="utf-8")
        .replace("__SECONDS__", str(seconds))
        .replace("__ELEMENT_ID__", element_id)
    )
    components.html(f"<script>{script}</script>", height=0)


def load_login_button_toggle_script(locked_out: bool) -> None:
    """Injeta o script que habilita/desabilita o botão "Entrar" a cada tecla digitada
    no campo de senha, mesmo padrão de `load_preference_counter_script()` para o botão
    "Recomendar"."""
    path = Path(__file__).parent / "static" / "login_button_toggle.js"
    script = path.read_text(encoding="utf-8").replace(
        "__LOCKED_OUT__", "true" if locked_out else "false"
    )
    components.html(f"<script>{script}</script>", height=0)


def render_feedback(kind: str, message: str, *, extra_html: str = "") -> None:
    """Renderiza uma caixa de mensagem de feedback padronizada (.msg-error/.msg-warning).

    kind: "error" (ícone ❌) ou "warning" (ícone ⚠️).
    extra_html: HTML bruto adicional anexado ao final, não escapado — usado só pelo
    countdown de rate limit de busca, para injetar o <span id="countdown"> vazio.
    """
    icon = "❌" if kind == "error" else "⚠️"
    st.markdown(
        f'<div class="msg-{kind}">{icon} {html.escape(message)}{extra_html}</div>',
        unsafe_allow_html=True,
    )


def _matches_highlighted(item: str, terms: list[str]) -> bool:
    """True se item contém (case-insensitive) algum dos termos destacados pela busca do
    usuário. Compartilhada por `_prioritize` (ordena) e pelo render de badges (decide o
    estilo "highlighted") pra garantir que os dois concordem sobre o que é destaque —
    um item que vem primeiro na lista sempre tem o mesmo item que ganha a borda laranja."""
    if not terms:
        return False
    item_lower = item.lower()
    return any(t.lower() in item_lower for t in terms if t)


def _prioritize(items: list[str], terms: list[str]) -> list[str]:
    """Reordena items colocando primeiro os que contêm algum termo destacado (case-insensitive),
    preservando a ordem relativa dentro de cada grupo. Usado para que um gênero/provedor
    mencionado explicitamente pelo usuário nunca fique escondido no badge "+N". Se o usuário
    pediu mais de um termo (ex: "ação e comédia"), todos os itens que baterem com algum deles
    vêm primeiro, não só o primeiro match."""
    if not terms:
        return items
    matched = [i for i in items if _matches_highlighted(i, terms)]
    unmatched = [i for i in items if not _matches_highlighted(i, terms)]
    return matched + unmatched


def _parse_provider_names(names_raw: str) -> list[str]:
    """Faz o parsing de um grupo de provedores (streaming ou aluguel/compra) a partir da
    string comma-joined vinda de glue_agg."""
    return [p.strip() for p in (names_raw or "").split(",") if p.strip()]


def _parse_provider_logos(logos_raw: str) -> list[str]:
    """Faz o parsing da string de logos comma-joined vinda de glue_agg (`streaming_provider_
    logos`/`rent_buy_provider_logos`), posicionalmente alinhada aos nomes de
    `_parse_provider_names` — ao contrário dela, não filtra entradas vazias (provedor sem
    logo no TMDB vira string vazia na origem, ver `queries.py`), pra não deslocar a posição
    dos itens seguintes."""
    return [p.strip() for p in (logos_raw or "").split(",")]


def _render_provider_badges(providers: list[tuple[str, str]], highlighted: list[str]) -> str:
    """Monta os badges de provedor (streaming e aluguel/compra já combinados, pareados com
    logo via zip posicional, e deduplicados por nome por `render_card`), priorizando via
    `_prioritize` o(s) provedor(es) mencionado(s) pelo usuário e marcando cada um com a
    classe "highlighted" (borda laranja, ver principal.css) — não só o primeiro, todo
    provedor que bateu com a busca. Cada badge mostra a logo real do TMDB antes do nome
    quando disponível (`.provider-logo`); sem logo, cai de volta pro badge só-texto. Mostra
    até `_MAX_VISIBLE_PROVIDER_BADGES` badges direto — o restante trunca silenciosamente,
    mesmo padrão que gêneros já usam, já que a linha de provedores se ajusta automaticamente
    ao card com mais badges na mesma fileira (grid da .card-body)."""
    logo_by_name = dict(providers)
    names = [name for name, _ in providers]
    prioritized = _prioritize(names, highlighted)[:_MAX_VISIBLE_PROVIDER_BADGES]
    badges = []
    for name in prioritized:
        logo_url = logo_by_name.get(name, "")
        logo_html = (
            f'<img src="{html.escape(logo_url)}" class="provider-logo" alt="" />' if logo_url else ""
        )
        highlighted_class = " highlighted" if _matches_highlighted(name, highlighted) else ""
        badges.append(
            f'<span class="provider-badge{highlighted_class}">{logo_html}{html.escape(name)}</span>'
        )
    return "".join(badges)


def render_card(title: dict, idx: int = 0) -> str:
    """Monta o HTML de um card de título com escape contra XSS.

    Com pôster (`backdrop_url`/`poster_url`), nota e classificação etária ficam sobrepostas
    na imagem — layout "at a glance" estilo Netflix/JustWatch. Sem pôster não há onde
    sobrepor, então nota/classificação ficam na meta-row. Em ambos os casos, duração e
    Trailer sempre dividem uma linha própria (duration-row), separada da meta-line de
    data/tipo."""
    poster = title.get("backdrop_url") or title.get("poster_url") or ""
    has_poster = bool(poster)
    title_name = html.escape(title.get("title", ""))
    year = html.escape(str(title.get("year", "")))
    title_type = html.escape(title.get("type", ""))
    rating = title.get("rating")
    overview_raw = title.get("overview") or ""
    reason = html.escape(title.get("reason") or "")
    genres = title.get("genres") or []
    duration = title.get("duration") or ""
    release_date = html.escape(title.get("release_date") or "")
    streaming_providers = title.get("streaming_providers") or ""
    streaming_provider_logos = title.get("streaming_provider_logos") or ""
    rent_buy_providers = title.get("rent_buy_providers") or ""
    rent_buy_provider_logos = title.get("rent_buy_provider_logos") or ""
    in_theaters = title.get("in_theaters") or False
    theater_end_date = html.escape(title.get("theater_end_date") or "")
    next_episode_season_number = title.get("next_episode_season_number")
    next_episode_number = title.get("next_episode_number")
    next_episode_date = html.escape(title.get("next_episode_date") or "")
    upcoming_date = html.escape(title.get("upcoming_date") or "")
    certification = html.escape(title.get("certification") or "")
    trailer_url = title.get("trailer_url") or ""
    cast = title.get("cast") or ""
    director = title.get("director") or ""
    creators = title.get("creators") or ""
    writers = title.get("writers") or ""
    composer = title.get("composer") or ""
    producer = title.get("producer") or ""
    cinematographer = title.get("cinematographer") or ""
    editor = title.get("editor") or ""

    highlighted_genres = title.get("highlighted_genres") or []
    genres_raw = _prioritize([g.strip() for g in genres if g.strip()], highlighted_genres)
    visible_genres_raw = genres_raw[:_MAX_VISIBLE_GENRES]
    # Todo gênero que bateu com a busca do usuário ganha "highlighted" (borda laranja, ver
    # principal.css) — não só o primeiro, mesmo padrão de _render_provider_badges.
    genres_html = "".join(
        f'<span class="genre{" highlighted" if _matches_highlighted(g, highlighted_genres) else ""}">'
        f"{html.escape(g)}</span>"
        for g in visible_genres_raw
    )
    # Faz parte do meio solto do card (ver principal.css) — só emite a div quando há algum
    # gênero pra mostrar.
    genres_block_html = ""
    if genres_html:
        genres_block_html = (
            f'<div class="genres-container">'
            f'<span class="meta-icon">🎭</span>'
            f'<span class="genre-badges">{genres_html}</span></div>'
        )

    # Filme (in_theaters), série (next_episode_*) e título ainda não lançado (upcoming_date)
    # nunca preenchem mais de um ao mesmo tempo (upcoming_date só existe pra air_date futuro —
    # incompatível com estar em cartaz ou ter próximo episódio de uma série já no ar) — por
    # isso a mesma linha/classe serve pros três badges, sem checar media_type explicitamente.
    # Sem nenhum dos três, não emite a div — o card fica com essa linha a menos (meio solto,
    # ver principal.css).
    cinema_content = ""
    if in_theaters:
        label = f"Em cartaz até {theater_end_date}" if theater_end_date else "Em cartaz"
        cinema_content = (
            f'<span class="meta-icon">🎬</span>'
            f'<span class="cinema-badge">{html.escape(label)}</span>'
        )
    elif next_episode_season_number is not None and next_episode_number is not None and next_episode_date:
        label = f"T{next_episode_season_number} E{next_episode_number} estreia em {next_episode_date}"
        cinema_content = (
            f'<span class="meta-icon">📅</span>'
            f'<span class="cinema-badge">{html.escape(label)}</span>'
        )
    elif upcoming_date:
        label = f"Em breve · {upcoming_date}"
        cinema_content = (
            f'<span class="meta-icon">🔜</span>'
            f'<span class="cinema-badge">{html.escape(label)}</span>'
        )
    cinema_html = f'<div class="meta-row cinema-row">{cinema_content}</div>' if cinema_content else ""

    certification_title = html.escape(_CERTIFICATION_DESCRIPTIONS.get(certification, certification))
    certification_html = (
        f'<span class="certification-badge" data-rating="{certification}"'
        f' title="{certification_title}">'
        f'{certification}</span>'
        if certification else ""
    )

    rating_str = html.escape(str(rating)) if rating is not None else ""
    rating_html = f'<span class="vital vital-rating">★ {rating_str}</span>' if rating_str else ""
    rating_chip_html = f'<span class="rating-chip">★ {rating_str}</span>' if rating_str else ""

    img_html = ""
    if poster:
        media_badges = f"{rating_chip_html}{certification_html}"
        media_badges_html = f'<div class="media-badges-top">{media_badges}</div>' if media_badges else ""
        img_html = (
            f'<div class="card-media">'
            f'<img src="{poster}" alt="{title_name}" class="card-img" loading="lazy" />'
            f'<div class="media-scrim"></div>'
            f'{media_badges_html}'
            f'</div>'
        )

    # Motivo é limitado a 90 caracteres na origem (prompt do agente) — cabe sem clamp nem
    # toggle na altura que o próprio card pede (faz parte do "meio solto" do card, sem
    # sincronia de altura com os vizinhos da fileira, ver principal.css). Sem motivo, a div
    # nem é gerada (meio solto) — caso comum, não só borda: `reason` costuma vir vazio fora
    # do fluxo de recomendação da IA. Rótulo "✨ Insight do FilmBot" acima do texto, mesmo
    # princípio do rótulo "Onde assistir" acima dos badges de provedor — a seção agora vem
    # depois dos gêneros (ver return, mais abaixo), não mais logo após o título.
    reason_block_html = (
        f'<div class="row-reason"><span class="reason-label">✨ Insight do FilmBot</span>'
        f'<p class="reason">{reason}</p></div>'
        if reason
        else ""
    )

    date_type_parts = []
    if release_date:
        date_type_parts.append(release_date)
    elif year:
        date_type_parts.append(f"({year})")
    if title_type:
        date_type_parts.append(title_type)
    meta_left = " · ".join(date_type_parts)
    if not has_poster and certification_html:
        meta_left = f"{meta_left} {certification_html}" if meta_left else certification_html

    trailer_html = ""
    if trailer_url:
        safe_url = html.escape(trailer_url)
        trailer_html = (
            f'<span class="vital vital-trailer">{_YT_IMG}'
            f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" class="trailer-link">'
            f'Trailer</a></span>'
        )

    # Com pôster a nota já saiu pra imagem, então a meta-line fica só com data/tipo; sem
    # pôster a nota continua no slot direito, como sempre foi. Faz parte do meio solto do
    # card (ver principal.css) — só emite a div quando há data/tipo ou nota (sem pôster) pra
    # mostrar. O ícone fica dentro de .meta-info (não como irmão solto de .meta-row) porque
    # .meta-line usa justify-content:space-between pra separar meta-info/nota — um 3º filho
    # direto do .meta-row empurraria o ícone pra ponta esquerda e o texto pra ponta direita,
    # longe um do outro, em vez de ficarem juntos como "ícone + texto".
    meta_icon_html = '<span class="meta-icon">ℹ</span>' if meta_left else ""
    duration_escaped = html.escape(duration) if duration else ""

    meta_right = "" if has_poster else rating_html
    meta_html = ""
    if meta_left or meta_right:
        meta_html = (
            f'<div class="meta-row meta-line">'
            f'<span class="meta-info">{meta_icon_html}{meta_left}</span>'
            f'{meta_right}</div>'
        )

    # Duração e Trailer sempre dividem uma linha própria, com ou sem pôster — medido via
    # Playwright que juntar os dois na mesma linha de data/tipo (pra "economizar" uma linha)
    # transborda e quebra em 3 linhas feias na largura mínima do card (~355-373px) com o
    # pior caso plausível (série com "3 temporadas · 61 episódios · ~24 min/ep" + Trailer) —
    # abrir mão dessa otimização de espaço bate com o próprio mockup, que já mostra duração e
    # data/tipo em linhas separadas mesmo com pôster. Emite quando há duração OU trailer pra
    # mostrar (não só duração) — sem isso, um título sem duração mas com trailer (ex.:
    # runtime ainda não confirmado no TMDB) perderia o link. Sem nenhum dos dois, a div nem é
    # gerada (meio solto, ver principal.css).
    duration_html = ""
    if duration or trailer_html:
        duration_info_html = (
            f'<span class="meta-info"><span class="meta-icon">⏱</span>{duration_escaped}</span>'
            if duration
            else ""
        )
        duration_html = f'<div class="meta-row duration-row">{duration_info_html}{trailer_html}</div>'

    # Nome e logo são pareados posicionalmente (zip_longest com fillvalue vazio — a logo
    # pode faltar/estar desalinhada em dados legados sem quebrar o pareamento) antes da
    # deduplicação por nome, que já existia — assim uma logo nunca duplica quando o mesmo
    # provedor aparece em streaming e aluguel/compra ao mesmo tempo, mesmo esquema que já
    # deduplicava os nomes.
    provider_pairs = list(
        zip_longest(_parse_provider_names(streaming_providers), _parse_provider_logos(streaming_provider_logos), fillvalue="")
    )
    provider_pairs += list(
        zip_longest(_parse_provider_names(rent_buy_providers), _parse_provider_logos(rent_buy_provider_logos), fillvalue="")
    )
    seen_providers: set[str] = set()
    deduped_providers: list[tuple[str, str]] = []
    for name, logo_url in provider_pairs:
        if not name:
            continue
        key = name.lower()
        if key in seen_providers:
            continue
        seen_providers.add(key)
        deduped_providers.append((name, logo_url))
    provider_badges_html = _render_provider_badges(
        deduped_providers, title.get("highlighted_providers") or []
    )

    # Trailer não entra mais aqui (ver comentário acima de meta_right) — esta linha é só
    # provedores agora, com ou sem pôster. Rótulo "Onde assistir" fica em linha própria,
    # acima dos badges (não espremido ao lado deles) — mesmo princípio do rótulo "✨
    # Insight do FilmBot" acima de `.reason`. Faz parte do meio solto do card (ver
    # principal.css) — só emite a div quando há algum provedor pra mostrar.
    providers_block_html = ""
    if provider_badges_html:
        providers_block_html = (
            f'<div class="providers-row">'
            f'<div class="providers-label-row">'
            f'<span class="meta-icon">📺</span>'
            f'<span class="providers-label">Onde assistir</span></div>'
            f'<div class="provider-badges">{provider_badges_html}</div>'
            f'</div>'
        )

    # Sinopse não divide mais linha com o Trailer (que subiu pra linha de duração — ver
    # meta_right/duration_html acima) — vira uma linha só com o label do accordion.
    # Checkbox fica fora da .synopsis-row, como sibling direto de .synopsis-text, pra o
    # seletor CSS ~ continuar funcionando. Ícone+texto ficam à esquerda e o chevron ⌄/⌃ na
    # ponta direita do label (`justify-content:space-between` em `.synopsis-label`, ver
    # principal.css) — mesmo padrão visual de `.people-label` (Ficha Técnica) abaixo.
    toggle_id = f"synopsis-toggle-{idx}"
    synopsis_toggle_html = ""
    synopsis_label_html = ""
    synopsis_text_html = ""
    if overview_raw:
        overview_escaped = html.escape(overview_raw)
        synopsis_toggle_html = f'<input type="checkbox" id="{toggle_id}" class="synopsis-toggle" hidden>'
        synopsis_label_html = (
            f'<label for="{toggle_id}" class="synopsis-label">'
            f'<span class="synopsis-icon-text"><span class="synopsis-icon">📄</span> Sinopse</span>'
            f'<span class="synopsis-arrow-closed">⌄</span>'
            f'<span class="synopsis-arrow-open">⌃</span></label>'
        )
        synopsis_text_html = f'<p class="synopsis-text">{overview_escaped}</p>'

    synopsis_row_html = (
        f'<div class="meta-row synopsis-row">{synopsis_label_html}</div>' if synopsis_label_html else ""
    )
    # Sinopse faz parte do meio solto do card (ver principal.css), sem sincronia de altura
    # com os vizinhos da fileira — só emite a div quando há de fato sinopse pra mostrar.
    synopsis_html = ""
    if synopsis_toggle_html or synopsis_row_html:
        synopsis_html = (
            f'<div class="row-synopsis">'
            f'{synopsis_toggle_html}{synopsis_row_html}{synopsis_text_html}</div>'
        )

    # Mesmo mecanismo de accordion da sinopse (checkbox hack, sem JS), posicionada ANTES da
    # sinopse — todo o elenco/equipe técnica já formatado em `title` aparece aqui, um bullet
    # por papel, com o rótulo em negrito pra escanear rápido. Faz parte do "meio solto" do
    # card (ver principal.css) — só emite a div quando há algum campo preenchido. Ícone+texto
    # à esquerda, chevron ⌄/⌃ na ponta direita, mesmo padrão de `.synopsis-label` acima.
    people_toggle_id = f"people-toggle-{idx}"
    people_html = ""
    people_fields = [
        ("Diretor", director),
        ("Criador(es)", creators),
        ("Elenco", cast),
        ("Roteiro", writers),
        ("Trilha sonora", composer),
        ("Produção", producer),
        ("Fotografia", cinematographer),
        ("Montagem", editor),
    ]
    if any(value for _, value in people_fields):
        people_toggle_html = (
            f'<input type="checkbox" id="{people_toggle_id}" class="people-toggle" hidden>'
        )
        people_row_html = (
            f'<div class="meta-row people-row">'
            f'<label for="{people_toggle_id}" class="people-label">'
            f'<span class="people-icon-text"><span class="people-icon">👥</span> Ficha Técnica</span>'
            f'<span class="people-arrow-closed">⌄</span>'
            f'<span class="people-arrow-open">⌃</span>'
            f'</label>'
            f'</div>'
        )
        people_items = "".join(
            f"<li><strong>{label}:</strong> {html.escape(value)}</li>"
            for label, value in people_fields
            if value
        )
        people_text_html = f'<ul class="people-list">{people_items}</ul>'
        people_html = f'<div class="row-people">{people_toggle_html}{people_row_html}{people_text_html}</div>'

    return f"""
    <article class="card">
      {img_html}
      <div class="card-body">
        <strong class="card-title">{title_name}</strong>
        {meta_html}
        {duration_html}
        {cinema_html}
        {genres_block_html}
        {reason_block_html}
        {providers_block_html}
        {people_html}
        {synopsis_html}
      </div>
    </article>
    """


def render_grid(titles: list[dict]) -> str:
    """Monta o HTML completo do grid de cards.

    Cada card estica pra altura do maior vizinho da fileira (`.grid-titles` com
    `align-items: stretch`, ver principal.css) — não precisa de nenhum posicionamento
    explícito de linha/coluna, o grid de 3 colunas com `repeat(3, 1fr)` já forma fileiras
    implícitas de 3 cards sozinho.
    """
    cards = [render_card(t, idx) for idx, t in enumerate(titles)]
    return '<div class="grid-titles">' + "".join(cards) + "</div>"


def render_footer() -> None:
    """Renderiza o rodapé da página principal com crédito TMDB."""
    year = datetime.now(tz=timezone.utc).year
    st.markdown(
        f'<div class="footer">'
        f"© {year} FilmBot · Dados fornecidos por "
        f'<a href="https://www.themoviedb.org/?language=pt-BR"'
        f' target="_blank" rel="noopener noreferrer">TMDB</a>'
        f" · Todos os direitos reservados"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_login_footer() -> None:
    """Renderiza o rodapé simplificado da tela de login."""
    year = datetime.now(tz=timezone.utc).year
    st.markdown(
        f'<div class="footer-login">'
        f"© {year} FilmBot · Todos os direitos reservados"
        f"</div>",
        unsafe_allow_html=True,
    )
