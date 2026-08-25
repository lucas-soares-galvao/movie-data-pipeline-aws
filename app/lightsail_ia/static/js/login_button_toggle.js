(function () {
    const doc = window.parent.document;
    // Mesmo motivo do "rateLimited" em contador_caracteres.js: se a Python já
    // computou disabled=True por bloqueio de tentativas (não por campo vazio),
    // o JS nunca deve reabilitar o botão via digitação — só o rerun seguinte
    // (quando o bloqueio já não se aplicar) manda de novo com esse valor
    // atualizado.
    const lockedOut = __LOCKED_OUT__;
    const buttonKey = "__BUTTON_KEY__";
    const emailKey = "__EMAIL_KEY__";

    // Mesma regex de _EMAIL_RE em login.py, que continua a fonte de verdade — este
    // script só antecipa a borda verde/vermelha antes do submit. Só a tela de
    // "esqueci a senha" passa emailKey (login não precisa: formato inválido já
    // falha na autenticação normalmente).
    const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

    function attach() {
        // Generalizado para N campos (login: e-mail+senha, cadastro: nome+e-mail+
        // senha+confirmar, esqueci senha: variável) — todos os stTextInput visíveis
        // precisam estar preenchidos, não só o primeiro. Só existe um formulário
        // visível por vez (render_login troca de view via st.session_state e chama
        // st.stop() logo depois), então "todos os inputs da página" == "todos os
        // inputs deste formulário".
        const inputs = doc.querySelectorAll('[data-testid="stTextInput"] input');
        const btn = doc.querySelector(`.st-key-${buttonKey} button`);
        const email = emailKey ? doc.querySelector(`.st-key-${emailKey} input`) : null;
        if (!inputs.length || !btn || (emailKey && !email)) { setTimeout(attach, 200); return; }

        const update = () => {
            if (lockedOut) return;
            let emailValid = true;
            if (email) {
                email.classList.remove("email-valid", "email-invalid");
                emailValid = EMAIL_RE.test(email.value);
                if (email.value.length > 0) {
                    email.classList.add(emailValid ? "email-valid" : "email-invalid");
                }
            }
            const allFilled = Array.from(inputs).every((input) => input.value.length > 0);
            btn.disabled = !(allFilled && emailValid);
        };

        // Reanexado a cada attach() (novo iframe injetado pelo components.html a cada
        // rerun do Streamlit), sem guard de "já anexado" — um guard baseado em dataset no
        // nó persistido do input sobrevive entre reruns e bloqueava o rebind quando o
        // iframe (e o listener antigo, funcional) era substituído no meio de uma sequência
        // como "digitar e-mail → tab → digitar senha", deixando o botão travado no estado
        // calculado no rerun anterior. update() é idempotente (só recalcula disabled/
        // classes a partir do valor atual dos campos), então listeners órfãos de iframes
        // anteriores rodarem em paralelo é inofensivo.
        inputs.forEach((input) => {
            input.addEventListener("input", update);
        });
        update();
    }
    attach();
})();
