if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
        navigator.serviceWorker.register("/sw.js").catch(function () {
            /* Service worker non bloquant si refusé par le navigateur */
        });
    });
}
