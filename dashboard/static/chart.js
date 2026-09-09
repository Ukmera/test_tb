/**
 * TradingView Lightweight Charts, Multi-Agent Pipeline & Playback Controller
 * Style institutionnel GPTHEIST DESK / Hyperliquid SMC
 */

let chart;
let candleSeries;
let trendlineSeries;
let currentMode = "live"; // "live" ou "playback"
let currentModel = "B";    // "A" (Scalp 1m) ou "B" (Structure MTF 5m)
let currentTimeframe = "5m";
let currentCoin = "SOL";    // Devise active visualisée sur le graphique (SOL pour Alpha Duo)
let currentActiveBasket = "alpha"; // Panier A/B testing actif (alpha, quad, core)
let allCandles = [];
let allTrades = [];
let currentPlaybackIndex = 0;
let isPlaying = false;
let playbackTimer = null;
let liveTimer = null;
let agentTimer = null;
let playbackSpeed = 1; // 1x = 300ms par bougie
let smcPriceLines = [];
let isSwitchingBasket = false;

const BASKET_SYMBOLS_MAP = {
    alpha: ["SOL", "SUI"],
    quad: ["BTC", "SOL", "MNT", "SUI"],
    core: ["BTC", "SOL"]
};

// État des calques de validation visuelle SMC
const smcLayers = {
    ob: true,
    fvg: true,
    swings: true,
    structure: true,
    range: true,
    ote: true,
    brackets: true
};

let lastSMCData = null;
let lastActiveTrade = null;

document.addEventListener("DOMContentLoaded", async () => {
    try {
        initChart();
    } catch (e) {
        console.error("Erreur initChart:", e);
    }

    try {
        await loadLiveStatus();
        await loadAgentsStatus();
        await loadPaperTradingStatus();
        await loadBacktestHistory();
        await loadNotificationStatus();
    } catch (e) {
        console.error("Erreur statut initial:", e);
    }

    // Démarrer par défaut en mode Live
    await switchMode("live");

    // Auto-refresh du statut, des agents et du paper trading toutes les 3 secondes
    setInterval(loadLiveStatus, 4000);
    setInterval(loadAgentsStatus, 3000);
    setInterval(loadPaperTradingStatus, 3000);

    // Initialiser les écouteurs d'événements
    setupEventListeners();
});



function initChart() {
    const chartContainer = document.getElementById("trading-chart");
    if (!chartContainer) return;

    if (typeof LightweightCharts === "undefined") {
        console.error("LightweightCharts non chargé !");
        return;
    }

    chartContainer.innerHTML = "";
    const isMobile = window.innerWidth <= 900;
    const width = chartContainer.clientWidth || (window.innerWidth - 360);
    const height = chartContainer.clientHeight || (isMobile ? 380 : 500);

    chart = LightweightCharts.createChart(chartContainer, {
        width: width,
        height: height,
        layout: {
            backgroundColor: "#131722",
            textColor: "#d1d4dc",
            fontSize: isMobile ? 11 : 12,
            fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        },
        grid: {
            vertLines: { color: "rgba(42, 46, 57, 0.4)" },
            horzLines: { color: "rgba(42, 46, 57, 0.4)" },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: "#242938",
            scaleMargins: {
                top: 0.1,
                bottom: 0.2,
            },
        },
        timeScale: {
            borderColor: "#242938",
            timeVisible: true,
            secondsVisible: false,
        },
        handleScroll: {
            mouseWheel: false,
            pressedMouseMove: true,
            horzTouchDrag: true,
            vertTouchDrag: !isMobile, // Permet le défilement vertical fluide de la page sur mobile
        },
        handleScale: {
            mouseWheel: false,
            pinch: true,
            axisPressedMouseMove: true,
            axisDoubleClickReset: true,
        },
    });

    const candleOptions = {
        upColor: "#00e676",
        downColor: "#ff3d71",
        borderVisible: false,
        wickUpColor: "#00e676",
        wickDownColor: "#ff3d71",
    };

    if (typeof chart.addCandlestickSeries === "function") {
        candleSeries = chart.addCandlestickSeries(candleOptions);
    } else if (typeof chart.addSeries === "function" && LightweightCharts.CandlestickSeries) {
        candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, candleOptions);
    }

    // Série de Trendline reliant les swings de structure de marché
    const lineOptions = {
        color: '#2962ff',
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
    };
    if (typeof chart.addLineSeries === "function") {
        trendlineSeries = chart.addLineSeries(lineOptions);
    } else if (typeof chart.addSeries === "function" && LightweightCharts.LineSeries) {
        trendlineSeries = chart.addSeries(LightweightCharts.LineSeries, lineOptions);
    }

    window.addEventListener("resize", () => {
        const chartCol = document.querySelector(".chart-column");
        const sidebar = document.querySelector(".sidebar");
        const isNowMobile = window.innerWidth <= 900;

        if (!isNowMobile) {
            if (chartCol) chartCol.style.display = "";
            if (sidebar) sidebar.style.display = "";
        }

        if (chart && chartContainer) {
            chart.applyOptions({
                width: chartContainer.clientWidth,
                height: chartContainer.clientHeight,
                handleScroll: {
                    mouseWheel: false,
                    pressedMouseMove: true,
                    horzTouchDrag: true,
                    vertTouchDrag: !isNowMobile,
                }
            });
        }
    });

    window.addEventListener("orientationchange", () => {
        setTimeout(() => {
            const chartContainer = document.getElementById("trading-chart");
            const isNowMobile = window.innerWidth <= 900;
            if (chart && chartContainer) {
                chart.applyOptions({
                    width: chartContainer.clientWidth,
                    height: chartContainer.clientHeight,
                    handleScroll: {
                        mouseWheel: false,
                        pressedMouseMove: true,
                        horzTouchDrag: true,
                        vertTouchDrag: !isNowMobile,
                    }
                });
                if (chart.timeScale) chart.timeScale().fitContent();
            }
        }, 150);
    });

    if (window.ResizeObserver && chartContainer) {
        const ro = new ResizeObserver(() => {
            if (chart && chartContainer.clientWidth > 40 && chartContainer.clientHeight > 40) {
                chart.applyOptions({
                    width: chartContainer.clientWidth,
                    height: chartContainer.clientHeight,
                });
            }
        });
        ro.observe(chartContainer);
    }
}

