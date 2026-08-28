"""components.py — Funções auxiliares de renderização para o FilmBot."""

import html
import re
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

# Ícones outline do design system "Luminous" (Lucide, stroke-only, brancos via .icon em
# base.css) — paths oficiais do pacote lucide-static, viewBox 24x24. Embutidos como
# <svg> inline (não <img> base64, como o antigo ícone de marca do YouTube que isso
# substituiu) porque só assim `stroke="currentColor"` consegue herdar cor via CSS. Públicos
# (sem prefixo `_`) porque `app.py` também usa pra montar o badge do ícone do cabeçalho, não
# só `render_card()` aqui dentro.
ICON_PATHS = {
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "play": '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/>',
    "calendar": (
        '<path d="M8 2v3"/><path d="M16 2v3"/>'
        '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/>'
    ),
    "tv": '<path d="m17 2-5 5-5-5"/><rect width="20" height="15" x="2" y="7" rx="2"/>',
    "file-text": (
        '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588'
        'A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/>'
        '<path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>'
    ),
    "users": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<path d="M16 3.128a4 4 0 0 1 0 7.744"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
        '<circle cx="9" cy="7" r="4"/>'
    ),
    "clapperboard": (
        '<path d="m12.296 3.464 3.02 3.956"/>'
        '<path d="M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3z"/>'
        '<path d="M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
        '<path d="m6.18 5.276 3.1 3.899"/>'
    ),
    "lightbulb": (
        '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 '
        '.2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/>'
        '<path d="M9 18h6"/><path d="M10 22h4"/>'
    ),
    "mic": (
        '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>'
        '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>'
    ),
    "user": (
        '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'
    ),
    "lock": (
        '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "mail": (
        '<rect width="20" height="16" x="2" y="4" rx="2"/>'
        '<path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>'
    ),
}

# E-mail de contato exibido nos rodapés (render_footer/render_form_footer) — caixa
# dedicada só para isso, distinta dos e-mails de notificação interna admin/sistema
# configurados via Terraform (var.filmbot_new_signup_notification_email e afins).
_CONTACT_EMAIL = "filmbot.lsgalvao@gmail.com"


def icon(name: str, size: int = 16) -> str:
    """Monta um ícone Lucide inline (outline, `stroke="currentColor"` — cor vem da classe
    `.icon` em base.css, branca por padrão; o ícone "lightbulb" do Insight do FilmBot é
    a única exceção, laranja via `.reason-label .icon` em cards.css). Usada por
    `render_card()` aqui dentro, pelo badge do ícone do cabeçalho/login em `app.py`/
    `forms.py`, pelo status "Transcrevendo áudio..." em `recommendation.py`, e pelo menu
    vertical de navegação (Usuários/Perfil/Senha) em `profile.py`/`admin.py`."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"'
        f' viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
        f' stroke-linecap="round" stroke-linejoin="round" class="icon icon-{name}"'
        f' aria-hidden="true">{ICON_PATHS[name]}</svg>'
    )


def favicon_svg() -> str:
    """Monta o favicon como SVG autocontido: fundo transparente com o ícone
    "clapperboard" laranja (#f97316) sozinho, reaproveitando ICON_PATHS como única fonte
    da geometria. Cor hardcoded (não `currentColor`, diferente de icon()) porque um
    favicon é carregado como recurso isolado, sem acesso ao CSS da página. Usada só por
    app.py (`st.set_page_config`)."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<g transform="translate(3 3) scale(0.75)" fill="none" stroke="#f97316"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'{ICON_PATHS["clapperboard"]}'
        '</g>'
        '</svg>'
    )


def _inject_css(file_name: str) -> None:
    """Lê um arquivo CSS de static/css/ e injeta na página via st.markdown."""
    path = Path(__file__).parent.parent / "static" / "css" / file_name
    css = path.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def load_base_css() -> None:
    """Injeta os estilos transversais (fundo, reset de botão, largura de container, ícones,
    mensagens de feedback), compartilhados entre a tela de login e a página principal."""
    _inject_css("base.css")


def load_forms_css() -> None:
    """Injeta os estilos base seguidos dos estilos específicos das telas de autenticação."""
    load_base_css()
    _inject_css("forms.css")


def load_app_css() -> None:
    """Injeta os estilos base seguidos dos estilos de cabeçalho/rodapé da página principal."""
    load_base_css()
    _inject_css("app.css")


