(function () {
    const doc = window.parent.document;
    let remaining = __SECONDS__;

    function tick() {
        const el = doc.getElementById("__ELEMENT_ID__");
        if (!el) return;
        if (remaining <= 0) {
            el.textContent = "00:00";
            window.parent.location.reload();
            return;
        }
        const m = Math.floor(remaining / 60);
        const s = remaining % 60;
        el.textContent = String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
        remaining--;
    }

    tick();
    setInterval(tick, 1000);
})();
