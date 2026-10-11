/* ============================================================
   期货数据工作台 · 前端逻辑
   图表：总览用自研轻量 SVG；品种详情用 Canvas K线组件(kline.js)
   ============================================================ */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const MARKET_COLORS = {
  CFFEX: "#4a63e7", SHFE: "#6a86ff", CZCE: "#0ea5a5",
  DCE: "#22c7b8", INE: "#f59e0b", GFEX: "#a855f7",
};
const PALETTE = ["#4a63e7", "#6a86ff", "#0ea5a5", "#22c7b8", "#f59e0b",
  "#a855f7", "#ec4899", "#14b8a6", "#f97316", "#8b5cf6",
  "#06b6d4", "#ef4444", "#84cc16", "#eab308", "#6366f1"];

const MAX_OVERLAY = 20;   // 折线叠加最多显示多少条合约

const STATUS = {
  chips: null,
  markets: new Set(),
  varieties: new Set(),
  allVarieties: [],
  summary: [],
  sortKey: null,
  sortDir: -1,
  pollTimer: null,
  lastLogCount: 0,
};

// 详情页状态
const KL = {
  chart: null,
  code: null,
  data: null,       // /api/variety 返回
  view: "weighted", // weighted | all | "1".."12" | contract:<symbol>
  cache: {},        // 月份分组数据缓存
  lastHigh: null,
  lastLow: null,
};

/* ---------------- 工具 ---------------- */
function fmtNum(v, digits = 0) {
  if (v === null || v === undefined || v === "" || Number.isNaN(v)) return "—";
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return n.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function fmtDate(s) {
  if (!s) return "—";
  s = String(s);
  return s.length === 8 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : s;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function toast(msg, type = "", sub = "") {
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.innerHTML = `<div>${esc(msg)}</div>${sub ? `<small>${esc(sub)}</small>` : ""}`;
  $("#toasts").appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .3s, transform .3s";
    el.style.opacity = "0"; el.style.transform = "translateX(24px)";
    setTimeout(() => el.remove(), 320);
  }, type === "err" ? 6500 : 3800);
}
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/* ============================================================
   一、配置与选择器
   ============================================================ */
async function loadConfig() {
  const cfg = await api("/api/config");
  STATUS.chips = cfg;

  const mc = $("#marketChips");
  mc.innerHTML = "";
  cfg.markets.forEach(m => {
    const b = document.createElement("button");
    b.className = "chip on";
    b.dataset.code = m.code;
    b.innerHTML = `${esc(m.cn)}<small>${esc(m.code)}</small>`;
    b.onclick = () => {
      if (STATUS.markets.has(m.code)) STATUS.markets.delete(m.code);
      else STATUS.markets.add(m.code);
      b.classList.toggle("on");
      renderVarieties();
    };
    mc.appendChild(b);
    STATUS.markets.add(m.code);
  });

  const lastOut = cfg.last_out || cfg.default_out;
  $("#outDir").value = lastOut;
  $("#cacheDir").value = cfg.last_cache || cfg.default_cache;
  $("#saveDir").value = lastOut;
  $("#localDir").value = cfg.last_dir || cfg.default_out;
  $("#dceYear").value = "2000";
  if (cfg.last_dir) {
    $("#localTip").innerHTML =
      `上次使用：<b>${esc(cfg.last_dir)}</b> · 启动时已自动恢复，无需重复抓取；如数据已迁移，可改选目录后点「载入本地数据」。`;
  }

  const all = [];
  cfg.markets.forEach(m => (m.varieties || []).forEach(v =>
    all.push({ code: v, name: cfg.variety_name[v] || v, market: m.code })));
  const seen = new Set();
  STATUS.allVarieties = all.filter(v => (seen.has(v.code) ? false : (seen.add(v.code), true)));

  if (!cfg.has_akshare) {
    toast("未检测到 akshare 库", "warn", "实际抓取需要：pip install akshare pandas numpy openpyxl");
  }
  renderVarieties();
}

function renderVarieties() {
  const box = $("#varietyBox");
  const kw = ($("#varSearch").value || "").trim().toUpperCase();
  const cfg = STATUS.chips;
  box.innerHTML = "";
  let shown = 0;

  cfg.markets.forEach(m => {
    if (!STATUS.markets.has(m.code)) return;
    const items = (m.varieties || []).map(c => ({
      code: c, name: cfg.variety_name[c] || c, market: m.code,
    })).filter(v => !kw || v.code.includes(kw) || v.name.toUpperCase().includes(kw));
    if (!items.length) return;
    shown += items.length;

    const wrap = document.createElement("div");
    wrap.className = "vgroup";

    const head = document.createElement("div");
    head.className = "vgroup-head";
    const selAll = STATUS.varieties.size === 0 || items.every(v => STATUS.varieties.has(v.code));
    head.innerHTML = `<span class="tag">${esc(m.code)}</span><span>${esc(m.cn)}</span>` +
      `<span class="gsel">${selAll ? "取消本组" : "全选本组"}</span>`;
    head.querySelector(".gsel").onclick = () => {
      STATUS.varieties.delete("_none_");
      if (STATUS.varieties.size === 0) STATUS.allVarieties.forEach(v => STATUS.varieties.add(v.code));
      const allOn = items.every(v => STATUS.varieties.has(v.code));
      items.forEach(v => allOn ? STATUS.varieties.delete(v.code) : STATUS.varieties.add(v.code));
      if (STATUS.varieties.size === STATUS.allVarieties.length) STATUS.varieties.clear();
      renderVarieties();
    };

    const list = document.createElement("div");
    list.className = "vitems";
    items.forEach(v => {
      const el = document.createElement("span");
      const on = STATUS.varieties.size === 0 || STATUS.varieties.has(v.code);
      el.className = "vitem" + (on ? " on" : "");
      el.textContent = `${v.code} ${v.name}`;
      el.onclick = () => {
        STATUS.varieties.delete("_none_");
        if (STATUS.varieties.size === 0) STATUS.allVarieties.forEach(x => STATUS.varieties.add(x.code));
        if (STATUS.varieties.has(v.code)) STATUS.varieties.delete(v.code);
        else STATUS.varieties.add(v.code);
        if (STATUS.varieties.size === STATUS.allVarieties.length) STATUS.varieties.clear();
        renderVarieties();
      };
      list.appendChild(el);
    });

    wrap.appendChild(head);
    wrap.appendChild(list);
    box.appendChild(wrap);
  });

  if (!shown) box.innerHTML = `<div class="vitems"><span class="vitem dim">没有匹配的品种</span></div>`;

  const n = STATUS.varieties.size === 0
    ? STATUS.allVarieties.length
    : (STATUS.varieties.has("_none_") ? 0 : STATUS.varieties.size);
  $("#varietyCount").textContent = `已选 ${n} / ${STATUS.allVarieties.length}`;
}

