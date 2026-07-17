(function () {
    const doc = window.parent.document;
    const maxChars = __MAX_CHARS__;
    let lastLength = -1;

    function attach() {
        // data-testid é o hook de teste oficial do Streamlit (mais estável que
        // classes CSS auto-geradas ou o texto exato do aria-label, que pode mudar
        // com a copy). Só existe uma st.text_area na página hoje.
        const textarea = doc.querySelector('[data-testid="stTextArea"] textarea');
        if (!textarea) { setTimeout(attach, 200); return; }

        let counter = doc.getElementById("pref-char-counter");
        if (!counter) {
            counter = doc.createElement("div");
            counter.id = "pref-char-counter";
            counter.style.cssText = "font-size:0.8rem;opacity:0.6;margin-top:4px;";
            textarea.closest('[data-testid="stTextArea"]').insertAdjacentElement("afterend", counter);
        }

        const update = () => {
            if (textarea.value.length === lastLength) return;
            lastLength = textarea.value.length;
            counter.innerText = `${textarea.value.length} / ${maxChars} caracteres`;
        };

        if (!textarea.dataset.counterBound) {
            textarea.addEventListener("input", update);
            textarea.dataset.counterBound = "1";
        }
        update();
        setInterval(update, 300);
    }
    attach();
})();
