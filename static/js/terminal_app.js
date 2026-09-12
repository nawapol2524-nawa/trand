/**
 * QuantPro Terminal - Main Application Controller
 * Architecture: Delta DOM Mutation, 60fps Slider Throttle, Ring Buffer Logs, Theme Sync
 */

(function () {
  'use strict';

  // State
  const AppState = {
    theme: localStorage.getItem('quantpro_theme') || 'dark',
    activeSymbol: 'EURUSD',
    safetyUnlocked: false,
    maxLogLines: 300,
    logBuffer: [],
    pollInterval: 1500,
    timer: null,
  };

  // DOM Elements cache
  const DOM = {
    themeBtn: document.getElementById('theme-toggle-btn'),
    marketTime: document.getElementById('market-time-utc'),
    accountBalance: document.getElementById('account-balance'),
    accountPnl: document.getElementById('account-pnl'),
    connectionPill: document.getElementById('connection-pill'),
    watchlistBody: document.getElementById('watchlist-tbody'),
    positionsList: document.getElementById('positions-list'),
    logFeed: document.getElementById('live-log-feed'),
    safetyToggle: document.getElementById('safety-lock-toggle'),
  };

  // 1. Theme Controller
  function initTheme() {
    applyTheme(AppState.theme);
    if (DOM.themeBtn) {
      DOM.themeBtn.addEventListener('click', toggleTheme);
    }
  }

  function applyTheme(theme) {
    AppState.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('quantpro_theme', theme);

    if (DOM.themeBtn) {
      DOM.themeBtn.innerHTML = theme === 'dark' 
        ? '<span class="theme-icon">☀️</span> <span class="theme-label">Light Mode</span>' 
        : '<span class="theme-icon">🌙</span> <span class="theme-label">Dark Mode</span>';
    }

    // Sync with Chart Engine if ready
    if (window.chartEngine && typeof window.chartEngine.setTheme === 'function') {
      window.chartEngine.setTheme(theme);
    }
  }

  function toggleTheme() {
    const nextTheme = AppState.theme === 'dark' ? 'light' : 'dark';
    applyTheme(nextTheme);
  }

  // 2. UTC Clock
  function startClock() {
    function updateTime() {
      const now = new Date();
      const h = String(now.getUTCHours()).padStart(2, '0');
      const m = String(now.getUTCMinutes()).padStart(2, '0');
      const s = String(now.getUTCSeconds()).padStart(2, '0');
      if (DOM.marketTime) {
        DOM.marketTime.textContent = `Market Time (${h}:${m}:${s} UTC)`;
      }
    }
    updateTime();
    setInterval(updateTime, 1000);
  }

  // 3. Watchlist Controller (Targeted Mutation)
  function renderWatchlist(items) {
    if (!DOM.watchlistBody) return;

    items.forEach((item) => {
      const rowId = `watchlist-row-${item.ticker}`;
      let row = document.getElementById(rowId);

      if (!row) {
        row = document.createElement('tr');
        row.id = rowId;
        row.className = 'watchlist-row';
        row.dataset.ticker = item.ticker;

        row.innerHTML = `
          <td class="ticker-col"><strong>${item.ticker}</strong></td>
          <td class="price-col" id="wl-price-${item.ticker}">${item.price}</td>
          <td class="spread-col" id="wl-spread-${item.ticker}">${item.spread}</td>
          <td class="change-col ${item.direction}" id="wl-change-${item.ticker}">${item.change}</td>
        `;

        row.addEventListener('click', () => {
          selectTicker(item.ticker);
        });

        DOM.watchlistBody.appendChild(row);
      } else {
        // Delta TextNode update only (Zero DOM rebuild)
        const priceEl = document.getElementById(`wl-price-${item.ticker}`);
        const spreadEl = document.getElementById(`wl-spread-${item.ticker}`);
        const changeEl = document.getElementById(`wl-change-${item.ticker}`);

        if (priceEl && priceEl.textContent !== item.price) {
          priceEl.textContent = item.price;
        }
        if (spreadEl && spreadEl.textContent !== item.spread) {
          spreadEl.textContent = item.spread;
        }
        if (changeEl && changeEl.textContent !== item.change) {
          changeEl.textContent = item.change;
          changeEl.className = `change-col ${item.direction}`;
        }
      }

      if (item.ticker === AppState.activeSymbol) {
        row.classList.add('active');
      } else {
        row.classList.remove('active');
      }
    });
  }

  function selectTicker(ticker) {
    AppState.activeSymbol = ticker;
    document.querySelectorAll('.watchlist-row').forEach(r => {
      if (r.dataset.ticker === ticker) {
        r.classList.add('active');
      } else {
        r.classList.remove('active');
      }
    });

    // Notify Chart Engine to switch active symbol
    if (window.chartEngine && typeof window.chartEngine.loadSymbol === 'function') {
      window.chartEngine.loadSymbol(ticker);
    }
  }

  // 4. Active Positions Controller (With 60fps Slider Throttle)
  function renderPositions(positions) {
    if (!DOM.positionsList) return;

    // Build or update position cards
    positions.forEach((pos) => {
      const cardId = `pos-card-${pos.id}`;
      let card = document.getElementById(cardId);

      if (!card) {
        card = document.createElement('div');
        card.id = cardId;
        card.className = `position-card ${pos.side.toLowerCase()}-card`;

        card.innerHTML = `
          <div class="pos-header">
            <div class="pos-title">
              <span class="pos-badge ${pos.side.toLowerCase()}">${pos.side}</span>
              <span class="pos-symbol">${pos.symbol} @ ${pos.entry}</span>
            </div>
            <div class="pos-pnl ${pos.pnl_class}" id="${pos.id}-pnl">${pos.pnl}</div>
          </div>
          <div class="pos-sub">
            <span class="pos-lots">${pos.lots}</span>
            <span class="pos-curr" id="${pos.id}-curr">Current: ${pos.current}</span>
          </div>

          <!-- Interactive SL Slider -->
          <div class="slider-group">
            <div class="slider-label-row">
              <span class="label-name">Stop Loss (SL)</span>
              <span class="label-val" id="${pos.id}-sl-val">${pos.sl}</span>
            </div>
            <input type="range" class="quant-slider sl-slider" id="${pos.id}-sl-slider"
                   min="${pos.sl_min}" max="${pos.sl_max}" step="0.0001" value="${pos.sl}"
                   ${AppState.safetyUnlocked ? '' : 'disabled'}>
          </div>

          <!-- Interactive TP Slider -->
          <div class="slider-group">
            <div class="slider-label-row">
              <span class="label-name">Take Profit (TP)</span>
              <span class="label-val" id="${pos.id}-tp-val">${pos.tp}</span>
            </div>
            <input type="range" class="quant-slider tp-slider" id="${pos.id}-tp-slider"
                   min="${pos.tp_min}" max="${pos.tp_max}" step="0.0001" value="${pos.tp}"
                   ${AppState.safetyUnlocked ? '' : 'disabled'}>
          </div>

          <!-- Trailing Stop Toggle -->
          <div class="ts-group">
            <span class="ts-label">Trailing Stop: ${pos.ts_pips} pips</span>
            <label class="toggle-switch">
              <input type="checkbox" id="${pos.id}-ts-toggle" ${pos.ts_active ? 'checked' : ''}
                     ${AppState.safetyUnlocked ? '' : 'disabled'}>
              <span class="slider round"></span>
            </label>
          </div>
        `;

        DOM.positionsList.appendChild(card);

        // Bind decoupled slider events
        bindSliderEvents(pos);
      } else {
        // Delta update pnl and current price
        const pnlEl = document.getElementById(`${pos.id}-pnl`);
        const currEl = document.getElementById(`${pos.id}-curr`);
        if (pnlEl && pnlEl.textContent !== pos.pnl) pnlEl.textContent = pos.pnl;
        if (currEl && currEl.textContent !== `Current: ${pos.current}`) {
          currEl.textContent = `Current: ${pos.current}`;
        }
      }
    });
  }

  function bindSliderEvents(pos) {
    const slSlider = document.getElementById(`${pos.id}-sl-slider`);
    const slVal = document.getElementById(`${pos.id}-sl-val`);
    const tpSlider = document.getElementById(`${pos.id}-tp-slider`);
    const tpVal = document.getElementById(`${pos.id}-tp-val`);

    if (slSlider && slVal) {
      // 60fps Visual Feedback only (No server flood)
      slSlider.addEventListener('input', (e) => {
        slVal.textContent = parseFloat(e.target.value).toFixed(5);
        if (window.chartEngine && typeof window.chartEngine.updatePriceLine === 'function') {
          window.chartEngine.updatePriceLine('sl', parseFloat(e.target.value));
        }
      });

      // Network trigger on release
      slSlider.addEventListener('change', (e) => {
        console.log(`[QuantPro] SL adjust requested for ${pos.symbol}: ${e.target.value}`);
      });
    }

    if (tpSlider && tpVal) {
      tpSlider.addEventListener('input', (e) => {
        tpVal.textContent = parseFloat(e.target.value).toFixed(5);
        if (window.chartEngine && typeof window.chartEngine.updatePriceLine === 'function') {
          window.chartEngine.updatePriceLine('tp', parseFloat(e.target.value));
        }
      });

      tpSlider.addEventListener('change', (e) => {
        console.log(`[QuantPro] TP adjust requested for ${pos.symbol}: ${e.target.value}`);
      });
    }
  }

  // 5. Live Trading Log (Sliding Window Ring Buffer)
  function renderLogs(logs) {
    if (!DOM.logFeed) return;

    logs.forEach((logText) => {
      if (!AppState.logBuffer.includes(logText)) {
        AppState.logBuffer.push(logText);
        if (AppState.logBuffer.length > AppState.maxLogLines) {
          AppState.logBuffer.shift(); // Evict oldest line
        }

        const logItem = document.createElement('div');
        logItem.className = 'log-line';
        logItem.textContent = logText;
        DOM.logFeed.appendChild(logItem);
      }
    });

    // Prune DOM nodes to match buffer limit
    while (DOM.logFeed.children.length > AppState.maxLogLines) {
      DOM.logFeed.removeChild(DOM.logFeed.firstChild);
    }

    // Smooth autoscroll to bottom
    DOM.logFeed.scrollTop = DOM.logFeed.scrollHeight;
  }

  // 6. Safety Lock Switch
  function initSafetyLock() {
    if (!DOM.safetyToggle) return;
    DOM.safetyToggle.addEventListener('change', (e) => {
      AppState.safetyUnlocked = e.target.checked;
      const sliders = document.querySelectorAll('.quant-slider, .ts-group input[type="checkbox"]');
      sliders.forEach((s) => {
        s.disabled = !AppState.safetyUnlocked;
      });
      console.log(`[QuantPro] Safety Lock: ${AppState.safetyUnlocked ? 'ARMED / UNLOCKED' : 'DISARMED / LOCKED'}`);
    });
  }

  // 7. Polling Data Feed
  async function fetchTerminalData() {
    try {
      const [stateRes, watchlistRes, posRes, logsRes] = await Promise.all([
        fetch('/api/state').then(r => r.json()),
        fetch('/api/watchlist').then(r => r.json()),
        fetch('/api/positions').then(r => r.json()),
        fetch('/api/logs').then(r => r.json())
      ]);

      // Update state & account
      if (DOM.accountBalance && stateRes.account) {
        DOM.accountBalance.textContent = `$${stateRes.account.balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
      }
      if (DOM.accountPnl && stateRes.account) {
        DOM.accountPnl.textContent = `(${stateRes.account.profit_pct})`;
      }
      if (DOM.connectionPill) {
        DOM.connectionPill.textContent = 'Connection: Green';
        DOM.connectionPill.className = 'status-pill green';
      }

      // Render sections
      renderWatchlist(watchlistRes);
      renderPositions(posRes);
      renderLogs(logsRes);

    } catch (err) {
      if (DOM.connectionPill) {
        DOM.connectionPill.textContent = 'Connection: Retrying...';
        DOM.connectionPill.className = 'status-pill yellow';
      }
    }
  }

  function startPolling() {
    fetchTerminalData();
    AppState.timer = setInterval(fetchTerminalData, AppState.pollInterval);
  }

  // Lifecycle Initialization
  window.addEventListener('DOMContentLoaded', () => {
    initTheme();
    startClock();
    initSafetyLock();
    startPolling();
    console.log('[QuantPro Terminal] Controller initialized successfully.');
  });

})();