def load_scroll_lock_script() -> None:
    """Injeta o script que zera o scrollLeft de stMain/stAppViewContainer sempre que
    ele muda — overflow-x:hidden (base.css) esconde a barra de rolagem horizontal mas
    não impede scrollLeft programático. Confirmado (Playwright) que, no painel admin,
    visitar a aba "Usuários" (st.dataframe) e depois "Senha" (st.components.v1.html,
    ver load_password_requirements_gate_script) deixa esses containers com
    scrollLeft > 0 num mecanismo interno do Streamlit não documentado (ligado ao
    ciclo de montagem/remontagem dos iframes de componente customizado dos dois
    widgets) — sem scrollbar visível, o conteúdo simplesmente aparece cortado à
    esquerda. Chamado uma vez por `app.py`, logo após `load_app_css()` — cobre todas
    as telas (admin/perfil/recomendação), já que qualquer combinação futura de
    st.dataframe/st.data_editor com um componente iframe pode reproduzir o mesmo
    sintoma."""
    path = Path(__file__).parent.parent / "static" / "js" / "scroll_lock.js"
    script = path.read_text(encoding="utf-8")
    components.html(f"<script>{script}</script>", height=0)


def load_recommendation_css() -> None:
    """Injeta os estilos do formulário de preferência/busca assíncrona (depende de base.css já
    injetado por load_app_css() na mesma execução de script)."""
    _inject_css("recommendation.css")


def load_cards_css() -> None:
    """Injeta os estilos da exibição de resultados (depende de base.css já injetado por
    load_app_css() na mesma execução de script)."""
    _inject_css("cards.css")


def load_admin_css() -> None:
    """Injeta os estilos do painel administrativo (depende de base.css já injetado por
    load_app_css() na mesma execução de script)."""
    _inject_css("admin.css")


def load_profile_css() -> None:
    """Injeta os estilos da tela "Meu Perfil" (depende de base.css já injetado por
    load_app_css() na mesma execução de script)."""
    _inject_css("profile.css")


def load_preference_counter_script(max_chars: int, rate_limited: bool = False) -> None:
    """Injeta o script do contador dinâmico de caracteres e do habilitar/desabilitar do botão "Recomendar"."""
    path = Path(__file__).parent.parent / "static" / "js" / "contador_caracteres.js"
    script = (
        path.read_text(encoding="utf-8")
        .replace("__MAX_CHARS__", str(max_chars))
        .replace("__RATE_LIMITED__", "true" if rate_limited else "false")
    )
    components.html(f"<script>{script}</script>", height=0)


def load_audio_cancel_script() -> None:
    """Injeta o script do ícone de descarte durante a gravação de áudio."""
    path = Path(__file__).parent.parent / "static" / "js" / "audio_cancel_recording.js"
    script = path.read_text(encoding="utf-8")
    components.html(f"<script>{script}</script>", height=0)


def load_audio_timer_script(max_seconds: int) -> None:
    """Injeta o script do timer decorrido/máximo do gravador, que também para a gravação sozinha ao atingir max_seconds."""
    path = Path(__file__).parent.parent / "static" / "js" / "audio_timer.js"
    script = path.read_text(encoding="utf-8").replace("__MAX_SECONDS__", str(max_seconds))
    components.html(f"<script>{script}</script>", height=0)


def load_textarea_autogrow_script() -> None:
    """Injeta o script que ajusta a altura do campo de preferência ao conteúdo digitado."""
    path = Path(__file__).parent.parent / "static" / "js" / "auto_grow_textarea.js"
    script = path.read_text(encoding="utf-8")
    components.html(f"<script>{script}</script>", height=0)


def load_countdown_script(seconds: int, element_id: str = "countdown") -> None:
    """Injeta o script de countdown MM:SS genérico (rate limit de busca, rate limit de
    transcrição e bloqueio temporário de login), que recarrega a página sozinho ao chegar
    a 00:00. `element_id` mira o `<span>` a atualizar — necessário quando mais de um
    countdown pode estar visível na mesma página ao mesmo tempo (busca e transcrição),
    para não colidir em `id="countdown"` duplicado no DOM.

    Os cooldowns de "enviar"/"reenviar código" do fluxo de troca de senha (`forms.py`)
    não usam mais este script — o reload de página resetaria `session_state`
    (`auth_view`/`reset_step`) e devolveria o usuário ao login no meio da troca. Em vez
    disso, usam `st.fragment(run_every=1)` pra recalcular o cooldown e o contador
    inteiramente no backend a cada segundo, sem reload e sem depender de JS/DOM pra
    reabilitar o botão (um hack anterior nesse sentido deixava o botão visualmente
    habilitado, mas o clique nunca chegava ao backend, já que o componente React
    continuava com o prop `disabled=True` até o próximo rerun)."""
    path = Path(__file__).parent.parent / "static" / "js" / "countdown.js"
    script = (
        path.read_text(encoding="utf-8")
        .replace("__SECONDS__", str(seconds))
        .replace("__ELEMENT_ID__", element_id)
    )
    components.html(f"<script>{script}</script>", height=0)


