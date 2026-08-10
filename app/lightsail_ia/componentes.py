"""componentes.py — Funções auxiliares de renderização para o FilmBot."""

import html
import math
from datetime import datetime, timezone
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

# Linhas locais do subgrid de cada card (pôster, título, motivo, data/tipo/nota, gêneros,
# duração, provedores, "em cartaz", sinopse/trailer, pessoas) — ver render_grid()/render_card()
# e a regra .grid-titles em principal.css, que precisam concordar com esse número pro
# alinhamento entre os 3 cards de uma fileira funcionar.
_CARD_GRID_ROWS = 10

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


def _render_provider_badges(names: list[str], highlighted: list[str]) -> str:
    """Monta os badges de texto de provedor (streaming e aluguel/compra já combinados e
    deduplicados por `render_card`), priorizando via `_prioritize` o(s) provedor(es)
    mencionado(s) pelo usuário e marcando cada um com a classe "highlighted" (borda laranja,
    ver principal.css) — não só o primeiro, todo provedor que bateu com a busca. Mostra até
    `_MAX_VISIBLE_PROVIDER_BADGES` badges direto — o restante trunca silenciosamente, mesmo
    padrão que gêneros já usam, já que a linha de provedores se ajusta automaticamente ao
    card com mais badges na mesma fileira (grid da .card-body)."""
    prioritized = _prioritize(names, highlighted)[:_MAX_VISIBLE_PROVIDER_BADGES]
    return "".join(
        f'<span class="provider-badge{" highlighted" if _matches_highlighted(name, highlighted) else ""}">'
        f"{html.escape(name)}</span>"
        for name in prioritized
    )