function setupEventListeners() {
    // 1. Boutons de mode : Live vs Playback
    const btnLive = document.getElementById("btn-mode-live");
    const btnPlayback = document.getElementById("btn-mode-playback");

    if (btnLive) btnLive.addEventListener("click", () => switchMode("live"));
    if (btnPlayback) btnPlayback.addEventListener("click", () => switchMode("playback"));

    // 2. Sélecteur de Modèle (Modèle A vs Modèle B)
    const btnModelA = document.getElementById("btn-model-a");
    const btnModelB = document.getElementById("btn-model-b");

    if (btnModelA) {
        btnModelA.addEventListener("click", async () => {
            btnModelA.classList.add("active");
            btnModelB.classList.remove("active");
            currentModel = "A";
            console.log("[Model Switch] Activation Modèle A (Fast Scalping 1m)");
            try { fetch("/api/paper-trading/model?model=A", { method: "POST" }); } catch (e) {}
            const btn1m = document.querySelector('.btn-tf[data-tf="1m"]');
            if (btn1m) btn1m.click();
        });
    }

    if (btnModelB) {
        btnModelB.addEventListener("click", async () => {
            btnModelB.classList.add("active");
            btnModelA.classList.remove("active");
            currentModel = "B";
            console.log("[Model Switch] Activation Modèle B (Structure MTF 5m / Bias 1h)");
            try { fetch("/api/paper-trading/model?model=B", { method: "POST" }); } catch (e) {}
            const btn5m = document.querySelector('.btn-tf[data-tf="5m"]');
            if (btn5m) btn5m.click();
        });
    }

    // 2b. Bouton d'activation / pause du Paper Trading en direct
    const btnTogglePaper = document.getElementById("btn-toggle-paper");
    if (btnTogglePaper) {
        btnTogglePaper.addEventListener("click", async () => {
            try {
                const resp = await fetch("/api/paper-trading/toggle", { method: "POST" });
                const res = await resp.json();
                console.log("[Paper Trading Toggle] État:", res);
                await loadPaperTradingStatus();
            } catch (e) {
                console.error("Erreur toggle paper:", e);
            }
        });
    }

    // 3. Onglets de la barre latérale (Activity vs Trades vs Bilans Histo)
    const tabActivity = document.getElementById("tab-btn-activity");
    const tabTrades = document.getElementById("tab-btn-trades");
    const tabHistory = document.getElementById("tab-btn-history");
    const panelActivity = document.getElementById("panel-activity-log");
    const panelTrades = document.getElementById("panel-trades");
    const panelHistory = document.getElementById("panel-history");

    function selectSidebarTab(activeTab, activePanel) {
        [tabActivity, tabTrades, tabHistory].forEach(t => t && t.classList.remove("active"));
        [panelActivity, panelTrades, panelHistory].forEach(p => p && p.classList.remove("active"));
        if (activeTab) activeTab.classList.add("active");
        if (activePanel) activePanel.classList.add("active");
    }

    if (tabActivity) tabActivity.addEventListener("click", () => selectSidebarTab(tabActivity, panelActivity));
    if (tabTrades) tabTrades.addEventListener("click", () => selectSidebarTab(tabTrades, panelTrades));
    if (tabHistory) {
        tabHistory.addEventListener("click", () => {
            selectSidebarTab(tabHistory, panelHistory);
            loadBacktestHistory();
        });
    }

    const btnRefreshHistory = document.getElementById("btn-refresh-history");
    if (btnRefreshHistory) {
        btnRefreshHistory.addEventListener("click", loadBacktestHistory);
    }

    // 3b. Toggles des Calques Visuels SMC (OB, FVG, Swings, BOS/CHoCH, Range, OTE, Brackets)
    const layerCheckboxes = {
        ob: document.getElementById("toggle-layer-ob"),
        fvg: document.getElementById("toggle-layer-fvg"),
        swings: document.getElementById("toggle-layer-swings"),
        structure: document.getElementById("toggle-layer-structure"),
        range: document.getElementById("toggle-layer-range"),
        ote: document.getElementById("toggle-layer-ote"),
        brackets: document.getElementById("toggle-layer-brackets")
    };

    Object.keys(layerCheckboxes).forEach(key => {
        const el = layerCheckboxes[key];
        if (el) {
            el.addEventListener("change", (e) => {
                smcLayers[key] = e.target.checked;
                refreshActiveLayers();
            });
        }
    });

    // 4. Boutons de Timeframe (1m, 3m, 5m, 15m, 1h)
    document.querySelectorAll(".btn-tf").forEach(btn => {
        btn.addEventListener("click", async (e) => {
            const targetBtn = e.currentTarget || btn;
            document.querySelectorAll(".btn-tf").forEach(b => b.classList.remove("active"));
            targetBtn.classList.add("active");
            currentTimeframe = targetBtn.getAttribute("data-tf") || "5m";
            console.log(`[Timeframe Switch] Passage en ${currentTimeframe}`);

            const overlay = document.getElementById("overlay-ohlc");
            if (overlay) {
                overlay.innerHTML = `<strong>${currentCoin}/USDC</strong> <span style="color:#00d2ff; font-weight:700;">${currentTimeframe.toUpperCase()}</span> &nbsp;|&nbsp; Chargement des flux...`;
            }

            if (currentMode === "live") {
                await loadLiveCandles(true);
            } else {
                const btnRun = document.getElementById("btn-run-backtest");
                if (btnRun) btnRun.click();
            }
        });
    });

    // 4a. Clic sur les pills de stratégie des cartes paniers (⚡ M1, 📊 M5, 🏛 M15)
    document.querySelectorAll(".strat-pill").forEach(pill => {
        pill.addEventListener("click", (e) => {
            e.stopPropagation();
            const id = pill.id || "";
            let tf = "5m";
            if (id.includes("scalp")) {
                tf = id.includes("quad") ? "3m" : "1m";
            } else if (id.includes("intraday")) {
                tf = "5m";
            } else if (id.includes("day")) {
                tf = "15m";
            }
            const parts = id.split("-");
            if (parts.length >= 4) {
                const bKey = parts[2];
                const sKey = parts[3];
                fetch(`/api/paper-trading/strategy?basket=${bKey}&strategy=${sKey}`, { method: "POST" })
                    .then(() => loadPaperTradingStatus())
                    .catch(err => console.error("Erreur switch strategy:", err));
            }
            const tfBtn = document.querySelector(`.btn-tf[data-tf="${tf}"]`);
            if (tfBtn) tfBtn.click();
        });
    });

    // 4b. Sélecteur de vues institutionnelles (Paper Trading, Live, Backtest, Agents)
    document.querySelectorAll(".view-tab-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const targetBtn = e.currentTarget || btn;
            const view = targetBtn.getAttribute("data-view");
            if (view) switchMainView(view);
        });
    });

    // 4c. Mode Plein Écran pour le graphique TradingView
    const btnFullscreen = document.getElementById("btn-fullscreen-chart");
    const btnExitFs = document.getElementById("btn-exit-fullscreen");
    const chartCol = document.querySelector(".chart-column");

    function setFullscreenMode(enable) {
        if (!chartCol) return;
        if (enable) {
            chartCol.classList.add("fullscreen-mode");
        } else {
            chartCol.classList.remove("fullscreen-mode");
        }
        const isFs = chartCol.classList.contains("fullscreen-mode");
        if (btnFullscreen) btnFullscreen.textContent = isFs ? "✕ Quitter Plein Écran" : "⛶ Plein Écran";
        if (chart) {
            const chartContainer = document.getElementById("trading-chart");
            setTimeout(() => {
                const isMobileScreen = window.innerWidth <= 900;
                chart.applyOptions({
                    width: chartContainer.clientWidth,
                    height: chartContainer.clientHeight,
                    handleScroll: {
                        mouseWheel: isFs,
                        pressedMouseMove: true,
                        horzTouchDrag: true,
                        vertTouchDrag: isFs || !isMobileScreen,
                    },
                    handleScale: {
                        mouseWheel: isFs,
                        pinch: true,
                        axisPressedMouseMove: true,
                        axisDoubleClickReset: true
                    }
                });
                if (chart.timeScale) chart.timeScale().fitContent();
            }, 100);
        }
    }

    if (btnFullscreen && chartCol) {
        btnFullscreen.addEventListener("click", () => {
            const isCurrentlyFs = chartCol.classList.contains("fullscreen-mode");
            setFullscreenMode(!isCurrentlyFs);
        });
    }

    if (btnExitFs && chartCol) {
        btnExitFs.addEventListener("click", () => {
            setFullscreenMode(false);
        });
    }

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && chartCol && chartCol.classList.contains("fullscreen-mode")) {
            setFullscreenMode(false);
        }
    });

    // 4d. Toggle de l'Inspecteur SMC Quant (Masqué par défaut)
    const toggleInsp = document.getElementById("toggle-layer-inspector");
    const hudInsp = document.getElementById("smc-inspector-hud");
    const btnCloseInsp = document.getElementById("btn-close-inspector");
    if (toggleInsp && hudInsp) {
        toggleInsp.addEventListener("change", (e) => {
            hudInsp.style.display = e.target.checked ? "block" : "none";
        });
    }
    if (btnCloseInsp && hudInsp && toggleInsp) {
        btnCloseInsp.addEventListener("click", () => {
            hudInsp.style.display = "none";
            toggleInsp.checked = false;
        });
    }

    // 5. Contrôles Playback
    const btnPlay = document.getElementById("btn-play");
    if (btnPlay) btnPlay.addEventListener("click", togglePlay);

    const btnStepFwd = document.getElementById("btn-step-fwd");
    if (btnStepFwd) btnStepFwd.addEventListener("click", stepForward);

    const btnStepBack = document.getElementById("btn-step-back");
    if (btnStepBack) btnStepBack.addEventListener("click", stepBackward);

    const speedSelect = document.getElementById("speed-select");
    if (speedSelect) {
        speedSelect.addEventListener("change", (e) => {
            playbackSpeed = parseFloat(e.target.value);
            if (isPlaying) {
                pausePlayback();
                startPlayback();
            }
        });
    }

    const scrubber = document.getElementById("timeline-scrubber");
    if (scrubber) {
        scrubber.addEventListener("input", (e) => {
            pausePlayback();
            goToIndex(parseInt(e.target.value, 10));
        });
    }

    // 6. Sélecteur de période / date de départ pour le playback
    const rangeSelect = document.getElementById("select-playback-range");
    const customDateInput = document.getElementById("input-custom-date");

    if (rangeSelect) {
        rangeSelect.addEventListener("change", async (e) => {
            if (e.target.value === "custom") {
                if (customDateInput) customDateInput.style.display = "inline-block";
            } else {
                if (customDateInput) customDateInput.style.display = "none";
                await triggerCustomBacktest();
            }
        });
    }

    if (customDateInput) {
        customDateInput.addEventListener("change", async () => {
            if (customDateInput.value) {
                await triggerCustomBacktest();
            }
        });
    }

    // 7. Bouton Relancer Backtest (avec choix du volume de bougies 1k, 3k, 5k)
    const btnRun = document.getElementById("btn-run-backtest");
    if (btnRun) {
        btnRun.addEventListener("click", triggerCustomBacktest);
    }

    // 8. Modules d'interactions & Responsive
    setupTelegramModalListeners();
    setupAgentDeckToggle();
    setupMobileNavigation();
}

async function triggerCustomBacktest() {
    const btnRun = document.getElementById("btn-run-backtest");
    const candleSelect = document.getElementById("select-backtest-candles");
    const targetCandles = candleSelect ? candleSelect.value : "3000";

    if (btnRun) btnRun.textContent = `⏳ Stress-Test (${targetCandles} bars)...`;

    const rangeSelect = document.getElementById("select-playback-range");
    const customDateInput = document.getElementById("input-custom-date");

    let queryParams = `coin=BTC&interval=${currentTimeframe}&model=${currentModel}&limit=${targetCandles}`;
    if (rangeSelect) {
        if (rangeSelect.value === "custom" && customDateInput && customDateInput.value) {
            queryParams += `&start_date=${customDateInput.value}`;
        }
    }

    try {
        const resp = await fetch(`/api/run-backtest?${queryParams}`, { method: "POST" });
        const data = await resp.json();
        console.log(`[Backtest ${currentTimeframe} - Modèle ${currentModel}] Terminé:`, data);
        await switchMode("playback");
        await loadBacktestHistory();
        const tabHistory = document.getElementById("tab-btn-history");
        if (tabHistory) tabHistory.click();
    } catch (e) {
        alert("Erreur lors de l'exécution du backtest: " + e);
    } finally {
        if (btnRun) btnRun.textContent = "⚡ Lancer Stress-Test";
    }
}


async function switchMode(mode) {
    currentMode = mode;
    const btnLive = document.getElementById("btn-mode-live");
    const btnPlayback = document.getElementById("btn-mode-playback");
    const playbackBar = document.getElementById("playback-bar");
    const liveStatusBar = document.getElementById("live-status-bar");

    if (mode === "live") {
        if (btnLive) btnLive.classList.add("active");
        if (btnPlayback) btnPlayback.classList.remove("active");
        if (playbackBar) playbackBar.style.display = "none";
        if (liveStatusBar) liveStatusBar.style.display = "flex";

        pausePlayback();
        await loadLiveCandles(true);

        // Actualisation automatique du flux direct toutes les 3s
        if (!liveTimer) {
            liveTimer = setInterval(loadLiveCandles, 3000);
        }
    } else {
        if (btnPlayback) btnPlayback.classList.add("active");
        if (btnLive) btnLive.classList.remove("active");
        if (playbackBar) playbackBar.style.display = "flex";
        if (liveStatusBar) liveStatusBar.style.display = "none";

        if (liveTimer) {
            clearInterval(liveTimer);
            liveTimer = null;
        }

        await loadBacktestForPlayback();
    }
}