/* ============================================================
   二、目录选择（系统原生对话框）
   ============================================================ */
async function pickDir(targetId, title) {
  const cur = $("#" + targetId).value || "";
  toast("正在打开系统选择窗口…", "", "如未弹出请检查是否被其他窗口遮挡");
  try {
    const res = await api("/api/pick", {
      method: "POST",
      body: JSON.stringify({ mode: "dir", initial: cur, title }),
    });
    if (res.ok && res.path) {
      $("#" + targetId).value = res.path;
      toast("已选择位置", "ok", res.path);
    } else if (res.error) toast("无法打开系统对话框", "err", res.error);
  } catch (e) { toast("无法打开系统对话框", "err", String(e)); }
}
document.addEventListener("click", e => {
  const btn = e.target.closest("[data-pick]");
  if (btn) pickDir(btn.dataset.pick, btn.dataset.title || "选择文件夹");
});

/* ============================================================
   三、运行任务
   ============================================================ */
async function startRun() {
  const markets = Array.from(STATUS.markets);
  if (!markets.length) return toast("请至少选择一个交易所", "warn");

  const picked = Array.from(STATUS.varieties).filter(x => x !== "_none_");
  if (STATUS.varieties.size && !picked.length) {
    return toast("请至少勾选一个品种", "warn", "或点击「全选」抓取全部品种");
  }
  const keep = STATUS.varieties.size ? picked : null;

  const body = {
    markets, keep,
    start: $("#startDate").value.trim(),
    end: $("#endDate").value.trim(),
    out_dir: $("#outDir").value.trim(),
    cache_dir: $("#cacheDir").value.trim(),
    workers: Number($("#workers").value),
    no_repair: $("#noRepair").checked,
    dce_start_year: Number($("#dceYear").value) || 2000,
  };

  try {
    const res = await api("/api/run", { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) return toast("无法启动任务", "err", res.error);
    toast("任务已启动", "ok", "首次全量抓取约需 1 个半小时，请保持窗口开启");
    setRunning(true);
    switchTab("log");
    poll();
  } catch (e) { toast("启动失败", "err", String(e)); }
}

async function stopRun() {
  try {
    const res = await api("/api/stop", { method: "POST" });
    toast(res.ok ? "已发送停止指令" : "无法停止", res.ok ? "warn" : "err", res.error || "");
  } catch (e) { toast("停止失败", "err", String(e)); }
}

function setRunning(on) {
  $("#btnRun").disabled = on;
  $("#btnRun").querySelector(".spinner").hidden = !on;
  $("#btnRun").querySelector(".txt").textContent = on ? "抓取中…" : "开始抓取";
  $("#btnStop").hidden = !on;
  const sp = $("#statusPill");
  sp.className = "pill " + (on ? "running" : "");
  sp.innerHTML = `<i class="dot"></i>${on ? "运行中" : "就绪"}`;
}

function setProgress(pct, text) {
  $("#progressBar").style.width = Math.max(0, Math.min(100, pct)) + "%";
  $("#progressPct").textContent = Math.round(pct) + "%";
  if (text) $("#progressText").textContent = text;
}

async function poll() {
  clearTimeout(STATUS.pollTimer);
  let st;
  try { st = await api("/api/progress"); }
  catch (e) { STATUS.pollTimer = setTimeout(poll, 2500); return; }

  setProgress(st.percent, st.running ? "正在抓取数据…" :
    (st.ok === "success" ? "已完成" : (st.ok === "error" ? "出错了" : "就绪")));

  const box = $("#logBox");
  if (st.logs.length !== STATUS.lastLogCount) {
    const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
    box.textContent = st.logs.join("\n");
    if (atBottom) box.scrollTop = box.scrollHeight;
    STATUS.lastLogCount = st.logs.length;
    $("#logBadge").textContent = st.logs.length;
  }

  if (st.running) { setRunning(true); STATUS.pollTimer = setTimeout(poll, 1200); return; }

  setRunning(false);
  if (st.ok === "success") {
    toast("抓取完成", "ok", `共 ${st.variety_count} 个品种，已生成 Excel`);
    await refreshResults();
    switchTab("overview");
  } else if (st.ok === "error") {
    toast("任务出错", "err", st.error || "详见运行日志");
    $("#statusPill").className = "pill err";
    $("#statusPill").innerHTML = `<i class="dot"></i>出错`;
  }
}

/* ============================================================
   四、结果渲染
   ============================================================ */
async function loadDemo() {
  try {
    const res = await api("/api/demo", { method: "POST" });
    if (!res.ok) return toast("载入失败", "err", res.error);
    toast("已载入文章示例数据", "ok", `${res.count} 个品种的汇总统计`);
    await refreshResults();
    switchTab("overview");
  } catch (e) { toast("载入失败", "err", String(e)); }
}

/* 读取本机已有数据目录（免重复联网抓取） */
async function loadLocal() {
  const dir = $("#localDir").value.trim();
  if (!dir) return toast("请先选择数据目录", "warn", "点右侧「浏览…」选择之前抓取生成的数据目录");
  const btn = $("#btnLoadLocal");
  const old = btn.textContent;
  btn.disabled = true; btn.textContent = "读取中…";
  try {
    const res = await api("/api/load-local", {
      method: "POST", body: JSON.stringify({ dir }),
    });
    if (!res.ok) return toast("载入失败", "err", res.error);
    const kind = res.kind === "pickle" ? "明细缓存" : "各品种 Excel";
    toast("已载入本地数据", "ok",
      `${res.variety_count} 个品种 / ${Number(res.rows).toLocaleString("zh-CN")} 行K线`);
    $("#outDir").value = res.dir;
    $("#saveDir").value = res.dir;
    $("#localTip").innerHTML =
      `已载入：<b>${esc(res.dir)}</b> · ${res.variety_count} 个品种 · ` +
      `${Number(res.rows).toLocaleString("zh-CN")} 行 · 来源 ${kind}`;
    await refreshResults();
    switchTab("overview");
  } catch (e) {
    toast("载入失败", "err", String(e));
  } finally {
    btn.disabled = false; btn.textContent = old;
  }
}

async function refreshResults() {
  const d = await api("/api/summary");
  STATUS.summary = d.summary || [];
  const pill = $("#sourcePill");
  if (d.source === "live") {
    const local = d.origin === "local";
    pill.className = "pill ok";
    pill.innerHTML = `<i class="dot"></i>${local ? "本地数据" : "实盘抓取"} · ${STATUS.summary.length} 品种`;
  } else if (d.source === "demo") {
    pill.className = "pill";
    pill.innerHTML = `<i class="dot"></i>文章示例数据 · ${STATUS.summary.length} 品种`;
  } else {
    pill.className = "pill ghost";
    pill.innerHTML = `<i class="dot"></i>未加载数据`;
  }
  KL.cache = {};
  KL.code = null;
  KL.data = null;
  KL.lastHigh = null;
  KL.lastLow = null;
  renderKpis();
  renderDonut();
  renderMktSummary();
  renderSummaryTable();
  renderDetailSelect();
  $("#btnSave").disabled = STATUS.summary.length === 0;

  const isLive = d.source === "live";
  $("#detailEmpty").hidden = isLive;
  $("#detailBody").hidden = !isLive;
  if (!isLive) {
    $("#detailEmptyMsg").textContent = d.source === "demo"
      ? "示例数据只含汇总统计，不含逐日行情。完成一次实际抓取后即可查看合约K线。"
      : "请先在左侧完成一次实际抓取，然后在此查看合约日K明细。";
  }
}

/* ---- KPI ---- */
function renderKpis() {
  const rows = STATUS.summary;
  if (!rows.length) { $("#kpis").innerHTML = ""; return; }
  const markets = new Set(rows.map(r => r["交易所"]));
  const totalK = rows.reduce((a, r) => a + (r["总K线条数"] || 0), 0);
  const totalDays = rows.reduce((a, r) => a + (r["总交易天数"] || 0), 0);
  const dates = rows.map(r => r["上市日期"]).filter(Boolean).sort();
  const items = [
    { l: "品种数量", v: fmtNum(rows.length), s: "个" },
    { l: "覆盖交易所", v: fmtNum(markets.size), s: "家" },
    { l: "日K记录总数", v: fmtNum(totalK), s: "条" },
    { l: "累计交易天数", v: fmtNum(totalDays), s: "天" },
    { l: "最早上市", v: fmtDate(dates[0]), hl: true, small: true },
    { l: "最晚上市", v: fmtDate(dates[dates.length - 1]), hl: true, small: true },
  ];
  $("#kpis").innerHTML = items.map(it => `
    <div class="kpi${it.hl ? " hl" : ""}">
      <div class="k-label">${it.l}</div>
      <div class="k-value" style="${it.small ? "font-size:17px" : ""}">${it.v}${it.s ? `<small>${it.s}</small>` : ""}</div>
    </div>`).join("");
}

/* ---- 环形图 ---- */
function renderDonut() {
  const host = $("#chartDonut");
  const rows = STATUS.summary;
  if (!rows.length) { host.innerHTML = emptySvg("暂无数据"); return; }

  const map = {};
  rows.forEach(r => { map[r["交易所"]] = (map[r["交易所"]] || 0) + 1; });
  const data = Object.entries(map).map(([k, v]) => ({ k, v })).sort((a, b) => b.v - a.v);
  const total = data.reduce((a, d) => a + d.v, 0);

  const W = host.clientWidth || 340, H = host.clientHeight || 260;
  const cx = W * 0.36, cy = H / 2;
  const R = Math.min(W * 0.30, H * 0.40), r = R * 0.62;

  let a0 = -Math.PI / 2, arcs = "";
  data.forEach((d, i) => {
    const a1 = a0 + (d.v / total) * Math.PI * 2;
    const color = MARKET_COLORS[d.k] || PALETTE[i % PALETTE.length];
    const large = (a1 - a0) > Math.PI ? 1 : 0;
    const x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0);
    const x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1);
    const x2 = cx + r * Math.cos(a1), y2 = cy + r * Math.sin(a1);
    const x3 = cx + r * Math.cos(a0), y3 = cy + r * Math.sin(a0);
    arcs += `<path d="M${x0} ${y0} A${R} ${R} 0 ${large} 1 ${x1} ${y1} L${x2} ${y2} A${r} ${r} 0 ${large} 0 ${x3} ${y3} Z"
              fill="${color}" stroke="#fff" stroke-width="2"/>`;
    a0 = a1;
  });

  const lx = W * 0.66, ly0 = cy - data.length * 12 + 5;
  let legend = "";
  data.forEach((d, i) => {
    const color = MARKET_COLORS[d.k] || PALETTE[i % PALETTE.length];
    const y = ly0 + i * 24;
    legend += `
      <rect x="${lx}" y="${y - 8}" width="9" height="9" rx="3" fill="${color}"/>
      <text x="${lx + 15}" y="${y + 1}" font-size="11.5" fill="#16224a" font-weight="600">${esc(d.k)}</text>
      <text x="${W - 6}" y="${y + 1}" font-size="11" fill="#5a678c" text-anchor="end">${d.v} 个 · ${((d.v / total) * 100).toFixed(0)}%</text>`;
  });

  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}">
    ${arcs}
    <text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="23" font-weight="700" fill="#16224a">${total}</text>
    <text x="${cx}" y="${cy + 17}" text-anchor="middle" font-size="10.5" fill="#93a0c0">品种总数</text>
    ${legend}
  </svg>`;
}

/* ---- 交易所明细 ---- */
function renderMktSummary() {
  const host = $("#mktSummary");
  const rows = STATUS.summary;
  if (!rows.length) { host.innerHTML = ""; return; }

  const agg = {};
  rows.forEach(r => {
    const m = r["交易所"] || "?";
    if (!agg[m]) agg[m] = { n: 0, k: 0, days: 0, mkts: r["交易所"] };
    agg[m].n += 1;
    agg[m].k += (r["总K线条数"] || 0);
    agg[m].days += (r["总交易天数"] || 0);
  });
  const arr = Object.entries(agg).map(([k, v]) => ({ k, ...v })).sort((a, b) => b.n - a.n);
  const maxN = Math.max(...arr.map(a => a.n)) || 1;
  const totalN = arr.reduce((a, b) => a + b.n, 0) || 1;

  host.innerHTML = arr.map((a, i) => {
    const color = MARKET_COLORS[a.k] || PALETTE[i % PALETTE.length];
    const cn = (STATUS.chips?.markets.find(m => m.code === a.k)?.cn) || a.k;
    return `<div class="mkt-row">
      <span class="mkt-dot" style="background:${color}"></span>
      <span class="mkt-name">${esc(cn)}<small>${esc(a.k)}</small></span>
      <span class="mkt-cell"><b>${a.n}</b>品种 · 占比 ${((a.n / totalN) * 100).toFixed(0)}%</span>
      <span class="mkt-cell"><b>${fmtNum(a.k)}</b>K线条数</span>
      <span class="mkt-bar"><span style="width:${(a.n / maxN) * 100}%;background:${color}"></span></span>
    </div>`;
  }).join("");
}

function emptySvg(txt) {
  return `<div style="height:100%;display:grid;place-items:center;color:#93a0c0;font-size:12.5px">${esc(txt)}</div>`;
}

/* ---- 汇总表 ---- */
const SUM_COLS = [
  { k: "品种代码", t: "品种代码", cls: "code" },
  { k: "品种名称", t: "品种名称" },
  { k: "交易所", t: "交易所", mkt: true },
  { k: "上市日期", t: "上市日期", fmt: fmtDate },
  { k: "总交易天数", t: "交易天数", num: true },
  { k: "总K线条数", t: "K线条数", num: true },
  { k: "历史最高价", t: "最高价", num: true, cls: "num hi" },
  { k: "最高价日期", t: "最高价日期", fmt: fmtDate },
  { k: "最高价合约", t: "最高价合约", mono: true },
  { k: "历史最低价", t: "最低价", num: true, cls: "num lo" },
  { k: "最低价日期", t: "最低价日期", fmt: fmtDate },
  { k: "最低价合约", t: "最低价合约", mono: true },
  { k: "主连平均收盘价", t: "主连均收盘", num: true, digits: 2 },
  { k: "主连平均结算价", t: "主连均结算", num: true, digits: 2 },
];

function renderSummaryTable() {
  const host = $("#summaryTable");
  const kw = ($("#tableSearch").value || "").trim().toUpperCase();
  let rows = STATUS.summary;

  if (kw) {
    rows = rows.filter(r =>
      String(r["品种代码"]).toUpperCase().includes(kw) ||
      String(r["品种名称"]).toUpperCase().includes(kw) ||
      String(r["交易所"]).toUpperCase().includes(kw));
  }
  if (STATUS.sortKey) {
    const k = STATUS.sortKey, dir = STATUS.sortDir;
    rows = [...rows].sort((a, b) => {
      const x = a[k], y = b[k];
      if (typeof x === "number" || typeof y === "number") return ((Number(x) || 0) - (Number(y) || 0)) * dir;
      return String(x ?? "").localeCompare(String(y ?? "")) * dir;
    });
  }

  let html = `<thead><tr>${SUM_COLS.map(c => {
    const sorted = STATUS.sortKey === c.k;
    return `<th class="sortable${sorted ? " sorted" : ""}" data-k="${esc(c.k)}">${esc(c.t)}<span class="arrow">${sorted ? (STATUS.sortDir > 0 ? "▲" : "▼") : "↕"}</span></th>`;
  }).join("")}</tr></thead><tbody>`;

  html += rows.map(r => `<tr>${SUM_COLS.map(c => {
    const v = r[c.k];
    let txt;
    if (c.fmt) txt = c.fmt(v);
    else if (c.num) txt = fmtNum(v, c.digits || 0);
    else txt = (v === null || v === undefined || v === "") ? "—" : esc(v);
    if (c.mkt) return `<td><span class="mkt">${txt}</span></td>`;
    if (c.code) return `<td class="code clickable" data-code="${esc(r["品种代码"])}">${txt}</td>`;
    if (c.cls) return `<td class="${c.cls}">${txt}</td>`;
    if (c.mono) return `<td style="font-family:var(--mono);font-size:11px;color:#5a678c">${txt}</td>`;
    return `<td>${txt}</td>`;
  }).join("")}</tr>`).join("");
  html += "</tbody>";
  host.innerHTML = html;
  $("#tableFoot").textContent = `显示 ${rows.length} / ${STATUS.summary.length} 条记录`;

  $$("th.sortable", host).forEach(th => th.onclick = () => {
    const k = th.dataset.k;
    if (STATUS.sortKey === k) STATUS.sortDir *= -1;
    else { STATUS.sortKey = k; STATUS.sortDir = -1; }
    renderSummaryTable();
  });
  $$("td.code.clickable", host).forEach(td => td.onclick = () => {
    $("#detailSelect").value = td.dataset.code;
    switchTab("detail");
  });
}

/* ============================================================
   五、品种详情（合约按月分组 + 加权合约 + 交互式K线）
   ============================================================ */
function renderDetailSelect() {
  const sel = $("#detailSelect");
  const rows = [...STATUS.summary].sort((a, b) =>
    String(a["品种代码"]).localeCompare(String(b["品种代码"])));
  sel.innerHTML = rows.map(r =>
    `<option value="${esc(r["品种代码"])}">${esc(r["品种代码"])} · ${esc(r["品种名称"])}（${esc(r["交易所"])}）</option>`
  ).join("") || `<option>暂无数据</option>`;
}

async function loadVariety(code) {
  code = code || $("#detailSelect").value;
  if (!code) return;
  KL.code = code;
  KL.cache = {};
  try {
    const d = await api(`/api/variety?code=${encodeURIComponent(code)}`);
    if (!d.ok) {
      $("#detailEmpty").hidden = false;
      $("#detailEmptyMsg").textContent = d.message || "暂无明细数据。";
      $("#detailBody").hidden = true;
      return;
    }
    KL.data = d;
    $("#detailEmpty").hidden = true;
    $("#detailBody").hidden = false;
    buildViewSeg();
    renderContractTable();
    renderDetailStats();
    setView("weighted");
  } catch (e) {
    toast("加载品种明细失败", "err", String(e));
  }
}

function buildViewSeg() {
  const seg = $("#viewSeg");
  const d = KL.data;
  const parts = [
    `<button data-v="weighted" class="on">加权合约</button>`,
    `<button data-v="all">全部合约</button>`,
  ];
  Object.keys(d.groups)
    .map(Number).sort((a, b) => a - b)
    .forEach(m => parts.push(`<button data-v="${m}">${m}月</button>`));
  seg.innerHTML = parts.join("");
  seg.onclick = e => {
    const b = e.target.closest("button");
    if (!b) return;
    $$("button", seg).forEach(x => x.classList.remove("on"));
    b.classList.add("on");
    setView(b.dataset.v);
  };
}

function renderDetailStats() {
  const row = STATUS.summary.find(r => r["品种代码"] === KL.code);
  const d = KL.data;
  const ds = $("#detailStats");
  const wh = d.weighted_high, wl = d.weighted_low;
  const items = [
    ["品种", `${d.code} ${d.name}`, d.market, ""],
    ["合约总数", fmtNum(d.contracts.length), "个（含已退市）", ""],
    ["日K记录", fmtNum(d.total_rows), "条", ""],
    ["加权合约最高", wh ? fmtNum(wh.price) : "—", wh ? wh.date : "", "up"],
    ["加权合约最低", wl ? fmtNum(wl.price) : "—", wl ? wl.date : "", "down"],
    ["加权合约天数", fmtNum(d.weighted.length), "个交易日", ""],
    ["汇总·上市日期", row ? fmtDate(row["上市日期"]) : "—", "", ""],
    ["汇总·总K线条数", row ? fmtNum(row["总K线条数"]) : "—", "条", ""],
  ];
  ds.innerHTML = items.map(([l, v, m, c]) => `<div class="dstat">
      <div class="dl">${esc(l)}</div>
      <div class="dv ${c}">${esc(v)}</div>
      ${m ? `<div class="dm">${esc(m)}</div>` : ""}
    </div>`).join("");
}

/* ---- 合约清单 ---- */
function renderContractTable() {
  const host = $("#contractTable");
  const d = KL.data;
  const contracts = d.contracts;

  // 按月份分组渲染：同一月份（跨年）排在一起
  const byMonth = {};
  contracts.forEach(c => (byMonth[c.month] = byMonth[c.month] || []).push(c));

  let html = `<thead><tr>
    <th>月份</th><th>合约</th><th>交割年月</th><th>首个交易日</th><th>最后交易日</th><th>K线条数</th>
  </tr></thead><tbody>`;

  Object.keys(byMonth).map(Number).sort((a, b) => a - b).forEach(m => {
    const list = byMonth[m];
    list.forEach((c, i) => {
      const isView = String(KL.view) === String(m);
      html += `<tr class="${isView ? "row-active" : ""}">
        ${i === 0 ? `<td rowspan="${list.length}"><span class="mkt">${m}月</span></td>` : ""}
        <td class="code clickable" data-sym="${esc(c.symbol)}">${esc(c.symbol)}</td>
        <td>${esc(c.delivery)}</td>
        <td>${fmtDate(c.first)}</td>
        <td>${fmtDate(c.last)}</td>
        <td>${fmtNum(c.rows)}</td>
      </tr>`;
    });
  });
  html += "</tbody>";
  host.innerHTML = html;
  $("#contractSub").textContent =
    `${contracts.length} 个合约 · ${Object.keys(byMonth).length} 个月份分组 · 点击合约可看单合约K线`;

  $$("td.code.clickable", host).forEach(td => td.onclick = () => {
    loadContract(td.dataset.sym);
  });
}

function markActiveRow(symbol) {
  $$("#contractTable tbody tr").forEach(tr => {
    const td = tr.querySelector("td.code");
    tr.classList.toggle("row-active", !!td && td.dataset.sym === symbol);
  });
}

/* ---- 视图切换 ---- */
async function setView(v) {
  if (!KL.data) return;
  KL.view = v;
  const seg = $("#viewSeg");
  $$("button", seg).forEach(x => x.classList.toggle("on", x.dataset.v === String(v)));
  const chart = KL.chart;
  const d = KL.data;

  if (v === "weighted") {
    chart.setCandle(d.weighted, {});
    setTitle(`${d.code} ${d.name} · 加权合约`, "按各合约持仓量加权合成（持仓量为 0 时退化为成交量加权）");
    KL.lastHigh = extrema(d.weighted, true).hi;
    KL.lastLow = extrema(d.weighted, true).lo;
    setLegendIndicators();
    renderExtrema();
    markActiveRow(null);
    return;
  }

  if (v === "all") {
    const res = await fetchContracts(null);
    if (!res) return;
    chart.setLines(res.series, {});
    setTitle(`${d.code} ${d.name} · 全部合约`,
      res.truncated
        ? `共 ${res.total_contracts} 个合约，为便于查看仅叠加最近 ${res.contracts.length} 个`
        : `共 ${res.contracts.length} 个合约折线叠加`);
    setLegendLines(chart);
    afterLinesExtrema(res);
    markActiveRow(null);
    return;
  }

  const m = Number(v);
  const res = await fetchContracts(m);
  if (!res) return;
  const names = Object.keys(res.series);
  if (names.length === 1) {
    // 该月只有一个合约 —— 直接用蜡烛图 + 指标
    const sym = names[0];
    chart.setCandle(res.series[sym], {});
    setTitle(`${d.code} ${d.name} · ${m}月合约 ${sym}`,
      `${fmtDate(res.contracts[0].first)} 起 · 共 ${res.contracts[0].rows} 根K线`);
    KL.lastHigh = extrema(res.series[sym], true).hi;
    KL.lastLow = extrema(res.series[sym], true).lo;
    setLegendIndicators();
    renderExtrema();
    markActiveRow(sym);
  } else {
    chart.setLines(res.series, {});
    setTitle(`${d.code} ${d.name} · ${m}月合约（跨年同月）`,
      res.truncated
        ? `共 ${res.total_contracts} 个合约，仅叠加最近 ${names.length} 个同期对比`
        : `共 ${names.length} 个合约同期对比，点击下方合约可切换为单合约K线`);
    setLegendLines(chart);
    afterLinesExtrema(res);
    markActiveRow(null);
  }
}

async function fetchContracts(month) {
  if (!KL.data) return null;
  const key = month === null ? "all" : String(month);
  if (KL.cache[key]) return KL.cache[key];
  try {
    const url = `/api/contracts?code=${encodeURIComponent(KL.code)}&limit=${MAX_OVERLAY}` +
      (month === null ? "" : `&month=${month}`);
    const res = await api(url);
    if (!res.ok) { toast("加载合约数据失败", "err", res.message || ""); return null; }
    KL.cache[key] = res;
    return res;
  } catch (e) { toast("加载合约数据失败", "err", String(e)); return null; }
}

async function loadContract(symbol) {
  try {
    const res = await api(`/api/contract?symbol=${encodeURIComponent(symbol)}`);
    if (!res.ok) return toast("加载合约失败", "err", res.message || "");
    KL.chart.setCandle(res.series, {});
    const d = KL.data;
    setTitle(`${d.code} ${d.name} · 单合约 ${res.symbol}`,
      `${fmtDate(res.series[0].d)} ~ ${fmtDate(res.series[res.series.length - 1].d)} · 共 ${res.series.length} 根K线`);
    KL.lastHigh = extrema(res.series, true).hi;
    KL.lastLow = extrema(res.series, true).lo;
    setLegendIndicators();
    renderExtrema();
    markActiveRow(res.symbol);
  } catch (e) { toast("加载合约失败", "err", String(e)); }
}

/* ---- 标题 / 图例 / 极值 ---- */
function setTitle(main, sub) {
  $("#klineTitle").innerHTML = `${esc(main)}${sub ? `<small>${esc(sub)}</small>` : ""}`;
}

function renderExtrema() {
  const host = $("#klineExtrema");
  const hi = KL.lastHigh, lo = KL.lastLow;
  host.innerHTML =
    (hi ? `<span class="hi">历史最高 <b>${fmtNum(hi.price)}</b></span><span>${esc(hi.date)}</span>` : "") +
    (lo ? `<span class="lo">历史最低 <b>${fmtNum(lo.price)}</b></span><span>${esc(lo.date)}</span>` : "");
  KL.chart.high = hi; KL.chart.low = lo;
  KL.chart.draw();
}

function setLegendIndicators() {
  const ind = KL.chart.indicators;
  const items = [];
  const C = window.KLINE_COLORS.C;
  if (ind.ma) window.KLINE_COLORS.MA_N.forEach((n, i) =>
    items.push(`<span class="lg"><i style="background:${C.ma[i % C.ma.length]}"></i>MA${n}</span>`));
  if (ind.expma) window.KLINE_COLORS.EXPMA_N.forEach((n, i) =>
    items.push(`<span class="lg"><i style="background:${C.expma[i % C.expma.length]}"></i>EXPMA${n}</span>`));
  if (ind.boll) items.push(
    `<span class="lg"><i style="background:${C.bollLine}"></i>BOLL(20,2)</span>`,
    `<span class="lg"><i style="background:${C.bollMid}"></i>BOLL中轨</span>`);
  if (ind.bbiboll) items.push(
    `<span class="lg"><i style="background:${C.bbiLine}"></i>BBIBOLL上/下轨</span>`,
    `<span class="lg"><i style="background:${C.bbiMid}"></i>BBI</span>`);
  if (ind.sar) items.push(`<span class="lg"><i style="background:${C.sar}"></i>SAR</span>`);
  items.push(`<span class="lg"><i style="background:${"#e5484d"}"></i>阳线</span>`,
    `<span class="lg"><i style="background:${"#12a150"}"></i>阴线</span>`);
  $("#klineLegend").innerHTML = items.join("");
}

