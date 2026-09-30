/**
 * Trading Bot Minimal Dashboard v3.0
 * Manages Gold, Forex, Synthetic modules — Zero-Flicker streaming.
 */

// State caches for table change detection (Zero-flicker table diffing)
let lastGoldPositionsHash = "";
let lastGoldOrdersHash = "";
let lastGoldHistoryHash = "";
let lastForexPairsHash = "";
let lastForexPositionsHash = "";
let lastForexOrdersHash = "";
let lastForexTradesHash = "";
let lastDerivPositionsHash = "";
let lastDerivTradesHash = "";
let lastNewsCalendarHash = "";
let lastBrainTracesHash = "";

// 1. Theme Controller (Vibrant Light / Midnight Dark with System Detection)
const themeToggleBtn = document.getElementById("theme-toggle-btn");
const themeIcon = document.getElementById("theme-icon");
const themeText = document.getElementById("theme-text");

function initTheme() {
  const savedTheme = localStorage.getItem("webboard_theme");
  if (savedTheme) {
    applyTheme(savedTheme);
  } else {
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(prefersDark ? "dark" : "light");
  }

  // Listen for OS theme changes if user hasn't explicitly set one
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
      if (!localStorage.getItem("webboard_theme")) {
        applyTheme(e.matches ? "dark" : "light");
      }
    });
  }
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  updateThemeButtonUI(theme);
}

function updateThemeButtonUI(theme) {
  if (theme === "dark") {
    if (themeIcon) themeIcon.textContent = "🌙";
    if (themeText) themeText.textContent = "Dark";
    themeToggleBtn?.setAttribute("title", "เปลี่ยนเป็น Light Mode");
  } else {
    if (themeIcon) themeIcon.textContent = "☀️";
    if (themeText) themeText.textContent = "Light";
    themeToggleBtn?.setAttribute("title", "เปลี่ยนเป็น Dark Mode");
  }
}

themeToggleBtn?.addEventListener("click", () => {
  const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
  const nextTheme = currentTheme === "light" ? "dark" : "light";
  applyTheme(nextTheme);
  localStorage.setItem("webboard_theme", nextTheme);
});

initTheme();

// 2. Tab Navigation Controller
window.switchTab = function(targetId) {
  document.querySelectorAll(".tab-btn").forEach((b) => {
    if (b.getAttribute("data-tab") === targetId) {
      b.classList.add("active");
    } else {
      b.classList.remove("active");
    }
  });
  document.querySelectorAll(".tab-content").forEach((c) => {
    if (c.id === targetId) {
      c.classList.add("active");
    } else {
      c.classList.remove("active");
    }
  });
};

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const targetId = btn.getAttribute("data-tab");
    if (targetId) window.switchTab(targetId);
  });
});

// Pillar Carousel — sync scroll position with dot indicators
(function initPillarCarousel() {
  const ribbon = document.querySelector(".pillars-ribbon");
  const dots   = document.querySelectorAll(".pillars-dot");
  if (!ribbon || !dots.length) return;

  // Scroll to card when dot is clicked
  dots.forEach((dot) => {
    dot.addEventListener("click", () => {
      const idx   = parseInt(dot.getAttribute("data-index"), 10);
      const cards = ribbon.querySelectorAll(".pillar-card");
      if (cards[idx]) {
        cards[idx].scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
      }
    });
  });

  // Update active dot based on scroll position
  let scrollTimer;
  ribbon.addEventListener("scroll", () => {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      const cards = ribbon.querySelectorAll(".pillar-card");
      let closestIdx = 0;
      let closestDist = Infinity;
      const ribbonCenter = ribbon.scrollLeft + ribbon.clientWidth / 2;

      cards.forEach((card, i) => {
        const cardCenter = card.offsetLeft + card.clientWidth / 2;
        const dist = Math.abs(ribbonCenter - cardCenter);
        if (dist < closestDist) {
          closestDist = dist;
          closestIdx = i;
        }
      });

      dots.forEach((d, i) => d.classList.toggle("active", i === closestIdx));
    }, 50);
  }, { passive: true });
})();

// 3. Real-time Clock (UTC + BKK GMT+7)
function updateClock() {
  const now = new Date();
  const utcH = String(now.getUTCHours()).padStart(2, "0");
  const utcM = String(now.getUTCMinutes()).padStart(2, "0");
  const utcS = String(now.getUTCSeconds()).padStart(2, "0");
  const utcStr = `${utcH}:${utcM}:${utcS} UTC`;

  const bkk = new Date(now.getTime() + (7 * 60 + now.getTimezoneOffset()) * 60000);
  const bH = String(bkk.getHours()).padStart(2, "0");
  const bM = String(bkk.getMinutes()).padStart(2, "0");
  const bS = String(bkk.getSeconds()).padStart(2, "0");
  const bkkStr = `${bH}:${bM}:${bS} BKK`;

  const clockEl = document.getElementById("header-clock");
  if (clockEl) clockEl.textContent = `${utcStr} | ${bkkStr}`;
}
setInterval(updateClock, 1000);
updateClock();


// 4. Surgical In-Place DOM Updater (No Screen Flicker)
function updateText(id, newText, isNumeric = false) {
  const el = document.getElementById(id);
  if (!el) return;

  const current = el.textContent;
  if (current === String(newText)) return;

  if (isNumeric) {
    const oldNum = parseFloat(String(current).replace(/[^0-9.-]/g, ""));
    const newNum = parseFloat(String(newText).replace(/[^0-9.-]/g, ""));

    if (!isNaN(oldNum) && !isNaN(newNum) && oldNum !== newNum) {
      const flashClass = newNum > oldNum ? "flash-up" : "flash-down";
      el.classList.add(flashClass);
      setTimeout(() => el.classList.remove(flashClass), 500);
    }
  }

  el.textContent = newText;
}