async function switchMainView(view) {
    currentActiveView = view;
    document.querySelectorAll(".view-tab-btn").forEach(b => {
        b.classList.toggle("active", b.getAttribute("data-view") === view);
    });

    const basketRibbon = document.getElementById("basket-ribbon");
    const playbackBar = document.getElementById("playback-bar");
    const backtestActions = document.getElementById("ribbon-backtest-actions");
    const liveStatusBar = document.getElementById("live-status-bar");
    const chartCol = document.querySelector(".chart-column");
    const sidebar = document.querySelector(".sidebar");
    const agentDeck = document.getElementById("agent-deck-container");

    if (view === "paper") {
        if (basketRibbon) basketRibbon.style.display = "flex";
        if (playbackBar) playbackBar.style.display = "none";
        if (backtestActions) backtestActions.style.display = "none";
        if (liveStatusBar) liveStatusBar.style.display = "flex";
        if (chartCol) chartCol.style.display = "flex";
        if (sidebar) sidebar.style.display = "flex";
        if (agentDeck) agentDeck.style.display = "flex";
        await switchMode("live");
    } else if (view === "live") {
        if (basketRibbon) basketRibbon.style.display = "none";
        if (playbackBar) playbackBar.style.display = "none";
        if (backtestActions) backtestActions.style.display = "none";
        if (liveStatusBar) liveStatusBar.style.display = "flex";
        if (chartCol) chartCol.style.display = "flex";
        if (sidebar) sidebar.style.display = "flex";
        if (agentDeck) agentDeck.style.display = "flex";
        await switchMode("live");
    } else if (view === "backtest") {
        if (basketRibbon) basketRibbon.style.display = "none";
        if (playbackBar) playbackBar.style.display = "flex";
        if (backtestActions) backtestActions.style.display = "flex";
        if (liveStatusBar) liveStatusBar.style.display = "none";
        if (chartCol) chartCol.style.display = "flex";
        if (sidebar) sidebar.style.display = "flex";
        if (agentDeck) agentDeck.style.display = "none";
        const tabHist = document.getElementById("tab-btn-history");
        if (tabHist) tabHist.click();
        await switchMode("playback");
    } else if (view === "agents") {
        if (basketRibbon) basketRibbon.style.display = "none";
        if (playbackBar) playbackBar.style.display = "none";
        if (backtestActions) backtestActions.style.display = "none";
        if (chartCol) chartCol.style.display = "flex";
        if (sidebar) sidebar.style.display = "flex";
        if (agentDeck) {
            agentDeck.style.display = "flex";
            agentDeck.classList.remove("collapsed");
            agentDeck.scrollIntoView({ behavior: "smooth" });
        }
        const tabAct = document.getElementById("tab-btn-activity");
        if (tabAct) tabAct.click();
    }

    setTimeout(() => {
        if (chart) {
            const chartContainer = document.getElementById("trading-chart");
            if (chartContainer) {
                chart.applyOptions({
                    width: chartContainer.clientWidth,
                    height: chartContainer.clientHeight,
                });
                if (chart.timeScale) chart.timeScale().fitContent();
            }
        }
    }, 100);
}
window.switchMainView = switchMainView;

let candleAbortController = null;

function updateCoinPills(symbols) {
    const container = document.getElementById("coin-pills-container");
    if (!container || !symbols || !symbols.length) return;
    container.innerHTML = "";
    symbols.forEach(sym => {
        const btn = document.createElement("button");
        btn.className = `btn btn-coin ${sym === currentCoin ? 'active' : ''}`;
        btn.setAttribute("data-coin", sym);
        btn.textContent = sym;
        btn.addEventListener("click", () => {
            currentCoin = sym;
            document.querySelectorAll(".btn-coin").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            loadLiveCandles(true, sym);
        });
        container.appendChild(btn);
    });
}

async function loadLiveCandles(fit = false, coinOverride = null) {
    if (currentMode !== "live") return;
    const coin = coinOverride || currentCoin || "SOL";
    currentCoin = coin;

    document.querySelectorAll(".btn-coin").forEach(b => {
        b.classList.toggle("active", b.getAttribute("data-coin") === coin);
    });

    if (candleAbortController) {
        candleAbortController.abort();
    }
    candleAbortController = new AbortController();

    try {
        const resp = await fetch(`/api/candles?coin=${coin}&interval=${currentTimeframe}&limit=250`, {
            signal: candleAbortController.signal
        });
        if (!resp.ok) return;
        const data = await resp.json();

        if (!data || !data.candles || !data.candles.length) return;

        candleSeries.setData(data.candles);

        // Afficher les composants SMC selon les calques actifs
        renderSMCLayers(data.smc, null);

        // Mise à jour de l'overlay OHLC
        const last = data.candles[data.candles.length - 1];
        const overlay = document.getElementById("overlay-ohlc");
        if (overlay) {
            overlay.innerHTML = `
                <strong>${coin}/USDC</strong> <span style="color:#00d2ff; font-weight:700;">${currentTimeframe.toUpperCase()}</span> (Direct HL) &nbsp;|&nbsp; 
                O: <span style="color:#d1d4dc">${last.open}</span> 
                H: <span style="color:#00e676">${last.high}</span> 
                L: <span style="color:#ff3d71">${last.low}</span> 
                C: <span style="color:#d1d4dc">${last.close}</span> &nbsp;|&nbsp;
                Biais: <span style="color:${data.smc.trend === 'BULLISH' ? '#00e676' : (data.smc.trend === 'BEARISH' ? '#ff3d71' : '#848e9c')}">${data.smc.trend}</span>
            `;
        }

        const badgeSym = document.getElementById("badge-active-symbol");
        if (badgeSym) badgeSym.textContent = coin;

        // Mise à jour du biais HTF dans le Header HUD
        const htfElem = document.getElementById("hud-htf-bias");
        if (htfElem && data.smc) {
            const htfVal = data.smc.htf_trend || data.smc.trend || "NEUTRAL";
            const icon = htfVal === "BULLISH" ? "🟢" : (htfVal === "BEARISH" ? "🔴" : "⚪");
            htfElem.textContent = `1H ${htfVal} ${icon}`;
            htfElem.style.color = htfVal === "BULLISH" ? "#00e676" : (htfVal === "BEARISH" ? "#ff3d71" : "#848e9c");
        }

        const infoElem = document.getElementById("live-candle-info");
        if (infoElem) {
            const nowTime = new Date().toLocaleTimeString("fr-FR");
            infoElem.textContent = `Dernière bougie : ${nowTime} (${data.candles.length} bougies ${currentTimeframe} chargées)`;
        }

        if (fit && chart && chart.timeScale) {
            chart.timeScale().fitContent();
        }
    } catch (e) {
        if (e.name !== "AbortError") {
            console.error("Erreur chargement live candles:", e);
        }
    }
}

