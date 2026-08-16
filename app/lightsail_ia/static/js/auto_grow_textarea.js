(function () {
    const doc = window.parent.document;
    const MAX_HEIGHT = 200; // rede de seguranca para colagem de texto com muitas quebras de linha

    function attach() {
        // Mesmo seletor/justificativa de contador_caracteres.js: data-testid é o hook
        // de teste oficial do Streamlit, mais estável que classes CSS auto-geradas.
        const textarea = doc.querySelector('[data-testid="stTextArea"] textarea');
        if (!textarea) { setTimeout(attach, 200); return; }

        const resize = () => {
            textarea.style.height = "auto";
            const newHeight = Math.min(textarea.scrollHeight, MAX_HEIGHT);
            textarea.style.height = newHeight + "px";
            textarea.style.overflowY = textarea.scrollHeight > MAX_HEIGHT ? "auto" : "hidden";
        };

        if (!textarea.dataset.autogrowBound) {
            textarea.addEventListener("input", resize);
            textarea.dataset.autogrowBound = "1";
        }
        // Roda uma vez de imediato: cobre o caso de texto já preenchido ao carregar
        // (ex: transcrição de áudio caindo em session_state["preference_text"]),
        // sem esperar o usuário digitar algo para a caixa ajustar a altura.
        resize();
    }
    attach();
})();
