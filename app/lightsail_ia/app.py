"""
app.py — Interface web do FilmBot (aplicativo Streamlit).

==============================================================================
O QUE É ESTE ARQUIVO?
==============================================================================
Este é o arquivo principal do app web de recomendações de filmes e séries.
Ele define a interface visual que o usuário vê no navegador.

TECNOLOGIA: Streamlit
  Streamlit é uma biblioteca Python que transforma scripts Python em
  aplicativos web interativos sem precisar escrever HTML/CSS/JavaScript "na mão".
  Cada vez que o usuário interage (digita, clica em botão), o script Python
  inteiro é re-executado do início.

  Exceção: neste arquivo, o HTML/CSS é escrito manualmente para o grid de cards,
  porque o Streamlit não tem um componente nativo de grade de cards com imagens.

COMO O APP FUNCIONA?
  1. Usuário digita uma preferência ("filmes de terror dos anos 2010")
  2. Clica em "Recomendar"
  3. O app chama recomendar() do agent.py, que:
     a. Envia o texto para o OpenAI GPT-4o extrair filtros (gênero, ano, etc.)
     b. Executa uma query SQL no Athena com esses filtros
     c. Envia os resultados reais de volta ao GPT-4o para gerar recomendações
  4. O app exibe os títulos em cards visuais (imagem + nota + gêneros + sinopse)

ESTRUTURA DO ARQUIVO:
  1. CSS inline: define o visual dark theme (fundo escuro, cards arredondados)
  2. Título e campo de texto: interface do usuário
  3. Lógica de botão: chama o agente e processa a resposta
  4. Geração de HTML: monta os cards manualmente para renderização via st.markdown

IMPLANTAÇÃO:
  Este app roda numa instância AWS Lightsail (servidor Linux na nuvem).
  O processo é gerenciado pelo systemd (reinicia automaticamente se cair).
  As variáveis de ambiente (chaves de API, configurações) são lidas do arquivo .env.
"""

import re
from datetime import date

import streamlit as st
from agent import limpar_duracao, recomendar

# Configuração global da página — deve ser a primeira chamada Streamlit do arquivo.
# page_title: aparece na aba do navegador
# layout="wide": usa toda a largura da janela (sem margens laterais grandes)
st.set_page_config(page_title="FilmBot", page_icon="🎬", layout="wide")