def load_form_button_toggle_script(
    locked_out: bool, button_key: str = "btn_entrar", email_key: str = ""
) -> None:
    """Injeta o script que habilita/desabilita o botão de submit a cada tecla digitada
    em qualquer campo do formulário ativo (login, cadastro ou esqueci senha — só um
    fica visível por vez), mesmo padrão de `load_preference_counter_script()` para o
    botão "Recomendar". `button_key` identifica o botão (`key=...` do `st.button`) de
    cada formulário. `email_key`, se informado (só a tela "esqueci a senha" passa —
    login não precisa), marca o campo de e-mail com borda verde/vermelha conforme o
    formato (mesma regex de `_EMAIL_RE` em `forms.py`) e inclui isso no gate do botão."""
    path = Path(__file__).parent.parent / "static" / "js" / "form_button_toggle.js"
    script = (
        path.read_text(encoding="utf-8")
        .replace("__LOCKED_OUT__", "true" if locked_out else "false")
        .replace("__BUTTON_KEY__", button_key)
        .replace("__EMAIL_KEY__", email_key)
    )
    components.html(f"<script>{script}</script>", height=0)


def load_password_requirements_gate_script(
    password_key: str, confirm_key: str, button_key: str, email_key: str = "", locked_out: bool = False,
) -> None:
    """Injeta o script que, a cada tecla digitada em qualquer campo do formulário (cadastro
    ou redefinir senha), marca o campo "Confirmar senha" com borda verde/vermelha e mantém o
    botão de submit desabilitado até todos os campos estarem preenchidos, senha e confirmação
    coincidirem, e a senha atender à política mínima (8 a 16 caracteres, maiúscula, número e
    símbolo — mesma política de infra/lightsail_ia.tf, ver password_requirements_gate.js).
    Substitui `load_form_button_toggle_script()` nessas duas telas (já cobre o "campo
    vazio" que aquele script cuidava, além de senha/confirmação); as telas sem confirmação
    de senha (login, esqueci senha) continuam usando o outro script. `password_key`/
    `confirm_key`/`button_key` identificam os campos e o botão (`key=...`) do formulário
    ativo. `email_key`, se informado (só a tela de cadastro passa — redefinir senha não tem
    campo de e-mail digitado), marca o campo de e-mail com borda verde/vermelha conforme o
    formato (mesma regex de `_EMAIL_RE` em `forms.py`) e inclui isso no gate do botão.
    `locked_out`, se `True` (bloqueio de tentativas de código incorreto na tela de redefinir
    senha, `forms.py::_render_forgot_password_confirm`), impede o script de reabilitar o
    botão via digitação — mesmo racional de `locked_out` em
    `load_form_button_toggle_script()`."""
    path = Path(__file__).parent.parent / "static" / "js" / "password_requirements_gate.js"
    script = (
        path.read_text(encoding="utf-8")
        .replace("__PASSWORD_KEY__", password_key)
        .replace("__CONFIRM_KEY__", confirm_key)
        .replace("__BUTTON_KEY__", button_key)
        .replace("__EMAIL_KEY__", email_key)
        .replace("__LOCKED_OUT__", "true" if locked_out else "false")
    )
    components.html(f"<script>{script}</script>", height=0)


_PASSWORD_REQUIREMENTS = (
    ("length", "8 a 16 caracteres"),
    ("lower", "Uma letra minúscula"),
    ("upper", "Uma letra maiúscula"),
    ("number", "Um número"),
    ("symbol", "Um símbolo (ex: ! @ # $)"),
    ("match", "Senha e confirmação iguais"),
)