function renderSMCLayers(smcData, activeTrade = null) {
    if (smcData) lastSMCData = smcData;
    if (activeTrade !== undefined) lastActiveTrade = activeTrade;

    const smc = lastSMCData;
    const trade = lastActiveTrade;

    // Supprimer les anciennes lignes de prix SMC
    if (smcPriceLines && smcPriceLines.length) {
        smcPriceLines.forEach(line => {
            try { candleSeries.removePriceLine(line); } catch (e) {}
        });
        smcPriceLines = [];
    }

    const markers = [];

    if (smc) {
        // A. ORDER BLOCKS
        if (smcLayers.ob && smc.order_blocks) {
            const activeOBs = smc.order_blocks.filter(ob => !ob.mitigated);
            activeOBs.forEach(ob => {
                markers.push({
                    time: ob.time,
                    position: ob.is_bullish ? "belowBar" : "aboveBar",
                    color: ob.is_bullish ? "#00e676" : "#ff3d71",
                    shape: "square",
                    text: `${ob.is_bullish ? 'Bull' : 'Bear'} OB [${ob.bottom.toFixed(0)}-${ob.top.toFixed(0)}]`
                });
            });

            activeOBs.slice(-2).forEach(ob => {
                try {
                    const obColor = ob.is_bullish ? "#00e676" : "#ff3d71";
                    const topLine = candleSeries.createPriceLine({
                        price: ob.top,
                        color: obColor,
                        lineWidth: 1,
                        lineStyle: LightweightCharts.LineStyle.Dotted,
                        axisLabelVisible: true,
                        title: `${ob.is_bullish ? 'Bull' : 'Bear'} OB Top`
                    });
                    const botLine = candleSeries.createPriceLine({
                        price: ob.bottom,
                        color: obColor,
                        lineWidth: 1,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title: `${ob.is_bullish ? 'Bull' : 'Bear'} OB Bot`
                    });
                    smcPriceLines.push(topLine, botLine);
                } catch (err) {}
            });
        }

        // B. FAIR VALUE GAPS (FVG + 50% CE)
        if (smcLayers.fvg && smc.fvgs) {
            const activeFVGs = smc.fvgs.filter(f => !f.mitigated);
            activeFVGs.slice(-3).forEach(fvg => {
                try {
                    const midPrice = fvg.consequent_encroachment || ((fvg.top + fvg.bottom) / 2.0);
                    const fvgLine = candleSeries.createPriceLine({
                        price: midPrice,
                        color: "#ffb000",
                        lineWidth: 1,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title: `FVG 50% CE (${fvg.is_bullish ? 'Bull' : 'Bear'})`
                    });
                    smcPriceLines.push(fvgLine);

                    markers.push({
                        time: fvg.time,
                        position: fvg.is_bullish ? "belowBar" : "aboveBar",
                        color: "#ffb000",
                        shape: "circle",
                        text: `FVG ${fvg.is_bullish ? 'Bull' : 'Bear'} (50% CE: ${midPrice.toFixed(0)})`
                    });
                } catch (err) {}
            });
        }

        // C. SWINGS & TRENDLINES
        if (smc.swings && smc.swings.length) {
            if (smcLayers.swings) {
                smc.swings.slice(-10).forEach(s => {
                    markers.push({
                        time: s.time,
                        position: s.is_high ? "aboveBar" : "belowBar",
                        color: "#2962ff",
                        shape: s.is_high ? "arrowDown" : "arrowUp",
                        text: `${s.is_high ? 'Swing H' : 'Swing L'} $${s.price.toFixed(0)}`
                    });
                });

                if (trendlineSeries) {
                    const uniqueSwings = [];
                    const seenTimes = new Set();
                    [...smc.swings].sort((a, b) => a.time - b.time).forEach(s => {
                        if (s && typeof s.time === "number" && !seenTimes.has(s.time)) {
                            seenTimes.add(s.time);
                            uniqueSwings.push({
                                time: s.time,
                                value: s.price
                            });
                        }
                    });
                    try {
                        trendlineSeries.setData(uniqueSwings);
                    } catch (err) {
                        console.warn("Trendline setData error:", err);
                    }
                }
            } else {
                if (trendlineSeries) trendlineSeries.setData([]);
            }
        }

        // D. STRUCTURE DE MARCHÉ (BOS & CHOCH)
        if (smcLayers.structure && smc.structures) {
            smc.structures.forEach(st => {
                const isBos = st.type === "BOS";
                const isBull = st.direction === "BULLISH";
                markers.push({
                    time: st.time,
                    position: isBull ? "belowBar" : "aboveBar",
                    color: isBos ? "#ba68c8" : "#00d2ff",
                    shape: isBull ? "arrowUp" : "arrowDown",
                    text: `${st.type} ${isBull ? '↑' : '↓'} ($${st.level.toFixed(0)})`
                });
            });
        }

        // E. RANGE & EQUILIBRIUM 50%
        if (smcLayers.range && smc.range_info && smc.range_info.range_high) {
            const r = smc.range_info;
            try {
                const rHighLine = candleSeries.createPriceLine({
                    price: r.range_high,
                    color: "#00d2ff",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `Range High (Premium)`
                });
                const eqLine = candleSeries.createPriceLine({
                    price: r.equilibrium,
                    color: "#ffffff",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `Range Eq 50%`
                });
                const rLowLine = candleSeries.createPriceLine({
                    price: r.range_low,
                    color: "#00d2ff",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `Range Low (Discount)`
                });
                smcPriceLines.push(rHighLine, eqLine, rLowLine);
            } catch (err) {}
        }

        // F. FIBONACCI OTE (61.8%, 70.5% Sweet Spot, 79.0%)
        if (smcLayers.ote && smc.active_ote) {
            const ote = smc.active_ote;
            try {
                const f618 = candleSeries.createPriceLine({
                    price: ote.fib_618,
                    color: "#ff8a65",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `Fib 61.8%`
                });
                const f705 = candleSeries.createPriceLine({
                    price: ote.fib_705,
                    color: "#ffd700",
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Solid,
                    axisLabelVisible: true,
                    title: `OTE 70.5% SWEET SPOT`
                });
                const f790 = candleSeries.createPriceLine({
                    price: ote.fib_790,
                    color: "#ff8a65",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `Fib 79.0%`
                });
                smcPriceLines.push(f618, f705, f790);
            } catch (err) {}
        }
    }

    // G. TRADE BRACKETS & BREAKEVEN
    if (smcLayers.brackets) {
        if (trade) {
            try {
                const entryLine = candleSeries.createPriceLine({
                    price: trade.entry_price,
                    color: "#00d2ff",
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Solid,
                    axisLabelVisible: true,
                    title: `ENTRY ${trade.is_long ? 'BUY' : 'SELL'} @ $${trade.entry_price.toFixed(1)}`
                });
                const isBE = trade.be_activated;
                const slLine = candleSeries.createPriceLine({
                    price: trade.stop_loss,
                    color: isBE ? "#ffd700" : "#ff3d71",
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: isBE ? `🛡️ BREAKEVEN @ $${trade.stop_loss.toFixed(1)}` : `SL @ $${trade.stop_loss.toFixed(1)}`
                });
                const tpLine = candleSeries.createPriceLine({
                    price: trade.take_profit,
                    color: "#00e676",
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `TP2 (3R) @ $${trade.take_profit.toFixed(1)}`
                });
                smcPriceLines.push(entryLine, slLine, tpLine);
            } catch (err) {}
        } else if (smc && smc.setups && smc.setups.length) {
            const s = smc.setups[0];
            try {
                const entryLine = candleSeries.createPriceLine({
                    price: s.entry_price,
                    color: "#00d2ff",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `ORDRE LIMITE ${s.grade}`
                });
                const slLine = candleSeries.createPriceLine({
                    price: s.stop_loss,
                    color: "#ff3d71",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `SL Prévu`
                });
                const tp1Line = candleSeries.createPriceLine({
                    price: s.take_profit_1r,
                    color: "#00d2ff",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `TP1 (1R)`
                });
                const tp2Line = candleSeries.createPriceLine({
                    price: s.take_profit_2r,
                    color: "#00e676",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `TP2 (3R)`
                });
                smcPriceLines.push(entryLine, slLine, tp1Line, tp2Line);
            } catch (err) {}
        }
    }

    // Nettoyage et tri strict des markers pour Lightweight Charts
    const cleanMarkers = [];
    const seenMarkerKeys = new Set();
    markers.sort((a, b) => a.time - b.time).forEach(m => {
        if (m && typeof m.time === "number" && !isNaN(m.time)) {
            const key = `${m.time}_${m.text || ''}`;
            if (!seenMarkerKeys.has(key)) {
                seenMarkerKeys.add(key);
                cleanMarkers.push(m);
            }
        }
    });

    try {
        candleSeries.setMarkers(cleanMarkers);
    } catch (e) {
        console.warn("[Chart Warning] setMarkers error:", e);
    }

    updateSMCInspector(smc, trade);
}

function refreshActiveLayers() {
    renderSMCLayers(lastSMCData, lastActiveTrade);
}

function updateSMCInspector(smc, trade) {
    if (!smc) return;
    const trendBadge = document.getElementById("inspector-trend-badge");
    if (trendBadge && smc.trend) {
        trendBadge.textContent = smc.trend;
        trendBadge.style.color = smc.trend === "BULLISH" ? "#00e676" : (smc.trend === "BEARISH" ? "#ff3d71" : "#848e9c");
        trendBadge.style.background = smc.trend === "BULLISH" ? "rgba(0, 230, 118, 0.2)" : (smc.trend === "BEARISH" ? "rgba(255, 61, 113, 0.2)" : "rgba(132, 142, 156, 0.2)");
    }

    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    };

    setVal("insp-atr", smc.current_atr ? `$${smc.current_atr}` : "--");
    setVal("insp-eq", smc.range_info && smc.range_info.equilibrium ? `$${smc.range_info.equilibrium}` : "--");
    setVal("insp-ote", smc.active_ote && smc.active_ote.fib_705 ? `$${smc.active_ote.fib_705}` : "--");
    setVal("insp-ob-count", smc.order_blocks ? smc.order_blocks.filter(b => !b.mitigated).length : "--");
    setVal("insp-fvg-count", smc.fvgs ? smc.fvgs.filter(f => !f.mitigated).length : "--");
    
    if (trade) {
        setVal("insp-be-status", trade.be_activated ? "ACTIF (0R)" : "ATTENTE (+1R)");
    } else {
        setVal("insp-be-status", "STANDBY");
    }
}

async function loadBacktestHistory() {
    const listElem = document.getElementById("history-runs-list");
    if (!listElem) return;

    try {
        const resp = await fetch("/api/backtest/history");
        const runs = await resp.json();

        if (!runs || !runs.length) {
            listElem.innerHTML = `
                <div style="color: var(--text-muted); font-size: 0.8rem; text-align: center; margin-top: 20px;">
                    Aucun stress-test enregistré. Lancez un backtest pour archiver les performances.
                </div>
            `;
            return;
        }

        listElem.innerHTML = "";
        runs.forEach(run => {
            const card = document.createElement("div");
            card.className = "history-run-card";
            const pnlSign = run.total_net_pnl >= 0 ? "+" : "";
            const isPos = run.total_net_pnl >= 0;

            card.innerHTML = `
                <div class="run-card-header">
                    <span class="run-model-badge">${run.coin} ${run.interval} | Modèle ${run.model}</span>
                    <span class="run-pnl ${isPos ? 'positive' : 'negative'}">${pnlSign}${run.total_net_pnl}$ (${pnlSign}${run.total_return_pct}%)</span>
                </div>
                <div class="run-metrics-grid">
                    <span>Bougies: <strong>${run.candles_count}</strong></span>
                    <span>Win Rate: <strong>${run.win_rate_pct}%</strong></span>
                    <span>Profit Factor: <strong>${run.profit_factor}</strong></span>
                    <span>Max DD: <strong>${run.max_drawdown_pct}%</strong></span>
                    <span>Sharpe: <strong>${run.sharpe_ratio || 0}</strong></span>
                    <span>Trades: <strong>${run.total_trades}</strong></span>
                </div>
                <div style="font-size: 0.65rem; color: #626c7e; margin-bottom: 6px;">${run.created_date || run.run_id}</div>
                <button class="btn-replay-run" onclick="loadRunForPlayback('${run.run_id}')">▶ Rejouer ce run (Playback)</button>
            `;
            listElem.appendChild(card);
        });
    } catch (e) {
        console.error("Erreur loadBacktestHistory:", e);
    }
}

