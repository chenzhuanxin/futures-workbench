/* ============================================================
   K 线图组件（Canvas 2D，零依赖）
   - 拖拽左右平移 / 滚轮缩放 / 双击复位
   - 十字光标 + 数据提示
   - 历史最高价、历史最低价自动标注
   - 技术指标：MA / EXPMA / BOLL / BBIBOLL / SAR
   ============================================================ */
(function () {
  'use strict';

  /* ---------------- 指标计算 ---------------- */
  function sma(v, n) {
    const out = new Array(v.length).fill(null);
    let sum = 0, cnt = 0;
    for (let i = 0; i < v.length; i++) {
      const x = v[i];
      if (x === null || x === undefined || Number.isNaN(x)) { sum = 0; cnt = 0; continue; }
      sum += x; cnt++;
      if (cnt > n) { sum -= v[i - n]; cnt = n; }
      if (cnt === n) out[i] = sum / n;
    }
    return out;
  }

  function ema(v, n) {
    const out = new Array(v.length).fill(null);
    const k = 2 / (n + 1);
    let prev = null;
    for (let i = 0; i < v.length; i++) {
      const x = v[i];
      if (x === null || x === undefined || Number.isNaN(x)) continue;
      prev = prev === null ? x : x * k + prev * (1 - k);
      out[i] = prev;
    }
    return out;
  }

  // 滚动标准差（窗口内出现空值则返回空）
  function rollStd(v, n) {
    const out = new Array(v.length).fill(null);
    for (let i = 0; i < v.length; i++) {
      if (i + 1 < n) continue;
      let ok = true, s = 0;
      for (let j = i - n + 1; j <= i; j++) {
        const x = v[j];
        if (x === null || x === undefined || Number.isNaN(x)) { ok = false; break; }
        s += x;
      }
      if (!ok) continue;
      const m = s / n;
      let acc = 0;
      for (let j = i - n + 1; j <= i; j++) acc += (v[j] - m) * (v[j] - m);
      out[i] = Math.sqrt(acc / n);
    }
    return out;
  }

  function boll(closes, n, p) {
    const mid = sma(closes, n), dev = rollStd(closes, n);
    const up = [], dn = [];
    for (let i = 0; i < closes.length; i++) {
      up.push(mid[i] === null || dev[i] === null ? null : mid[i] + p * dev[i]);
      dn.push(mid[i] === null || dev[i] === null ? null : mid[i] - p * dev[i]);
    }
    return { mid, up, dn };
  }

  // BBIBOLL：BBI=(MA3+MA6+MA12+MA24)/4，上下轨 = BBI ± P*STD(BBI,N)
  function bbiboll(closes, n, p) {
    const a = sma(closes, 3), b = sma(closes, 6), c = sma(closes, 12), d = sma(closes, 24);
    const bbi = closes.map((_, i) =>
      (a[i] === null || b[i] === null || c[i] === null || d[i] === null)
        ? null : (a[i] + b[i] + c[i] + d[i]) / 4);
    const dev = rollStd(bbi, n);
    const up = [], dn = [];
    for (let i = 0; i < closes.length; i++) {
      up.push(bbi[i] === null || dev[i] === null ? null : bbi[i] + p * dev[i]);
      dn.push(bbi[i] === null || dev[i] === null ? null : bbi[i] - p * dev[i]);
    }
    return { mid: bbi, up, dn };
  }

  // 抛物线转向 SAR（无效K线跳过，输出与输入等长，无效位置为 null）
  function sar(bars, af0, step, maxAf) {
    const n = bars.length, out = new Array(n).fill(null);
    const idxs = [], bs = [];
    for (let i = 0; i < n; i++) {
      if (okBar(bars[i])) { idxs.push(i); bs.push(bars[i]); }
    }
    const m = bs.length;
    if (m < 2) return out;
    const tmp = new Array(m).fill(null);
    let bull = true, af = af0, ep = bs[0].h, sv = bs[0].l;
    tmp[0] = sv;
    for (let i = 1; i < m; i++) {
      const b = bs[i];
      let cur = sv + af * (ep - sv);
      if (bull) {
        if (b.l < cur) { bull = false; af = af0; cur = ep; ep = b.l; sv = cur; }
        else {
          if (b.h > ep) { ep = b.h; af = Math.min(af + step, maxAf); }
          sv = cur;
        }
      } else {
        if (b.h > cur) { bull = true; af = af0; cur = ep; ep = b.h; sv = cur; }
        else {
          if (b.l < ep) { ep = b.l; af = Math.min(af + step, maxAf); }
          sv = cur;
        }
      }
      tmp[i] = cur;
    }
    for (let i = 0; i < m; i++) out[idxs[i]] = tmp[i];
    return out;
  }

  /* ---------------- 配色 ---------------- */
  const UP = '#e5484d', DOWN = '#12a150';
  const C = {
    grid: '#eaeef8', axis: '#93a0c0', text: '#5a678c',
    ma: ['#f59e0b', '#4a63e7', '#a855f7', '#0ea5a5'],
    expma: ['#ec4899', '#2563eb'],
    bollMid: '#f59e0b', bollBand: 'rgba(74,99,231,0.10)', bollLine: '#6a86ff',
    bbiMid: '#a855f7', bbiBand: 'rgba(168,85,247,0.09)', bbiLine: '#c084fc',
    sar: '#0ea5a5',
  };
  const MA_N = [5, 10, 20, 60], EXPMA_N = [12, 50];
  const LINE_COLORS = ['#4a63e7', '#0ea5a5', '#f59e0b', '#ec4899', '#8b5cf6',
    '#06b6d4', '#ef4444', '#84cc16', '#f97316', '#14b8a6',
    '#6366f1', '#eab308', '#a855f7', '#10b981', '#f43f5e',
    '#0891b2', '#7c3aed', '#65a30d', '#d97706', '#be185d'];

  function niceDate(d) { return d; }

  /* 价格有效性：期货价格不可能为 0，0 / 空 / 非数一律视为缺失，不绘制 */
  function okPx(v) {
    return v !== null && v !== undefined && typeof v === 'number' &&
      isFinite(v) && v > 0;
  }
  /* 一根可绘制的 K 线：开高低收全部为有效正价格 */
  function okBar(b) {
    return !!b && okPx(b.o) && okPx(b.h) && okPx(b.l) && okPx(b.c);
  }

  /* ---------------- 主类 ---------------- */
  class KLineChart {
    constructor(canvas) {
      this.cv = canvas;
      this.ctx = canvas.getContext('2d');
      this.mode = 'candle';
      this.axis = [];
      this.bars = null;
      this.lines = [];
      this.hidden = new Set();
      this.indicators = { ma: true, expma: false, boll: false, bbiboll: false, sar: false };
      this.view = { start: 0, count: 260 };
      this.hover = null;
      this.drag = null;
      this.high = null;
      this.low = null;
      this._cache = null;
      this.onHover = null;
      this._bind();
      const ro = new ResizeObserver(() => this.draw());
      ro.observe(canvas);
    }

    /* --- 数据 --- */
    setCandle(bars, meta = {}) {
      this.mode = 'candle';
      // 保险起见再过滤一遍：完全没有有效价格的点不进入坐标轴
      const clean = (bars || []).filter(b =>
        b && (okPx(b.o) || okPx(b.h) || okPx(b.l) || okPx(b.c)));
      this.axis = clean.map(b => b.d);
      this.bars = clean;
      this.lines = [];
      this.high = meta.high || null;
      this.low = meta.low || null;
      this._cache = null;
      this.reset();
    }

    setLines(map, meta = {}) {
      // map: { name: [ {d,o,h,l,c,v} ] }，c 为 0/缺失的点不参与绘制
      this.mode = 'lines';
      this.bars = null;
      const dates = new Set();
      Object.values(map).forEach(arr => arr.forEach(p => { if (okPx(p.c)) dates.add(p.d); }));
      this.axis = Array.from(dates).sort();
      const idx = new Map(this.axis.map((d, i) => [d, i]));
      this.lines = Object.keys(map).map((name, k) => {
        const vals = new Array(this.axis.length).fill(null);
        map[name].forEach(p => {
          if (!okPx(p.c)) return;                       // 零值点：留空，断开连线
          const i = idx.get(p.d);
          if (i !== undefined) vals[i] = p.c;
        });
        return { name, vals, color: LINE_COLORS[k % LINE_COLORS.length], visible: true };
      });
      this.high = meta.high || null;
      this.low = meta.low || null;
      this._cache = null;
      this.reset();
    }

    setIndicators(ind) {
      this.indicators = Object.assign({}, this.indicators, ind);
      this._cache = null;
      this.draw();
    }

    toggleLine(name) {
      const ln = this.lines.find(l => l.name === name);
      if (!ln) return;
      ln.visible = !ln.visible;
      this.draw();
    }

    reset() {
      const n = this.axis.length || 1;
      const count = Math.min(Math.max(60, 260), n);
      this.view = { start: Math.max(0, n - count), count };
      this.hover = null;
      this.draw();
    }

    gotoIndex(i) {
      if (i === null || i === undefined) return;
      const half = Math.floor(this.view.count / 2);
      this.view.start = Math.max(0, Math.min(this.axis.length - this.view.count, i - half));
      this.draw();
    }

    /* --- 指标缓存 --- */
    _ind() {
      if (this._cache) return this._cache;
      const res = { ma: [], expma: [], boll: null, bbiboll: null, sar: null };
      if (this.mode === 'candle' && this.bars) {
        // 零值收盘不参与指标计算，否则均线会被拉到 0 附近
        const closes = this.bars.map(b => okPx(b.c) ? b.c : null);
        res.ma = MA_N.map(n => ({ n, vals: sma(closes, n) }));
        res.expma = EXPMA_N.map(n => ({ n, vals: ema(closes, n) }));
        res.boll = boll(closes, 20, 2);
        res.bbiboll = bbiboll(closes, 11, 6);
        res.sar = sar(this.bars, 0.02, 0.02, 0.2);
      }
      this._cache = res;
      return res;
    }

    /* --- 布局 --- */
    _layout() {
      const W = this.cv.clientWidth || 800;
      const H = this.cv.clientHeight || 420;
      const hasVol = this.mode === 'candle';
      const padL = 10, padR = 68, padT = 14, padB = 24;
      const volH = hasVol ? 62 : 0, gapV = hasVol ? 12 : 0;
      const plotX0 = padL, plotX1 = W - padR;
      const priceY0 = padT, priceY1 = H - padB - volH - gapV;
      const volY0 = priceY1 + gapV, volY1 = H - padB;
      return { W, H, padL, padR, padT, padB, plotX0, plotX1, priceY0, priceY1, volY0, volY1, hasVol };
    }

    _visible() {
      const n = this.axis.length;
      let { start, count } = this.view;
      count = Math.max(10, Math.min(count, n));
      start = Math.max(0, Math.min(start, Math.max(0, n - count)));
      this.view.start = start;
      this.view.count = count;
      return { i0: start, i1: Math.min(n, start + count), n };
    }

    /* --- 绘制 --- */
    draw() {
      const cv = this.cv, ctx = this.ctx;
      const L = this._layout();
      const dpr = window.devicePixelRatio || 1;
      if (cv.width !== Math.round(L.W * dpr) || cv.height !== Math.round(L.H * dpr)) {
        cv.width = Math.round(L.W * dpr);
        cv.height = Math.round(L.H * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, L.W, L.H);

      const { i0, i1 } = this._visible();
      if (!i1 || i1 <= i0) { this._empty(ctx, L); return; }

      const step = (L.plotX1 - L.plotX0) / (i1 - i0);
      const xOf = i => L.plotX0 + (i - i0 + 0.5) * step;
      const ind = this._ind();

      /* ---- 计算纵向范围（忽略无效/零值，避免坐标轴被拉到 0） ---- */
      let lo = Infinity, hi = -Infinity;
      const acc = v => { if (okPx(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } };

      if (this.mode === 'candle') {
        for (let i = i0; i < i1; i++) {
          const b = this.bars[i];
          if (!okBar(b)) continue;
          acc(b.h); acc(b.l);
        }
        const vis = a => { if (!a) return; for (let i = i0; i < i1; i++) acc(a[i]); };
        if (this.indicators.ma) ind.ma.forEach(m => vis(m.vals));
        if (this.indicators.expma) ind.expma.forEach(m => vis(m.vals));
        if (this.indicators.boll) { vis(ind.boll.up); vis(ind.boll.dn); }
        if (this.indicators.bbiboll) { vis(ind.bbiboll.up); vis(ind.bbiboll.dn); }
        if (this.indicators.sar) vis(ind.sar);
      } else {
        this.lines.forEach(l => {
          if (!l.visible) return;
          for (let i = i0; i < i1; i++) acc(l.vals[i]);
        });
      }
      if (!isFinite(lo) || !isFinite(hi)) { this._empty(ctx, L); return; }
      if (lo === hi) { lo -= 1; hi += 1; }
      const padY = (hi - lo) * 0.07;
      lo -= padY; hi += padY;
      const yOf = v => L.priceY1 - (v - lo) / (hi - lo) * (L.priceY1 - L.priceY0);

      /* ---- 网格与价格刻度 ---- */
      ctx.font = '10.5px ui-sans-serif, system-ui, "Microsoft YaHei", sans-serif';
      ctx.textBaseline = 'middle';
      const ticks = 5;
      for (let k = 0; k <= ticks; k++) {
        const v = lo + (hi - lo) * (k / ticks);
        const y = yOf(v);
        ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(L.plotX0, Math.round(y) + .5); ctx.lineTo(L.plotX1, Math.round(y) + .5); ctx.stroke();
        ctx.fillStyle = C.axis; ctx.textAlign = 'left';
        ctx.fillText(fmt(v), L.plotX1 + 6, y);
      }

      /* ---- 日期刻度 ---- */
      const nx = Math.max(2, Math.min(8, Math.floor((L.plotX1 - L.plotX0) / 90)));
      ctx.textAlign = 'center'; ctx.fillStyle = C.axis;
      for (let k = 0; k < nx; k++) {
        const i = Math.round(i0 + (k / (nx - 1 || 1)) * (i1 - i0 - 1));
        const d = this.axis[Math.min(i, this.axis.length - 1)];
        if (!d) continue;
        ctx.fillText(d.slice(0, 7), xOf(i), L.H - L.padB / 2 + 1);
      }

      /* ---- 指标带（先画填充，避免遮挡K线） ---- */
      const drawBand = (up, dn, fill, line) => {
        ctx.beginPath();
        let started = false;
        for (let i = i0; i < i1; i++) {
          const v = up[i]; if (!okPx(v)) continue;
          started ? ctx.lineTo(xOf(i), yOf(v)) : (ctx.moveTo(xOf(i), yOf(v)), started = true);
        }
        for (let i = i1 - 1; i >= i0; i--) {
          const v = dn[i]; if (!okPx(v)) continue;
          ctx.lineTo(xOf(i), yOf(v));
        }
        ctx.closePath();
        ctx.fillStyle = fill; ctx.fill();
        // 上下轨线条
        [[up, line], [dn, line]].forEach(([a, col]) => {
          ctx.beginPath(); let st = false;
          for (let i = i0; i < i1; i++) {
            const v = a[i]; if (!okPx(v)) continue;
            st ? ctx.lineTo(xOf(i), yOf(v)) : (ctx.moveTo(xOf(i), yOf(v)), st = true);
          }
          ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.stroke();
        });
      };

      if (this.mode === 'candle' && this.indicators.boll && ind.boll) drawBand(ind.boll.up, ind.boll.dn, C.bollBand, C.bollLine);
      if (this.mode === 'candle' && this.indicators.bbiboll && ind.bbiboll) drawBand(ind.bbiboll.up, ind.bbiboll.dn, C.bbiBand, C.bbiLine);

      /* ---- 主图 ---- */
      if (this.mode === 'candle') {
        const cw = Math.max(1, Math.min(step * 0.72, 16));
        for (let i = i0; i < i1; i++) {
          const b = this.bars[i];
          if (!okBar(b)) continue;               // 零值/无效K线：不绘制
          const x = xOf(i);
          const up = b.c >= b.o;
          const col = up ? UP : DOWN;
          ctx.strokeStyle = col; ctx.fillStyle = up ? 'rgba(229,72,77,0.92)' : DOWN;
          ctx.lineWidth = Math.max(1, Math.min(cw * 0.16, 1.6));
          const yh = yOf(b.h), yl = yOf(b.l);
          ctx.beginPath(); ctx.moveTo(x, yh); ctx.lineTo(x, yl); ctx.stroke();
          const yo = yOf(b.o), yc = yOf(b.c);
          const top = Math.min(yo, yc), hgt = Math.max(1, Math.abs(yc - yo));
          ctx.fillRect(x - cw / 2, top, cw, hgt);
          if (up) { // 阳线中空更清晰
            ctx.fillStyle = '#fff';
            ctx.fillRect(x - cw / 2 + 1, top + 1, Math.max(0, cw - 2), Math.max(0, hgt - 2));
            ctx.strokeStyle = col; ctx.lineWidth = 1;
            ctx.strokeRect(x - cw / 2 + .5, top + .5, cw - 1, hgt - 1);
          }
        }

        const drawLine = (vals, color, width, dash) => {
          ctx.beginPath(); let st = false;
          for (let i = i0; i < i1; i++) {
            const v = vals[i];
            if (!okPx(v)) { st = false; continue; }
            st ? ctx.lineTo(xOf(i), yOf(v)) : (ctx.moveTo(xOf(i), yOf(v)), st = true);
          }
          ctx.strokeStyle = color; ctx.lineWidth = width || 1.4;
          ctx.setLineDash(dash || []); ctx.stroke(); ctx.setLineDash([]);
        };

        if (this.indicators.ma) ind.ma.forEach((m, k) => drawLine(m.vals, C.ma[k % C.ma.length], 1.3));
        if (this.indicators.expma) ind.expma.forEach((m, k) => drawLine(m.vals, C.expma[k % C.expma.length], 1.3));
        if (this.indicators.boll) {
          drawLine(ind.boll.mid, C.bollMid, 1, [4, 3]);
        }
        if (this.indicators.bbiboll) {
          drawLine(ind.bbiboll.mid, C.bbiMid, 1.4);
        }
        if (this.indicators.sar) {
          ctx.fillStyle = C.sar;
          for (let i = i0; i < i1; i++) {
            const v = ind.sar[i];
            if (!okPx(v)) continue;
            const y = yOf(v);
            const prev = i > 0 ? ind.sar[i - 1] : null;
            ctx.beginPath();
            ctx.arc(xOf(i), y, 1.9, 0, Math.PI * 2);
            ctx.fill();
            if (okPx(prev)) {
              ctx.strokeStyle = 'rgba(14,165,165,0.5)'; ctx.lineWidth = .8;
              ctx.beginPath(); ctx.moveTo(xOf(i - 1), yOf(prev)); ctx.lineTo(xOf(i), y); ctx.stroke();
            }
          }
        }
      } else {
        // 多合约折线叠加（零值点自动断线）
        this.lines.forEach(l => {
          if (!l.visible) return;
          ctx.beginPath(); let st = false;
          for (let i = i0; i < i1; i++) {
            const v = l.vals[i];
            if (!okPx(v)) { st = false; continue; }
            st ? ctx.lineTo(xOf(i), yOf(v)) : (ctx.moveTo(xOf(i), yOf(v)), st = true);
          }
          ctx.strokeStyle = l.color; ctx.lineWidth = 1.5;
          ctx.lineJoin = 'round'; ctx.stroke();
        });
      }

      /* ---- 历史最高 / 最低标注 ---- */
      this._mark(ctx, L, xOf, yOf, i0, i1, this.high, UP, '最高', true);
      this._mark(ctx, L, xOf, yOf, i0, i1, this.low, DOWN, '最低', false);

      /* ---- 成交量 ---- */
      if (L.hasVol) {
        let vmax = 0;
        for (let i = i0; i < i1; i++) {
          const b = this.bars[i];
          if (okBar(b) && b.v > vmax) vmax = b.v;
        }
        vmax = vmax || 1;
        const vh = L.volY1 - L.volY0;
        ctx.strokeStyle = C.grid; ctx.beginPath();
        ctx.moveTo(L.plotX0, Math.round(L.volY0) + .5); ctx.lineTo(L.plotX1, Math.round(L.volY0) + .5); ctx.stroke();
        ctx.fillStyle = C.axis; ctx.textAlign = 'left';
        ctx.fillText('成交量', L.plotX0 + 2, L.volY0 + 8);

        const cw2 = Math.max(1, Math.min(step * 0.72, 16));
        for (let i = i0; i < i1; i++) {
          const b = this.bars[i];
          if (!okBar(b) || !(b.v > 0)) continue;
          const h = (b.v / vmax) * (vh - 6);
          const y = L.volY1 - h;
          ctx.fillStyle = (b.c >= b.o) ? 'rgba(229,72,77,0.55)' : 'rgba(18,161,80,0.55)';
          ctx.fillRect(xOf(i) - cw2 / 2, y, cw2, h);
        }
      }

      /* ---- 十字光标 ---- */
      if (this.hover !== null && this.hover >= i0 && this.hover < i1) {
        const i = this.hover, x = xOf(i);
        ctx.strokeStyle = 'rgba(74,99,231,.45)'; ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(x, L.priceY0); ctx.lineTo(x, L.priceY1); ctx.stroke();
        if (this.mode === 'candle') {
          const b = this.bars[i];
          if (okBar(b)) {
            const y = yOf(b.c);
            ctx.beginPath(); ctx.moveTo(L.plotX0, y); ctx.lineTo(L.plotX1, y); ctx.stroke();
          }
        }
        ctx.setLineDash([]);
      }

      /* ---- 边框 ---- */
      ctx.strokeStyle = 'rgba(22,34,74,.10)'; ctx.lineWidth = 1;
      ctx.strokeRect(L.plotX0 + .5, L.priceY0 + .5, L.plotX1 - L.plotX0 - 1, L.priceY1 - L.priceY0 - 1);
    }

    _mark(ctx, L, xOf, yOf, i0, i1, m, color, tag, above) {
      if (!m || m.index === null || m.index === undefined) return;
      if (m.index < i0 || m.index >= i1) return;
      if (!okPx(m.price)) return;
      const x = xOf(m.index), y = yOf(m.price);
      ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(L.plotX0, y); ctx.lineTo(L.plotX1, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(x, y, 3.4, 0, Math.PI * 2);
      ctx.fillStyle = color; ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.6; ctx.stroke();

      const txt = `${tag} ${fmt(m.price)}  ${m.date}`;
      ctx.font = '10.5px ui-sans-serif, system-ui, "Microsoft YaHei", sans-serif';
      const w = ctx.measureText(txt).width + 12;
      const bx = Math.min(Math.max(x - w / 2, L.plotX0 + 1), L.plotX1 - w - 1);
      const by = above ? Math.max(L.priceY0 + 2, y - 18) : Math.min(L.priceY1 - 18, y + 4);
      ctx.fillStyle = color;
      roundRect(ctx, bx, by, w, 15, 4); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(txt, bx + w / 2, by + 8);
    }

    _empty(ctx, L) {
      ctx.fillStyle = '#93a0c0';
      ctx.font = '13px ui-sans-serif, system-ui, "Microsoft YaHei", sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('暂无可绘制的K线数据', L.W / 2, L.H / 2);
    }

    /* --- 交互 --- */
    _pos(e) {
      const r = this.cv.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    _indexAt(x, L) {
      const { i0, i1 } = this._visible();
      const step = (L.plotX1 - L.plotX0) / (i1 - i0);
      const i = Math.floor((x - L.plotX0) / step) + i0;
      return Math.max(i0, Math.min(i1 - 1, i));
    }

    _bind() {
      const cv = this.cv;
      cv.style.cursor = 'crosshair';

      cv.addEventListener('mousedown', e => {
        const p = this._pos(e);
        this.drag = { x: p.x, start: this.view.start, moved: false };
        cv.style.cursor = 'grabbing';
      });
      window.addEventListener('mouseup', () => {
        if (this.drag) { this.drag = null; cv.style.cursor = 'crosshair'; }
      });
      cv.addEventListener('mousemove', e => {
        const L = this._layout();
        const p = this._pos(e);
        if (this.drag) {
          const { i0, i1 } = this._visible();
          const step = (L.plotX1 - L.plotX0) / (i1 - i0);
          const d = Math.round((p.x - this.drag.x) / step);
          if (d !== 0) this.drag.moved = true;
          this.view.start = Math.max(0, Math.min(this.axis.length - this.view.count, this.drag.start - d));
        }
        this.hover = this._indexAt(p.x, L);
        this.draw();
        if (this.onHover) this.onHover(this.hover, this.axis[this.hover]);
      });
      cv.addEventListener('mouseleave', () => {
        this.hover = null; this.draw();
        if (this.onHover) this.onHover(null, null);
      });

      cv.addEventListener('wheel', e => {
        e.preventDefault();
        const L = this._layout();
        const p = this._pos(e);
        const { i0, i1 } = this._visible();
        const anchor = i0 + (p.x - L.plotX0) / ((L.plotX1 - L.plotX0) / (i1 - i0));
        const ratio = p.x / Math.max(1, L.plotX1 - L.plotX0);
        const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
        const n = this.axis.length;
        let count = Math.round(this.view.count * factor);
        count = Math.max(20, Math.min(n, count));
        let start = Math.round(anchor - ratio * count);
        start = Math.max(0, Math.min(n - count, start));
        this.view = { start, count };
        this.draw();
      }, { passive: false });

      cv.addEventListener('dblclick', () => this.reset());
    }
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function fmt(v) {
    if (v === null || v === undefined || !isFinite(v)) return '—';
    const a = Math.abs(v);
    if (a >= 10000) return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
    if (a >= 100) return v.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
    if (a >= 1) return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
    return v.toLocaleString('zh-CN', { maximumFractionDigits: 4 });
  }

  window.KLineChart = KLineChart;
  window.klineFmt = fmt;
  window.KLINE_COLORS = { MA_N, EXPMA_N, C };
  // 供外部复用的有效性判定：期货价格不可能为 0，<=0 视为无效
  window.KLINE_OK = { px: okPx, bar: okBar };
})();
