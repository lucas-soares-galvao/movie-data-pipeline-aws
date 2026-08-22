(function () {
    const doc = window.parent.document;
    const passwordKey = "__PASSWORD_KEY__";
    const confirmKey = "__CONFIRM_KEY__";
    const buttonKey = "__BUTTON_KEY__";

    // Mesma política de infra/lightsail_ia.tf (aws_cognito_user_pool.filmbot.password_policy)
    // + teto de 16 caracteres (regra só do app — Cognito não impõe máximo). Espelha
    // _validate_password em login.py, que continua a fonte de verdade: este script só
    // antecipa o feedback antes do submit, a chamada ao Cognito valida de novo.
    function passwordValid(value) {
        return (
            value.length >= 8 &&
            value.length <= 16 &&
            /[a-z]/.test(value) &&
            /[A-Z]/.test(value) &&
            /\d/.test(value) &&
            /[^\w\s]/.test(value)
        );
    }

    function attach() {
        const password = doc.querySelector(`.st-key-${passwordKey} input`);
        const confirm = doc.querySelector(`.st-key-${confirmKey} input`);
        const btn = doc.querySelector(`.st-key-${buttonKey} button`);
        // Generalizado para N campos (cadastro: nome+e-mail+senha+confirmar; redefinir
        // senha: código+senha+confirmar), mesmo racional de login_button_toggle.js — só
        // existe um formulário visível por vez.
        const inputs = doc.querySelectorAll('[data-testid="stTextInput"] input');
        if (!password || !confirm || !btn || !inputs.length) { setTimeout(attach, 200); return; }

        const update = () => {
            confirm.classList.remove("password-match", "password-mismatch");
            const matches = confirm.value.length > 0 && confirm.value === password.value;
            if (confirm.value.length > 0) {
                confirm.classList.add(matches ? "password-match" : "password-mismatch");
            }
            const allFilled = Array.from(inputs).every((input) => input.value.length > 0);
            btn.disabled = !(allFilled && matches && passwordValid(password.value));
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