// 5. Apply Complete Snapshot to DOM
function applySnapshot(data) {
  if (!data) return;

  const port = data.portfolio || {};
  const gold = data.gold || data.forex_gold || {};
  const forex = data.forex || {};
  const syn = data.synthetic || data.deriv_synthetic || {};
  const brain = data.ai_brain || {};
  const news = data.news || {};

  // --- TOP PILLARS RIBBON (3 เสาหลัก) ---
  const goldMkt = gold.market_status || {};
  const goldCap = gold.capital || {};
  updateText("ribbon-gold-price", `$${(goldMkt.spot_price || 2658.45).toFixed(2)}`, true);
  updateText("ribbon-gold-balance", `$${(goldCap.current_balance || 7003.10).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  updateText("ribbon-gold-spread", `${goldMkt.spread_pips || 3.0} pips`);
  
  const ribbonGoldTrend = document.getElementById("ribbon-gold-trend");
  if (ribbonGoldTrend) ribbonGoldTrend.textContent = goldMkt.trend || "BULLISH";

  const ribbonGoldNews = document.getElementById("ribbon-gold-news");
  if (ribbonGoldNews) {
    ribbonGoldNews.textContent = news.blackout_active ? "BLACKOUT" : "CLEAR";
    ribbonGoldNews.style.color = news.blackout_active ? "var(--red)" : "var(--green)";
  }

  // Forex Ribbon
  const forexPairs = forex.pairs || [];
  const eurusd = forexPairs.find((p) => p.symbol === "EURUSD") || { spot_price: 1.1340 };
  const gbpusd = forexPairs.find((p) => p.symbol === "GBPUSD") || { spot_price: 1.3217 };
  const usdjpy = forexPairs.find((p) => p.symbol === "USDJPY") || { spot_price: 157.48 };

  updateText("ribbon-forex-price", `${eurusd.spot_price.toFixed(5)} EURUSD`, true);
  updateText("ribbon-forex-gbp", gbpusd.spot_price.toFixed(5));
  updateText("ribbon-forex-jpy", usdjpy.spot_price.toFixed(3));
  updateText("ribbon-forex-session", forex.active_session || "LONDON / NY OVERLAP");

  // Synthetic Ribbon
  const synCap = syn.capital || {};
  const synMkt = syn.market_status || {};
  updateText("ribbon-deriv-price", `${(synMkt.spot_price || 23422.31).toFixed(2)} 1HZ90V`, true);
  updateText("ribbon-deriv-balance", `$${(synCap.current_balance || 8428.34).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  const synPnl = synCap.net_pnl_usd !== undefined ? synCap.net_pnl_usd : (synCap.daily_pnl_usd || -1571.66);
  updateText("ribbon-deriv-pnl", `${synPnl >= 0 ? "+" : ""}$${synPnl.toFixed(2)}`);

  // --- TAB 0: OVERVIEW ---
  updateText("ov-total-balance", `$${(port.total_balance_usd || 15431.44).toLocaleString("en-US", { minimumFractionDigits: 2 })}`, true);
  updateText("ov-starting-balance", `เงินทุนเริ่มต้น: $${(port.total_starting_balance_usd || 17003.10).toLocaleString("en-US", { minimumFractionDigits: 2 })} | Deriv พอร์ตรวม: $${(port.total_deriv_assets_usd || 35431.44).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  
  const totalPnl = port.total_daily_pnl_usd || 0.00;
  updateText("ov-daily-pnl", `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`, true);
  const ovPnlBadge = document.getElementById("ov-pnl-badge");
  if (ovPnlBadge) {
    ovPnlBadge.textContent = `${totalPnl >= 0 ? "+" : ""}${(port.total_daily_pnl_pct || 0.00).toFixed(2)}%`;
  }
  updateText("ov-open-count", `${port.total_open_positions || 0} ไม้`, true);
  updateText("ov-open-sub", `${gold.open_positions_count || 0} ทองคำ | ${forex.open_positions_count || 0} Forex | ${syn.open_positions_count || 0} Deriv`);

  updateText("ov-gold-spot", `$${(goldMkt.spot_price || 2658.45).toFixed(2)}`);
  updateText("ov-gold-bal", `$${(goldCap.current_balance || 7003.10).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  const goldFloating = goldCap.floating_pnl !== undefined ? goldCap.floating_pnl : (goldCap.daily_pnl_usd || 0.00);
  updateText("ov-gold-pnl", `${goldFloating >= 0 ? "+" : ""}$${Number(goldFloating).toFixed(2)}`);
  const gCount = gold.open_positions_count || 0;
  const ovGoldRisk = document.getElementById("ov-gold-risk-badge");
  if (ovGoldRisk) {
    ovGoldRisk.textContent = gCount > 0 ? `${gCount} ไม้ (ACTIVE)` : "SAFE";
    ovGoldRisk.className = gCount > 0 ? "badge badge-active" : "badge badge-bullish";
  }

  updateText("ov-forex-price", `${eurusd.spot_price.toFixed(4)} / ${gbpusd.spot_price.toFixed(4)}`);
  const forexBalVal = forex.capital?.current_balance || goldCap.current_balance || 6977.48;
  updateText("ov-forex-bal", `cTrader #2548625 ($${Number(forexBalVal).toLocaleString("en-US", { minimumFractionDigits: 2 })})`);
  const forexFloating = forex.capital?.floating_pnl ?? 0.00;
  updateText("ov-forex-pnl", `${forexFloating >= 0 ? "+" : ""}$${Number(forexFloating).toFixed(2)}`);
  const fCount = forex.open_positions_count || 0;
  const ovForexBadge = document.getElementById("ov-forex-badge");
  if (ovForexBadge) {
    ovForexBadge.textContent = `${fCount} ไม้ (${fCount > 0 ? "ACTIVE" : "WAIT"})`;
    ovForexBadge.className = fCount > 0 ? "badge badge-active" : "badge badge-neutral";
  }

  updateText("ov-deriv-spot", (synMkt.spot_price || 23422.31).toFixed(2));
  updateText("ov-deriv-bal", `$${(synCap.current_balance || 8428.34).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);

  // --- TAB 1: GOLD ---
  updateText("gold-balance", `$${(goldCap.current_balance || 7003.10).toLocaleString("en-US", { minimumFractionDigits: 2 })}`, true);
  updateText("gold-equity", `$${(goldCap.equity || 7003.10).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  updateText("gold-margin", `${goldCap.margin_level_pct || 0}%`);
  updateText("gold-daily-pnl", `$${(goldCap.daily_pnl_usd || 0).toFixed(2)}`);
  updateText("gold-spot-price", `$${(goldMkt.spot_price || 2658.45).toFixed(2)}`, true);
  updateText("gold-spread", `${goldMkt.spread_pips || 3.0} pips`);
  updateText("gold-structure", goldMkt.market_structure || "BOS_LONG");
  const rsiVal = parseFloat(goldMkt.rsi_14 || 58.4);
  updateText("gold-rsi", rsiVal.toFixed(1));
  updateText("gold-atr", String(goldMkt.atr_14 || 4.85));
  updateText("gold-session", goldMkt.session || "London/NY Overlap");
  updateText("gold-active-count", `${gold.open_positions_count || 0} ไม้`);

  // Gold News Alert Banner
  const goldBanner = document.getElementById("gold-news-banner");
  const goldBannerTitle = document.getElementById("gold-banner-title");
  const goldBannerDesc = document.getElementById("gold-banner-desc");
  const goldBannerBadge = document.getElementById("gold-banner-badge");
  if (goldBanner && goldBannerTitle && goldBannerDesc && goldBannerBadge) {
    if (news.blackout_active) {
      goldBanner.className = "news-alert-banner";
      goldBannerTitle.textContent = "🚨 BLACKOUT ACTIVE: ตลาดทองคำผันผวนสูงจากข่าวเศรษฐกิจ";
      goldBannerDesc.textContent = `${news.blackout_reason}. ระบบสั่งหยุดเปิดไม้ใหม่เพื่อป้องกันเงินทุน`;
      goldBannerBadge.textContent = "BLACKOUT PAUSE";
      goldBannerBadge.className = "badge badge-high-impact";
    } else {
      goldBanner.className = "news-alert-banner clear";
      const nextTxt = news.next_event ? `${news.next_event.currency} ${news.next_event.title} ในอีก ${news.next_event.minutes_away} นาที` : "ไม่มีข่าวใหญ่ในระยะประชิด";
      goldBannerTitle.textContent = "🟢 GOLD MARKET LIQUIDITY CLEAR: สภาพคล่องทองคำปกติ";
      goldBannerDesc.textContent = `ข่าวสำคัญถัดไป: ${nextTxt}. ระบบพร้อมเทรดตามโครงสร้าง Trend Following`;
      goldBannerBadge.textContent = "SAFE TRADING";
      goldBannerBadge.className = "badge badge-bullish";
    }
  }

  renderGoldPositions(gold.open_positions || []);
  renderGoldOrders(gold.order_history || []);
  renderGoldHistory(gold.closed_trades_history || []);

  // --- TAB 2: FOREX ---
  const forexCap = forex.capital || {};
  updateText("forex-balance", `$${(forexCap.current_balance || 7003.10).toLocaleString("en-US", { minimumFractionDigits: 2 })}`, true);
  updateText("forex-equity", `$${(forexCap.equity || 7003.10).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  const forexFloatingPnl = forexCap.floating_pnl !== undefined ? forexCap.floating_pnl : (forexCap.daily_pnl_usd || 0.00);
  updateText("forex-floating-pnl", `${forexFloatingPnl >= 0 ? "+" : ""}$${Number(forexFloatingPnl).toFixed(2)}`);
  updateText("forex-margin", `$${(forexCap.margin_used || 0.00).toFixed(2)}`);
  updateText("forex-free-margin", `$${(forexCap.free_margin || 7003.10).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  updateText("forex-margin-level", `${(forexCap.margin_level_pct || 0.00).toFixed(2)}%`);
  updateText("forex-active-count", `${forex.open_positions_count || 0} ไม้`);
  updateText("forex-active-session", forex.active_session || "London / NY Overlap");
  renderForexPairs(forex.pairs || []);
  renderForexPositions(forex.open_positions || []);
  renderForexOrders(forex.order_history || []);
  renderForexTrades(forex.recent_trades || []);

  // --- TAB 3: SYNTHETIC ---
  const synOpenCount = syn.open_positions_count !== undefined ? syn.open_positions_count : (syn.open_positions?.length || 1);
  updateText("syn-active-count", `${synOpenCount} สัญญา`);
  updateText("syn-balance", `$${(synCap.current_balance || 8428.34).toLocaleString("en-US", { minimumFractionDigits: 2 })}`, true);
  const synFloating = synCap.floating_pnl !== undefined ? synCap.floating_pnl : 8.75;
  const synEq = synCap.equity || ((synCap.current_balance || 8428.34) + synFloating);
  updateText("syn-equity", `$${synEq.toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  updateText("syn-floating", `${synFloating >= 0 ? "+" : ""}$${synFloating.toFixed(2)}`);
  updateText("syn-pnl", `${synPnl >= 0 ? "+" : ""}$${synPnl.toFixed(2)} (${(synCap.net_pnl_pct || -15.72).toFixed(2)}%)`);
  updateText("syn-winrate", `${syn.performance?.win_rate_pct || 39.2}%`);
  updateText("syn-spot", (synMkt.spot_price || 21213.40).toFixed(2), true);
  updateText("syn-spread", `${(synMkt.spread_pips || 3.0).toFixed(1)} pts`);
  updateText("syn-structure", synMkt.market_structure || "BOS_LONG");
  updateText("syn-rsi", (synMkt.rsi_14 !== undefined ? Number(synMkt.rsi_14) : 52.4).toFixed(1));
  const synTrendBadge = document.getElementById("syn-trend-badge");
  if (synTrendBadge) {
    const isBull = synMkt.trend === "BULLISH";
    synTrendBadge.textContent = synMkt.trend || "BULLISH";
    synTrendBadge.className = isBull ? "badge badge-bullish" : "badge badge-bearish";
  }
  renderSyntheticPositions(syn.open_positions || []);
  renderDerivTrades(syn.recent_trades || []);

  // --- TAB 4: NEWS RADAR ---
  const nextEvent = news.next_event;
  if (nextEvent) {
    updateText("news-tab-countdown", nextEvent.minutes_away > 0 ? `อีก ${nextEvent.minutes_away} นาที` : "กำลังปล่อยข่าวสด");
    updateText("news-tab-title", `${nextEvent.currency} ${nextEvent.title} (${nextEvent.time_bkk})`);
    updateText("news-tab-directive", `คำสั่งความเสี่ยง: ${news.blackout_reason}`);
  } else {
    updateText("news-tab-countdown", "ไม่มีข่าวสำคัญ");
    updateText("news-tab-title", "ปฏิทินเศรษฐกิจเปิดทางสะดวก");
    updateText("news-tab-directive", "คำสั่งความเสี่ยง: สภาพตลาดปกติ สามารถเปิดไม้ได้เต็มประสิทธิภาพ");
  }
  renderNewsCalendar(news.upcoming_events || []);

  // --- TAB 5: AI-BRAIN ---
  updateText("brain-tab-latency", `${brain.avg_latency_ms || 142.5} ms`);
  updateText("brain-tab-evals", (brain.total_evaluations || 14280).toLocaleString());
  const dec = brain.decisions || {};
  updateText("brain-tab-buy", (dec.BUY || 1840).toLocaleString());
  updateText("brain-tab-sell", (dec.SELL || 2110).toLocaleString());
  updateText("brain-tab-hold", (dec.HOLD || 8940).toLocaleString());
  updateText("brain-tab-block", (dec.BLOCK || 1390).toLocaleString());
  renderBrainTraces(brain.recent_traces || []);
}

// 6. Zero-Flicker Table Renderers
function renderGoldPositions(positions) {
  const hash = JSON.stringify(positions);
  if (hash === lastGoldPositionsHash) return;
  lastGoldPositionsHash = hash;

  const tbody = document.getElementById("gold-positions-tbody");
  if (!tbody) return;

  if (positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-3); padding: 1.5rem;">ไม่มีไม้ค้างอยู่ในตลาด บอทกำลังเฝ้ารอจุดกลับตัวและเบรคเอาท์</td></tr>`;
    return;
  }

  let html = "";
  positions.forEach((p) => {
    const isBuy = p.direction.toUpperCase() === "BUY";
    const dirClass = isBuy ? "badge-bullish" : "badge-bearish";
    html += `
      <tr>
        <td><strong>#${p.position_id}</strong></td>
        <td><strong style="color: var(--accent-gold);">${p.symbol}</strong></td>
        <td><span class="badge ${dirClass}">${p.direction}</span></td>
        <td>${p.volume_lots} lots</td>
        <td>$${p.entry_price.toFixed(2)}</td>
        <td>$${p.sl_price > 0 ? p.sl_price.toFixed(2) : "-"}</td>
        <td>$${p.tp_price > 0 ? p.tp_price.toFixed(2) : "-"}</td>
        <td style="color: ${p.floating_pnl >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight: 700;">
          ${p.floating_pnl >= 0 ? "+" : ""}$${p.floating_pnl.toFixed(2)}
        </td>
        <td style="color: var(--text-3); font-size: 0.8rem;">${p.open_time.split("T")[1]?.slice(0, 8) || p.open_time}</td>
        <td><span class="badge badge-bullish">${p.status}</span></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderGoldOrders(orders) {
  const hash = JSON.stringify(orders);
  if (hash === lastGoldOrdersHash) return;
  lastGoldOrdersHash = hash;

  const tbody = document.getElementById("gold-orders-tbody");
  if (!tbody) return;

  if (!orders || orders.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-3); padding: 1rem;">ไม่มีประวัติคำสั่งซื้อขาย Gold ล่าสุด</td></tr>`;
    return;
  }

  let html = "";
  orders.forEach((o) => {
    const isBuy = o.direction.toUpperCase() === "BUY";
    const dirClass = isBuy ? "badge-bullish" : "badge-bearish";
    const statusClass = (o.status === "FILLED" || o.status === "EXECUTED") ? "badge-bullish" : (o.status === "CANCELLED" ? "badge-neutral" : "badge-neutral");
    html += `
      <tr>
        <td><strong>#${o.order_id}</strong></td>
        <td><strong style="color: var(--accent-gold);">${o.symbol}</strong></td>
        <td><span class="badge badge-neutral">${o.order_type}</span></td>
        <td><span class="badge ${dirClass}">${o.direction}</span></td>
        <td>${Number(o.volume_lots).toFixed(2)} lots</td>
        <td>$${Number(o.order_price).toFixed(2)}</td>
        <td>${o.fill_price ? `$${Number(o.fill_price).toFixed(2)}` : "-"}</td>
        <td>${o.sl_price > 0 ? `$${Number(o.sl_price).toFixed(2)}` : "-"}</td>
        <td>${o.tp_price > 0 ? `$${Number(o.tp_price).toFixed(2)}` : "-"}</td>
        <td style="color: var(--text-3); font-size: 0.8rem;">${o.created_at || "-"}</td>
        <td><span class="badge ${statusClass}">${o.status}</span></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderGoldHistory(trades) {
  const hash = JSON.stringify(trades);
  if (hash === lastGoldHistoryHash) return;
  lastGoldHistoryHash = hash;

  const tbody = document.getElementById("gold-history-tbody");
  if (!tbody) return;

  if (trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-3); padding: 1rem;">ไม่มีประวัติไม้ที่ปิดล่าสุด</td></tr>`;
    return;
  }

  let html = "";
  trades.slice().reverse().forEach((t) => {
    const isBuy = t.direction.toUpperCase() === "BUY";
    const dirClass = isBuy ? "badge-bullish" : "badge-bearish";
    const pnl = t.net_pnl || 0;
    html += `
      <tr>
        <td>#${t.position_id}</td>
        <td>${t.symbol}</td>
        <td><span class="badge ${dirClass}">${t.direction}</span></td>
        <td>${t.volume_lots} lots</td>
        <td>$${t.entry_price.toFixed(2)}</td>
        <td>$${t.exit_price.toFixed(2)}</td>
        <td style="color: ${pnl >= 0 ? "var(--green)" : "var(--red)"}; font-weight: 700;">
          ${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}
        </td>
        <td style="color: var(--text-3); font-size: 0.8rem;">${t.close_time.split("T")[1]?.slice(0, 8) || "-"}</td>
        <td><span class="badge badge-neutral">${t.status}</span></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderForexPairs(pairs) {
  const hash = JSON.stringify(pairs);
  if (hash === lastForexPairsHash) return;
  lastForexPairsHash = hash;

  const tbody = document.getElementById("forex-pairs-tbody");
  if (!tbody) return;

  let html = "";
  pairs.forEach((p) => {
    const isBull = p.trend === "BULLISH";
    html += `
      <tr>
        <td><strong style="color: var(--accent-forex); font-size: 0.95rem;">${p.symbol}</strong></td>
        <td><strong>${p.spot_price.toFixed(p.symbol.includes("JPY") ? 2 : 4)}</strong></td>
        <td style="color: var(--text-3);">${p.bid.toFixed(p.symbol.includes("JPY") ? 2 : 4)} / ${p.ask.toFixed(p.symbol.includes("JPY") ? 2 : 4)}</td>
        <td>${p.spread_pips} pips</td>
        <td><span class="badge ${isBull ? "badge-bullish" : "badge-bearish"}">${p.trend}</span></td>
        <td><strong>${p.structure}</strong></td>
        <td>${p.rsi}</td>
        <td>${p.atr}</td>
        <td><span class="badge badge-forex">${p.strategy}</span></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderForexPositions(positions) {
  const hash = JSON.stringify(positions);
  if (hash === lastForexPositionsHash) return;
  lastForexPositionsHash = hash;

  const tbody = document.getElementById("forex-positions-tbody");
  if (!tbody) return;

  if (!positions || positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-3); padding: 1.25rem;">ไม่มีไม้ Forex ค้างอยู่ — บอทกำลังรอ Breakout ตามเซสชัน</td></tr>`;
    return;
  }

  let html = "";
  positions.forEach((p) => {
    const isBuy = p.direction.toUpperCase() === "BUY";
    const dirClass = isBuy ? "badge-bullish" : "badge-bearish";
    const dec = (p.symbol && p.symbol.includes("JPY")) ? 3 : 5;
    html += `
      <tr>
        <td><strong>#${p.position_id}</strong></td>
        <td><strong style="color: var(--accent-forex);">${p.symbol}</strong></td>
        <td><span class="badge ${dirClass}">${p.direction}</span></td>
        <td>${Number(p.volume_lots).toFixed(2)} lots</td>
        <td>${Number(p.entry_price).toFixed(dec)}</td>
        <td>${p.sl_price > 0 ? Number(p.sl_price).toFixed(dec) : "-"}</td>
        <td>${p.tp_price > 0 ? Number(p.tp_price).toFixed(dec) : "-"}</td>
        <td style="color: ${p.floating_pnl >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight: 700;">
          ${p.floating_pnl >= 0 ? "+" : ""}$${Number(p.floating_pnl).toFixed(2)}
        </td>
        <td style="color: var(--text-3); font-size: 0.8rem;">${p.open_time?.split("T")[1]?.slice(0, 8) || p.open_time || "-"}</td>
        <td><span class="badge badge-bullish">${p.status}</span></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderForexOrders(orders) {
  const hash = JSON.stringify(orders);
  if (hash === lastForexOrdersHash) return;
  lastForexOrdersHash = hash;

  const tbody = document.getElementById("forex-orders-tbody");
  if (!tbody) return;

  if (!orders || orders.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-3); padding: 1rem;">ไม่มีประวัติคำสั่งซื้อขาย Forex ล่าสุด</td></tr>`;
    return;
  }

  let html = "";
  orders.forEach((o) => {
    const isBuy = o.direction.toUpperCase() === "BUY";
    const dirClass = isBuy ? "badge-bullish" : "badge-bearish";
    const statusClass = (o.status === "FILLED" || o.status === "EXECUTED") ? "badge-bullish" : (o.status === "CANCELLED" ? "badge-neutral" : "badge-neutral");
    html += `
      <tr>
        <td><strong>#${o.order_id}</strong></td>
        <td><strong style="color: var(--accent-forex);">${o.symbol}</strong></td>
        <td><span class="badge badge-neutral">${o.order_type}</span></td>
        <td><span class="badge ${dirClass}">${o.direction}</span></td>
        <td>${Number(o.volume_lots).toFixed(2)} lots</td>
        <td>${Number(o.order_price).toFixed(4)}</td>
        <td>${o.fill_price ? Number(o.fill_price).toFixed(4) : "-"}</td>
        <td>${o.sl_price > 0 ? Number(o.sl_price).toFixed(4) : "-"}</td>
        <td>${o.tp_price > 0 ? Number(o.tp_price).toFixed(4) : "-"}</td>
        <td style="color: var(--text-3); font-size: 0.8rem;">${o.created_at || "-"}</td>
        <td><span class="badge ${statusClass}">${o.status}</span></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderForexTrades(trades) {
  const hash = JSON.stringify(trades);
  if (hash === lastForexTradesHash) return;
  lastForexTradesHash = hash;

  const tbody = document.getElementById("forex-trades-history-tbody");
  if (!tbody) return;

  let html = "";
  trades.forEach((t) => {
    html += `
      <tr>
        <td><strong>${t.trade_id}</strong></td>
        <td>${t.symbol}</td>
        <td><span class="badge badge-bullish">${t.direction}</span></td>
        <td>${t.volume_lots} lots</td>
        <td>${t.entry_price}</td>
        <td>${t.exit_price}</td>
        <td style="color: var(--green); font-weight: 700;">+$${t.net_pnl.toFixed(2)}</td>
        <td><span class="badge badge-bullish">${t.exit_reason}</span></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderSyntheticPositions(positions) {
  const hash = JSON.stringify(positions);
  if (hash === lastDerivPositionsHash) return;
  lastDerivPositionsHash = hash;

  const tbody = document.getElementById("syn-positions-tbody");
  if (!tbody) return;

  if (!positions || positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-3); padding: 1.25rem;">ไม่มี Position ที่เปิดอยู่ — บอทกำลังรอจังหวะเข้าสัญญา Multipliers</td></tr>`;
    return;
  }

  let html = "";
  positions.forEach((p) => {
    const isLong = p.direction.toUpperCase() === "LONG" || p.direction.toUpperCase() === "BUY";
    const dirClass = isLong ? "badge-bullish" : "badge-bearish";
    const pnl = p.floating_pnl || 0;
    const entryNum = Number(p.entry_price || 0);
    const currNum = Number(p.current_price || p.entry_price || 0);
    const entryStr = entryNum > 0 && entryNum < 10 ? entryNum.toFixed(4) : entryNum.toFixed(2);
    const currStr = currNum > 0 && currNum < 10 ? currNum.toFixed(4) : currNum.toFixed(2);
    const contractDisplay = p.symbol ? `${p.symbol} ${p.contract_type || "Multipliers"}` : (p.contract_type || "Multipliers");
    html += `
      <tr>
        <td><strong>#${p.position_id}</strong></td>
        <td><strong style="color: var(--accent-syn);">${contractDisplay}</strong></td>
        <td><span class="badge ${dirClass}">${p.direction}</span></td>
        <td>$${Number(p.stake || 9.5).toFixed(2)}</td>
        <td>x${p.multiplier || 100}</td>
        <td>${entryStr}</td>
        <td>${currStr}</td>
        <td style="color: var(--red);">$${Number(p.sl_amount || 4.75).toFixed(2)}</td>
        <td style="color: var(--green);">$${Number(p.tp_amount || 9.50).toFixed(2)}</td>
        <td style="color: ${pnl >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight: 700;">
          ${pnl >= 0 ? "+" : ""}$${Number(pnl).toFixed(2)}
        </td>
        <td><span class="badge badge-bullish">${p.status || "OPEN"}</span></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderDerivTrades(trades) {
  const hash = JSON.stringify(trades);
  if (hash === lastDerivTradesHash) return;
  lastDerivTradesHash = hash;

  const tbody = document.getElementById("syn-trades-tbody");
  if (!tbody) return;

  if (trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-3); padding: 1rem;">ไม่มีประวัติสัญญา Multipliers ล่าสุด</td></tr>`;
    return;
  }

  let html = "";
  trades.slice().reverse().forEach((t) => {
    const isLong = t.direction.toUpperCase() === "LONG";
    const dirClass = isLong ? "badge-bullish" : "badge-bearish";
    const pnl = t.net_pnl || 0;
    html += `
      <tr>
        <td><strong>#${t.trade_id}</strong></td>
        <td><strong style="color: var(--accent-syn);">${t.contract_type}</strong></td>
        <td><span class="badge ${dirClass}">${t.direction}</span></td>
        <td>${t.entry_price.toFixed(2)}</td>
        <td>${t.exit_price.toFixed(2)}</td>
        <td><span class="badge ${t.exit_reason === "TAKE_PROFIT" ? "badge-bullish" : "badge-bearish"}">${t.exit_reason}</span></td>
        <td>${t.duration_bars} แท่ง (${t.duration_bars * 5}m)</td>
        <td style="color: ${pnl >= 0 ? "var(--green)" : "var(--red)"}; font-weight: 700;">${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}</td>
        <td>$${t.balance_after.toFixed(2)}</td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderNewsCalendar(events) {
  const hash = JSON.stringify(events);
  if (hash === lastNewsCalendarHash) return;
  lastNewsCalendarHash = hash;

  const tbody = document.getElementById("news-tab-calendar-tbody");
  if (!tbody) return;

  let html = "";
  events.forEach((e) => {
    let impactClass = "badge-neutral";
    if (e.impact === "HIGH") impactClass = "badge-high-impact";
    else if (e.impact === "MEDIUM") impactClass = "badge-neutral";

    html += `
      <tr>
        <td><strong>${e.date}</strong> ${e.time_bkk}</td>
        <td style="color: var(--text-3);">${e.time_utc}</td>
        <td><strong>${e.currency}</strong></td>
        <td><strong>${e.title}</strong></td>
        <td><span class="badge ${impactClass}">${e.impact}</span></td>
        <td>${e.forecast} ${e.unit}</td>
        <td style="color: var(--text-3);">${e.previous}</td>
        <td><span class="badge ${e.minutes_away <= 30 && e.minutes_away >= 0 ? "badge-high-impact" : "badge-neutral"}">${e.countdown}</span></td>
        <td style="font-size: 0.8rem; color: var(--text-3);">${e.gold_scenario}</td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderBrainTraces(traces) {
  const hash = JSON.stringify(traces);
  if (hash === lastBrainTracesHash) return;
  lastBrainTracesHash = hash;

  const tbody = document.getElementById("brain-tab-traces-tbody");
  if (!tbody) return;

  if (traces.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-3); padding: 1rem;">กำลังรอการประเมินสัญญาณรอบถัดไป...</td></tr>`;
    return;
  }

  let html = "";
  traces.slice().reverse().forEach((tr) => {
    const dec = tr.final_decision;
    let badgeClass = "badge-neutral";
    if (dec === "BUY") badgeClass = "badge-bullish";
    else if (dec === "SELL") badgeClass = "badge-bearish";
    else if (dec === "BLOCK") badgeClass = "badge-high-impact";

    const reasons = (tr.proposal?.reasons && tr.proposal.reasons.length > 0)
      ? tr.proposal.reasons.join(", ")
      : (tr.block_reason || tr.validation?.reason || tr.proposal?.rationale || "-");
    const tsTime = tr.timestamp
      ? (tr.timestamp.includes("T") ? tr.timestamp.split("T")[1]?.slice(0, 8) : tr.timestamp)
      : "-";
    const latencyVal = Number(tr.latency_ms || 0).toFixed(1);

    html += `
      <tr>
        <td style="color: var(--text-3); font-size: 0.8rem;">${tsTime}</td>
        <td><strong>${tr.symbol || "XAUUSD"}</strong></td>
        <td><span class="badge badge-neutral">${tr.market_type || "MARKET"}</span></td>
        <td><span class="badge ${badgeClass}">${dec}</span></td>
        <td>${((tr.llm_confidence || 0) * 100).toFixed(0)}%</td>
        <td style="color: var(--accent-forex); font-weight: 600;">${tr.provider || "AI-Ensemble"}</td>
        <td>${latencyVal} ms</td>
        <td style="font-size: 0.8rem; max-width: 320px; white-space: normal;">${reasons}</td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

// 7. Data Streaming & Polling Controller
function startStreaming() {
  const syncStatus = document.getElementById("sync-status");

  if (!!window.EventSource) {
    const evtSource = new EventSource("/api/stream");

    evtSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        applySnapshot(data);
        if (syncStatus) syncStatus.textContent = "LIVE";
      } catch (err) {
        console.error("SSE parse error", err);
      }
    };

    evtSource.onerror = (err) => {
      // Gracefully fallback to fast polling without changing UI to confusing technical labels
      evtSource.close();
      startPolling();
    };
  } else {
    startPolling();
  }
}

function startPolling() {
  fetchStatus();
  setInterval(fetchStatus, 1500);
}

function fetchStatus() {
  fetch("/api/status")
    .then((res) => res.json())
    .then((data) => {
      applySnapshot(data);
      const syncStatus = document.getElementById("sync-status");
      if (syncStatus) syncStatus.textContent = "LIVE";
    })
    .catch((err) => {
      console.error("Fetch status error:", err);
      const syncStatus = document.getElementById("sync-status");
      if (syncStatus) syncStatus.textContent = "OFFLINE";
    });
}

document.getElementById("refresh-btn")?.addEventListener("click", () => {
  fetchStatus();
});

// 8. Weekly Checklist Report Modal Controller
(function initWeeklyReportModal() {
  const reportModal = document.getElementById("weekly-report-modal");
  const reportBtn = document.getElementById("weekly-report-btn");
  const closeBtn = document.getElementById("modal-close-btn");
  const dismissBtn = document.getElementById("btn-dismiss-modal");
  const copyBtn = document.getElementById("btn-copy-report");
  const copyText = document.getElementById("btn-copy-text");
  const copyIcon = document.getElementById("btn-copy-icon");

  const loadingEl = document.getElementById("modal-loading");
  const gridEl = document.getElementById("checklist-grid");
  const dateLabel = document.getElementById("modal-date-label");

  let currentMarkdown = "";

  function openModal() {
    if (!reportModal) return;
    reportModal.style.display = "flex";
    if (loadingEl) loadingEl.style.display = "block";
    if (gridEl) gridEl.style.display = "none";

    fetch("/api/weekly-report")
      .then((res) => res.json())
      .then((data) => {
        currentMarkdown = data.formatted_markdown || "";

        if (dateLabel) dateLabel.textContent = `รอบสัปดาห์วันที่ ${data.date_label || "-"}`;

        // Category 1: Weekly Performance
        const wp = data.weekly_performance || {};
        updateText("rep-weekly-count", String(wp.trades_count || 0), true);
        const wlEl = document.getElementById("rep-weekly-wl");
        if (wlEl) wlEl.textContent = `ชนะ ${wp.wins || 0} / แพ้ ${wp.losses || 0}`;
        const wrEl = document.getElementById("rep-weekly-wr");
        if (wrEl) wrEl.textContent = `${wp.win_rate_pct || 0}%`;
        const pnlEl = document.getElementById("rep-weekly-pnl");
        if (pnlEl) {
          const pnlVal = wp.net_pnl_usd || 0;
          pnlEl.textContent = `${pnlVal >= 0 ? "+" : ""}$${pnlVal.toFixed(2)}`;
          pnlEl.className = `c-value num ${pnlVal >= 0 ? "text-green" : "text-red"}`;
        }
        const ddEl = document.getElementById("rep-weekly-dd");
        if (ddEl) ddEl.textContent = `-$${wp.max_drawdown_usd || 0} (-${wp.max_drawdown_pct || 0}%)`;

        // Category 2: Cumulative All-Time Stats
        const cs = data.cumulative_stats || {};
        updateText("rep-cum-trades", `${cs.trades_count || 0}/${cs.target_milestone || 100}`, true);
        const cumWrEl = document.getElementById("rep-cum-wr");
        if (cumWrEl) cumWrEl.textContent = `${cs.win_rate_pct || 0}%`;
        const cumPfEl = document.getElementById("rep-cum-pf");
        if (cumPfEl) cumPfEl.textContent = String(cs.profit_factor || "1.0");

        // Category 3: Execution Audit
        const ea = data.execution_audit || {};
        const sltp = ea.sl_tp_integrity || {};
        const cd = ea.cooldown_check || {};
        const sp = ea.slippage_spread_check || {};

        const sltpBadge = document.getElementById("rep-audit-sltp");
        if (sltpBadge) sltpBadge.textContent = sltp.label || "PASS";
        updateText("rep-audit-sltp-desc", sltp.detail || "-");

        const cdBadge = document.getElementById("rep-audit-cooldown");
        if (cdBadge) cdBadge.textContent = cd.label || "PASS";
        updateText("rep-audit-cooldown-desc", cd.detail || "-");

        const spBadge = document.getElementById("rep-audit-spread");
        if (spBadge) spBadge.textContent = sp.label || "PASS";
        updateText("rep-audit-spread-desc", sp.detail || "-");

        // Category 4: Market Context Note
        const mc = data.market_context || {};
        const noteEl = document.getElementById("rep-market-note");
        if (noteEl) noteEl.textContent = mc.note || "-";

        const evList = document.getElementById("rep-market-events");
        if (evList) {
          const events = mc.events || [];
          evList.innerHTML = events
            .map((ev) => `<span class="market-event-pill">⚡ ${ev}</span>`)
            .join("");
        }

        if (loadingEl) loadingEl.style.display = "none";
        if (gridEl) gridEl.style.display = "flex";
      })
      .catch((err) => {
        console.error("Failed to fetch weekly report", err);
        if (loadingEl) loadingEl.textContent = "ไม่สามารถโหลดข้อมูลรายงานได้ กรุณาลองใหม่อีกครั้ง";
      });
  }

  function closeModal() {
    if (reportModal) reportModal.style.display = "none";
  }

  reportBtn?.addEventListener("click", openModal);
  closeBtn?.addEventListener("click", closeModal);
  dismissBtn?.addEventListener("click", closeModal);

  // Close modal when clicking outside card
  reportModal?.addEventListener("click", (e) => {
    if (e.target === reportModal) closeModal();
  });

  // Copy report to clipboard
  copyBtn?.addEventListener("click", () => {
    if (!currentMarkdown) return;
    navigator.clipboard.writeText(currentMarkdown).then(() => {
      if (copyIcon) copyIcon.textContent = "✓";
      if (copyText) copyText.textContent = "คัดลอกเรียบร้อยแล้ว!";
      copyBtn.style.background = "var(--text-1)";
      setTimeout(() => {
        if (copyIcon) copyIcon.textContent = "📋";
        if (copyText) copyText.textContent = "คัดลอกรายงาน (Copy)";
        copyBtn.style.background = "var(--green)";
      }, 2000);
    });
  });
})();

document.addEventListener("DOMContentLoaded", () => {
  startStreaming();
});