def render_card(title: dict, idx: int = 0) -> str:
    """Monta o HTML de um card de título com escape contra XSS.

    Com pôster (`backdrop_url`/`poster_url`), nota e classificação etária ficam sobrepostas
    na imagem e o trailer sobe para a meta-line — layout "at a glance" estilo
    Netflix/JustWatch. Sem pôster não há onde sobrepor, então o card cai no layout anterior:
    nota/classificação na meta-row, trailer e provedores na mesma linha."""
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
    rent_buy_providers = title.get("rent_buy_providers") or ""
    in_theaters = title.get("in_theaters") or False
    theater_end_date = html.escape(title.get("theater_end_date") or "")
    next_episode_season_number = title.get("next_episode_season_number")
    next_episode_number = title.get("next_episode_number")
    next_episode_date = html.escape(title.get("next_episode_date") or "")
    certification = html.escape(title.get("certification") or "")
    trailer_url = title.get("trailer_url") or ""
    cast = title.get("cast") or ""
    # Série sem diretor de episódio agregado no crew: cai pro(s) criador(es) da série.
    director = title.get("director") or title.get("creators") or ""

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
    genres_icon_html = '<span class="meta-icon">🎭</span>' if genres_html else ""

    # Sempre gera a div, vazia quando não aplicável — reserva a linha própria do
    # subgrid (ver principal.css) pra não deslocar o que vem depois só nesse card.
    # Filme (in_theaters) e série (next_episode_*) nunca preenchem os dois ao mesmo
    # tempo — por isso a mesma linha/classe serve pros dois badges, sem checar
    # media_type explicitamente.
    cinema_content = ""
    if in_theaters:
        label = f"Em cartaz até {theater_end_date}" if theater_end_date else "Em cartaz"
        cinema_content = (
            f'<span class="meta-icon">🎬</span>'
            f'<span class="cinema-badge">{html.escape(label)}</span>'
        )
    elif next_episode_season_number is not None and next_episode_number is not None and next_episode_date:
        label = f"T{next_episode_season_number}E{next_episode_number} estreia em {next_episode_date}"
        cinema_content = (
            f'<span class="meta-icon">📅</span>'
            f'<span class="cinema-badge">{html.escape(label)}</span>'
        )
    cinema_html = f'<div class="meta-row cinema-row">{cinema_content}</div>'

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

    # Motivo é limitado a 90 caracteres na origem (prompt do agente), então a variação de
    # altura entre os 3 cards da mesma fileira é pequena — sem clamp nem toggle, o subgrid
    # de .card-body (ver principal.css) já alinha a linha do motivo sozinho, ajustando a
    # altura ao maior motivo entre os cards da fileira.
    reason_html = f'<p class="reason">{reason}</p>' if reason else ""

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
    # pôster a nota continua no slot direito, como sempre foi. O trailer não entra mais
    # aqui — fica na linha da sinopse (ver synopsis_row_html), junto da outra ação de
    # "quero saber mais" do card, em vez de disputar espaço com um fato objetivo.
    # meta-line e duration-row sempre geram a div (mesmo vazia) — reservam a própria linha
    # do subgrid, senão a ausência do campo desloca as linhas seguintes só nesse card.
    # O ícone fica dentro de .meta-info (não como irmão solto de .meta-row) porque
    # .meta-line usa justify-content:space-between pra separar meta-info/nota — um 3º
    # filho direto do .meta-row empurraria o ícone pra ponta esquerda e o texto pra ponta
    # direita, longe um do outro, em vez de ficarem juntos como "ícone + texto". Só aparece
    # quando há data/tipo pra rotular — sem isso, .meta-info fica vazio (linha ainda
    # reservada pelo subgrid, ver comentário abaixo) e um ícone sozinho, sem texto ao lado,
    # não faria sentido.
    meta_icon_html = '<span class="meta-icon">ℹ</span>' if meta_left else ""
    duration_escaped = html.escape(duration) if duration else ""

    # Com pôster, duração entra na mesma linha de data/tipo (medido via Playwright: mesmo
    # o pior caso plausível — série com "3 temps · 24 eps · ~45 min/ep" — cabe numa linha
    # só na largura mínima hoje garantida pro card, ~373px). Sem pôster essa linha já
    # carrega classificação (meta_left) e nota (meta_right) — testado e esse extra
    # transborda e quebra linha, então duração continua na própria linha só nesse caso.
    duration_in_meta_line = has_poster and duration
    meta_duration_html = (
        f'<span class="meta-icon">⏱</span>{duration_escaped}' if duration_in_meta_line else ""
    )
    meta_right = "" if has_poster else rating_html
    meta_html = (
        f'<div class="meta-row meta-line">'
        f'<span class="meta-info">{meta_icon_html}{meta_left}{meta_duration_html}</span>'
        f'{meta_right}</div>'
    )

    duration_icon_html = (
        '<span class="meta-icon">⏱</span>' if duration and not duration_in_meta_line else ""
    )
    duration_html = (
        f'<div class="meta-row duration-row">{duration_icon_html}'
        f'{duration_escaped if not duration_in_meta_line else ""}</div>'
    )

    provider_names = _parse_provider_names(streaming_providers)
    provider_names += _parse_provider_names(rent_buy_providers)
    seen_providers: set[str] = set()
    deduped_names = []
    for name in provider_names:
        key = name.lower()
        if key in seen_providers:
            continue
        seen_providers.add(key)
        deduped_names.append(name)
    provider_badges_html = _render_provider_badges(
        deduped_names, title.get("highlighted_providers") or []
    )

    # Trailer não entra mais aqui (ver comentário acima de meta_right) — esta linha é só
    # provedores agora, com ou sem pôster. Sempre gera a div (mesmo vazia), mesma razão de
    # meta-line/duration-row acima.
    providers_icon_html = '<span class="meta-icon">📺</span>' if provider_badges_html else ""
    providers_block_html = (
        f'<div class="meta-row providers-row">'
        f'{providers_icon_html}<span class="provider-badges">{provider_badges_html}</span></div>'
    )

    # Sinopse e trailer são as duas ações de "quero saber mais" do card, então dividem a
    # mesma linha (checkbox fica fora da .synopsis-row, como sibling direto de
    # .synopsis-text, pra o seletor CSS ~ continuar funcionando).
    toggle_id = f"synopsis-toggle-{idx}"
    synopsis_toggle_html = ""
    synopsis_label_html = ""
    synopsis_text_html = ""
    if overview_raw:
        overview_escaped = html.escape(overview_raw)
        synopsis_toggle_html = f'<input type="checkbox" id="{toggle_id}" class="synopsis-toggle" hidden>'
        synopsis_label_html = (
            f'<label for="{toggle_id}" class="synopsis-label">'
            f'<span class="synopsis-arrow-closed">▸</span>'
            f'<span class="synopsis-arrow-open">▾</span> Sinopse</label>'
        )
        synopsis_text_html = f'<p class="synopsis-text">{overview_escaped}</p>'

    synopsis_row_html = ""
    if synopsis_label_html or trailer_html:
        synopsis_row_html = (
            f'<div class="meta-row synopsis-row">{synopsis_label_html}{trailer_html}</div>'
        )

    # Mesmo mecanismo de accordion da sinopse (checkbox hack, sem JS), em linha própria do
    # subgrid — diretor/elenco são os dois papéis que o público reconhece e busca, os demais
    # campos de ficha técnica (roteiro, trilha sonora, produção, fotografia, montagem) já
    # chegam formatados em `title` mas ficam fora do card por ora.
    people_toggle_id = f"people-toggle-{idx}"
    people_toggle_html = ""
    people_row_html = ""
    people_text_html = ""
    if director or cast:
        people_toggle_html = (
            f'<input type="checkbox" id="{people_toggle_id}" class="people-toggle" hidden>'
        )
        people_row_html = (
            f'<div class="meta-row people-row">'
            f'<label for="{people_toggle_id}" class="people-label">'
            f'<span class="people-arrow-closed">▸</span>'
            f'<span class="people-arrow-open">▾</span> Pessoas</label>'
            f'</div>'
        )
        people_lines = []
        if director:
            people_lines.append(f"Diretor: {html.escape(director)}")
        if cast:
            people_lines.append(f"Elenco: {html.escape(cast)}")
        people_text_html = f'<p class="people-text">{"<br>".join(people_lines)}</p>'

    # Posição do card no subgrid compartilhado da fileira: cada card ocupa um bloco de
    # _CARD_GRID_ROWS linhas (mais 1 linha de respiro entre fileiras, ver render_grid) na
    # coluna correspondente ao seu índice dentro do grupo de 3. Ver principal.css pra como
    # cada campo (título, motivo, gêneros...) se posiciona dentro desse bloco.
    row_start = (idx // 3) * (_CARD_GRID_ROWS + 1) + 1
    column = (idx % 3) + 1
    card_style = f"grid-row:{row_start} / span {_CARD_GRID_ROWS};grid-column:{column}"

    return f"""
    <article class="card" style="{card_style}">
      {img_html}
      <div class="card-body">
        <strong class="card-title">{title_name}</strong>
        <div class="row-reason">{reason_html}</div>
        {meta_html}
        {duration_html}
        {cinema_html}
        <div class="genres-container">{genres_icon_html}<span class="genre-badges">{genres_html}</span></div>
        {providers_block_html}
        <div class="row-synopsis">{synopsis_toggle_html}{synopsis_row_html}{synopsis_text_html}</div>
        <div class="row-people">{people_toggle_html}{people_row_html}{people_text_html}</div>
      </div>
    </article>
    """


def render_grid(titles: list[dict]) -> str:
    """Monta o HTML completo do grid de cards.

    O subgrid de cada card (ver render_card()/principal.css) exige que .grid-titles declare
    o total de linhas explicitamente — um bloco de _CARD_GRID_ROWS linhas de conteúdo mais 1
    linha de respiro (16px) por fileira de até 3 títulos. CSS não permite aninhar repeat()
    dentro de repeat(), por isso as _CARD_GRID_ROWS linhas "auto" são escritas por extenso
    dentro do padrão repetido, em vez de um repeat() aninhado.
    """
    cards = [render_card(t, idx) for idx, t in enumerate(titles)]
    n_groups = math.ceil(len(titles) / 3) if titles else 0
    style_attr = ""
    if n_groups:
        group_pattern = " ".join(["auto"] * _CARD_GRID_ROWS) + " 16px"
        style_attr = f' style="grid-template-rows: repeat({n_groups}, {group_pattern})"'
    return f'<div class="grid-titles"{style_attr}>' + "".join(cards) + "</div>"


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