function setLegendLines(chart) {
  $("#klineLegend").innerHTML = chart.lines.map(l =>
    `<span class="lg toggleable${l.visible ? "" : " dim"}" data-name="${esc(l.name)}">
       <i style="background:${l.color}"></i>${esc(l.name)}
     </span>`).join("");
  $$("#klineLegend .lg.toggleable").forEach(el => el.onclick = () => {
    chart.toggleLine(el.dataset.name);
    el.classList.toggle("dim");
  });
}

function afterLinesExtrema(res) {
  // 折线叠加模式下，极值在合并后的坐标轴内计算（零值点不计入）
  let hi = null, lo = null;
  Object.entries(res.series).forEach(([sym, arr]) => {
    arr.forEach(p => {
      if (!(p.c > 0)) return;
      if (hi === null || p.c > hi.price) hi = { price: p.c, date: p.d, symbol: sym };
      if (lo === null || p.c < lo.price) lo = { price: p.c, date: p.d, symbol: sym };
    });
  });
  const axis = KL.chart.axis;
  if (hi) hi.index = axis.indexOf(hi.date);
  if (lo) lo.index = axis.indexOf(lo.date);
  KL.lastHigh = hi; KL.lastLow = lo;
  renderExtrema();
}

function extrema(points, useHL) {
  let hi = null, lo = null;
  points.forEach((p, i) => {
    const hv = useHL ? p.h : p.c, lv = useHL ? p.l : p.c;
    if (hv !== null && hv !== undefined && isFinite(hv) && hv > 0) {
      if (hi === null || hv > hi.price) hi = { price: hv, date: p.d, index: i };
    }
    if (lv !== null && lv !== undefined && isFinite(lv) && lv > 0) {
      if (lo === null || lv < lo.price) lo = { price: lv, date: p.d, index: i };
    }
  });
  return { hi, lo };
}

