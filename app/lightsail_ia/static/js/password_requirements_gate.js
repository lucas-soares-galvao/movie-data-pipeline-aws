(function () {
    const doc = window.parent.document;
    const passwordKey = "__PASSWORD_KEY__";
    const confirmKey = "__CONFIRM_KEY__";
    const buttonKey = "__BUTTON_KEY__";
    const emailKey = "__EMAIL_KEY__";
    // Mesmo motivo do "lockedOut" em login_button_toggle.js: se a Python já computou
    // disabled=True por bloqueio de tentativas de código incorreto (não por campo vazio ou
    // senha inválida), o JS nunca deve reabilitar o botão via digitação — só o rerun
    // seguinte (quando o bloqueio já não se aplicar) manda esse valor atualizado.
    const lockedOut = __LOCKED_OUT__;

    // Mesma regex de _EMAIL_RE em login.py, que continua a fonte de verdade — este
    // script só antecipa a borda verde/vermelha antes do submit.
    const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

    // Mesma política de infra/lightsail_ia.tf (aws_cognito_user_pool.filmbot.password_policy)
    // + teto de 16 caracteres (regra só do app — Cognito não impõe máximo). Espelha
    // _validate_password em login.py, que continua a fonte de verdade: este script só
    // antecipa o feedback antes do submit, a chamada ao Cognito valida de novo. Nomeados
    // por `key` (casam com os data-req="..." de render_password_requirements() em
    // components.py) em vez de um só booleano encadeado, pra dar o ✓/✗ por critério.
    const CRITERIA = [
        { key: "length", test: (v) => v.length >= 8 && v.length <= 16 },
        { key: "lower", test: (v) => /[a-z]/.test(v) },
        { key: "upper", test: (v) => /[A-Z]/.test(v) },
        { key: "number", test: (v) => /\d/.test(v) },
        { key: "symbol", test: (v) => /[^\w\s]/.test(v) },
    ];
    function passwordValid(value) {
        return CRITERIA.every((c) => c.test(value));
    }

    function attach() {
        const password = doc.querySelector(`.st-key-${passwordKey} input`);
        const confirm = doc.querySelector(`.st-key-${confirmKey} input`);
        const btn = doc.querySelector(`.st-key-${buttonKey} button`);
        const requirements = doc.getElementById("password-requirements");
        // Só a tela de cadastro passa emailKey (redefinir senha não tem campo de e-mail
        // digitado — o e-mail já foi confirmado no passo anterior).
        const email = emailKey ? doc.querySelector(`.st-key-${emailKey} input`) : null;
        // Generalizado para N campos (cadastro: nome+e-mail+senha+confirmar; redefinir
        // senha: código+senha+confirmar), mesmo racional de login_button_toggle.js — só
        // existe um formulário visível por vez.
        const inputs = doc.querySelectorAll('[data-testid="stTextInput"] input');
        if (!password || !confirm || !btn || !requirements || (emailKey && !email) || !inputs.length) {
            setTimeout(attach, 200);
            return;
        }

        const update = () => {
            if (lockedOut) return;
            confirm.classList.remove("password-match", "password-mismatch");
            const matches = confirm.value.length > 0 && confirm.value === password.value;
            if (confirm.value.length > 0) {
                confirm.classList.add(matches ? "password-match" : "password-mismatch");
            }
            let emailValid = true;
            if (email) {
                email.classList.remove("email-valid", "email-invalid");
                emailValid = EMAIL_RE.test(email.value);
                if (email.value.length > 0) {
                    email.classList.add(emailValid ? "email-valid" : "email-invalid");
                }
            }
            const allFilled = Array.from(inputs).every((input) => input.value.length > 0);
            btn.disabled = !(allFilled && matches && passwordValid(password.value) && emailValid);

            const setReqState = (key, neutral, met) => {
                const item = requirements.querySelector(`li[data-req="${key}"]`);
                const iconEl = item.querySelector(".req-icon");
                item.classList.remove("req-met", "req-unmet");
                if (neutral) {
                    iconEl.textContent = "•";
                    return;
                }
                item.classList.add(met ? "req-met" : "req-unmet");
                iconEl.textContent = met ? "✓" : "✗";
            };

            const typed = password.value.length > 0;
            CRITERIA.forEach(({ key, test }) => {
                setReqState(key, !typed, test(password.value));
            });
            // Critério "match" reage aos dois campos (senha + confirmar), diferente dos
            // demais (só a senha) — por isso fica fora de CRITERIA, tratado à parte.
            setReqState("match", confirm.value.length === 0, matches);
        };

        // Reanexado a cada attach() sem guard — mesmo racional de login_button_toggle.js:
        // um guard baseado em dataset no nó persistido do input sobrevive entre reruns e
        // bloqueava o rebind quando o iframe (components.html, recriado a cada rerun) e o
        // listener antigo eram substituídos no meio de uma sequência de campos, travando o
        // botão no estado calculado no rerun anterior. update() é idempotente, então
        // listeners órfãos de iframes anteriores rodarem em paralelo é inofensivo.
        inputs.forEach((input) => {
            input.addEventListener("input", update);
        });
        update();
    }
    attach();
})();