window.loadRunForPlayback = async function(runId) {
    try {
        console.log(`[Playback] Chargement du run historique: ${runId}`);
        const resp = await fetch(`/api/backtest/run/${runId}`);
        const data = await resp.json();

        allCandles = data.candles.map(c => ({
            time: Math.floor(c.timestamp / 1000),
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
            volume: c.volume
        }));

        allTrades = data.trades || [];

        if (data.summary) {
            const winElem = document.getElementById("stat-winrate");
            if (winElem) winElem.textContent = `${data.summary.win_rate_pct}%`;
            const tradesElem = document.getElementById("stat-trades");
            if (tradesElem) tradesElem.textContent = data.summary.total_trades;
            const pnlElem = document.getElementById("stat-pnl");
            if (pnlElem) {
                const pnlSign = data.summary.total_net_pnl > 0 ? '+' : '';
                pnlElem.textContent = `${pnlSign}${data.summary.total_net_pnl}$ (${pnlSign}${data.summary.total_return_pct}%)`;
                pnlElem.className = `hud-value ${data.summary.total_net_pnl >= 0 ? 'positive' : 'negative'}`;
            }
        }

        await switchMode("playback");
        const scrubber = document.getElementById("timeline-scrubber");
        if (scrubber) {
            scrubber.max = allCandles.length - 1;
            scrubber.value = 0;
        }
        currentPlaybackIndex = Math.min(60, allCandles.length - 1);
        goToIndex(currentPlaybackIndex);
        if (chart && chart.timeScale) {
            chart.timeScale().fitContent();
        }
        const tabTrades = document.getElementById("tab-btn-trades");
        if (tabTrades) tabTrades.click();
    } catch (e) {
        alert("Erreur chargement du run: " + e);
    }
};

async function loadLiveStatus() {
    try {
        const resp = await fetch("/api/status");
        const data = await resp.json();

        const priceElem = document.getElementById("live-price");
        if (priceElem) priceElem.textContent = data.best_bid > 0 ? `$${data.best_bid.toLocaleString()}` : "--";

        const spreadElem = document.getElementById("live-spread");
        if (spreadElem) {
            spreadElem.textContent = `${data.spread_pct}%`;
            spreadElem.className = `hud-value ${data.spread_allowed ? 'positive' : 'negative'}`;
        }

        const capElem = document.getElementById("live-capital");
        if (capElem && currentMode !== "live") capElem.textContent = `$${data.capital_usd}`;
    } catch (e) {
        console.error("Erreur statut:", e);
    }
}

async function loadAgentsStatus() {
    try {
        const resp = await fetch("/api/agents");
        const data = await resp.json();
        if (!data) return;

        // 1. Mission Clock
        const clockElem = document.getElementById("mission-clock-display");
        if (clockElem && data.mission_clock) {
            clockElem.textContent = data.mission_clock;
        }

        // 2. Approval Gate Status (Palermo Gate)
        const gateDot = document.getElementById("gate-dot");
        const gateStatus = document.getElementById("gate-status-text");
        const gateAgent = document.getElementById("gate-agent-name");

        const isVeto = data.palermo_halted;
        if (isVeto) {
            if (gateDot) { gateDot.className = "gate-dot-veto"; gateDot.textContent = "●"; }
            if (gateStatus) { gateStatus.className = "gate-veto"; gateStatus.textContent = "VETO BLOQUÉ"; }
            if (gateAgent) { gateAgent.style.color = "#ff3d71"; }
        } else {
            if (gateDot) { gateDot.className = "gate-dot-cleared"; gateDot.textContent = "●"; }
            if (gateStatus) { gateStatus.className = "gate-cleared"; gateStatus.textContent = "ENTRY CLEARED"; }
            if (gateAgent) { gateAgent.style.color = "#00e676"; }
        }

        // 3. Segmented Gate Bars (10 segments)
        const segmentsContainer = document.getElementById("gate-segments");
        if (segmentsContainer) {
            const segs = segmentsContainer.querySelectorAll(".seg");
            segs.forEach(seg => {
                if (isVeto) {
                    seg.className = "seg seg-veto";
                } else {
                    seg.className = "seg seg-cleared";
                }
            });
        }

        // 4. Mettre à jour les cartes d'agents du Desk
        if (data.agents) {
            Object.keys(data.agents).forEach(agentKey => {
                const info = data.agents[agentKey];
                const card = document.getElementById(`card-${agentKey}`);
                if (card) {
                    const tag = card.querySelector(".agent-status-tag");
                    if (tag) {
                        tag.textContent = info.status;
                        if (info.status === "CLEARED") {
                            tag.className = "agent-status-tag status-cleared";
                        } else if (info.status === "VETO") {
                            tag.className = "agent-status-tag status-veto";
                        } else if (info.status === "APPROVED") {
                            tag.className = "agent-status-tag status-router";
                        } else {
                            tag.className = "agent-status-tag status-active";
                        }
                    }
                }
            });
        }

        // 5. Mettre à jour le flux Activity Log
        if (data.activity_log && data.activity_log.length) {
            const stream = document.getElementById("activity-log-stream");
            if (stream) {
                stream.innerHTML = "";
                data.activity_log.forEach(item => {
                    const div = document.createElement("div");
                    const statusClass = item.status === "CLEARED" ? "log-cleared" : (item.status === "VETO" ? "log-veto" : "log-info");
                    const agentClass = `log-${item.agent.toLowerCase()}`;
                    div.className = `log-entry ${statusClass}`;
                    div.innerHTML = `
                        <span class="log-time">${item.timestamp}</span>
                        <span class="log-agent ${agentClass}">${item.agent}</span>
                        <span class="log-msg">${item.message}</span>
                    `;
                    stream.appendChild(div);
                });
            }
        }
    } catch (e) {
        console.error("Erreur loadAgentsStatus:", e);
    }
}


async function loadPaperTradingStatus() {
    try {
        const resp = await fetch("/api/paper-trading");
        const data = await resp.json();
        if (!data) return;

        if (!isSwitchingBasket && data.active_basket_key) {
            currentActiveBasket = data.active_basket_key;
        }

        // 1. Bouton toggle
        const btnToggle = document.getElementById("btn-toggle-paper");
        if (btnToggle) {
            if (data.is_running) {
                btnToggle.textContent = "🟢 Paper Trading : ACTIF";
                btnToggle.style.color = "#00e676";
                btnToggle.style.borderColor = "rgba(0, 230, 118, 0.4)";
            } else {
                btnToggle.textContent = "⏸ Paper Trading : PAUSE";
                btnToggle.style.color = "#ffb000";
                btnToggle.style.borderColor = "rgba(255, 176, 0, 0.4)";
            }
        }

        // 2. Badge de session
        const sessionElem = document.getElementById("session-badge-text");
        if (sessionElem) {
            sessionElem.textContent = data.session_message ? `[${data.session_message}]` : "";
            sessionElem.style.color = data.session_allowed ? "#00e676" : "#ffb000";
        }

        // 3. Cartes A/B Testing Multi-Paniers
        if (data.baskets) {
            ["alpha", "quad", "core"].forEach(bKey => {
                const bInfo = data.baskets[bKey];
                if (!bInfo) return;

                const card = document.getElementById(`card-basket-${bKey}`);
                if (card && !isSwitchingBasket) {
                    card.classList.toggle("active", bKey === currentActiveBasket);
                }

                const balElem = document.getElementById(`basket-${bKey}-bal`);
                if (balElem) {
                    const bBal = bInfo.total_balance !== undefined ? bInfo.total_balance : bInfo.current_balance;
                    const bInit = bInfo.total_initial_capital !== undefined ? bInfo.total_initial_capital : 300;
                    balElem.textContent = `$${bBal.toFixed(2)} / $${bInit.toFixed(0)}`;
                }

                const pnlElem = document.getElementById(`basket-${bKey}-pnl`);
                if (pnlElem) {
                    const bRetUsd = bInfo.total_return_usd !== undefined ? bInfo.total_return_usd : (bInfo.current_balance - bInfo.initial_capital);
                    const bRetPct = bInfo.total_return_pct !== undefined ? bInfo.total_return_pct : 0;
                    const sign = bRetUsd >= 0 ? "+" : "";
                    pnlElem.textContent = `${sign}${bRetUsd.toFixed(2)}$ (${sign}${bRetPct.toFixed(1)}%)`;
                    pnlElem.className = `basket-pnl ${bRetUsd >= 0 ? 'positive' : 'negative'}`;
                }

                const tradesElem = document.getElementById(`basket-${bKey}-trades`);
                if (tradesElem) {
                    const trCount = bInfo.total_closed_trades_count !== undefined ? bInfo.total_closed_trades_count : bInfo.closed_trades_count;
                    const wrPct = bInfo.total_win_rate_pct !== undefined ? bInfo.total_win_rate_pct : bInfo.win_rate_pct;
                    tradesElem.textContent = `${trCount} trade${trCount > 1 ? 's' : ''} | WR: ${wrPct}%`;
                }

                const statusElem = document.getElementById(`basket-${bKey}-status`);
                if (statusElem) {
                    if (bInfo.active_position) {
                        statusElem.textContent = `EN POS (${bInfo.active_position.symbol})`;
                        statusElem.className = "basket-status-dot in_pos";
                    } else if (bInfo.pending_orders && bInfo.pending_orders.length) {
                        statusElem.textContent = `ORDRE (${bInfo.pending_orders[0].symbol})`;
                        statusElem.className = "basket-status-dot order_pending";
                    } else {
                        statusElem.textContent = "SCANNING";
                        statusElem.className = "basket-status-dot scanning";
                    }
                }

                // Mettre à jour les pills de stratégies (Scalp, Intraday, Day)
                if (bInfo.strategies) {
                    ["scalp", "intraday", "day"].forEach(sId => {
                        const pill = document.getElementById(`strat-pill-${bKey}-${sId}`);
                        const sData = bInfo.strategies[sId];
                        if (pill && sData) {
                            const isAct = (bInfo.active_strategy_id === sId);
                            pill.classList.toggle("active", isAct);
                            pill.title = `${sData.name} | Solde: $${sData.current_balance.toFixed(2)} (${sData.closed_trades_count} trades | WR: ${sData.win_rate_pct}%)`;
                            if (sData.active_position) {
                                pill.style.borderColor = "#00e676";
                                pill.style.color = "#00e676";
                                pill.style.boxShadow = "0 0 6px rgba(0, 230, 118, 0.4)";
                            } else {
                                pill.style.borderColor = "";
                                pill.style.color = "";
                                pill.style.boxShadow = "";
                            }
                        }
                    });
                }
            });
        }

        if (data.portfolio_symbols && data.portfolio_symbols.length) {
            const coinContainer = document.getElementById("coin-pills-container");
            if (coinContainer && coinContainer.children.length !== data.portfolio_symbols.length) {
                updateCoinPills(data.portfolio_symbols);
            }
        }

        // 4. Position en direct (Header HUD)
        const posElem = document.getElementById("hud-live-position");
        if (posElem) {
            if (data.active_position) {
                const pos = data.active_position;
                const pnlSign = pos.unrealized_pnl >= 0 ? "+" : "";
                posElem.textContent = `${pos.is_long ? 'LONG' : 'SHORT'} ${pos.size} ${pos.symbol} @ $${pos.entry_price} (${pnlSign}${pos.unrealized_pnl}$)`;
                posElem.style.color = pos.unrealized_pnl >= 0 ? "#00e676" : "#ff3d71";
            } else if (data.pending_orders && data.pending_orders.length) {
                const ord = data.pending_orders[0];
                posElem.textContent = `LIMITE ${ord.is_long ? 'BUY' : 'SELL'} ${ord.symbol} @ $${ord.entry_price}`;
                posElem.style.color = "#ffb000";
            } else {
                posElem.textContent = "AUCUNE";
                posElem.style.color = "#848e9c";
            }
        }

        // 5. Mettre à jour le solde et PnL si en mode Live
        if (currentMode === "live") {
            const capElem = document.getElementById("live-capital");
            if (capElem) {
                const liveBal = data.total_balance !== undefined ? data.total_balance : data.current_balance;
                const liveInit = data.total_initial_capital !== undefined ? data.total_initial_capital : 300;
                capElem.textContent = `$${liveBal.toFixed(2)} / $${liveInit.toFixed(0)}`;
            }
            const pnlElem = document.getElementById("stat-pnl");
            if (pnlElem && data.total_return_usd !== undefined) {
                const sign = data.total_return_usd >= 0 ? "+" : "";
                pnlElem.textContent = `${sign}${data.total_return_usd.toFixed(2)}$ (${sign}${data.total_return_pct.toFixed(1)}%)`;
                pnlElem.className = `hud-value ${data.total_return_usd >= 0 ? 'positive' : 'negative'}`;
            }

            // 6. Afficher la position active ou les trades fermés dans l'onglet Exécutions
            renderLiveExecutions(data.active_position, data.closed_trades, data.pending_orders);
        }
    } catch (e) {
        console.error("Erreur loadPaperTradingStatus:", e);
    }
}

