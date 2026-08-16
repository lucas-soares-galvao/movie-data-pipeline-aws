(function () {
    const doc = window.parent.document;

    function findConfirmCancelButton() {
        // "✕ Cancelar" (áudio) é distinto do "Cancelar" da busca (sem o ✕) —
        // evita clicar no botão errado se as duas telas coexistirem.
        return Array.from(doc.querySelectorAll("button")).find(
            (btn) => btn.textContent.includes("✕") && btn.textContent.includes("Cancelar")
        );
    }

    function findUseButton() {
        return Array.from(doc.querySelectorAll("button")).find(
            (btn) => btn.textContent.includes("Usar gravação")
        );
    }

    // Clica no botão certo só uma vez por instância dele no DOM. Sem isso, o
    // poll de 250ms clicava repetidamente no mesmo <button> obsoleto até o
    // Streamlit terminar o round-trip e re-renderizar (removendo os botões
    // escondidos) — múltiplos cliques sintéticos chegavam pro backend antes
    // do primeiro ser processado, derrubando o fluxo silenciosamente (a
    // gravação era descartada sem transcrever nem mostrar erro, reproduzido
    // via Playwright). O marcador fica no próprio elemento: como
    // audio_widget_seq muda a cada ciclo, o Streamlit sempre re-renderiza um
    // <button> novo sem o marcador, então o guard nunca trava um clique
    // legítimo futuro.
    function clickOnce(btn) {
        if (!btn || btn.dataset.filmbotClicked) return false;
        btn.dataset.filmbotClicked = "1";
        btn.click();
        return true;
    }

    function tick() {
        const stopBtn = doc.querySelector('[aria-label="Stop recording"]');
        let trash = doc.getElementById("audio-cancel-btn");

        if (stopBtn) {
            if (!trash) {
                trash = doc.createElement("button");
                trash.id = "audio-cancel-btn";
                trash.type = "button";
                trash.title = "Descartar gravação";
                trash.innerText = "✕";
                // 28x28 casa com o tamanho renderizado do botão nativo
                // (stAudioInputActionButton, ver recommendation.css) — medido via
                // inspeção real do DOM (Playwright); se o Streamlit mudar esse
                // tamanho num upgrade, ajustar aqui também.
                trash.style.cssText =
                    "margin-left:8px;width:28px;height:28px;border-radius:50%;border:none;" +
                    "background:rgba(248,113,113,0.15);color:#f87171;font-size:14px;font-weight:700;" +
                    "cursor:pointer;flex-shrink:0;" +
                    "display:flex;align-items:center;justify-content:center;padding:0;";
                trash.addEventListener("click", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    doc.querySelector('[aria-label="Stop recording"]')?.click();
                    window.localStorage.setItem("filmbot_audio_autocancel", "1");
                });
                // O botão nativo fica dentro de um <span> que vira "block" por ser
                // item flex (shrink-to-fit ao redor de um único botão) — inserir ali
                // dentro estoura a largura e quebra linha. Inserir depois desse <span>,
                // direto na div flex que organiza os botões em linha, mantém tudo lado a lado.
                (stopBtn.parentElement || stopBtn).insertAdjacentElement("afterend", trash);
            }
        } else if (trash) {
            trash.remove();
        }

        const wantsDiscard = window.localStorage.getItem("filmbot_audio_autocancel") === "1";
        if (wantsDiscard) {
            if (clickOnce(findConfirmCancelButton())) {
                window.localStorage.removeItem("filmbot_audio_autocancel");
            }
        } else {
            // Botões de confirmação ficam escondidos via CSS (.st-key-audio-confirm-buttons) —
            // "Usar gravação" é a ação padrão, confirmada automaticamente aqui assim que aparece.
            clickOnce(findUseButton());
        }
    }

    setInterval(tick, 250);
})();
