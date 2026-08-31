(function () {
    const doc = window.parent.document;
    const win = window.parent;
    const STORAGE_KEY = "filmbot-theme";

    // Tema efetivo: escolha manual salva (localStorage) vence; sem escolha manual, segue
    // a preferência do SO/navegador (mesma fonte que a media query prefers-color-scheme
    // de theme.css usa, consultada aqui só para decidir qual ícone mostrar no botão).
    function effectiveTheme() {
        const stored = win.localStorage.getItem(STORAGE_KEY);
        if (stored === "light" || stored === "dark") return stored;
        return win.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }

    // Sem escolha manual salva, não seta o atributo — deixa a media query de theme.css
    // decidir sozinha (modo automático).
    function applyStoredTheme() {
        const stored = win.localStorage.getItem(STORAGE_KEY);
        if (stored === "light" || stored === "dark") {
            doc.documentElement.dataset.theme = stored;
        } else {
            delete doc.documentElement.dataset.theme;
        }
    }

    function syncButtonIcon(btn) {
        btn.dataset.effectiveTheme = effectiveTheme();
    }

    function bind(btn) {
        if (!btn || btn.dataset.themeToggleBound) return;
        btn.dataset.themeToggleBound = "1";
        btn.addEventListener("click", () => {
            const next = effectiveTheme() === "dark" ? "light" : "dark";
            win.localStorage.setItem(STORAGE_KEY, next);
            doc.documentElement.dataset.theme = next;
            syncButtonIcon(btn);
        });
    }

    // Loop de retentativa (mesmo padrão de scroll_lock.js): o botão é remontado a cada
    // rerun do Streamlit, então reaplica o tema salvo e regarante o binding do clique
    // (dataset.themeToggleBound evita duplicar o listener num botão que sobreviveu ao
    // rerun) a cada ciclo, indefinidamente.
    function attach() {
        applyStoredTheme();
        const btn = doc.getElementById("theme-toggle");
        if (btn) {
            bind(btn);
            syncButtonIcon(btn);
        }
        setTimeout(attach, 500);
    }
    attach();
})();
