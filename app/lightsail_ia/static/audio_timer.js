(function () {
    const doc = window.parent.document;
    const maxSeconds = __MAX_SECONDS__;

    // Timer nativo só entrega "MM:SS" (ou "HH:MM:SS" pra gravações bem
    // longas, sem uso aqui já que o limite é de segundos) — soma os campos
    // tratando o texto como base 60 em vez de fixar em 2 partes.
    function parseElapsedSeconds(text) {
        const parts = text.trim().split(":").map(Number);
        if (parts.some((n) => Number.isNaN(n))) return 0;
        return parts.reduce((acc, val) => acc * 60 + val, 0);
    }

    function tick() {
        const badge = doc.getElementById("audio-timer-badge");
        if (!badge) return;
        const maxLabel = badge.textContent.split(" / ")[1] || badge.textContent;
        const stopBtn = doc.querySelector('[aria-label="Stop recording"]');
        const nativeTime = doc.querySelector('[data-testid="stAudioInputWaveformTimeCode"]');
        const elapsedText = stopBtn && nativeTime ? nativeTime.textContent.trim() : "00:00";
        const next = `${elapsedText} / ${maxLabel}`;
        if (badge.textContent !== next) badge.textContent = next;

        // Para a gravação sozinha ao atingir o limite, em vez de depender da
        // pessoa perceber o badge e clicar em parar — audio_cancel_recording.js
        // já confirma "Usar gravação" automaticamente assim que o botão de
        // parar some, então isso só antecipa esse mesmo fluxo (a validação de
        // duração em transcribe_preference() continua como rede de segurança,
        // já que esse polling de 250ms pode deixar passar um pouquinho além
        // do limite antes de clicar).
        if (stopBtn && parseElapsedSeconds(elapsedText) >= maxSeconds) {
            stopBtn.click();
        }
    }

    setInterval(tick, 250);
})();
