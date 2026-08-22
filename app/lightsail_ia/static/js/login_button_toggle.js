(function () {
    const doc = window.parent.document;
    // Mesmo motivo do "rateLimited" em contador_caracteres.js: se a Python já
    // computou disabled=True por bloqueio de tentativas (não por campo vazio),
    // o JS nunca deve reabilitar o botão via digitação — só o rerun seguinte
    // (quando o bloqueio já não se aplicar) manda de novo com esse valor
    // atualizado.
    const lockedOut = __LOCKED_OUT__;
    const buttonKey = "__BUTTON_KEY__";

    function attach() {
        // Generalizado para N campos (login: e-mail+senha, cadastro: nome+e-mail+
        // senha+confirmar, esqueci senha: variável) — todos os stTextInput visíveis
        // precisam estar preenchidos, não só o primeiro. Só existe um formulário
        // visível por vez (render_login troca de view via st.session_state e chama
        // st.stop() logo depois), então "todos os inputs da página" == "todos os
        // inputs deste formulário".
        const inputs = doc.querySelectorAll('[data-testid="stTextInput"] input');
        const btn = doc.querySelector(`.st-key-${buttonKey} button`);
        if (!inputs.length || !btn) { setTimeout(attach, 200); return; }

        const update = () => {
            if (lockedOut) return;
            btn.disabled = Array.from(inputs).some((input) => input.value.length === 0);
        };

        inputs.forEach((input) => {
            if (!input.dataset.loginToggleBound) {
                input.addEventListener("input", update);
                input.dataset.loginToggleBound = "1";
            }
        });
        update();
    }
    attach();
})();