def validate_password(password: str) -> str:
    """Valida a senha contra a mesma política configurada no Cognito (infra/lightsail_ia.tf:
    aws_cognito_user_pool.filmbot.password_policy), mais o teto de 16 caracteres — regra só
    do app, o Cognito não impõe máximo — checar aqui evita disparar a chamada só para
    receber InvalidPasswordException. Retorna "" se válida, senão a mensagem de erro.

    Pública (movida de forms.py) porque profile.py também usa, na troca de senha da tela
    de perfil — mesma política em todos os 3 lugares que pedem senha nova (cadastro,
    esqueci senha, perfil)."""
    if len(password) < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    if len(password) > 16:
        return "A senha pode ter no máximo 16 caracteres."
    if not re.search(r"[a-z]", password):
        return "A senha precisa ter pelo menos uma letra minúscula."
    if not re.search(r"[A-Z]", password):
        return "A senha precisa ter pelo menos uma letra maiúscula."
    if not re.search(r"\d", password):
        return "A senha precisa ter pelo menos um número."
    if not re.search(r"[^\w\s]", password):
        return "A senha precisa ter pelo menos um símbolo (ex: ! @ # $)."
    return ""


def render_password_requirements() -> None:
    """Renderiza a lista de critérios da política de senha (mesma política de
    `validate_password()` acima e de `password_requirements_gate.js`) mais o
    critério de senha/confirmação iguais, abaixo do campo "Confirmar senha" nas telas de
    cadastro, redefinir senha e troca de senha do perfil. Estado inicial neutro (ícone "•", sem classe) —
    `password_requirements_gate.js` assume o `id` fixo "password-requirements" (só uma
    tela de autenticação renderiza por vez) e atualiza cada `<li data-req="...">` para
    ✓/✗ (classes `req-met`/`req-unmet`) a cada tecla digitada nos campos de senha/
    confirmar senha — o item "match" reage a ambos, os demais só ao campo de senha."""
    items = "".join(
        f'<li data-req="{key}"><span class="req-icon">•</span>'
        f'<span class="req-label">{label}</span></li>'
        for key, label in _PASSWORD_REQUIREMENTS
    )
    st.markdown(
        f'<ul id="password-requirements" class="password-requirements">{items}</ul>',
        unsafe_allow_html=True,
    )


def render_email_hint() -> None:
    """Renderiza a mensagem de formato de e-mail inválido, escondida por padrão —
    form_button_toggle.js/password_requirements_gate.js mostram (classe
    "email-hint-visible") quando o usuário sai do campo de e-mail (evento "blur", não a
    cada tecla — evita mostrar "inválido" enquanto o e-mail ainda está sendo digitado)
    com um valor que não bate com _EMAIL_RE. Chamada logo abaixo do st.text_input de
    e-mail em cadastro e esqueci senha."""
    st.markdown(
        '<p id="email-hint" class="email-hint">Digite um e-mail válido.</p>',
        unsafe_allow_html=True,
    )


_FEEDBACK_ICONS = {"error": "❌", "warning": "⚠️", "success": "✅"}


