(function () {
    const doc = window.parent.document;

    function tick() {
        const badge = doc.getElementById("audio-timer-badge");
        if (!badge) return;
        const maxLabel = badge.textContent.split(" / ")[1] || badge.textContent;
        const recording = doc.querySelector('[aria-label="Stop recording"]');
        const nativeTime = doc.querySelector('[data-testid="stAudioInputWaveformTimeCode"]');
        const elapsed = recording && nativeTime ? nativeTime.textContent.trim() : "00:00";
        const next = `${elapsed} / ${maxLabel}`;
        if (badge.textContent !== next) badge.textContent = next;
    }

    setInterval(tick, 250);
})();
