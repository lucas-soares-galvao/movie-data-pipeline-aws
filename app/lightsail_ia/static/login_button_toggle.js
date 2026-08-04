(function () {
    const doc = window.parent.document;
    // Mesmo motivo do "rateLimited" em contador_caracteres.js: se a Python já
    // computou disabled=True por bloqueio de tentativas (não por campo vazio),
    // o JS nunca deve reabilitar o botão via digitação — só o rerun seguinte
    // (quando o bloqueio já não se aplicar) manda de novo com esse valor
    // atualizado.
    const lockedOut = __LOCKED_OUT__;

    function attach() {
        const input = doc.querySelector('[data-testid="stTextInput"] input');
        const btn = doc.querySelector('.st-key-btn_entrar button');
        if (!input || !btn) { setTimeout(attach, 200); return; }

        // Habilita/desabilita "Entrar" a cada tecla. Python só calcula
        // disabled=_locked_out (não depende do texto digitado, para não
        // conflitar com a prop React que o clique nativo do st.button usa
        // internamente) — este script é a única fonte da gate de campo vazio.
        const update = () => {
            if (lockedOut) return;
            btn.disabled = input.value.length === 0;
        };

        if (!input.dataset.loginToggleBound) {
            input.addEventListener("input", update);
            input.dataset.loginToggleBound = "1";
        }
        update();
    }
    attach();
})();