# ==============================================================================
# AUTENTICAÇÃO
# ==============================================================================
# Protege o app com senha configurada em .streamlit/secrets.toml (não commitado).
# Isso evita abuso da API OpenAI e Athena por quem descobrir o IP da instância.
# secrets.toml esperado:
#   [auth]
#   password = "sua-senha-forte"
if not st.session_state.get("autenticado"):
    st.markdown("""
    <style>
      /* Oculta header/toolbar do Streamlit na tela de login */
      [data-testid="stHeader"] { display: none; }
      [data-testid="stToolbar"] { display: none; }
      [data-testid="stDecoration"] { display: none; }

      /* Fundo cinematográfico */
      [data-testid="stAppViewContainer"] {
        background: radial-gradient(ellipse at 50% 0%, #1a0a00 0%, #0a0a0f 55%, #050508 100%);
        min-height: 100vh;
      }

      /* Card de login centralizado */
      .login-card {
        background: rgba(17, 17, 17, 0.92);
        border: 1px solid rgba(249,115,22,0.18);
        border-radius: 20px;
        padding: 40px 36px 32px;
        box-shadow: 0 8px 48px rgba(0,0,0,0.6), 0 0 0 1px rgba(249,115,22,0.06);
        margin-bottom: 8px;
      }
      .login-title {
        font-size: 32px;
        font-weight: 800;
        color: #ffffff;
        margin: 0 0 6px 0;
        letter-spacing: -0.5px;
      }
      .login-subtitle {
        font-size: 14px;
        color: #737373;
        margin: 0 0 24px 0;
      }
      .login-divider {
        border: none;
        border-top: 2px solid #f97316;
        opacity: 0.5;
        margin: 0 0 24px 0;
      }

      /* Sobrescreve o input de senha */
      [data-testid="stTextInput"] input {
        background: #1a1a1a !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 10px !important;
        color: #f5f5f5 !important;
        font-size: 15px !important;
        padding: 10px 14px !important;
      }
      [data-testid="stTextInput"] input:focus {
        border-color: rgba(249,115,22,0.5) !important;
        box-shadow: 0 0 0 3px rgba(249,115,22,0.12) !important;
      }

      /* Sobrescreve o botão */
      [data-testid="stButton"] > button {
        background: linear-gradient(135deg, #f97316, #ea580c) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 10px !important;
        font-size: 15px !important;
        font-weight: 600 !important;
        padding: 10px 0 !important;
        width: 100% !important;
        margin-top: 8px !important;
        transition: opacity 0.15s ease !important;
      }
      [data-testid="stButton"] > button:hover {
        opacity: 0.88 !important;
      }

      /* Erro customizado */
      .login-error {
        background: rgba(239,68,68,0.08);
        border: 1px solid rgba(239,68,68,0.25);
        color: #fca5a5;
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 13px;
        margin-top: 10px;
      }
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.1, 1])
    with col:
        st.markdown("""
        <div class="login-card">
          <p class="login-title">🎬 FilmBot</p>
          <p class="login-subtitle">Seu assistente de recomendações de filmes e séries</p>
          <hr class="login-divider">
        </div>
        """, unsafe_allow_html=True)

        senha = st.text_input("", placeholder="Digite a senha de acesso...", type="password", label_visibility="collapsed")
        entrar = st.button("Entrar →", use_container_width=True)

        if entrar and senha == st.secrets.get("auth", {}).get("password", ""):
            st.session_state["autenticado"] = True
            st.rerun()
        elif entrar and senha:
            st.markdown('<div class="login-error">❌ Senha incorreta. Tente novamente.</div>', unsafe_allow_html=True)

    st.markdown(f"""
<div style="text-align:center; padding: 16px 0 8px; color: #6b7280; font-size: 12px; letter-spacing: 0.05em;">
  © {date.today().year} FilmBot · Todos os direitos reservados
</div>
""", unsafe_allow_html=True)
    st.stop()

# ==============================================================================
# ESTILOS VISUAIS (CSS)
# ==============================================================================
# Streamlit permite injetar CSS personalizado via st.markdown com unsafe_allow_html=True.
# Isso é necessário porque o Streamlit não expõe controle fino de estilos de grade.
#
# CLASSES CSS DEFINIDAS:
#   .grid-filmes     → container em grade de 4 colunas para os cards
#   .card            → card individual (fundo escuro, bordas arredondadas)
#   .card-body       → área de conteúdo textual dentro do card
#   .genero          → badge laranja com o nome do gênero (ex: "Ação")
#   .meta-row        → linha de metadados (ícone + texto alinhados horizontalmente)
#   .nota            → texto da nota em laranja negrito
#   .duracao         → texto de duração em cinza
#   .sinopse         → parágrafo da sinopse em cinza claro
#   .motivo          → rodapé itálico com o motivo da recomendação pelo GPT
#   .provider        → badge verde com o nome da plataforma de streaming
#   .providers-row   → linha de badges de streaming com flex-wrap
st.markdown("""
<style>
  .grid-filmes {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 16px;
  }
  @media (max-width: 768px) {
    .grid-filmes {
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 12px;
    }
    .login-title { font-size: 24px; }
    .login-card { padding: 24px 20px 20px; }
  }
  @media (max-width: 480px) {
    .grid-filmes {
      grid-template-columns: 1fr;
    }
    .grid-filmes img { height: 160px; }
  }
  .card {
    background: #111;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.06);
    display: flex;
    flex-direction: column;
  }
.card-body {
    padding: 12px;
    display: flex;
    flex-direction: column;
    flex: 1;
  }
  .genero {
    background: rgba(249,115,22,0.13);
    color: #fb923c;
    border-radius: 99px;
    padding: 2px 8px;
    font-size: 11px;
    display: inline-block;
    margin: 2px;
    border: 1px solid rgba(249,115,22,0.2);
  }
  .meta-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 2px 0;
  }
  .meta-icon {
    font-size: 16px;
    line-height: 1;
    flex-shrink: 0;
    width: 20px;
    text-align: center;
  }
  .nota { color: #f97316; font-weight: bold; font-size: 16px; }
  .duracao { color: #a3a3a3; font-size: 14px; }
  .data-lancamento { color: #a3a3a3; font-size: 14px; }
  .sinopse { color: #d4d4d4; font-size: 12px; margin-top: 6px; line-height: 1.5; flex: 1; }
  .motivo {
    color: #a3a3a3;
    font-size: 11px;
    font-style: italic;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(255,255,255,0.05);
  }
  .provider {
    background: rgba(34,197,94,0.12);
    color: #4ade80;
    border-radius: 99px;
    padding: 2px 8px;
    font-size: 11px;
    display: inline-block;
    margin: 2px;
    vertical-align: middle;
  }
  .cinema-badge {
    background: rgba(250,204,21,0.15);
    color: #fbbf24;
    border-radius: 99px;
    padding: 2px 8px;
    font-size: 11px;
    display: inline-block;
    margin: 2px;
    vertical-align: middle;
  }
  .providers-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
    margin: 2px 0;
  }
  .providers-label {
    color: #737373;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 6px 0 2px 0;
  }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# CABEÇALHO E CAMPO DE ENTRADA
# ==============================================================================
col_titulo, col_sair = st.columns([9, 1])
with col_titulo:
    st.title("🎬 FilmBot — Seu assistente de filmes e séries")
    st.caption("Descubra o que assistir com ajuda da inteligência artificial")
with col_sair:
    st.write("")  # empurra o botão para baixo, alinhando com o título
    if st.button("Sair", use_container_width=True):
        st.session_state["autenticado"] = False
        st.rerun()

# Campo de texto onde o usuário digita sua preferência em linguagem natural.
# O Streamlit armazena o valor na variável "preferencia" a cada re-execução.
preferencia = st.text_input(
    "O que você quer assistir?",
    placeholder="Ex: filmes de terror dos anos 2010, séries parecidas com O Senhor dos Anéis...",
)

# ==============================================================================
# LÓGICA DO BOTÃO E EXIBIÇÃO DOS RESULTADOS
# ==============================================================================
# O bloco "if st.button(...) and preferencia" executa apenas quando:
#   1. O usuário clicou no botão "Recomendar" E
#   2. O campo de texto não está vazio
if st.button("Recomendar", type="primary") and preferencia:
    # st.spinner() exibe uma animação de carregamento enquanto o bloco interno processa
    with st.spinner("Buscando as melhores opções para você..."):
        # Chama o agente de IA (agent.py): LLM extrai filtros → Athena consulta → LLM formata
        try:
            titulos = recomendar(preferencia)
        except Exception:
            st.error("Algo deu errado ao buscar as recomendações. Tente novamente em instantes.")
            titulos = []

    if not titulos:
        st.warning("Não encontramos nada com essa descrição. Tente usar outras palavras ou ser mais específico.")
    else:
        palavra = "opção" if len(titulos) == 1 else "opções"
        st.markdown(f"**Encontramos {len(titulos)} {palavra} para você!**")

        # Streamlit não tem componente de grid de cards nativo, então montamos HTML manualmente.
        # st.markdown(..., unsafe_allow_html=True) renderiza HTML bruto dentro da página.
        cards_html = []
        for t in titulos:
            # Preferimos backdrop (imagem wide de fundo) sobre poster (imagem vertical).
            # Se nenhum estiver disponível, não exibe imagem.
            poster = t.get("backdrop_url") or t.get("poster_url") or ""
            nota = t.get("nota")
            sinopse = t.get("sinopse") or ""
            generos = t.get("generos") or []
            motivo = t.get("motivo") or ""  # motivo de recomendação gerado pelo GPT

            duracao = limpar_duracao(t.get("duracao") or "")
            data_lancamento = t.get("data_lancamento") or ""
            streaming_providers = t.get("streaming_providers") or ""
            in_theaters = t.get("in_theaters") or False
            theater_end_date = t.get("theater_end_date") or ""

            # HTML da imagem do card (largura 100%, altura fixa 200px, crop centralizado)
            img_html = (
                f'<img src="{poster}" style="width:100%;height:200px;object-fit:cover;display:block;" />'
                if poster else ""
            )

            # Gera os badges de gênero (ex: "Ação", "Aventura", "Terror")
            generos_html = "".join(
                f'<span class="genero">{g.strip()}</span>' for g in generos
            )

            # Gera os badges de plataformas de streaming e cinema
            # (streaming_providers é uma string "Netflix, Prime Video, Max")
            providers_html = ""
            cinema_html = ""
            if in_theaters:
                label = f"Em cartaz até {theater_end_date}" if theater_end_date else "Em cartaz"
                cinema_html = f'<div class="meta-row"><span class="meta-icon">🎬</span><span class="cinema-badge">{label}</span></div>'
            providers_html = ""
            if streaming_providers:
                stream_badges = "".join(
                    f'<span class="provider">{p.strip()}</span>'
                    for p in streaming_providers.split(",")
                    if p.strip()
                )
                providers_html = f'<div class="meta-row providers-row"><span class="meta-icon">📺</span>{stream_badges}</div>'

            # Monta o HTML completo de um card
            cards_html.append(f"""
            <div class="card">
              {img_html}
              <div class="card-body">
                <strong>{t.get('titulo', '')}</strong>
                <span style="color:#737373; font-size:12px">
                  &nbsp;({t.get('ano', '')}) — {t.get('tipo', '')}
                </span>
                <div style="margin: 6px 0">{generos_html}</div>
                {f'<div class="meta-row"><span class="meta-icon">★</span><span class="nota">{nota}</span></div>' if nota else ''}
                {f'<div class="meta-row"><span class="meta-icon">⏱</span><span class="duracao">{duracao}</span></div>' if duracao else ''}
                {f'<div class="meta-row"><span class="meta-icon">📅</span><span class="data-lancamento">{data_lancamento}</span></div>' if data_lancamento else ''}
                {cinema_html}
                {providers_html}
                <p class="sinopse">{sinopse}</p>
                <p class="motivo">💡 {motivo}</p>
              </div>
            </div>
            """)

        # Envolve todos os cards no container de grade
        grid_html = '<div class="grid-filmes">' + "".join(cards_html) + "</div>"
        # re.sub(r'\s+', ' ', ...) colapsa múltiplos espaços e quebras de linha em um único espaço.
        # Isso é necessário porque o parser HTML do Streamlit às vezes falha com
        # indentação excessiva no HTML injetado via st.markdown.
        grid_html = re.sub(r'\s+', ' ', grid_html)
        st.markdown(grid_html, unsafe_allow_html=True)

st.markdown(f"""
<div style="text-align:center; padding: 16px 0 8px; color: #6b7280; font-size: 12px; letter-spacing: 0.05em; border-top: 1px solid #1f2937; margin-top: 32px;">
  © {date.today().year} FilmBot · Dados fornecidos por <a href="https://www.themoviedb.org/?language=pt-BR" target="_blank" style="color:#6b7280; text-decoration:underline;">TMDB</a> · Todos os direitos reservados
</div>
""", unsafe_allow_html=True)