/* ============================================================
   六、导出 / 保存到本机
   ============================================================ */
async function saveToLocal() {
  const dir = $("#saveDir").value.trim();
  if (!dir) return toast("请先选择本机保存位置", "warn", "点击右侧「选择位置…」按钮");
  if (!STATUS.summary.length) return toast("当前没有可保存的数据", "warn", "请先抓取或载入示例数据");
  const body = { dir, format: $("#saveFormat").value, scope: $("#saveScope").value };
  try {
    const res = await api("/api/export", { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) return toast("保存失败", "err", res.error);
    toast(`已保存 ${res.count} 个文件`, "ok", dir);
  } catch (e) { toast("保存失败", "err", String(e)); }
}

/* ============================================================
   七、Tab 与事件
   ============================================================ */
function switchTab(name) {
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  $$(".pane").forEach(p => p.classList.toggle("active", p.id === "pane-" + name));
  if (name === "overview") { renderDonut(); renderMktSummary(); }
  if (name === "table") renderSummaryTable();
  if (name === "detail") {
    const sel = $("#detailSelect").value;
    // 首次进入或切换了品种时按需加载（懒加载，避免无谓的接口开销）
    if (sel && STATUS.summary.length && KL.code !== sel) {
      loadVariety(sel).then(() => {
        KL.chart.draw();
        KL.chart.reset();
      });
    } else if (KL.chart) {
      setTimeout(() => { KL.chart.draw(); }, 30);
    }
  }
}

function bind() {
  $("#klineTip").textContent = "移动鼠标查看该日数据 · 拖拽平移 · 滚轮缩放 · 双击复位";
  $("#tabs").addEventListener("click", e => {
    const t = e.target.closest(".tab");
    if (t) switchTab(t.dataset.tab);
  });

  $("#btnRun").onclick = startRun;
  $("#btnStop").onclick = stopRun;
  $("#btnDemo").onclick = loadDemo;
  $("#btnLoadLocal").onclick = loadLocal;
  $("#btnSave").onclick = saveToLocal;

  // 底部「数据源说明」折叠面板（默认折叠）
  (function bindSrcPanel() {
    const bar = $("#srcBar"), body = $("#srcBody"), head = $("#srcToggle");
    if (!bar || !body || !head) return;
    head.onclick = () => {
      const willOpen = body.hidden;
      body.hidden = !willOpen;
      bar.classList.toggle("open", willOpen);
      head.setAttribute("aria-expanded", String(willOpen));
    };
  })();

  $("#btnAllVar").onclick = () => { STATUS.varieties.clear(); renderVarieties(); };
  $("#btnNoVar").onclick = () => { STATUS.varieties = new Set(["_none_"]); renderVarieties(); };
  $("#varSearch").oninput = renderVarieties;
  $("#tableSearch").oninput = renderSummaryTable;
  $("#workers").oninput = e => $("#workerVal").textContent = e.target.value;

  $("#detailSelect").onchange = () => loadVariety($("#detailSelect").value);

  // 指标勾选
  $$("#indBar input[data-ind]").forEach(cb => cb.onchange = () => {
    const ind = {};
    $$("#indBar input[data-ind]").forEach(x => ind[x.dataset.ind] = x.checked);
    KL.chart.setIndicators(ind);
    if (KL.chart.mode === "candle") setLegendIndicators();
  });

  $("#btnResetView").onclick = () => KL.chart && KL.chart.reset();
  $("#btnGotoHigh").onclick = () => {
    if (KL.lastHigh && KL.lastHigh.index >= 0) KL.chart.gotoIndex(KL.lastHigh.index);
    else toast("当前视图内没有历史最高价", "warn");
  };
  $("#btnGotoLow").onclick = () => {
    if (KL.lastLow && KL.lastLow.index >= 0) KL.chart.gotoIndex(KL.lastLow.index);
    else toast("当前视图内没有历史最低价", "warn");
  };

  $("#btnClearLog").onclick = () => {
    $("#logBox").textContent = "";
    $("#logBadge").textContent = "0";
    STATUS.lastLogCount = -1;
  };
  $("#btnCopyLog").onclick = async () => {
    try { await navigator.clipboard.writeText($("#logBox").textContent); toast("日志已复制", "ok"); }
    catch (e) { toast("复制失败", "err", String(e)); }
  };
  $("#btnExportCsv").onclick = () => { $("#saveFormat").value = "csv"; saveToLocal(); };
  $("#btnReset").onclick = () => {
    STATUS.markets = new Set();
    $$("#marketChips .chip").forEach(c => { STATUS.markets.add(c.dataset.code); c.classList.add("on"); });
    STATUS.varieties.clear();
    $("#varSearch").value = "";
    $("#startDate").value = "";
    $("#endDate").value = "";
    $("#workers").value = 10; $("#workerVal").textContent = "10";
    $("#dceYear").value = "2000";
    $("#noRepair").checked = false;
    $("#outDir").value = STATUS.chips?.default_out || "";
    $("#cacheDir").value = STATUS.chips?.default_cache || "";
    renderVarieties();
    toast("已恢复默认配置");
  };
}

/* ============================================================
   八、启动
   ============================================================ */
(function init() {
  bind();

  KL.chart = new window.KLineChart($("#klineCanvas"));
  KL.chart.onHover = (i, date) => {
    const tip = $("#klineTip");
    if (i === null || !date) { tip.textContent = "移动鼠标查看该日数据"; return; }
    const chart = KL.chart;
    if (chart.mode === "candle") {
      const b = chart.bars[i];
      if (!b) { tip.textContent = date; return; }
      if (!(b.o > 0 && b.h > 0 && b.l > 0 && b.c > 0)) {
        // 该日为零值/缺失占位数据，图上不绘制
        tip.innerHTML = `<b>${esc(b.d)}</b>　<span class="muted">该日无有效行情（零值数据，未绘制）</span>`;
        return;
      }
      const up = b.c >= b.o;
      tip.innerHTML = `<b>${esc(b.d)}</b>　开 ${window.klineFmt(b.o)}　高 <span class="up">${window.klineFmt(b.h)}</span>　低 <span class="down">${window.klineFmt(b.l)}</span>　收 <b class="${up ? "up" : "down"}">${window.klineFmt(b.c)}</b>　量 ${fmtNum(b.v)}`;
    } else {
      const parts = chart.lines.filter(l => l.vals[i] > 0)
        .map(l => `${esc(l.name)} ${window.klineFmt(l.vals[i])}`);
      tip.innerHTML = `<b>${esc(date)}</b>　${parts.join("　│　") || "该日无有效行情"}`;
    }
  };

  (async () => {
    try { await loadConfig(); }
    catch (e) { toast("无法读取配置", "err", String(e)); }
    try {
      const st = await api("/api/progress");
      if (st.has_result) await refreshResults();
      else await loadDemo();
      if (st.running) { setRunning(true); poll(); }
    } catch (e) { /* ignore */ }
  })();
})();
