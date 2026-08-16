(function () {
    const doc = window.parent.document;
    const maxChars = __MAX_CHARS__;
    // Se a Python computou disabled=True por rate limit (não por campo vazio),
    // o JS nunca deve reabilitar o botão via digitação — só o rerun seguinte
    // (quando o rate limit já não se aplicar) manda de novo com esse valor
    // atualizado.
    const rateLimited = __RATE_LIMITED__;
    let lastLength = -1;

    function attach() {
        // data-testid é o hook de teste oficial do Streamlit (mais estável que
        // classes CSS auto-geradas ou o texto exato do aria-label, que pode mudar
        // com a copy). Só existe uma st.text_area na página hoje.
        const textarea = doc.querySelector('[data-testid="stTextArea"] textarea');
        // Contador vive na mesma linha do gravador (.st-key-recorder-card,
        // flex row com label+stAudioInput) — anexado como terceiro filho,
        // empurrado para a ponta direita via margin-left:auto.
        const recorderRow = doc.querySelector('.st-key-recorder-card');
        if (!textarea || !recorderRow) { setTimeout(attach, 200); return; }

        let counter = doc.getElementById("pref-char-counter");
        if (!counter) {
            counter = doc.createElement("div");
            counter.id = "pref-char-counter";
            // position:relative;top:-2px — nudge vertical fino medido via inspeção
            // real do DOM (Playwright), igual ao usado em .recorder-timer
            // (recommendation.css) para os dois labels ficarem na mesma linha de base.
            // left:12px — compensa o margin-left:-12px de .st-key-recorder-card
            // (recommendation.css, nudge de alinhamento do gravador com o início do
            // texto): como o contador é filho dessa mesma linha e empurrado pra
            // ponta via margin-left:auto, aquele nudge também arrastava o
            // contador 12px pra esquerda do fim real do texto — medido via
            // getBoundingClientRect (Chrome DevTools).
            counter.style.cssText = "font-size:14px;opacity:0.6;margin-left:auto;white-space:nowrap;position:relative;top:-2px;left:12px;";
            recorderRow.appendChild(counter);
        }

        const update = () => {
            if (textarea.value.length === lastLength) return;
            lastLength = textarea.value.length;
            counter.innerText = `${textarea.value.length} / ${maxChars} caracteres`;
        };

        // Habilita/desabilita "Recomendar" a cada tecla. Python só calcula
        // disabled=_remaining<=0 (não depende do texto digitado, para não
        // conflitar com a prop React que o clique nativo do st.button usa
        // internamente) — este script é a única fonte da gate de campo vazio.
        const updateButton = () => {
            if (rateLimited) return;
            const btn = doc.querySelector('.st-key-btn_recomendar button');
            if (!btn) return;
            btn.disabled = textarea.value.trim().length === 0;
        };

        if (!textarea.dataset.counterBound) {
            textarea.addEventListener("input", () => {
                update();
                updateButton();
            });
            textarea.dataset.counterBound = "1";
        }
        update();
        updateButton();
        setInterval(() => {
            update();
            updateButton();
        }, 300);
    }
    attach();
})();
