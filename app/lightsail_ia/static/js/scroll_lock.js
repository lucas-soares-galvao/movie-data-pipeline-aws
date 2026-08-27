(function () {
    const doc = window.parent.document;

    // overflow-x:hidden (base.css) esconde a barra de rolagem, mas não impede
    // scrollLeft programático — confirmado (Playwright) que, depois de visitar uma
    // seção com st.dataframe (painel admin, aba "Usuários") e navegar pra uma com
    // st.components.v1.html (aba "Senha"), o próprio Streamlit acaba deixando
    // [data-testid="stMain"]/[data-testid="stAppViewContainer"] com scrollLeft > 0
    // (mecanismo interno não documentado, ligado ao ciclo de montagem/remontagem dos
    // iframes de componente customizado dos dois widgets) — sem scrollbar visível, o
    // conteúdo simplesmente aparece cortado à esquerda. Este script zera o
    // scrollLeft desses containers sempre que ele muda, e novamente a cada rerun
    // (reattach), sem depender de entender a causa raiz do lado do Streamlit.
    function lockOne(el) {
        if (!el || el.dataset.scrollLockBound) return;
        el.dataset.scrollLockBound = "1";
        el.addEventListener("scroll", () => {
            if (el.scrollLeft !== 0) el.scrollLeft = 0;
        });
    }

    function attach() {
        lockOne(doc.querySelector('[data-testid="stAppViewContainer"]'));
        lockOne(doc.querySelector('[data-testid="stMain"]'));
        const main = doc.querySelector('[data-testid="stMain"]');
        const appContainer = doc.querySelector('[data-testid="stAppViewContainer"]');
        if (main && main.scrollLeft !== 0) main.scrollLeft = 0;
        if (appContainer && appContainer.scrollLeft !== 0) appContainer.scrollLeft = 0;
        if (!main && !appContainer) { setTimeout(attach, 200); return; }
        setTimeout(attach, 500);
    }
    attach();
})();
