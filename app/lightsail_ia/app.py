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
import streamlit as st
from agent import recomendar

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
    senha = st.text_input("Senha de acesso:", type="password")
    if senha and senha == st.secrets.get("auth", {}).get("password", ""):
        st.session_state["autenticado"] = True
        st.rerun()
    elif senha:
        st.error("Senha incorreta.")
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
    grid-template-columns: repeat(4, 1fr);  /* 4 colunas de tamanho igual */
    gap: 16px;
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
st.title("🎬 FilmBot — Recomendações do seu data lake")
st.caption("Os dados vêm da tabela SPEC do pipeline AWS (TMDB)")

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
    with st.spinner("Consultando o data lake e gerando recomendações..."):
        # Chama o agente de IA (agent.py): OpenAI extrai filtros → Athena consulta → OpenAI formata
        titulos = recomendar(preferencia)

    if not titulos:
        st.warning("Nenhum título encontrado para essa busca. Tente outra descrição.")
    else:
        st.markdown(f"**{len(titulos)} título(s) encontrado(s)**")

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

            # Limpa a string de duração: remove fragmentos "~null" que o GPT às vezes inclui
            # quando um campo de duração está ausente (ex: "3 temporadas · ~null")
            duracao = (t.get("duracao") or "").replace("~null", "").strip(" ·")
            # Reconstrói a string de duração removendo partes vazias
            # Ex: " · 36 eps · " → "36 eps"
            duracao = " · ".join(part.strip() for part in duracao.split(" · ") if part.strip())
            streaming_providers = t.get("streaming_providers") or ""

            # HTML da imagem do card (largura 100%, altura fixa 200px, crop centralizado)
            img_html = (
                f'<img src="{poster}" style="width:100%;height:200px;object-fit:cover;display:block;" />'
                if poster else ""
            )

            # Gera os badges de gênero (ex: "Ação", "Aventura", "Terror")
            generos_html = "".join(
                f'<span class="genero">{g.strip()}</span>' for g in generos
            )

            # Gera os badges de plataformas de streaming
            # (streaming_providers é uma string "Netflix, Prime Video, Max")
            providers_html = ""
            if streaming_providers:
                badges = "".join(
                    f'<span class="provider">{p.strip()}</span>'
                    for p in streaming_providers.split(",")
                    if p.strip()
                )
                providers_html = f'<div class="meta-row providers-row"><span class="meta-icon">📺</span>{badges}</div>'

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
