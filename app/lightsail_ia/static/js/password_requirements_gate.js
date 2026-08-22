(function () {
    const doc = window.parent.document;
    const passwordKey = "__PASSWORD_KEY__";
    const confirmKey = "__CONFIRM_KEY__";
    const buttonKey = "__BUTTON_KEY__";

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
        // Generalizado para N campos (cadastro: nome+e-mail+senha+confirmar; redefinir
        // senha: código+senha+confirmar), mesmo racional de login_button_toggle.js — só
        // existe um formulário visível por vez.
        const inputs = doc.querySelectorAll('[data-testid="stTextInput"] input');
        if (!password || !confirm || !btn || !requirements || !inputs.length) {
            setTimeout(attach, 200);
            return;
        }

        const update = () => {
            confirm.classList.remove("password-match", "password-mismatch");
            const matches = confirm.value.length > 0 && confirm.value === password.value;
            if (confirm.value.length > 0) {
                confirm.classList.add(matches ? "password-match" : "password-mismatch");
            }
            const allFilled = Array.from(inputs).every((input) => input.value.length > 0);
            btn.disabled = !(allFilled && matches && passwordValid(password.value));

            const typed = password.value.length > 0;
            CRITERIA.forEach(({ key, test }) => {
                const item = requirements.querySelector(`li[data-req="${key}"]`);
                const iconEl = item.querySelector(".req-icon");
                item.classList.remove("req-met", "req-unmet");
                if (!typed) {
                    iconEl.textContent = "•";
                    return;
                }
                const met = test(password.value);
                item.classList.add(met ? "req-met" : "req-unmet");
                iconEl.textContent = met ? "✓" : "✗";
            });
        };

        inputs.forEach((input) => {
            if (!input.dataset.passwordGateBound) {
                input.addEventListener("input", update);
                input.dataset.passwordGateBound = "1";
            }
        });
        update();
    }
    attach();
})();