async function switchActiveBasket(basketKey) {
    try {
        isSwitchingBasket = true;
        currentActiveBasket = basketKey;
        // Changement visuel immédiat (zéro lag perçu)
        ["alpha", "quad", "core"].forEach(k => {
            const card = document.getElementById(`card-basket-${k}`);
            if (card) card.classList.toggle("active", k === basketKey);
        });

        const syms = BASKET_SYMBOLS_MAP[basketKey] || ["SOL", "SUI"];
        if (!syms.includes(currentCoin)) {
            currentCoin = syms[0];
        }
        updateCoinPills(syms);
        loadLiveCandles(true, currentCoin);

        const resp = await fetch(`/api/paper-trading/basket?basket=${basketKey}`, { method: "POST" });
        const data = await resp.json();
        if (data.status === "success") {
            currentActiveBasket = data.active_basket_key;
            if (data.symbols && data.symbols.length) {
                if (!data.symbols.includes(currentCoin)) {
                    currentCoin = data.symbols[0];
                }
                updateCoinPills(data.symbols);
            }
        }
    } catch (e) {
        console.error("Erreur switchActiveBasket:", e);
    } finally {
        setTimeout(() => { isSwitchingBasket = false; }, 800);
    }
}
window.switchActiveBasket = switchActiveBasket;


function renderLiveExecutions(activePos, closedTrades, pendingOrders) {
    const tradesListElem = document.getElementById("trades-list");
    if (!tradesListElem) return;
    tradesListElem.innerHTML = "";

    // Position active en tête de liste
    if (activePos) {
        const item = document.createElement("div");
        item.className = `trade-item ${activePos.unrealized_pnl >= 0 ? 'win' : 'loss'}`;
        item.style.boxShadow = "0 0 8px rgba(41, 98, 255, 0.4)";
        item.innerHTML = `
            <div class="trade-row">
                <span class="trade-type ${activePos.is_long ? 'long' : 'short'}">⚡ EN DIRECT : ${activePos.is_long ? 'BUY LONG' : 'SELL SHORT'}</span>
                <span class="trade-pnl ${activePos.unrealized_pnl >= 0 ? 'positive' : 'negative'}">${activePos.unrealized_pnl >= 0 ? '+' : ''}${activePos.unrealized_pnl}$ (${activePos.roi_pct}%)</span>
            </div>
            <div class="trade-row trade-sub">
                <span>Entrée: $${activePos.entry_price}</span>
                <span>Prix Actuel: $${activePos.current_price}</span>
            </div>
            <div class="trade-row trade-sub">
                <span>SL: $${activePos.stop_loss}</span>
                <span>TP: $${activePos.take_profit}</span>
            </div>
        `;
        tradesListElem.appendChild(item);
    }

    // Ordres limites en attente
    if (pendingOrders && pendingOrders.length) {
        pendingOrders.forEach(ord => {
            const item = document.createElement("div");
            item.className = "trade-item";
            item.style.borderColor = "#ffb000";
            item.innerHTML = `
                <div class="trade-row">
                    <span class="trade-type" style="color: #ffb000;">⏳ ORDRE LIMIT MAKER</span>
                    <span class="trade-sub">EN ATTENTE RETEST</span>
                </div>
                <div class="trade-row trade-sub">
                    <span>${ord.is_long ? 'BUY' : 'SELL'} @ $${ord.entry_price}</span>
                    <span>SL: $${ord.stop_loss} | TP: $${ord.take_profit}</span>
                </div>
            `;
            tradesListElem.appendChild(item);
        });
    }

    // Trades fermés
    if (closedTrades && closedTrades.length) {
        closedTrades.forEach(trade => {
            let diagHtml = "";
            if (trade.diagnostics) {
                const d = trade.diagnostics;
                diagHtml = `
                    <div class="trade-diag-box" style="margin-top: 6px; padding: 6px 8px; background: rgba(0,0,0,0.35); border-radius: 4px; border-left: 3px solid ${d.badge_color};">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px;">
                            <span style="font-size: 0.72rem; font-weight: 700; color: ${d.badge_color};">${d.badge_label}</span>
                            <span style="font-size: 0.68rem; color: #848e9c;">MAE: ${d.mae_r}R | MFE: ${d.mfe_r}R</span>
                        </div>
                        <div style="font-size: 0.70rem; color: #d1d4dc; line-height: 1.3;">${d.diagnosis_summary}</div>
                        <div style="font-size: 0.68rem; color: #ffd700; margin-top: 4px; font-style: italic;">💡 Conseil IA : ${d.ai_tuning_tip}</div>
                    </div>
                `;
            }

            const beBadge = trade.be_activated ? `<span style="background: rgba(255, 215, 0, 0.2); color: #ffd700; padding: 1px 4px; border-radius: 2px; font-size: 0.65rem; margin-left: 4px;">🛡️ VRAI BE</span>` : "";
            const tp1Badge = trade.tp1_hit ? `<span style="background: rgba(0, 210, 255, 0.2); color: #00d2ff; padding: 1px 4px; border-radius: 2px; font-size: 0.65rem; margin-left: 4px;">💰 TP1 +1R</span>` : "";
            const tp2Badge = trade.tp2_hit ? `<span style="background: rgba(0, 230, 118, 0.2); color: #00e676; padding: 1px 4px; border-radius: 2px; font-size: 0.65rem; margin-left: 4px;">🎯 TP2 +3R</span>` : "";
            const runnerBadge = trade.exit_reason === "RUNNER_TRAIL" ? `<span style="background: rgba(186, 104, 200, 0.25); color: #ba68c8; padding: 1px 4px; border-radius: 2px; font-size: 0.65rem; margin-left: 4px;">🚀 RUNNER</span>` : "";

            const item = document.createElement("div");
            item.className = `trade-item ${trade.pnl_usd >= 0 ? 'win' : 'loss'}`;
            item.innerHTML = `
                <div class="trade-row">
                    <span class="trade-type ${trade.is_long ? 'long' : 'short'}">${trade.is_long ? 'BUY LONG' : 'SELL SHORT'} [${trade.exit_reason}] ${beBadge} ${tp1Badge} ${tp2Badge} ${runnerBadge}</span>
                    <span class="trade-pnl ${trade.pnl_usd >= 0 ? 'positive' : 'negative'}">${trade.pnl_usd >= 0 ? '+' : ''}${trade.pnl_usd}$</span>
                </div>
                <div class="trade-row trade-sub">
                    <span>Entrée: $${trade.entry_price}</span>
                    <span>Sortie: $${trade.exit_price}</span>
                </div>
                <div class="trade-row trade-sub">
                    <span>Multiple R: ${trade.r_multiple >= 0 ? '+' : ''}${trade.r_multiple}R</span>
                    <span>Solde: $${trade.closed_balance || '--'}</span>
                </div>
                ${diagHtml}
            `;
            tradesListElem.appendChild(item);
        });
    }

    if (!activePos && (!pendingOrders || !pendingOrders.length) && (!closedTrades || !closedTrades.length)) {
        tradesListElem.innerHTML = `
            <div style="color: var(--text-muted); font-size: 0.8rem; text-align: center; margin-top: 20px;">
                En attente d'un setup de trading validé par les agents...
            </div>
        `;
    }
}


