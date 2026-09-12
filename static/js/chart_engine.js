/**
 * QuantPro Terminal - High-Performance Charting Engine
 * File: js/chart_engine.js
 * 
 * High-Performance Charting Engineer Implementation
 * 
 * 1. Dual Engine Architecture:
 *    - Primary: TradingView Lightweight Charts (window.LightweightCharts)
 *    - Fallback: High-Performance Native HTML5 Canvas (Zero-dependency, Retina ready, 60 FPS, Pan & Zoom)
 * 2. Multi-Timeframe Charting (Top: M15, Bottom: H1)
 * 3. Candlesticks with Pro Trading Palette (Up: #10b981, Down: #ef4444)
 * 4. Technical Indicators:
 *    - Bollinger Bands (20, 2) Upper, Middle, Lower via LineSeries
 *    - EMA 50 LineSeries
 *    - Volume Histogram Series
 *    - RSI (14) Indicator Pane with Overbought (70) and Oversold (30) levels + Rebound Markers
 * 5. SMC (Smart Money Concepts) Liquidity Sweep Zones:
 *    - BSL (Buy-Side Liquidity) Order Block Zones
 *    - SSL (Sell-Side Liquidity) Order Block Zones
 * 6. Real-Time Tick Updates (`updateTick`) at 60 FPS without stutter or clearing
 * 7. In-Place Theme Switching (`setTheme`) Dark ⇄ Light preserving 100% zoom & candle history
 * 8. Real-Time Interactive SL / TP Price Line Markers (`updateSLTPMarkers`)
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    const engine = factory();
    root.ChartEngine = engine;
    root.chartEngine = engine; // lowercase alias for seamless app integration
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // =========================================================================
  // 1. THEME DEFINITIONS & COLOR PALETTES
  // =========================================================================
  const THEMES = {
    dark: {
      name: 'dark',
      bg: '#0b0f19',
      cardBg: '#111827',
      textColor: '#94a3b8',
      textSecondary: '#64748b',
      gridColor: '#1e293b',
      borderColor: '#1e293b',
      crosshairColor: '#475569',
      candleUp: '#10b981',
      candleDown: '#ef4444',
      wickUp: '#10b981',
      wickDown: '#ef4444',
      volUp: 'rgba(16, 185, 129, 0.35)',
      volDown: 'rgba(239, 68, 68, 0.35)',
      ema50: '#a855f7',
      bbUpper: '#38bdf8',
      bbMiddle: '#f59e0b',
      bbLower: '#38bdf8',
      bbArea: 'rgba(56, 189, 248, 0.05)',
      rsiLine: '#818cf8',
      rsiOB: '#ef4444',
      rsiOS: '#10b981',
      rsiBand: 'rgba(129, 140, 248, 0.06)',
      bslFill: 'rgba(239, 68, 68, 0.16)',
      bslBorder: '#ef4444',
      sslFill: 'rgba(16, 185, 129, 0.16)',
      sslBorder: '#10b981',
      slLine: '#ef4444',
      tpLine: '#10b981',
      paneSeparator: '#1e293b',
      legendBg: 'rgba(15, 23, 42, 0.85)'
    },
    light: {
      name: 'light',
      bg: '#ffffff',
      cardBg: '#f8fafc',
      textColor: '#475569',
      textSecondary: '#94a3b8',
      gridColor: '#f1f5f9',
      borderColor: '#e2e8f0',
      crosshairColor: '#cbd5e1',
      candleUp: '#10b981',
      candleDown: '#ef4444',
      wickUp: '#10b981',
      wickDown: '#ef4444',
      volUp: 'rgba(16, 185, 129, 0.45)',
      volDown: 'rgba(239, 68, 68, 0.45)',
      ema50: '#9333ea',
      bbUpper: '#0284c7',
      bbMiddle: '#d97706',
      bbLower: '#0284c7',
      bbArea: 'rgba(2, 132, 199, 0.05)',
      rsiLine: '#6366f1',
      rsiOB: '#dc2626',
      rsiOS: '#059669',
      rsiBand: 'rgba(99, 102, 241, 0.06)',
      bslFill: 'rgba(239, 68, 68, 0.14)',
      bslBorder: '#dc2626',
      sslFill: 'rgba(16, 185, 129, 0.14)',
      sslBorder: '#059669',
      slLine: '#dc2626',
      tpLine: '#059669',
      paneSeparator: '#e2e8f0',
      legendBg: 'rgba(255, 255, 255, 0.9)'
    }
  };

  // =========================================================================
  // 2. TECHNICAL INDICATOR ALGORITHMS (HIGH-SPEED VECTORIZED MATH)
  // =========================================================================
  const Indicators = {
    calculateEMA(candles, period = 50) {
      if (!candles || candles.length === 0) return [];
      const k = 2 / (period + 1);
      const result = [];
      let ema = candles[0].close;

      for (let i = 0; i < candles.length; i++) {
        const c = candles[i];
        if (i < period - 1) {
          ema = ((ema * i) + c.close) / (i + 1);
        } else if (i === period - 1) {
          let sum = 0;
          for (let j = 0; j < period; j++) sum += candles[j].close;
          ema = sum / period;
        } else {
          ema = (c.close * k) + (ema * (1 - k));
        }
        result.push({ time: c.time, value: parseFloat(ema.toFixed(4)) });
      }
      return result;
    },

    calculateBollingerBands(candles, period = 20, multiplier = 2) {
      if (!candles || candles.length === 0) return { upper: [], middle: [], lower: [] };
      const upper = [];
      const middle = [];
      const lower = [];

      for (let i = 0; i < candles.length; i++) {
        const c = candles[i];
        if (i < period - 1) {
          let sum = 0;
          for (let j = 0; j <= i; j++) sum += candles[j].close;
          const sma = sum / (i + 1);
          middle.push({ time: c.time, value: parseFloat(sma.toFixed(4)) });
          upper.push({ time: c.time, value: parseFloat((sma * 1.008).toFixed(4)) });
          lower.push({ time: c.time, value: parseFloat((sma * 0.992).toFixed(4)) });
          continue;
        }

        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) {
          sum += candles[j].close;
        }
        const sma = sum / period;

        let sqDiffSum = 0;
        for (let j = i - period + 1; j <= i; j++) {
          const diff = candles[j].close - sma;
          sqDiffSum += diff * diff;
        }
        const stdDev = Math.sqrt(sqDiffSum / period);

        const upVal = parseFloat((sma + (multiplier * stdDev)).toFixed(4));
        const midVal = parseFloat(sma.toFixed(4));
        const lowVal = parseFloat((sma - (multiplier * stdDev)).toFixed(4));

        middle.push({ time: c.time, value: midVal });
        upper.push({ time: c.time, value: upVal });
        lower.push({ time: c.time, value: lowVal });
      }

      return { upper, middle, lower };
    },

    calculateRSI(candles, period = 14) {
      if (!candles || candles.length === 0) return { rsi: [], markers: [] };
      const rsi = [];
      const markers = [];

      let gains = 0;
      let losses = 0;

      for (let i = 1; i <= period && i < candles.length; i++) {
        const change = candles[i].close - candles[i - 1].close;
        if (change >= 0) gains += change;
        else losses -= change;
      }

      let avgGain = gains / period;
      let avgLoss = losses / period;

      for (let i = 0; i < candles.length; i++) {
        const c = candles[i];
        if (i <= period) {
          rsi.push({ time: c.time, value: 50 });
          continue;
        }

        const change = candles[i].close - candles[i - 1].close;
        const currentGain = change > 0 ? change : 0;
        const currentLoss = change < 0 ? -change : 0;

        avgGain = ((avgGain * (period - 1)) + currentGain) / period;
        avgLoss = ((avgLoss * (period - 1)) + currentLoss) / period;

        let rsVal = 50;
        if (avgLoss === 0) {
          rsVal = 100;
        } else {
          const rs = avgGain / avgLoss;
          rsVal = 100 - (100 / (1 + rs));
        }

        const val = parseFloat(rsVal.toFixed(2));
        rsi.push({ time: c.time, value: val });

        // Check for rebound signals:
        // Bullish rebound: was <= 30 and crossed back above 30
        // Bearish rebound: was >= 70 and crossed back below 70
        const prevVal = rsi[rsi.length - 2]?.value ?? 50;
        if (prevVal <= 30 && val > 30) {
          markers.push({
            time: c.time,
            position: 'belowBar',
            color: '#10b981',
            shape: 'arrowUp',
            text: 'RSI Rebound ↗ (OS 30)',
            type: 'bullish_rebound'
          });
        } else if (prevVal >= 70 && val < 70) {
          markers.push({
            time: c.time,
            position: 'aboveBar',
            color: '#ef4444',
            shape: 'arrowDown',
            text: 'RSI Rebound ↘ (OB 70)',
            type: 'bearish_rebound'
          });
        }
      }

      return { rsi, markers };
    },

    detectSMCZones(candles, pivot = 4) {
      if (!candles || candles.length < pivot * 2 + 1) return [];
      const zones = [];

      for (let i = pivot; i < candles.length - pivot; i++) {
        const cur = candles[i];
        let isHigh = true;
        let isLow = true;

        for (let j = i - pivot; j <= i + pivot; j++) {
          if (j === i) continue;
          if (candles[j].high >= cur.high) isHigh = false;
          if (candles[j].low <= cur.low) isLow = false;
        }

        // BSL - Buy-Side Liquidity Pool / Bearish Order Block
        if (isHigh) {
          let swept = false;
          let sweptTime = null;
          for (let k = i + 1; k < Math.min(candles.length, i + 35); k++) {
            if (candles[k].high > cur.high && candles[k].close < cur.high) {
              swept = true;
              sweptTime = candles[k].time;
              break;
            }
          }

          zones.push({
            id: 'bsl_' + cur.time,
            type: 'BSL',
            label: swept ? 'BSL Liquidity Sweep' : 'BSL Order Block',
            high: cur.high,
            low: Math.max(cur.open, cur.close),
            timeStart: cur.time,
            timeEnd: sweptTime || (candles[Math.min(candles.length - 1, i + 30)].time),
            swept: swept
          });
        }

        // SSL - Sell-Side Liquidity Pool / Bullish Order Block
        if (isLow) {
          let swept = false;
          let sweptTime = null;
          for (let k = i + 1; k < Math.min(candles.length, i + 35); k++) {
            if (candles[k].low < cur.low && candles[k].close > cur.low) {
              swept = true;
              sweptTime = candles[k].time;
              break;
            }
          }

          zones.push({
            id: 'ssl_' + cur.time,
            type: 'SSL',
            label: swept ? 'SSL Liquidity Sweep' : 'SSL Order Block',
            high: Math.min(cur.open, cur.close),
            low: cur.low,
            timeStart: cur.time,
            timeEnd: sweptTime || (candles[Math.min(candles.length - 1, i + 30)].time),
            swept: swept
          });
        }
      }

      return zones.slice(-8); // Keep the most recent, most relevant zones
    }
  };

  // =========================================================================
  // 3. MOCK DATA GENERATOR (INSTANT SEEDING & OFFLINE SIMULATION)
  // =========================================================================
  function generateRealisticMarketData(count = 180, basePrice = 64500, intervalSeconds = 900) {
    const candles = [];
    let currentPrice = basePrice;
    const now = Math.floor(Date.now() / 1000);
    const startTime = now - (count * intervalSeconds);

    let trend = 1;
    const isCrypto = basePrice > 1000;
    const digits = isCrypto ? 2 : 5;

    for (let i = 0; i < count; i++) {
      const time = startTime + (i * intervalSeconds);
      if (i % 22 === 0) trend = (Math.random() > 0.48 ? 1 : -1);

      const relVol = isCrypto ? 0.0035 : 0.0008;
      const volatility = currentPrice * relVol;
      const drift = (Math.random() - 0.48 + (trend * 0.07)) * volatility;
      const open = currentPrice;
      const close = parseFloat((open + drift).toFixed(digits));
      const high = parseFloat((Math.max(open, close) + (Math.random() * volatility * 0.8)).toFixed(digits));
      const low = parseFloat((Math.min(open, close) - (Math.random() * volatility * 0.8)).toFixed(digits));
      const volume = Math.floor(50 + Math.random() * 450 + (Math.abs(close - open) / (volatility || 1) * 200));

      candles.push({ time, open, high, low, close, volume });
      currentPrice = close;
    }

    return candles;
  }

  // =========================================================================
  // 4. TRADINGVIEW LIGHTWEIGHT CHARTS IMPLEMENTATION
  // =========================================================================
  class LightweightChartWrapper {
    constructor(containerEl, timeframe, theme = 'dark') {
      this.container = typeof containerEl === 'string' ? document.getElementById(containerEl) : containerEl;
      this.timeframe = timeframe;
      this.currentTheme = theme;
      this.themeConfig = THEMES[theme] || THEMES.dark;

      this.chart = null;
      this.rsiChart = null;
      this.candlestickSeries = null;
      this.volumeSeries = null;
      this.emaSeries = null;
      this.bbUpperSeries = null;
      this.bbMiddleSeries = null;
      this.bbLowerSeries = null;
      this.rsiSeries = null;
      this.rsiOBLine = null;
      this.rsiOSLine = null;

      this.overlayCanvas = null;
      this.overlayCtx = null;
      this.smcZones = [];
      this.sltpPriceLines = new Map(); // positionId -> { slLine, tpLine }

      this.data = [];
      this.isDestroyed = false;

      this._init();
    }

    _init() {
      if (!this.container) return;
      this.container.innerHTML = '';
      this.container.style.position = 'relative';
      this.container.style.display = 'flex';
      this.container.style.flexDirection = 'column';
      this.container.style.width = '100%';
      this.container.style.height = '100%';
      this.container.style.overflow = 'hidden';
      this.container.style.backgroundColor = this.themeConfig.bg;

      // Create split sub-containers: Main chart (75%) and RSI pane (25%)
      this.mainBox = document.createElement('div');
      this.mainBox.style.position = 'relative';
      this.mainBox.style.width = '100%';
      this.mainBox.style.height = '75%';
      this.mainBox.style.flexShrink = '0';
      this.container.appendChild(this.mainBox);

      this.rsiBox = document.createElement('div');
      this.rsiBox.style.position = 'relative';
      this.rsiBox.style.width = '100%';
      this.rsiBox.style.height = '25%';
      this.rsiBox.style.flexShrink = '0';
      this.rsiBox.style.borderTop = `1px solid ${this.themeConfig.borderColor}`;
      this.container.appendChild(this.rsiBox);

      // SMC Overlay canvas for BSL/SSL zones
      this.overlayCanvas = document.createElement('canvas');
      this.overlayCanvas.style.position = 'absolute';
      this.overlayCanvas.style.top = '0';
      this.overlayCanvas.style.left = '0';
      this.overlayCanvas.style.width = '100%';
      this.overlayCanvas.style.height = '100%';
      this.overlayCanvas.style.pointerEvents = 'none';
      this.overlayCanvas.style.zIndex = '5';
      this.mainBox.appendChild(this.overlayCanvas);
      this.overlayCtx = this.overlayCanvas.getContext('2d');

      const LC = window.LightweightCharts;

      // 1. Create Main Chart
      this.chart = LC.createChart(this.mainBox, {
        width: this.mainBox.clientWidth || 800,
        height: this.mainBox.clientHeight || 450,
        layout: {
          background: { type: 'solid', color: this.themeConfig.bg },
          textColor: this.themeConfig.textColor,
          fontSize: 11,
          fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
        },
        grid: {
          vertLines: { color: this.themeConfig.gridColor },
          horzLines: { color: this.themeConfig.gridColor }
        },
        crosshair: {
          vertLine: { color: this.themeConfig.crosshairColor, width: 1, style: LC.LineStyle.Dashed },
          horzLine: { color: this.themeConfig.crosshairColor, width: 1, style: LC.LineStyle.Dashed }
        },
        rightPriceScale: {
          borderColor: this.themeConfig.borderColor,
          scaleMargins: { top: 0.1, bottom: 0.2 }
        },
        timeScale: {
          borderColor: this.themeConfig.borderColor,
          timeVisible: true,
          secondsVisible: false
        }
      });

      // 2. Candlestick Series
      this.candlestickSeries = this.chart.addCandlestickSeries({
        upColor: this.themeConfig.candleUp,
        downColor: this.themeConfig.candleDown,
        wickUpColor: this.themeConfig.wickUp,
        wickDownColor: this.themeConfig.wickDown,
        borderVisible: false
      });

      // 3. Volume Histogram Series
      this.volumeSeries = this.chart.addHistogramSeries({
        color: this.themeConfig.volUp,
        priceFormat: { type: 'volume' },
        priceScaleId: '', // overlay scale
        scaleMargins: { top: 0.82, bottom: 0 }
      });

      // 4. Bollinger Bands (Upper, Middle, Lower)
      this.bbUpperSeries = this.chart.addLineSeries({
        color: this.themeConfig.bbUpper,
        lineWidth: 1,
        title: 'BB Upper'
      });
      this.bbMiddleSeries = this.chart.addLineSeries({
        color: this.themeConfig.bbMiddle,
        lineWidth: 1,
        lineStyle: LC.LineStyle.Dashed,
        title: 'BB Mid (SMA 20)'
      });
      this.bbLowerSeries = this.chart.addLineSeries({
        color: this.themeConfig.bbLower,
        lineWidth: 1,
        title: 'BB Lower'
      });

      // 5. EMA 50
      this.emaSeries = this.chart.addLineSeries({
        color: this.themeConfig.ema50,
        lineWidth: 2,
        title: 'EMA 50'
      });

      // 6. RSI Chart (Bottom Pane)
      this.rsiChart = LC.createChart(this.rsiBox, {
        width: this.rsiBox.clientWidth || 800,
        height: this.rsiBox.clientHeight || 150,
        layout: {
          background: { type: 'solid', color: this.themeConfig.bg },
          textColor: this.themeConfig.textColor,
          fontSize: 10,
          fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
        },
        grid: {
          vertLines: { color: this.themeConfig.gridColor },
          horzLines: { color: this.themeConfig.gridColor }
        },
        crosshair: {
          vertLine: { color: this.themeConfig.crosshairColor, width: 1, style: LC.LineStyle.Dashed },
          horzLine: { color: this.themeConfig.crosshairColor, width: 1, style: LC.LineStyle.Dashed }
        },
        rightPriceScale: {
          borderColor: this.themeConfig.borderColor,
          scaleMargins: { top: 0.1, bottom: 0.1 }
        },
        timeScale: {
          visible: false, // Time axis shared with top chart
          borderColor: this.themeConfig.borderColor
        }
      });

      this.rsiSeries = this.rsiChart.addLineSeries({
        color: this.themeConfig.rsiLine,
        lineWidth: 2,
        title: 'RSI (14)'
      });

      // RSI Overbought (70) and Oversold (30) reference lines
      this.rsiOBLine = this.rsiSeries.createPriceLine({
        price: 70,
        color: this.themeConfig.rsiOB,
        lineWidth: 1,
        lineStyle: LC.LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'OB 70'
      });

      this.rsiOSLine = this.rsiSeries.createPriceLine({
        price: 30,
        color: this.themeConfig.rsiOS,
        lineWidth: 1,
        lineStyle: LC.LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'OS 30'
      });

      // Synchronize time scales between Main Chart and RSI Pane
      let isSyncing = false;
      this.chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (isSyncing || !range) return;
        isSyncing = true;
        this.rsiChart.timeScale().setVisibleLogicalRange(range);
        this._renderSMCZones();
        isSyncing = false;
      });

      this.rsiChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (isSyncing || !range) return;
        isSyncing = true;
        this.chart.timeScale().setVisibleLogicalRange(range);
        this._renderSMCZones();
        isSyncing = false;
      });

      // Resize observer
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(this.container);
      window.addEventListener('resize', () => this.resize());
    }

    resize() {
      if (!this.container || !this.chart || !this.rsiChart) return;
      const w = this.container.clientWidth;
      const h = this.container.clientHeight;
      if (w <= 0 || h <= 0) return;

      const mainH = Math.floor(h * 0.75);
      const rsiH = h - mainH;

      this.mainBox.style.height = mainH + 'px';
      this.rsiBox.style.height = rsiH + 'px';

      this.chart.resize(w, mainH);
      this.rsiChart.resize(w, rsiH);

      // Sync overlay canvas resolution
      const dpr = window.devicePixelRatio || 1;
      this.overlayCanvas.width = w * dpr;
      this.overlayCanvas.height = mainH * dpr;
      this.overlayCanvas.style.width = w + 'px';
      this.overlayCanvas.style.height = mainH + 'px';
      this.overlayCtx.scale(dpr, dpr);

      this._renderSMCZones();
    }

    setData(candles) {
      if (!candles || candles.length === 0) return;
      this.data = candles.slice();

      // Format for TradingView
      const formattedCandles = this.data.map(c => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close
      }));

      const formattedVolume = this.data.map(c => ({
        time: c.time,
        value: c.volume || 100,
        color: c.close >= c.open ? this.themeConfig.volUp : this.themeConfig.volDown
      }));

      this.candlestickSeries.setData(formattedCandles);
      this.volumeSeries.setData(formattedVolume);

      // Indicators
      const emaData = Indicators.calculateEMA(this.data, 50);
      const bbData = Indicators.calculateBollingerBands(this.data, 20, 2);
      const rsiResult = Indicators.calculateRSI(this.data, 14);

      this.emaSeries.setData(emaData);
      this.bbUpperSeries.setData(bbData.upper);
      this.bbMiddleSeries.setData(bbData.middle);
      this.bbLowerSeries.setData(bbData.lower);

      this.rsiSeries.setData(rsiResult.rsi);
      if (rsiResult.markers && rsiResult.markers.length > 0) {
        this.rsiSeries.setMarkers(rsiResult.markers);
      }

      // Auto-detect SMC zones
      this.smcZones = Indicators.detectSMCZones(this.data);
      setTimeout(() => this._renderSMCZones(), 50);
    }

    updateTick(tick) {
      if (!tick) return;
      const lastCandle = this.data[this.data.length - 1];
      let updatedCandle;

      if (typeof tick.price === 'number') {
        // Micro price tick
        if (!lastCandle) return;
        const p = tick.price;
        const v = tick.volume || 1;
        updatedCandle = {
          time: lastCandle.time,
          open: lastCandle.open,
          high: Math.max(lastCandle.high, p),
          low: Math.min(lastCandle.low, p),
          close: p,
          volume: (lastCandle.volume || 0) + v
        };
        this.data[this.data.length - 1] = updatedCandle;
      } else {
        // Full candle tick
        const tickTime = typeof tick.time === 'string' ? Math.floor(new Date(tick.time).getTime() / 1000) : tick.time;
        updatedCandle = {
          time: tickTime,
          open: tick.open,
          high: tick.high,
          low: tick.low,
          close: tick.close,
          volume: tick.volume || 100
        };

        if (lastCandle && lastCandle.time === tickTime) {
          this.data[this.data.length - 1] = updatedCandle;
        } else {
          this.data.push(updatedCandle);
          if (this.data.length > 1000) this.data.shift();
        }
      }

      // High-performance 60 FPS update via series.update()
      this.candlestickSeries.update({
        time: updatedCandle.time,
        open: updatedCandle.open,
        high: updatedCandle.high,
        low: updatedCandle.low,
        close: updatedCandle.close
      });

      this.volumeSeries.update({
        time: updatedCandle.time,
        value: updatedCandle.volume,
        color: updatedCandle.close >= updatedCandle.open ? this.themeConfig.volUp : this.themeConfig.volDown
      });

      // Incremental indicator updates
      const recent = this.data.slice(-55);
      const emaRes = Indicators.calculateEMA(recent, 50);
      const bbRes = Indicators.calculateBollingerBands(recent, 20, 2);
      const rsiRes = Indicators.calculateRSI(this.data.slice(-30), 14);

      if (emaRes.length) this.emaSeries.update(emaRes[emaRes.length - 1]);
      if (bbRes.upper.length) {
        this.bbUpperSeries.update(bbRes.upper[bbRes.upper.length - 1]);
        this.bbMiddleSeries.update(bbRes.middle[bbRes.middle.length - 1]);
        this.bbLowerSeries.update(bbRes.lower[bbRes.lower.length - 1]);
      }
      if (rsiRes.rsi.length) {
        this.rsiSeries.update(rsiRes.rsi[rsiRes.rsi.length - 1]);
      }
    }

    setTheme(themeName) {
      const t = THEMES[themeName];
      if (!t) return;
      this.currentTheme = themeName;
      this.themeConfig = t;

      this.container.style.backgroundColor = t.bg;
      this.rsiBox.style.borderTop = `1px solid ${t.borderColor}`;

      // In-place update preserving zoom, scroll & series state 100%
      const chartOpts = {
        layout: {
          background: { type: 'solid', color: t.bg },
          textColor: t.textColor
        },
        grid: {
          vertLines: { color: t.gridColor },
          horzLines: { color: t.gridColor }
        },
        crosshair: {
          vertLine: { color: t.crosshairColor },
          horzLine: { color: t.crosshairColor }
        },
        rightPriceScale: { borderColor: t.borderColor },
        timeScale: { borderColor: t.borderColor }
      };

      this.chart.applyOptions(chartOpts);
      this.rsiChart.applyOptions(chartOpts);

      this.candlestickSeries.applyOptions({
        upColor: t.candleUp,
        downColor: t.candleDown,
        wickUpColor: t.wickUp,
        wickDownColor: t.wickDown
      });

      this.emaSeries.applyOptions({ color: t.ema50 });
      this.bbUpperSeries.applyOptions({ color: t.bbUpper });
      this.bbMiddleSeries.applyOptions({ color: t.bbMiddle });
      this.bbLowerSeries.applyOptions({ color: t.bbLower });
      this.rsiSeries.applyOptions({ color: t.rsiLine });

      if (this.rsiOBLine) this.rsiOBLine.applyOptions({ color: t.rsiOB });
      if (this.rsiOSLine) this.rsiOSLine.applyOptions({ color: t.rsiOS });

      this._renderSMCZones();
    }

    updateSLTPMarkers(positionId, slPrice, tpPrice) {
      const LC = window.LightweightCharts;
      let lines = this.sltpPriceLines.get(positionId);

      if (!lines) {
        lines = {};
        if (typeof slPrice === 'number' && slPrice > 0) {
          lines.slLine = this.candlestickSeries.createPriceLine({
            price: slPrice,
            color: this.themeConfig.slLine,
            lineWidth: 2,
            lineStyle: LC.LineStyle.Dashed,
            axisLabelVisible: true,
            title: `SL [${positionId}]`
          });
        }
        if (typeof tpPrice === 'number' && tpPrice > 0) {
          lines.tpLine = this.candlestickSeries.createPriceLine({
            price: tpPrice,
            color: this.themeConfig.tpLine,
            lineWidth: 2,
            lineStyle: LC.LineStyle.Dashed,
            axisLabelVisible: true,
            title: `TP [${positionId}]`
          });
        }
        this.sltpPriceLines.set(positionId, lines);
      } else {
        // Real-time slider update
        if (lines.slLine && typeof slPrice === 'number') {
          lines.slLine.applyOptions({ price: slPrice });
        } else if (!lines.slLine && typeof slPrice === 'number') {
          lines.slLine = this.candlestickSeries.createPriceLine({
            price: slPrice,
            color: this.themeConfig.slLine,
            lineWidth: 2,
            lineStyle: LC.LineStyle.Dashed,
            axisLabelVisible: true,
            title: `SL [${positionId}]`
          });
        }

        if (lines.tpLine && typeof tpPrice === 'number') {
          lines.tpLine.applyOptions({ price: tpPrice });
        } else if (!lines.tpLine && typeof tpPrice === 'number') {
          lines.tpLine = this.candlestickSeries.createPriceLine({
            price: tpPrice,
            color: this.themeConfig.tpLine,
            lineWidth: 2,
            lineStyle: LC.LineStyle.Dashed,
            axisLabelVisible: true,
            title: `TP [${positionId}]`
          });
        }
      }
    }

    setSMCZones(zones) {
      this.smcZones = zones || [];
      this._renderSMCZones();
    }

    _renderSMCZones() {
      if (!this.overlayCtx || !this.chart || !this.candlestickSeries) return;
      const ctx = this.overlayCtx;
      const w = this.mainBox.clientWidth;
      const h = this.mainBox.clientHeight;
      ctx.clearRect(0, 0, w, h);

      if (!this.smcZones || this.smcZones.length === 0) return;

      const timeScale = this.chart.timeScale();
      const series = this.candlestickSeries;

      for (const zone of this.smcZones) {
        const xStart = timeScale.timeToCoordinate(zone.timeStart);
        const xEnd = zone.timeEnd ? (timeScale.timeToCoordinate(zone.timeEnd) || w - 65) : w - 65;
        const yHigh = series.priceToCoordinate(zone.high);
        const yLow = series.priceToCoordinate(zone.low);

        if (xStart === null && xEnd === null) continue;
        if (yHigh === null || yLow === null) continue;

        const left = Math.max(0, xStart !== null ? xStart : 0);
        const right = Math.min(w - 65, xEnd !== null ? xEnd : w - 65);
        const boxWidth = right - left;
        const boxHeight = Math.abs(yLow - yHigh);
        const top = Math.min(yHigh, yLow);

        if (boxWidth <= 0 || boxHeight <= 0) continue;

        const isBSL = zone.type === 'BSL';
        const fillColor = isBSL ? this.themeConfig.bslFill : this.themeConfig.sslFill;
        const borderColor = isBSL ? this.themeConfig.bslBorder : this.themeConfig.sslBorder;

        // Draw Order Block Box
        ctx.fillStyle = fillColor;
        ctx.fillRect(left, top, boxWidth, boxHeight);

        ctx.strokeStyle = borderColor;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(left, top, boxWidth, boxHeight);
        ctx.setLineDash([]);

        // Label Badge
        ctx.fillStyle = borderColor;
        ctx.font = 'bold 9px monospace';
        const labelText = zone.label || (isBSL ? 'BSL SWEEP' : 'SSL SWEEP');
        ctx.fillText(labelText, left + 4, top + 11);
      }
    }
  }

  // =========================================================================
  // 5. HIGH-PERFORMANCE NATIVE CANVAS FALLBACK ENGINE (ZERO-DEPENDENCY)
  // =========================================================================
  class QuantProNativeCanvasChart {
    constructor(containerEl, timeframe, theme = 'dark') {
      this.container = typeof containerEl === 'string' ? document.getElementById(containerEl) : containerEl;
      this.timeframe = timeframe;
      this.currentTheme = theme;
      this.themeConfig = THEMES[theme] || THEMES.dark;

      this.canvas = null;
      this.ctx = null;
      this.data = [];
      this.smcZones = [];
      this.sltpMarkers = new Map(); // positionId -> { slPrice, tpPrice }

      // Viewport & Scaling State
      this.visibleCount = 65;
      this.scrollOffset = 0; // 0 = anchored to newest right edge
      this.candleWidth = 8;
      this.candleSpacing = 4;
      this.scaleWidth = 65;
      this.timeScaleHeight = 24;

      // Mouse & Gesture interaction
      this.isDragging = false;
      this.dragStartX = 0;
      this.dragStartOffset = 0;
      this.mousePos = { x: -1, y: -1, active: false };

      // High-performance render scheduling (60 FPS rAF)
      this.isRenderPending = false;

      this._init();
    }

    _init() {
      if (!this.container) return;
      this.container.innerHTML = '';
      this.container.style.position = 'relative';
      this.container.style.width = '100%';
      this.container.style.height = '100%';
      this.container.style.overflow = 'hidden';
      this.container.style.userSelect = 'none';
      this.container.style.backgroundColor = this.themeConfig.bg;

      this.canvas = document.createElement('canvas');
      this.canvas.style.display = 'block';
      this.canvas.style.width = '100%';
      this.canvas.style.height = '100%';
      this.canvas.style.cursor = 'crosshair';
      this.container.appendChild(this.canvas);
      this.ctx = this.canvas.getContext('2d');

      this._bindEvents();
      this.resize();
    }

    _bindEvents() {
      const c = this.canvas;

      c.addEventListener('mousedown', e => {
        this.isDragging = true;
        this.dragStartX = e.clientX;
        this.dragStartOffset = this.scrollOffset;
      });

      window.addEventListener('mouseup', () => {
        this.isDragging = false;
      });

      window.addEventListener('mousemove', e => {
        const rect = c.getBoundingClientRect();
        if (this.isDragging) {
          const deltaX = e.clientX - this.dragStartX;
          const deltaBars = Math.round(deltaX / (this.candleWidth + this.candleSpacing));
          this.scrollOffset = Math.max(0, Math.min(this.data.length - 15, this.dragStartOffset + deltaBars));
          this.requestRender();
        }

        if (e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom) {
          this.mousePos.x = e.clientX - rect.left;
          this.mousePos.y = e.clientY - rect.top;
          this.mousePos.active = true;
          this.requestRender();
        } else if (this.mousePos.active) {
          this.mousePos.active = false;
          this.requestRender();
        }
      });

      c.addEventListener('wheel', e => {
        e.preventDefault();
        const zoomDelta = e.deltaY > 0 ? 3 : -3;
        this.visibleCount = Math.max(20, Math.min(220, this.visibleCount + zoomDelta));
        this.requestRender();
      }, { passive: false });

      // Touch gesture support
      let touchStartX = 0;
      let touchStartOffset = 0;
      c.addEventListener('touchstart', e => {
        if (e.touches.length === 1) {
          touchStartX = e.touches[0].clientX;
          touchStartOffset = this.scrollOffset;
        }
      }, { passive: true });

      c.addEventListener('touchmove', e => {
        if (e.touches.length === 1) {
          const deltaX = e.touches[0].clientX - touchStartX;
          const deltaBars = Math.round(deltaX / (this.candleWidth + this.candleSpacing));
          this.scrollOffset = Math.max(0, Math.min(this.data.length - 15, touchStartOffset + deltaBars));
          this.requestRender();
        }
      }, { passive: true });

      // Resize observer
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(this.container);
      window.addEventListener('resize', () => this.resize());
    }

    resize() {
      if (!this.container || !this.canvas) return;
      const rect = this.container.getBoundingClientRect();
      const w = Math.floor(rect.width);
      const h = Math.floor(rect.height);
      if (w <= 0 || h <= 0) return;

      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = w * dpr;
      this.canvas.height = h * dpr;
      this.ctx.resetTransform?.() || this.ctx.setTransform(1, 0, 0, 1, 0, 0);
      this.ctx.scale(dpr, dpr);

      this.width = w;
      this.height = h;
      this.requestRender();
    }

    setData(candles) {
      if (!candles || candles.length === 0) return;
      this.data = candles.slice();
      this.smcZones = Indicators.detectSMCZones(this.data);
      this.scrollOffset = 0;
      this.requestRender();
    }

    updateTick(tick) {
      if (!tick) return;
      const lastCandle = this.data[this.data.length - 1];

      if (typeof tick.price === 'number') {
        if (!lastCandle) return;
        lastCandle.close = tick.price;
        lastCandle.high = Math.max(lastCandle.high, tick.price);
        lastCandle.low = Math.min(lastCandle.low, tick.price);
        lastCandle.volume = (lastCandle.volume || 0) + (tick.volume || 1);
      } else {
        const tickTime = typeof tick.time === 'string' ? Math.floor(new Date(tick.time).getTime() / 1000) : tick.time;
        const newCandle = {
          time: tickTime,
          open: tick.open,
          high: tick.high,
          low: tick.low,
          close: tick.close,
          volume: tick.volume || 100
        };

        if (lastCandle && lastCandle.time === tickTime) {
          this.data[this.data.length - 1] = newCandle;
        } else {
          this.data.push(newCandle);
          if (this.data.length > 1200) this.data.shift();
        }
      }

      this.requestRender();
    }

    setTheme(themeName) {
      const t = THEMES[themeName];
      if (!t) return;
      this.currentTheme = themeName;
      this.themeConfig = t;
      this.container.style.backgroundColor = t.bg;
      this.requestRender();
    }

    updateSLTPMarkers(positionId, slPrice, tpPrice) {
      const current = this.sltpMarkers.get(positionId) || {};
      if (typeof slPrice === 'number') current.slPrice = slPrice;
      if (typeof tpPrice === 'number') current.tpPrice = tpPrice;
      this.sltpMarkers.set(positionId, current);
      this.requestRender();
    }

    setSMCZones(zones) {
      this.smcZones = zones || [];
      this.requestRender();
    }

    requestRender() {
      if (this.isRenderPending) return;
      this.isRenderPending = true;
      requestAnimationFrame(() => {
        this.isRenderPending = false;
        this.render();
      });
    }

    render() {
      if (!this.ctx || !this.width || !this.height) return;
      const ctx = this.ctx;
      const w = this.width;
      const h = this.height;
      const t = this.themeConfig;

      // Clear Canvas
      ctx.fillStyle = t.bg;
      ctx.fillRect(0, 0, w, h);

      if (!this.data || this.data.length === 0) {
        ctx.fillStyle = t.textSecondary;
        ctx.font = '13px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('QuantPro Terminal - No Data Feed Connected', w / 2, h / 2);
        return;
      }

      // Geometry Layout
      const scaleW = this.scaleWidth;
      const timeH = this.timeScaleHeight;
      const plotW = w - scaleW;

      const mainChartH = Math.floor((h - timeH) * 0.74);
      const rsiTop = mainChartH;
      const rsiH = (h - timeH) - rsiTop;

      // Slice visible candle window
      const totalCandles = this.data.length;
      const endIndex = Math.max(1, totalCandles - this.scrollOffset);
      const startIndex = Math.max(0, endIndex - this.visibleCount);
      const visibleCandles = this.data.slice(startIndex, endIndex);
      const count = visibleCandles.length;
      if (count === 0) return;

      const candlePitch = plotW / count;
      const candleBodyW = Math.max(2, Math.min(candlePitch * 0.72, 28));

      // Calculate Min & Max Price for Main Chart
      let minPrice = Infinity;
      let maxPrice = -Infinity;
      let maxVolume = 0;

      for (let i = 0; i < count; i++) {
        const c = visibleCandles[i];
        if (c.low < minPrice) minPrice = c.low;
        if (c.high > maxPrice) maxPrice = c.high;
        if (c.volume > maxVolume) maxVolume = c.volume;
      }

      // Add 6% vertical padding
      const pricePadding = (maxPrice - minPrice) * 0.08 || 1;
      minPrice -= pricePadding;
      maxPrice += pricePadding;
      const priceRange = maxPrice - minPrice;

      const priceToY = (price) => mainChartH - ((price - minPrice) / priceRange) * mainChartH;
      const yToPrice = (y) => maxPrice - (y / mainChartH) * priceRange;
      const indexToX = (i) => Math.floor(i * candlePitch + (candlePitch / 2));

      // 1. Grid Lines (Horz & Vert)
      ctx.lineWidth = 1;
      ctx.strokeStyle = t.gridColor;

      const gridSteps = 5;
      for (let i = 0; i <= gridSteps; i++) {
        const y = Math.floor((mainChartH / gridSteps) * i);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(plotW, y);
        ctx.stroke();

        // Right Scale Price text
        const pVal = yToPrice(y);
        ctx.fillStyle = t.textColor;
        ctx.font = '10px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(pVal.toFixed(pVal > 100 ? 2 : 5), plotW + 6, y + 3);
      }

      // 2. SMC Liquidity Sweep Zones (BSL / SSL Order Blocks)
      if (this.smcZones && this.smcZones.length > 0) {
        for (const zone of this.smcZones) {
          const yH = priceToY(zone.high);
          const yL = priceToY(zone.low);
          const boxH = Math.max(4, Math.abs(yL - yH));
          const boxTop = Math.min(yH, yL);

          let startIdx = -1;
          let endIdx = -1;
          for (let i = 0; i < count; i++) {
            if (visibleCandles[i].time >= zone.timeStart && startIdx === -1) startIdx = i;
            if (zone.timeEnd && visibleCandles[i].time >= zone.timeEnd && endIdx === -1) endIdx = i;
          }

          const boxLeft = startIdx !== -1 ? indexToX(startIdx) : 0;
          const boxRight = endIdx !== -1 ? indexToX(endIdx) : plotW;
          const boxWidth = Math.max(12, boxRight - boxLeft);

          const isBSL = zone.type === 'BSL';
          ctx.fillStyle = isBSL ? t.bslFill : t.sslFill;
          ctx.fillRect(boxLeft, boxTop, boxWidth, boxH);

          ctx.strokeStyle = isBSL ? t.bslBorder : t.sslBorder;
          ctx.lineWidth = 1;
          ctx.setLineDash([3, 3]);
          ctx.strokeRect(boxLeft, boxTop, boxWidth, boxH);
          ctx.setLineDash([]);

          ctx.fillStyle = isBSL ? t.bslBorder : t.sslBorder;
          ctx.font = 'bold 9px monospace';
          ctx.fillText(zone.label || (isBSL ? 'BSL SWEEP' : 'SSL SWEEP'), boxLeft + 4, boxTop + 10);
        }
      }

      // 3. Volume Histogram (Bottom of Main Chart)
      const volH = mainChartH * 0.18;
      for (let i = 0; i < count; i++) {
        const c = visibleCandles[i];
        const vRatio = maxVolume > 0 ? (c.volume || 10) / maxVolume : 0.2;
        const barH = vRatio * volH;
        const x = indexToX(i) - (candleBodyW / 2);
        const y = mainChartH - barH;

        ctx.fillStyle = c.close >= c.open ? t.volUp : t.volDown;
        ctx.fillRect(x, y, candleBodyW, barH);
      }

      // 4. Candlesticks (Wicks & Bodies)
      for (let i = 0; i < count; i++) {
        const c = visibleCandles[i];
        const x = indexToX(i);
        const isUp = c.close >= c.open;
        const color = isUp ? t.candleUp : t.candleDown;

        const yOpen = priceToY(c.open);
        const yClose = priceToY(c.close);
        const yHigh = priceToY(c.high);
        const yLow = priceToY(c.low);

        // Draw Wick
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x, yHigh);
        ctx.lineTo(x, yLow);
        ctx.stroke();

        // Draw Body
        const top = Math.min(yOpen, yClose);
        const bodyHeight = Math.max(1.5, Math.abs(yOpen - yClose));
        ctx.fillStyle = color;
        ctx.fillRect(Math.floor(x - (candleBodyW / 2)), Math.floor(top), Math.floor(candleBodyW), Math.floor(bodyHeight));
      }

      // 5. Bollinger Bands (20, 2)
      const fullBB = Indicators.calculateBollingerBands(this.data, 20, 2);
      const visBBUpper = fullBB.upper.slice(startIndex, endIndex);
      const visBBMid = fullBB.middle.slice(startIndex, endIndex);
      const visBBLower = fullBB.lower.slice(startIndex, endIndex);

      // Shaded Band Area
      ctx.fillStyle = t.bbArea;
      ctx.beginPath();
      for (let i = 0; i < visBBUpper.length; i++) {
        const x = indexToX(i);
        const y = priceToY(visBBUpper[i].value);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      for (let i = visBBLower.length - 1; i >= 0; i--) {
        const x = indexToX(i);
        const y = priceToY(visBBLower[i].value);
        ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fill();

      // Band Lines
      this._drawLineSeries(ctx, visBBUpper, t.bbUpper, indexToX, priceToY, 1);
      this._drawLineSeries(ctx, visBBMid, t.bbMiddle, indexToX, priceToY, 1, [3, 3]);
      this._drawLineSeries(ctx, visBBLower, t.bbLower, indexToX, priceToY, 1);

      // 6. EMA 50 Line
      const fullEMA = Indicators.calculateEMA(this.data, 50);
      const visEMA = fullEMA.slice(startIndex, endIndex);
      this._drawLineSeries(ctx, visEMA, t.ema50, indexToX, priceToY, 2);

      // 7. Interactive SL & TP Markers
      for (const [posId, marker] of this.sltpMarkers.entries()) {
        if (typeof marker.slPrice === 'number' && marker.slPrice > 0) {
          const slY = priceToY(marker.slPrice);
          if (slY >= 0 && slY <= mainChartH) {
            ctx.strokeStyle = t.slLine;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 3]);
            ctx.beginPath();
            ctx.moveTo(0, slY);
            ctx.lineTo(plotW, slY);
            ctx.stroke();
            ctx.setLineDash([]);

            // Badge on Price Scale
            ctx.fillStyle = t.slLine;
            ctx.fillRect(plotW, slY - 9, scaleW, 18);
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 9px monospace';
            const digits = marker.slPrice > 100 ? 1 : 4;
            ctx.fillText(`SL:${marker.slPrice.toFixed(digits)}`, plotW + 3, slY + 3);
          }
        }

        if (typeof marker.tpPrice === 'number' && marker.tpPrice > 0) {
          const tpY = priceToY(marker.tpPrice);
          if (tpY >= 0 && tpY <= mainChartH) {
            ctx.strokeStyle = t.tpLine;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 3]);
            ctx.beginPath();
            ctx.moveTo(0, tpY);
            ctx.lineTo(plotW, tpY);
            ctx.stroke();
            ctx.setLineDash([]);

            // Badge on Price Scale
            ctx.fillStyle = t.tpLine;
            ctx.fillRect(plotW, tpY - 9, scaleW, 18);
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 9px monospace';
            const digits = marker.tpPrice > 100 ? 1 : 4;
            ctx.fillText(`TP:${marker.tpPrice.toFixed(digits)}`, plotW + 3, tpY + 3);
          }
        }
      }

      // 8. RSI (14) Indicator Pane
      this._renderRSIPane(ctx, startIndex, endIndex, plotW, rsiTop, rsiH, scaleW, indexToX);

      // 9. Time Scale (Bottom Axis)
      this._renderTimeScale(ctx, visibleCandles, plotW, h, timeH, indexToX);

      // 10. Interactive Crosshair & HUD
      if (this.mousePos.active && this.mousePos.x <= plotW && this.mousePos.y <= h - timeH) {
        this._renderCrosshair(ctx, this.mousePos, plotW, h, timeH, scaleW, mainChartH, rsiTop, rsiH, visibleCandles, indexToX, yToPrice);
      }

      // 11. Header Watermark / Title
      ctx.fillStyle = t.textSecondary;
      ctx.font = 'bold 11px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`QuantPro [${this.timeframe}] • BB(20,2) • EMA(50) • RSI(14) • SMC Liquidity`, 12, 18);
    }

    _drawLineSeries(ctx, seriesData, color, xFunc, yFunc, lineWidth = 1.5, dash = []) {
      if (!seriesData || seriesData.length < 2) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;
      if (dash.length > 0) ctx.setLineDash(dash);
      ctx.beginPath();

      for (let i = 0; i < seriesData.length; i++) {
        const x = xFunc(i);
        const y = yFunc(seriesData[i].value);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      if (dash.length > 0) ctx.setLineDash([]);
    }

    _renderRSIPane(ctx, startIndex, endIndex, plotW, rsiTop, rsiH, scaleW, indexToX) {
      const t = this.themeConfig;

      // Pane Separator
      ctx.strokeStyle = t.paneSeparator;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, rsiTop);
      ctx.lineTo(plotW + scaleW, rsiTop);
      ctx.stroke();

      const rsiToY = (val) => rsiTop + rsiH - ((val / 100) * rsiH);

      // Reference lines 70 & 30
      const y70 = rsiToY(70);
      const y30 = rsiToY(30);

      // 30 - 70 Shaded Zone
      ctx.fillStyle = t.rsiBand;
      ctx.fillRect(0, y70, plotW, y30 - y70);

      // Line 70 (Overbought)
      ctx.strokeStyle = t.rsiOB;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(0, y70);
      ctx.lineTo(plotW, y70);
      ctx.stroke();

      // Line 30 (Oversold)
      ctx.strokeStyle = t.rsiOS;
      ctx.beginPath();
      ctx.moveTo(0, y30);
      ctx.lineTo(plotW, y30);
      ctx.stroke();
      ctx.setLineDash([]);

      // Scale Labels
      ctx.fillStyle = t.textColor;
      ctx.font = '9px monospace';
      ctx.fillText('70 OB', plotW + 6, y70 + 3);
      ctx.fillText('30 OS', plotW + 6, y30 + 3);

      // RSI Curve
      const fullRSI = Indicators.calculateRSI(this.data, 14);
      const visRSI = fullRSI.rsi.slice(startIndex, endIndex);

      ctx.strokeStyle = t.rsiLine;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      for (let i = 0; i < visRSI.length; i++) {
        const x = indexToX(i);
        const y = rsiToY(visRSI[i].value);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Rebound Markers
      if (fullRSI.markers && fullRSI.markers.length > 0) {
        for (const m of fullRSI.markers) {
          for (let i = 0; i < visRSI.length; i++) {
            if (visRSI[i].time === m.time) {
              const mx = indexToX(i);
              const my = rsiToY(visRSI[i].value);

              ctx.fillStyle = m.color;
              ctx.beginPath();
              ctx.arc(mx, my, 4, 0, Math.PI * 2);
              ctx.fill();

              ctx.font = 'bold 8px monospace';
              ctx.fillText(m.type === 'bullish_rebound' ? '▲ 30 Rev' : '▼ 70 Rev', mx - 14, m.type === 'bullish_rebound' ? my + 14 : my - 8);
            }
          }
        }
      }

      // RSI Label
      ctx.fillStyle = t.rsiLine;
      ctx.font = 'bold 10px monospace';
      const latestRSI = visRSI.length ? visRSI[visRSI.length - 1].value : 50;
      ctx.fillText(`RSI(14): ${latestRSI}`, 12, rsiTop + 14);
    }

    _renderTimeScale(ctx, visibleCandles, plotW, h, timeH, indexToX) {
      const t = this.themeConfig;
      const yAxis = h - timeH;

      ctx.strokeStyle = t.borderColor;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, yAxis);
      ctx.lineTo(plotW + this.scaleWidth, yAxis);
      ctx.stroke();

      ctx.fillStyle = t.textColor;
      ctx.font = '10px monospace';
      ctx.textAlign = 'center';

      const step = Math.max(1, Math.floor(visibleCandles.length / 6));
      for (let i = 0; i < visibleCandles.length; i += step) {
        const c = visibleCandles[i];
        const x = indexToX(i);
        const date = new Date(c.time * 1000);
        const hours = String(date.getHours()).padStart(2, '0');
        const mins = String(date.getMinutes()).padStart(2, '0');
        ctx.fillText(`${hours}:${mins}`, x, h - 7);
      }
    }

    _renderCrosshair(ctx, pos, plotW, h, timeH, scaleW, mainChartH, rsiTop, rsiH, visibleCandles, indexToX, yToPrice) {
      const t = this.themeConfig;
      ctx.strokeStyle = t.crosshairColor;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);

      // Vertical line
      ctx.beginPath();
      ctx.moveTo(pos.x, 0);
      ctx.lineTo(pos.x, h - timeH);
      ctx.stroke();

      // Horizontal line
      ctx.beginPath();
      ctx.moveTo(0, pos.y);
      ctx.lineTo(plotW, pos.y);
      ctx.stroke();
      ctx.setLineDash([]);

      // Floating Price Badge
      if (pos.y < mainChartH) {
        const price = yToPrice(pos.y);
        ctx.fillStyle = t.cardBg;
        ctx.fillRect(plotW, pos.y - 10, scaleW, 20);
        ctx.strokeStyle = t.borderColor;
        ctx.strokeRect(plotW, pos.y - 10, scaleW, 20);

        ctx.fillStyle = t.textColor;
        ctx.font = 'bold 10px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(price.toFixed(price > 100 ? 2 : 5), plotW + 5, pos.y + 4);
      }
    }
  }

  // =========================================================================
  // 6. UNIFIED PUBLIC CHART ENGINE FACADE
  // =========================================================================
  const ChartEngine = {
    mode: 'auto', // 'lightweight' | 'canvas' | 'auto'
    activeTheme: 'dark',
    activeSymbol: 'BTCUSD',
    charts: {
      m15: null,
      h1: null
    },
    tickerTimer: null,

    /**
     * Initializes dual charts (Top: M15, Bottom: H1)
     * @param {string|HTMLElement} containerM15Id
     * @param {string|HTMLElement} containerH1Id
     * @param {string} theme ('dark' | 'light')
     */
    initCharts(containerM15Id, containerH1Id, theme = 'dark') {
      this.activeTheme = theme;
      const hasLightweightCharts = typeof window.LightweightCharts !== 'undefined' && 
                                   typeof window.LightweightCharts.createChart === 'function';

      const useLightweight = (this.mode === 'lightweight') || (this.mode === 'auto' && hasLightweightCharts);

      console.log(`[QuantPro ChartEngine] Initializing charts. Engine: ${useLightweight ? 'TradingView Lightweight Charts' : 'High-Performance Native Canvas Fallback (Offline Mode)'}`);

      const EngineClass = useLightweight ? LightweightChartWrapper : QuantProNativeCanvasChart;

      this.charts.m15 = new EngineClass(containerM15Id, 'M15', theme);
      this.charts.h1 = new EngineClass(containerH1Id, 'H1', theme);

      // Populate initial realistic market data stream
      const basePrice = this._getBasePrice(this.activeSymbol);
      const m15Data = generateRealisticMarketData(160, basePrice, 900);
      const h1Data = generateRealisticMarketData(160, basePrice, 3600);

      this.charts.m15.setData(m15Data);
      this.charts.h1.setData(h1Data);

      // Default SL/TP price lines
      this._seedDefaultSLTP(basePrice);

      // Start realistic high-speed 60fps micro-tick feed simulation
      this.startRealtimeSimulation();

      return {
        m15: this.charts.m15,
        h1: this.charts.h1,
        engineType: useLightweight ? 'lightweight' : 'canvas'
      };
    },

    _getBasePrice(symbol) {
      if (!symbol) return 64250.0;
      const s = symbol.toUpperCase();
      if (s.includes('BTC')) return 64450.0;
      if (s.includes('ETH')) return 3480.0;
      if (s.includes('EUR')) return 1.08250;
      if (s.includes('GBP')) return 1.29500;
      if (s.includes('XAU') || s.includes('GOLD')) return 2410.0;
      if (s.includes('SOL')) return 145.0;
      if (s.includes('75')) return 51057.90;
      if (s.includes('25')) return 2766.17;
      return 64250.0;
    },

    _seedDefaultSLTP(basePrice) {
      const isCrypto = basePrice > 1000;
      const slDist = isCrypto ? basePrice * 0.015 : 0.0035;
      const tpDist = isCrypto ? basePrice * 0.03 : 0.0070;

      const slPrice = parseFloat((basePrice - slDist).toFixed(isCrypto ? 2 : 5));
      const tpPrice = parseFloat((basePrice + tpDist).toFixed(isCrypto ? 2 : 5));

      this.updateSLTPMarkers('active', slPrice, tpPrice);
    },

    /**
     * Updates real-time tick smoothly with 60 FPS series.update()
     * @param {string} symbol - e.g. 'BTCUSDT'
     * @param {Object} tickData - { time, open, high, low, close, volume } or { price, volume }
     */
    updateTick(symbol, tickData) {
      if (!tickData) return;
      if (this.charts.m15) this.charts.m15.updateTick(tickData);
      if (this.charts.h1) this.charts.h1.updateTick(tickData);
    },

    /**
     * In-place theme toggle Dark ⇄ Light without destroying instances
     * @param {string} themeName ('dark' | 'light')
     */
    setTheme(themeName) {
      this.activeTheme = themeName;
      if (this.charts.m15) this.charts.m15.setTheme(themeName);
      if (this.charts.h1) this.charts.h1.setTheme(themeName);
    },

    /**
     * Real-time Stop Loss & Take Profit Price Line slider updater
     * @param {string} positionId
     * @param {number} slPrice
     * @param {number} tpPrice
     */
    updateSLTPMarkers(positionId, slPrice, tpPrice) {
      if (this.charts.m15) this.charts.m15.updateSLTPMarkers(positionId, slPrice, tpPrice);
      if (this.charts.h1) this.charts.h1.updateSLTPMarkers(positionId, slPrice, tpPrice);
    },

    /**
     * Direct slider helper alias for terminal_app.js: updatePriceLine('sl'|'tp', price)
     */
    updatePriceLine(type, price, posId = 'active') {
      if (type === 'sl') {
        this.updateSLTPMarkers(posId, price, null);
      } else if (type === 'tp') {
        this.updateSLTPMarkers(posId, null, price);
      }
    },

    /**
     * Load / Switch Active Symbol
     */
    loadSymbol(symbol) {
      if (!symbol) return;
      this.activeSymbol = symbol;
      const basePrice = this._getBasePrice(symbol);
      const m15Data = generateRealisticMarketData(160, basePrice, 900);
      const h1Data = generateRealisticMarketData(160, basePrice, 3600);

      this.setData('M15', m15Data);
      this.setData('H1', h1Data);
      this._seedDefaultSLTP(basePrice);

      // Update Chart header displays if present
      const m15Title = document.getElementById('chart-m15-title');
      const h1Title = document.getElementById('chart-h1-title');
      if (m15Title) m15Title.textContent = `${symbol} · M15`;
      if (h1Title) h1Title.textContent = `${symbol} · H1`;
    },

    /**
     * Set explicit SMC Liquidity Sweep Order Block Zones
     * @param {'M15'|'H1'} timeframe
     * @param {Array} zones
     */
    setSMCZones(timeframe, zones) {
      const chart = (timeframe === 'H1') ? this.charts.h1 : this.charts.m15;
      if (chart && typeof chart.setSMCZones === 'function') {
        chart.setSMCZones(zones);
      }
    },

    /**
     * Set full candle historical series
     * @param {'M15'|'H1'} timeframe
     * @param {Array} candles
     */
    setData(timeframe, candles) {
      const chart = (timeframe === 'H1') ? this.charts.h1 : this.charts.m15;
      if (chart && typeof chart.setData === 'function') {
        chart.setData(candles);
      }
    },

    /**
     * Trigger responsive recalculation
     */
    resize() {
      if (this.charts.m15) this.charts.m15.resize();
      if (this.charts.h1) this.charts.h1.resize();
    },

    getEngineType() {
      return (typeof window.LightweightCharts !== 'undefined' && typeof window.LightweightCharts.createChart === 'function')
        ? 'lightweight'
        : 'canvas';
    },

    /**
     * High-speed real-time simulation tick engine (60 FPS capable, throttled to smooth 1.2s ticks)
     */
    startRealtimeSimulation() {
      if (this.tickerTimer) clearInterval(this.tickerTimer);

      this.tickerTimer = setInterval(() => {
        if (!this.charts.m15 || !this.charts.m15.data || this.charts.m15.data.length === 0) return;
        const lastCandle = this.charts.m15.data[this.charts.m15.data.length - 1];
        const isCrypto = lastCandle.close > 1000;
        const delta = (Math.random() - 0.49) * (lastCandle.close * (isCrypto ? 0.0004 : 0.0001));
        const newPrice = parseFloat((lastCandle.close + delta).toFixed(isCrypto ? 2 : 5));

        this.updateTick(this.activeSymbol, {
          price: newPrice,
          volume: Math.floor(1 + Math.random() * 8)
        });

        // Update live price indicators in DOM
        const m15PriceEl = document.getElementById('chart-m15-price');
        const h1PriceEl = document.getElementById('chart-h1-price');
        const formatted = isCrypto 
          ? newPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
          : newPrice.toFixed(5);

        if (m15PriceEl) m15PriceEl.textContent = formatted;
        if (h1PriceEl) h1PriceEl.textContent = formatted;
      }, 1200);
    },

    generateMockData: generateRealisticMarketData,
    Indicators: Indicators,
    THEMES: THEMES
  };

  // =========================================================================
  // 7. AUTO-INITIALIZATION & EVENT BINDINGS FOR QUANTPRO TERMINAL
  // =========================================================================
  if (typeof window !== 'undefined') {
    // Custom Event: Theme Switch
    window.addEventListener('quantpro:theme-change', (e) => {
      if (e.detail && e.detail.theme) {
        ChartEngine.setTheme(e.detail.theme);
      }
    });

    // Custom Event: Symbol Switch
    window.addEventListener('quantpro:symbol-change', (e) => {
      if (e.detail && e.detail.symbol) {
        ChartEngine.loadSymbol(e.detail.symbol);
      }
    });

    // Auto-init on page load if default containers exist
    window.addEventListener('DOMContentLoaded', () => {
      const m15Container = document.getElementById('chart-m15-container');
      const h1Container = document.getElementById('chart-h1-container');

      if (m15Container && h1Container) {
        const theme = document.documentElement.getAttribute('data-theme') || 
                      localStorage.getItem('quantpro_theme') || 
                      localStorage.getItem('quantpro-theme') || 'dark';

        ChartEngine.initCharts('chart-m15-container', 'chart-h1-container', theme);

        // Bind SL/TP sliders in index.html directly to Chart Engine
        const bindSlider = (sliderId, type) => {
          const slider = document.getElementById(sliderId);
          if (slider) {
            slider.addEventListener('input', (e) => {
              const val = parseFloat(e.target.value);
              if (!isNaN(val)) ChartEngine.updatePriceLine(type, val);
            });
          }
        };

        bindSlider('sl-slider-btcusd', 'sl');
        bindSlider('tp-slider-btcusd', 'tp');
        bindSlider('sl-slider-eurusd', 'sl');
        bindSlider('tp-slider-eurusd', 'tp');
      }
    });
  }

  return ChartEngine;
}));