def render_feedback(kind: str, message: str, *, extra_html: str = "") -> None:
    """Renderiza uma caixa de mensagem de feedback padronizada
    (.msg-error/.msg-warning/.msg-success).

    kind: "error" (ícone ❌), "warning" (ícone ⚠️) ou "success" (ícone ✅).
    extra_html: HTML bruto adicional anexado ao final, não escapado — usado só pelo
    countdown de rate limit de busca, para injetar o <span id="countdown"> vazio.
    Ícone e texto ficam em spans (.msg-icon/.msg-text) separados para que o CSS
    (base.css) possa alinhá-los verticalmente via flexbox — o glifo de emoji usa a fonte
    de emoji do sistema, com métricas de altura diferentes da fonte de texto, e sem
    wrapper próprio o conjunto desalinhava dentro da caixa.
    """
    icon_char = _FEEDBACK_ICONS[kind]
    st.markdown(
        f'<div class="msg-{kind}"><span class="msg-icon">{icon_char}</span>'
        f'<span class="msg-text">{html.escape(message)}{extra_html}</span></div>',
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
    classe "highlighted" (borda laranja, ver cards.css) — não só o primeiro, todo
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
    # cards.css) — não só o primeiro, mesmo padrão de _render_provider_badges.
    genres_html = "".join(
        f'<span class="genre{" highlighted" if _matches_highlighted(g, highlighted_genres) else ""}">'
        f"{html.escape(g)}</span>"
        for g in visible_genres_raw
    )
    # Faz parte do meio solto do card (ver cards.css) — só emite a div quando há algum
    # gênero pra mostrar.
    genres_block_html = ""
    if genres_html:
        genres_block_html = (
            f'<div class="genres-container">'
            f'<span class="genre-badges">{genres_html}</span></div>'
        )

    # Filme (in_theaters), série (next_episode_*) e título ainda não lançado (upcoming_date)
    # nunca preenchem mais de um ao mesmo tempo (upcoming_date só existe pra air_date futuro —
    # incompatível com estar em cartaz ou ter próximo episódio de uma série já no ar) — por
    # isso a mesma linha/classe serve pros três badges, sem checar media_type explicitamente.
    # Os três usam o mesmo ícone de calendário (antes eram emoji diferentes por estado —
    # 🎬/📅/🔜 —, unificados num só ícone Lucide). Sem nenhum dos três, não emite a div — o
    # card fica com essa linha a menos (meio solto, ver cards.css).
    cinema_icon_html = f'<span class="meta-icon">{icon("calendar")}</span>'
    cinema_content = ""
    if in_theaters:
        label = f"Em cartaz até {theater_end_date}" if theater_end_date else "Em cartaz"
        cinema_content = (
            f'{cinema_icon_html}<span class="cinema-badge">{html.escape(label)}</span>'
        )
    elif next_episode_season_number is not None and next_episode_number is not None and next_episode_date:
        label = f"T{next_episode_season_number} E{next_episode_number} estreia em {next_episode_date}"
        cinema_content = (
            f'{cinema_icon_html}<span class="cinema-badge">{html.escape(label)}</span>'
        )
    elif upcoming_date:
        label = f"Em breve · {upcoming_date}"
        cinema_content = (
            f'{cinema_icon_html}<span class="cinema-badge">{html.escape(label)}</span>'
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

    # Motivo é limitado a 150 caracteres na origem (prompt do agente) — cabe sem clamp nem
    # toggle na altura que o próprio card pede (faz parte do "meio solto" do card, sem
    # sincronia de altura com os vizinhos da fileira, ver cards.css). Sem motivo, a div
    # nem é gerada (meio solto) — caso comum, não só borda: `reason` costuma vir vazio fora
    # do fluxo de recomendação da IA. Rótulo "💡 Insight do FilmBot" acima do texto, mesmo
    # princípio do rótulo "Onde assistir" acima dos badges de provedor — a seção agora vem
    # depois dos gêneros (ver return, mais abaixo), não mais logo após o título.
    reason_block_html = (
        f'<div class="row-reason"><span class="reason-label">{icon("lightbulb")} Insight do FilmBot</span>'
        f'<p class="reason">{reason}</p></div>'
        if reason
        else ""
    )

    date_type_parts = []
    if title_type:
        date_type_parts.append(title_type)
    if release_date:
        date_type_parts.append(release_date)
    elif year:
        date_type_parts.append(f"({year})")
    meta_left = " · ".join(date_type_parts)
    if not has_poster and certification_html:
        meta_left = f"{meta_left} {certification_html}" if meta_left else certification_html

    trailer_html = ""
    if trailer_url:
        safe_url = html.escape(trailer_url)
        trailer_html = (
            f'<span class="vital vital-trailer">{icon("play")}'
            f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" class="trailer-link">'
            f'Trailer</a></span>'
        )

    # Com pôster a nota já saiu pra imagem, então a meta-line fica só com data/tipo (+
    # Trailer); sem pôster a nota continua no slot direito, como sempre foi. Faz parte do
    # meio solto do card (ver cards.css) — só emite a div quando há data/tipo, Trailer ou
    # nota (sem pôster) pra mostrar. Ícone e Trailer ficam dentro de .meta-info (não como
    # irmãos soltos de .meta-row) porque .meta-line usa justify-content:space-between pra
    # separar meta-info/nota — um filho a mais direto do .meta-row empurraria pra ponta
    # esquerda/direita, longe do resto do grupo, em vez de ficarem juntos à esquerda.
    meta_icon_html = f'<span class="meta-icon">{icon("info")}</span>' if meta_left else ""
    duration_escaped = html.escape(duration) if duration else ""

    meta_right = "" if has_poster else rating_html
    meta_html = ""
    if meta_left or trailer_html or meta_right:
        meta_html = (
            f'<div class="meta-row meta-line">'
            f'<span class="meta-info">{meta_icon_html}{meta_left}{trailer_html}</span>'
            f'{meta_right}</div>'
        )

    # Duração em linha própria — só quando há duração pra mostrar (o Trailer não entra mais
    # aqui, subiu pra meta-line acima, do lado esquerdo, junto de data/tipo). Faz parte do
    # meio solto do card (ver cards.css) — sem duração, a div nem é gerada.
    duration_html = ""
    if duration:
        duration_html = (
            f'<div class="meta-row duration-row">'
            f'<span class="meta-info"><span class="meta-icon">{icon("clock")}</span>'
            f'{duration_escaped}</span></div>'
        )

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
    # cards.css) — só emite a div quando há algum provedor pra mostrar.
    providers_block_html = ""
    if provider_badges_html:
        providers_block_html = (
            f'<div class="providers-row">'
            f'<div class="providers-label-row">'
            f'<span class="meta-icon">{icon("tv")}</span>'
            f'<span class="providers-label">Onde assistir</span></div>'
            f'<div class="provider-badges">{provider_badges_html}</div>'
            f'</div>'
        )

    # Sinopse não divide mais linha com o Trailer (que subiu pra linha de duração — ver
    # meta_right/duration_html acima) — vira uma linha só com o label do accordion.
    # Checkbox fica fora da .synopsis-row, como sibling direto de .synopsis-text, pra o
    # seletor CSS ~ continuar funcionando. Ícone+texto ficam à esquerda e o chevron ⌄/⌃ na
    # ponta direita do label (`justify-content:space-between` em `.synopsis-label`, ver
    # cards.css) — mesmo padrão visual de `.people-label` (Ficha Técnica) abaixo.
    toggle_id = f"synopsis-toggle-{idx}"
    synopsis_toggle_html = ""
    synopsis_label_html = ""
    synopsis_text_html = ""
    if overview_raw:
        overview_escaped = html.escape(overview_raw)
        synopsis_toggle_html = f'<input type="checkbox" id="{toggle_id}" class="synopsis-toggle" hidden>'
        synopsis_label_html = (
            f'<label for="{toggle_id}" class="synopsis-label">'
            f'<span class="synopsis-icon-text"><span class="synopsis-icon">{icon("file-text")}</span> Sinopse</span>'
            f'<span class="synopsis-arrow-closed">⌄</span>'
            f'<span class="synopsis-arrow-open">⌃</span></label>'
        )
        synopsis_text_html = f'<p class="synopsis-text">{overview_escaped}</p>'

    synopsis_row_html = (
        f'<div class="meta-row synopsis-row">{synopsis_label_html}</div>' if synopsis_label_html else ""
    )
    # Sinopse faz parte do meio solto do card (ver cards.css), sem sincronia de altura
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
    # card (ver cards.css) — só emite a div quando há algum campo preenchido. Ícone+texto
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
            f'<span class="people-icon-text"><span class="people-icon">{icon("users")}</span> Ficha Técnica</span>'
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
    `align-items: stretch`, ver cards.css) — não precisa de nenhum posicionamento
    explícito de linha/coluna, o grid de 3 colunas com `repeat(3, 1fr)` já forma fileiras
    implícitas de 3 cards sozinho.
    """
    cards = [render_card(t, idx) for idx, t in enumerate(titles)]
    return '<div class="grid-titles">' + "".join(cards) + "</div>"


def _render_contact_line() -> str:
    """Monta o link de contato (ícone + e-mail) reaproveitado pelos dois rodapés."""
    return (
        f'<div class="footer-contact">'
        f'<a href="mailto:{_CONTACT_EMAIL}">{icon("mail", 14)} {_CONTACT_EMAIL}</a>'
        f"</div>"
    )


def render_footer() -> None:
    """Renderiza o rodapé da página principal com crédito TMDB e contato por e-mail."""
    year = datetime.now(tz=timezone.utc).year
    st.markdown(
        f'<div class="footer">'
        f"© {year} FilmBot · Dados fornecidos por "
        f'<a href="https://www.themoviedb.org/?language=pt-BR"'
        f' target="_blank" rel="noopener noreferrer">TMDB</a>'
        f" · Todos os direitos reservados"
        f"{_render_contact_line()}"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_form_footer() -> None:
    """Renderiza o rodapé simplificado das telas de autenticação, com contato por e-mail."""
    year = datetime.now(tz=timezone.utc).year
    st.markdown(
        f'<div class="footer-form">'
        f"© {year} FilmBot · Todos os direitos reservados"
        f"{_render_contact_line()}"
        f"</div>",
        unsafe_allow_html=True,
    )