async function loadBacktestForPlayback() {

    try {
        const resp = await fetch("/api/backtest");
        const data = await resp.json();

        allCandles = data.candles.map(c => ({
            time: Math.floor(c.timestamp / 1000),
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
            volume: c.volume
        }));

        allTrades = data.trades || [];

        // Mise à jour des stats globales dans l'UI
        if (data.summary) {
            const winElem = document.getElementById("stat-winrate");
            if (winElem) winElem.textContent = `${data.summary.win_rate_pct}%`;
            const tradesElem = document.getElementById("stat-trades");
            if (tradesElem) tradesElem.textContent = data.summary.total_trades;
            const pnlElem = document.getElementById("stat-pnl");
            if (pnlElem) {
                pnlElem.textContent = `${data.summary.total_net_pnl > 0 ? '+' : ''}${data.summary.total_net_pnl}$ (${data.summary.total_return_pct}%)`;
                pnlElem.className = `hud-value ${data.summary.total_net_pnl >= 0 ? 'positive' : 'negative'}`;
            }
        }

        const scrubber = document.getElementById("timeline-scrubber");
        scrubber.max = allCandles.length - 1;
        scrubber.value = 0;

        currentPlaybackIndex = Math.min(60, allCandles.length - 1);
        goToIndex(currentPlaybackIndex);
        if (chart && chart.timeScale) {
            chart.timeScale().fitContent();
        }
    } catch (e) {
        console.error("Erreur chargement playback:", e);
    }
}

function goToIndex(index) {
    if (!allCandles.length) return;
    currentPlaybackIndex = Math.max(0, Math.min(index, allCandles.length - 1));

    const scrubber = document.getElementById("timeline-scrubber");
    scrubber.value = currentPlaybackIndex;

    const visibleCandles = allCandles.slice(0, currentPlaybackIndex + 1);
    candleSeries.setData(visibleCandles);

    // Mettre à jour les marqueurs de trades visibles jusqu'à cet instant
    updateTradeMarkers(visibleCandles[visibleCandles.length - 1].time);

    // Info temps
    const currentCandle = visibleCandles[visibleCandles.length - 1];
    const dateStr = new Date(currentCandle.time * 1000).toLocaleString("fr-FR", {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
    });
    document.getElementById("playback-time-label").textContent = `${dateStr} (${currentPlaybackIndex + 1}/${allCandles.length})`;

    // Overlay info
    document.getElementById("overlay-ohlc").innerHTML = `
        <strong>BTC/USDC</strong> <span style="color:#2962ff; font-weight:700;">PLAYBACK</span> &nbsp;|&nbsp; 
        O: <span style="color:#d1d4dc">${currentCandle.open}</span> 
        H: <span style="color:#00e676">${currentCandle.high}</span> 
        L: <span style="color:#ff3d71">${currentCandle.low}</span> 
        C: <span style="color:#d1d4dc">${currentCandle.close}</span>
    `;
}

function updateTradeMarkers(currentTimestamp) {
    const markers = [];
    const tradesListElem = document.getElementById("trades-list");
    tradesListElem.innerHTML = "";

    const activeOrPastTrades = allTrades.filter(t => Math.floor(t.entry_time / 1000) <= currentTimestamp);

    activeOrPastTrades.forEach(trade => {
        const entryTimeSec = Math.floor(trade.entry_time / 1000);
        const exitTimeSec = Math.floor(trade.exit_time / 1000);

        // Marqueur d'entrée
        markers.push({
            time: entryTimeSec,
            position: trade.is_long ? "belowBar" : "aboveBar",
            color: trade.is_long ? "#00e676" : "#ff3d71",
            shape: trade.is_long ? "arrowUp" : "arrowDown",
            text: `${trade.is_long ? 'LONG' : 'SHORT'} @ ${trade.entry_price}`
        });

        // Marqueur de sortie si l'instant actuel dépasse la sortie
        const hasExited = exitTimeSec <= currentTimestamp;
        if (hasExited) {
            markers.push({
                time: exitTimeSec,
                position: trade.is_long ? "aboveBar" : "belowBar",
                color: trade.pnl_usd >= 0 ? "#00e676" : "#ff3d71",
                shape: "circle",
                text: `${trade.exit_reason}: ${trade.pnl_usd > 0 ? '+' : ''}${trade.pnl_usd}$`
            });
        }

        // Diagnostic médico-légal
        let diagHtml = "";
        if (trade.diagnostics) {
            const d = trade.diagnostics;
            diagHtml = `
                <div class="trade-diag-box" style="margin-top: 6px; padding: 6px 8px; background: rgba(0,0,0,0.35); border-radius: 4px; border-left: 3px solid ${d.badge_color};">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px;">
                        <span style="font-size: 0.72rem; font-weight: 700; color: ${d.badge_color};">${d.badge_label}</span>
                        <span style="font-size: 0.68rem; color: #848e9c;">MAE: ${d.mae_r}R | MFE: ${d.mfe_r}R</span>
                    </div>
                    <div style="font-size: 0.70rem; color: #d1d4dc; line-height: 1.3;">${d.diagnosis_summary}</div>
                    <div style="font-size: 0.68rem; color: #ffd700; margin-top: 4px; font-style: italic;">💡 Conseil IA : ${d.ai_tuning_tip}</div>
                </div>
            `;
        }

        const beBadge = trade.be_activated ? `<span style="background: rgba(255, 215, 0, 0.2); color: #ffd700; padding: 1px 4px; border-radius: 2px; font-size: 0.65rem; margin-left: 4px;">🛡️ VRAI BE</span>` : "";
        const tp1Badge = trade.tp1_hit ? `<span style="background: rgba(0, 210, 255, 0.2); color: #00d2ff; padding: 1px 4px; border-radius: 2px; font-size: 0.65rem; margin-left: 4px;">💰 TP1 +1R</span>` : "";

        // Ajouter à la liste latérale
        const item = document.createElement("div");
        item.className = `trade-item ${trade.pnl_usd >= 0 ? 'win' : 'loss'}`;
        item.innerHTML = `
            <div class="trade-row">
                <span class="trade-type ${trade.is_long ? 'long' : 'short'}">${trade.is_long ? 'BUY LONG' : 'SELL SHORT'} [${trade.exit_reason || 'OUVERT'}] ${beBadge} ${tp1Badge}</span>
                <span class="trade-pnl ${trade.pnl_usd >= 0 ? 'positive' : 'negative'}">${hasExited ? `${trade.pnl_usd > 0 ? '+' : ''}${trade.pnl_usd}$` : 'EN COURS'}</span>
            </div>
            <div class="trade-row trade-sub">
                <span>Entrée: $${trade.entry_price}</span>
                <span>Sortie: ${hasExited ? '$' + trade.exit_price : '--'}</span>
            </div>
            <div class="trade-row trade-sub">
                <span>SL: $${trade.stop_loss} | TP: $${trade.take_profit}</span>
                <span>R: ${trade.r_multiple >= 0 ? '+' : ''}${trade.r_multiple}R</span>
            </div>
            ${diagHtml}
        `;
        tradesListElem.prepend(item);
    });

    markers.sort((a, b) => a.time - b.time);
    candleSeries.setMarkers(markers);

    // Détecter si un trade est en cours sur la bougie courante pour afficher les brackets
    const currentActiveTrade = allTrades.find(t => {
        const ent = Math.floor(t.entry_time / 1000);
        const ext = Math.floor(t.exit_time / 1000);
        return ent <= currentTimestamp && ext >= currentTimestamp;
    });

    renderSMCLayers(lastSMCData, currentActiveTrade || null);
}

function togglePlay() {
    if (isPlaying) {
        pausePlayback();
    } else {
        startPlayback();
    }
}

function startPlayback() {
    isPlaying = true;
    document.getElementById("btn-play").innerHTML = "⏸ Pause";
    const delay = Math.max(10, Math.floor(400 / playbackSpeed));

    playbackTimer = setInterval(() => {
        if (currentPlaybackIndex >= allCandles.length - 1) {
            pausePlayback();
            return;
        }
        stepForward();
    }, delay);
}

function pausePlayback() {
    isPlaying = false;
    document.getElementById("btn-play").innerHTML = "▶ Playback";
    if (playbackTimer) {
        clearInterval(playbackTimer);
        playbackTimer = null;
    }
}

function stepForward() {
    if (currentPlaybackIndex < allCandles.length - 1) {
        goToIndex(currentPlaybackIndex + 1);
    }
}

function stepBackward() {
    if (currentPlaybackIndex > 0) {
        goToIndex(currentPlaybackIndex - 1);
    }
}


// ==========================================================================
// Notifications & Telegram Smartphone Integration
// ==========================================================================
async function loadNotificationStatus() {
    try {
        const resp = await fetch("/api/notifications/status");
        if (!resp.ok) return;
        const data = await resp.json();

        const headerStatus = document.getElementById("header-tg-status");
        const btnHeader = document.getElementById("btn-open-telegram");
        const modalDot = document.getElementById("tg-modal-dot");
        const modalStatus = document.getElementById("tg-modal-status-text");
        const inputToken = document.getElementById("input-tg-token");
        const inputChatId = document.getElementById("input-tg-chat-id");

        if (data.telegram_configured) {
            if (headerStatus) headerStatus.textContent = "Telegram 🟢";
            if (btnHeader) btnHeader.classList.add("connected");
            if (modalDot) modalDot.classList.add("connected");
            if (modalStatus) modalStatus.textContent = `Connecté au smartphone (Chat ID: ${data.telegram_chat_id})`;
            if (inputToken && data.telegram_token_masked) inputToken.placeholder = `Token actif : ${data.telegram_token_masked}`;
            if (inputChatId && data.telegram_chat_id) inputChatId.value = data.telegram_chat_id;
        } else {
            if (headerStatus) headerStatus.textContent = "Telegram 📱";
            if (btnHeader) btnHeader.classList.remove("connected");
            if (modalDot) modalDot.classList.remove("connected");
            if (modalStatus) modalStatus.textContent = "Non configuré (en attente du token)";
        }
    } catch (e) {
        console.warn("[Notifications] Impossible de charger le statut:", e);
    }
}

function setupTelegramModalListeners() {
    const btnOpen = document.getElementById("btn-open-telegram");
    const modal = document.getElementById("modal-telegram");
    const btnClose = document.getElementById("btn-close-tg-modal");
    const btnDetect = document.getElementById("btn-tg-detect");
    const btnTest = document.getElementById("btn-tg-test");
    const btnSave = document.getElementById("btn-tg-save");
    const inputToken = document.getElementById("input-tg-token");
    const inputChat = document.getElementById("input-tg-chat-id");
    const feedback = document.getElementById("tg-action-feedback");
    const detectResult = document.getElementById("tg-detect-result");

    if (btnOpen && modal) {
        btnOpen.addEventListener("click", () => {
            modal.style.display = "flex";
            loadNotificationStatus();
        });
    }

    if (btnClose && modal) {
        btnClose.addEventListener("click", () => {
            modal.style.display = "none";
        });
    }

    if (modal) {
        modal.addEventListener("click", (e) => {
            if (e.target === modal) modal.style.display = "none";
        });
    }

    if (btnDetect) {
        btnDetect.addEventListener("click", async () => {
            const token = inputToken ? inputToken.value.trim() : "";
            if (!token) {
                if (detectResult) {
                    detectResult.style.display = "block";
                    detectResult.style.background = "rgba(255, 61, 113, 0.15)";
                    detectResult.style.color = "#ff3d71";
                    detectResult.textContent = "⚠️ Veuillez coller votre Token Telegram d'abord (Étape 2).";
                }
                return;
            }

            if (detectResult) {
                detectResult.style.display = "block";
                detectResult.style.background = "rgba(0, 210, 255, 0.15)";
                detectResult.style.color = "#00d2ff";
                detectResult.textContent = "🔍 Interrogation de Telegram en cours...";
            }

            try {
                const resp = await fetch("/api/notifications/telegram/detect", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token: token })
                });
                const res = await resp.json();
                if (res.success) {
                    if (inputChat) inputChat.value = res.chat_id;
                    if (detectResult) {
                        detectResult.style.background = "rgba(0, 230, 118, 0.15)";
                        detectResult.style.color = "#00e676";
                        detectResult.innerHTML = `✅ Chat ID <b>${res.chat_id}</b> détecté avec succès (${res.first_name || ''}) !`;
                    }
                } else {
                    if (detectResult) {
                        detectResult.style.background = "rgba(255, 61, 113, 0.15)";
                        detectResult.style.color = "#ff3d71";
                        detectResult.textContent = `❌ ${res.error || 'Erreur lors de la détection.'}`;
                    }
                }
            } catch (err) {
                if (detectResult) {
                    detectResult.style.background = "rgba(255, 61, 113, 0.15)";
                    detectResult.style.color = "#ff3d71";
                    detectResult.textContent = `❌ Erreur réseau: ${err}`;
                }
            }
        });
    }

    if (btnTest) {
        btnTest.addEventListener("click", async () => {
            const token = inputToken ? inputToken.value.trim() : "";
            const chatId = inputChat ? inputChat.value.trim() : "";

            if (feedback) {
                feedback.style.color = "#00d2ff";
                feedback.textContent = "🚀 Envoi du message test vers votre smartphone...";
            }

            try {
                const resp = await fetch("/api/notifications/telegram/test", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token: token, chat_id: chatId })
                });
                const res = await resp.json();
                if (res.success) {
                    if (feedback) {
                        feedback.style.color = "#00e676";
                        feedback.textContent = `✅ ${res.message}`;
                    }
                } else {
                    if (feedback) {
                        feedback.style.color = "#ff3d71";
                        feedback.textContent = `❌ ${res.error || "Erreur d'envoi."}`;
                    }
                }
            } catch (err) {
                if (feedback) {
                    feedback.style.color = "#ff3d71";
                    feedback.textContent = `❌ Erreur réseau: ${err}`;
                }
            }
        });
    }

    if (btnSave) {
        btnSave.addEventListener("click", async () => {
            const token = inputToken ? inputToken.value.trim() : "";
            const chatId = inputChat ? inputChat.value.trim() : "";

            if (!token || !chatId) {
                if (feedback) {
                    feedback.style.color = "#ff3d71";
                    feedback.textContent = "⚠️ Veuillez renseigner le Token et le Chat ID avant de sauvegarder.";
                }
                return;
            }

            try {
                const resp = await fetch("/api/notifications/telegram/save", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token: token, chat_id: chatId })
                });
                const res = await resp.json();
                if (res.status === "success") {
                    if (feedback) {
                        feedback.style.color = "#00e676";
                        feedback.textContent = "💾 Identifiants enregistrés ! Le desk vous notifiera en temps réel.";
                    }
                    await loadNotificationStatus();
                    setTimeout(() => {
                        if (modal) modal.style.display = "none";
                    }, 1500);
                } else {
                    if (feedback) {
                        feedback.style.color = "#ff3d71";
                        feedback.textContent = `❌ ${res.detail || "Erreur d'enregistrement."}`;
                    }
                }
            } catch (err) {
                if (feedback) {
                    feedback.style.color = "#ff3d71";
                    feedback.textContent = `❌ Erreur réseau: ${err}`;
                }
            }
        });
    }
}

// ==========================================================================
// Agent Deck Collapse Toggle
// ==========================================================================
function setupAgentDeckToggle() {
    const btnToggle = document.getElementById("btn-toggle-agents");
    const container = document.getElementById("agent-deck-container");
    if (btnToggle && container) {
        btnToggle.addEventListener("click", () => {
            container.classList.toggle("collapsed");
            const isCollapsed = container.classList.contains("collapsed");
            btnToggle.textContent = isCollapsed ? "▲ Afficher" : "▼ Masquer";
            if (chart) {
                const chartContainer = document.getElementById("trading-chart");
                if (chartContainer) {
                    setTimeout(() => {
                        chart.applyOptions({
                            width: chartContainer.clientWidth,
                            height: chartContainer.clientHeight,
                        });
                    }, 100);
                }
            }
        });
    }
}

// ==========================================================================
// Mobile Viewport Navigation
// ==========================================================================
function setupMobileNavigation() {
    const tabs = document.querySelectorAll(".mob-tab-btn");
    const chartCol = document.querySelector(".chart-column");
    const sidebar = document.querySelector(".sidebar");
    const basketRibbon = document.getElementById("basket-ribbon");
    const agentDeck = document.getElementById("agent-deck-container");

    // S'assurer qu'au démarrage aucun panneau n'est masqué par erreur
    if (chartCol) chartCol.style.display = "";
    if (sidebar) sidebar.style.display = "";

    tabs.forEach(btn => {
        btn.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active"));
            btn.classList.add("active");
            const view = btn.dataset.view;

            if (view === "chart") {
                if (chartCol) {
                    chartCol.style.display = "";
                    chartCol.scrollIntoView({ behavior: "smooth", block: "start" });
                }
                if (chart) {
                    setTimeout(() => {
                        const chartContainer = document.getElementById("trading-chart");
                        if (chartContainer) {
                            chart.applyOptions({
                                width: chartContainer.clientWidth,
                                height: chartContainer.clientHeight,
                            });
                            if (chart.timeScale) chart.timeScale().fitContent();
                        }
                    }, 120);
                }
            } else if (view === "baskets") {
                if (basketRibbon) {
                    basketRibbon.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            } else if (view === "activity") {
                const tabAct = document.getElementById("tab-btn-activity");
                if (tabAct) tabAct.click();
                if (sidebar) {
                    sidebar.style.display = "";
                    sidebar.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            } else if (view === "trades") {
                const tabTr = document.getElementById("tab-btn-trades");
                if (tabTr) tabTr.click();
                if (sidebar) {
                    sidebar.style.display = "";
                    sidebar.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            } else if (view === "agents") {
                if (agentDeck) {
                    agentDeck.classList.remove("collapsed");
                    const btnToggle = document.getElementById("btn-toggle-agents");
                    if (btnToggle) btnToggle.textContent = "▼ Masquer";
                    agentDeck.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            }
        });
    });

    // Synchronisation automatique de l'onglet actif lors du défilement manuel de la page
    if (window.IntersectionObserver) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && entry.intersectionRatio >= 0.25) {
                    let activeView = null;
                    if (entry.target.classList.contains("chart-column") || entry.target.id === "trading-chart") {
                        activeView = "chart";
                    } else if (entry.target.id === "basket-ribbon") {
                        activeView = "baskets";
                    } else if (entry.target.classList.contains("sidebar")) {
                        const isTrades = document.getElementById("panel-trades")?.classList.contains("active");
                        activeView = isTrades ? "trades" : "activity";
                    } else if (entry.target.id === "agent-deck-container") {
                        activeView = "agents";
                    }
                    if (activeView) {
                        tabs.forEach(t => t.classList.toggle("active", t.dataset.view === activeView));
                    }
                }
            });
        }, { threshold: [0.25] });

        if (chartCol) observer.observe(chartCol);
        if (basketRibbon) observer.observe(basketRibbon);
        if (sidebar) observer.observe(sidebar);
        if (agentDeck) observer.observe(agentDeck);
    }
}

