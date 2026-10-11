# -*- coding: utf-8 -*-
"""国内期货全品种全合约日K数据工作台 —— Flask 后端

把公众号文章《公歧工作流：从期交所获取全部品种日K数据并分析.py》里的脚本，
包装成一个本地网页应用：
  · 网页上勾选交易所 / 品种 / 日期区间 / 并发线程
  · 点「开始抓取」，实时看日志与进度条
  · 结果以表格 + 图表呈现，可搜索、排序
  · 用系统原生对话框选择本机保存位置，一键导出 Excel / CSV

启动： python app.py      然后浏览器打开 http://127.0.0.1:8770
"""

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
import webbrowser


def _setup_stdio():
    """输出被重定向到文件/管道时改用 UTF-8，避免 Windows 默认 GBK 造成中文乱码。

    只处理「非终端」的情况：真正的控制台窗口保持原样，汉字本来就能正常显示。
    """
    for s in (sys.stdout, sys.stderr):
        try:
            if s is not None and not s.isatty():
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _writable(d):
    """目录是否可写（用临时文件实测，避免 Program Files 这类只读位置）。"""
    try:
        p = os.path.join(d, f"._wtest_{os.getpid()}")
        with open(p, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(p)
        return True
    except Exception:
        return False


def _app_dir():
    """用户工作目录：数据、缓存、偏好都放这里。

    打包成 exe 后取 exe 所在目录（数据跟着 exe 走，不会写进临时解包目录）；
    源码运行时取脚本所在目录。
    若该目录不可写（例如放进了 Program Files），退回用户主目录下的
    FuturesWorkbench 文件夹，避免抓取到最后一步才发现写不进去。
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
        if not _writable(base):
            alt = os.path.join(os.path.expanduser("~"), "FuturesWorkbench")
            try:
                os.makedirs(alt, exist_ok=True)
                if _writable(alt):
                    return alt
            except Exception:
                pass
        return base
    return os.path.dirname(os.path.abspath(__file__))


def _res_dir():
    """只读资源目录：templates / static / demo_data.json。

    打包后这些被解包到 sys._MEIPASS；源码运行时就是脚本目录。
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", _app_dir())
    return os.path.dirname(os.path.abspath(__file__))


HERE = _app_dir()          # 可写：输出 / 缓存 / 偏好
RES = _res_dir()           # 只读：页面资源
DEFAULT_OUT = os.path.join(HERE, "期货日K数据")
DEFAULT_CACHE = os.path.join(HERE, "期货数据缓存")
DEMO_JSON = os.path.join(RES, "demo_data.json")
RESULT_PKL = "_result.pkl"
PREFS_JSON = os.path.join(HERE, "_prefs.json")
VERSION = "1.0.0"

if RES not in sys.path:
    sys.path.insert(0, RES)
import _pickdir   # noqa: E402  （原生对话框，单独成文件便于复用）

_setup_stdio()

# —— 打包后的「子命令」快速通道 ——
# 必须在导入 numpy / pandas / flask / akshare 之前处理：子进程只弹一个
# tkinter 对话框，不该为此加载几百 MB 的依赖，否则每次点「浏览…」都要等很久。
if len(sys.argv) > 1 and sys.argv[1] == "--pickdir":
    sys.exit(_pickdir.main(sys.argv[2:]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

import futures_core as core  # noqa: E402

# 一个目录里若没直接放数据，就往下找这些常见子目录名
_SUBDIRS = ("期货日K数据", "数据", "output", "out", "data")

app = Flask(__name__, static_folder=os.path.join(RES, "static"),
            template_folder=os.path.join(RES, "templates"))
app.config["JSON_AS_ASCII"] = False

# ----------------------------------------------------------------------------
# 全局任务状态
# ----------------------------------------------------------------------------
STATE = {
    "running": False,
    "percent": 0.0,
    "logs": [],          # 日志行
    "started": None,
    "finished": None,
    "error": None,
    "ok": None,
    "out_dir": None,
}
_LOCK = threading.Lock()
_CANCEL = threading.Event()
_THREAD = None

RESULT = {
    "source": None,      # demo | live
    "origin": None,      # fetch(联网抓取) | local(读取本机已有数据) | demo
    "summary": [],       # list[dict]
    "out_dir": None,
    "data_pkl": None,    # 真实抓取后 all_df 的落盘位置
    "finished": None,
    "markets": [],
}


def _log(msg):
    ts = dt.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with _LOCK:
        STATE["logs"].append(line)
        if len(STATE["logs"]) > 3000:
            STATE["logs"] = STATE["logs"][-2000:]


def _set_progress(p):
    with _LOCK:
        STATE["percent"] = round(max(0.0, min(1.0, float(p))) * 100, 1)


# ----------------------------------------------------------------------------
# 静态页面
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(os.path.join(RES, "templates"), "index.html")


@app.route("/health")
def health():
    return jsonify(ok=True, version=VERSION, frozen=bool(getattr(sys, "frozen", False)))


# ----------------------------------------------------------------------------
# 配置信息
# ----------------------------------------------------------------------------
@app.route("/api/config")
def api_config():
    try:
        import akshare  # noqa: F401
        has_ak = True
    except Exception:
        has_ak = False

    prefs = _read_prefs()
    return jsonify(
        markets=[
            {"code": m, "cn": core.MARKET_CN.get(m, m),
             "start": core.MARKET_START.get(m),
             "varieties": core.MARKET_VARIETIES.get(m, []),
             "fallback": m in core.SINA_FALLBACK}
            for m in core.MARKETS
        ],
        variety_name=core.VARIETY_NAME,
        synthetic_suffix=sorted(core.SYNTHETIC_SUFFIX),
        exclude_varieties=sorted(core.EXCLUDE_VARIETIES),
        default_out=DEFAULT_OUT,
        default_cache=DEFAULT_CACHE,
        last_dir=prefs.get("last_dir") or DEFAULT_OUT,
        last_out=prefs.get("last_out") or DEFAULT_OUT,
        last_cache=prefs.get("last_cache") or DEFAULT_CACHE,
        today=dt.date.today().strftime("%Y%m%d"),
        has_akshare=has_ak,
        core_file=os.path.basename(core.__file__),
    )


# ----------------------------------------------------------------------------
# 原生文件夹 / 另存为 对话框
# ----------------------------------------------------------------------------
@app.route("/api/pick", methods=["POST"])
def api_pick():
    """弹出系统原生对话框让用户选目录 / 另存为路径。

    浏览器拿不到真实磁盘路径，只能靠本地进程弹原生框，所以这里起一个子进程。
    子进程用临时文件回传结果（比解析 stdout 更可靠，尤其在没有控制台时）。
    """
    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "dir")            # dir | save
    initial = body.get("initial", "") or ""
    title = body.get("title", "选择文件夹")

    if getattr(sys, "frozen", False):
        # 打包后 sys.executable 就是本程序，用 --pickdir 子命令再启动一个自身进程
        cmd = [sys.executable, "--pickdir", mode, initial, title]
    else:
        script = os.path.join(RES, "_pickdir.py")
        cmd = [sys.executable, script, mode, initial, title]

    tmp = os.path.join(HERE, f"._pickres_{os.getpid()}_{int(dt.datetime.now().timestamp()*1000)}.tmp")
    cmd.append(tmp)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=600)
        path = ""
        try:
            if os.path.exists(tmp):
                with open(tmp, encoding="utf-8") as f:
                    path = f.read().strip()
        except Exception:
            pass
        if not path:
            out = proc.stdout.decode("utf-8", "ignore").strip()
            lines = [l for l in out.splitlines() if l.strip()]
            path = lines[-1].strip() if lines else ""
        err = proc.stderr.decode("utf-8", "ignore").strip()
        return jsonify(ok=True, path=path, err=err)
    except Exception as e:
        return jsonify(ok=False, path="", error=str(e))
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# 启动抓取任务
# ----------------------------------------------------------------------------
def _job(markets, start, end, out_dir, cache_dir, workers, no_repair, keep, dce_start_year):
    try:
        with _LOCK:
            STATE.update(running=True, percent=0.0, logs=[], error=None,
                         ok=None, started=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         finished=None, out_dir=out_dir)
        _log("任务已启动。")

        summary, out = core.run(
            markets=markets, start=start, end=end,
            out_dir=out_dir, cache_dir=cache_dir, workers=workers,
            no_repair=no_repair, dce_start_year=dce_start_year,
            log=_log, progress=_set_progress, cancel_event=_CANCEL, keep=keep,
        )

        # 落盘全量明细，供网页「品种详情」按需读取
        pkl = os.path.join(out, RESULT_PKL)
        records = json.loads(summary.to_json(orient="records", force_ascii=False))
        with _LOCK:
            RESULT.update(source="live", origin="fetch", summary=records, out_dir=out,
                          finished=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                          markets=markets,
                          data_pkl=pkl if os.path.exists(pkl) else None)
            STATE.update(running=False, ok="success", percent=100.0,
                         finished=RESULT["finished"])
        _log(f"任务完成，共 {len(records)} 个品种。")

    except Exception as e:
        _log("发生错误：" + str(e))
        _log(traceback.format_exc())
        with _LOCK:
            STATE.update(running=False, ok="error", error=str(e),
                         finished=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    finally:
        _CANCEL.clear()


@app.route("/api/run", methods=["POST"])
def api_run():
    global _THREAD
    if STATE["running"]:
        return jsonify(ok=False, error="已有任务在运行中，请先等待完成或点停止。")

    body = request.get_json(silent=True) or {}
    markets = body.get("markets") or core.MARKETS
    keep = body.get("keep") or None
    start = (body.get("start") or "").strip() or None
    end = (body.get("end") or "").strip() or None
    out_dir = (body.get("out_dir") or "").strip() or DEFAULT_OUT
    cache_dir = (body.get("cache_dir") or "").strip() or DEFAULT_CACHE
    workers = int(body.get("workers") or 10)
    no_repair = bool(body.get("no_repair"))
    dce_start_year = int(body.get("dce_start_year") or 2000)

    try:
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        return jsonify(ok=False, error=f"目录不可用：{e}")

    _CANCEL.clear()
    _write_prefs(last_out=out_dir, last_cache=cache_dir)
    _THREAD = threading.Thread(
        target=_job,
        args=(markets, start, end, out_dir, cache_dir, workers,
              no_repair, keep, dce_start_year),
        daemon=True,
    )
    _THREAD.start()
    return jsonify(ok=True, message="任务已启动")


@app.route("/api/progress")
def api_progress():
    with _LOCK:
        return jsonify(
            running=STATE["running"], percent=STATE["percent"],
            logs=STATE["logs"], error=STATE["error"], ok=STATE["ok"],
            started=STATE["started"], finished=STATE["finished"],
            out_dir=STATE["out_dir"],
            source=RESULT["source"],
            has_result=bool(RESULT["summary"]),
            variety_count=len(RESULT["summary"]),
            has_detail=bool(RESULT.get("data_pkl") and os.path.exists(RESULT["data_pkl"] or "")),
        )


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if not STATE["running"]:
        return jsonify(ok=False, error="当前没有运行中的任务。")
    _CANCEL.set()
    _log("已发送停止指令，正在中断...")
    return jsonify(ok=True)


# ----------------------------------------------------------------------------
# 结果数据
# ----------------------------------------------------------------------------
DEMO_META = {"label": "文章示例数据（截止 2026-09-29）", "is_demo": True}

# demo_data.json 里的英文字段 -> 与 futures_core 输出一致的统计字段
_DEMO_MAP = {
    "code": "品种代码", "name": "品种名称", "market": "交易所",
    "listing": "上市日期", "days": "总交易天数", "klines": "总K线条数",
    "high": "历史最高价", "high_date": "最高价日期", "high_symbol": "最高价合约",
    "low": "历史最低价", "low_date": "最低价日期", "low_symbol": "最低价合约",
    "avg_close": "主连平均收盘价", "avg_settle": "主连平均结算价",
}


@app.route("/api/demo", methods=["POST"])
def api_demo():
    """载入文章末尾附带的示例汇总数据，便于在没有网络时预览完整界面。"""
    if not os.path.exists(DEMO_JSON):
        return jsonify(ok=False, error="未找到示例数据文件 demo_data.json")
    with open(DEMO_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    rows = [{_DEMO_MAP[k]: v for k, v in r.items() if k in _DEMO_MAP} for r in raw]
    with _LOCK:
        RESULT.update(source="demo", origin="demo", summary=rows, out_dir=None,
                      finished=DEMO_META["label"], data_pkl=None, markets=[])
    return jsonify(ok=True, count=len(rows), meta=DEMO_META)


@app.route("/api/summary")
def api_summary():
    with _LOCK:
        return jsonify(
            source=RESULT["source"],
            origin=RESULT.get("origin"),
            summary=RESULT["summary"],
            out_dir=RESULT["out_dir"],
            finished=RESULT["finished"],
            markets=RESULT["markets"],
            is_demo=RESULT["source"] == "demo",
        )


@app.route("/api/varieties")
def api_varieties():
    with _LOCK:
        rows = RESULT["summary"]
    return jsonify([
        {"code": r.get("品种代码"), "name": r.get("品种名称"), "market": r.get("交易所")}
        for r in rows
    ])


@app.route("/api/detail")
def api_detail():
    """返回某品种的日K明细（仅真实抓取后有数据）。"""
    code = (request.args.get("code") or "").upper()
    limit = int(request.args.get("limit") or 800)
    with _LOCK:
        pkl = RESULT.get("data_pkl")
        source = RESULT["source"]

    if source != "live":
        return jsonify(ok=False, reason="demo",
                       message="示例数据只含汇总统计；日K明细需实际抓取后查看。")

    if not (pkl and os.path.exists(pkl)):
        # 退化：直接读输出目录里该品种的 Excel
        out_dir = RESULT.get("out_dir")
        if not out_dir:
            return jsonify(ok=False, reason="nodata", message="未找到明细数据。")
        cand = None
        for fn in os.listdir(out_dir):
            if fn.startswith(code + "_") and fn.endswith(".xlsx"):
                cand = os.path.join(out_dir, fn)
                break
        if not cand:
            return jsonify(ok=False, reason="nodata", message="未找到该品种明细。")
        df = pd.read_excel(cand, sheet_name="日K线")
        return jsonify(ok=True, code=code, total=len(df),
                       rows=json.loads(df.tail(limit).to_json(orient="records", force_ascii=False)))

    df = pd.read_pickle(pkl)
    sub = df[df["variety"].astype(str).str.upper() == code].sort_values("date")
    if not len(sub):
        return jsonify(ok=False, reason="nodata", message="该品种没有明细数据。")
    total = len(sub)
    head = sub.tail(limit)
    rows = json.loads(head.to_json(orient="records", force_ascii=False))
    # 主连序列（每日持仓量最大合约）用于画图
    m = sub.dropna(subset=["open_interest"]).sort_values("open_interest", ascending=False)
    m = m.drop_duplicates(subset=["date"]).sort_values("date")
    series = [{"date": str(d)[:4] + "-" + str(d)[4:6] + "-" + str(d)[6:8],
               "close": None if pd.isna(c) else round(float(c), 2),
               "settle": None if pd.isna(s) else round(float(s), 2)}
              for d, c, s in zip(m["date"], m["close"], m["settle"])]
    return jsonify(ok=True, code=code, total=total, rows=rows, series=series)


# ----------------------------------------------------------------------------
# 品种明细：合约按月分组 / 持仓量加权合约 / 单合约
# ----------------------------------------------------------------------------
_DF_CACHE = {"path": None, "df": None}
# 加权合约与月份分组结果缓存（按 数据文件 + 品种 缓存，避免重复计算）
_VAR_CACHE = {}


def _result_pkl_path():
    with _LOCK:
        p = RESULT.get("data_pkl")
        out = RESULT.get("out_dir")
    if p and os.path.exists(p):
        return p
    if out:
        cand = os.path.join(out, RESULT_PKL)
        if os.path.exists(cand):
            return cand
    return None


def _get_df():
    """载入并缓存全量明细（避免每次请求都读 pickle）。"""
    p = _result_pkl_path()
    if not p:
        return None
    if _DF_CACHE["path"] != p or _DF_CACHE["df"] is None:
        df = pd.read_pickle(p)
        df["date"] = df["date"].astype(str)
        df["symbol"] = df["symbol"].astype(str)
        df["variety"] = df["variety"].astype(str).str.upper()
        _DF_CACHE["path"] = p
        _DF_CACHE["df"] = df
        _VAR_CACHE.clear()
    return _DF_CACHE["df"]


_MONTH_CN = ["", "1月", "2月", "3月", "4月", "5月", "6月",
             "7月", "8月", "9月", "10月", "11月", "12月"]


def _parse_symbol(symbol):
    """从合约代码取 (品种前缀, 交割月份, 交割年份或None)。

    上期所/大商所/能源中心/广期所/中金所 为 4 位(YYMM)，如 CU2401、a2105
    —— 年份可直接由代码前两位得到；
    郑商所为 3 位(YMM)，如 CF401、SR409 —— 首位只是年份末位，存在十年歧义，
    需由实际交易数据反推年份。
    """
    m = re.match(r"^([A-Za-z]+)(\d{3,4})$", str(symbol))
    if not m:
        return None, None, None
    digits = m.group(2)
    month = int(digits[-2:])
    if not 1 <= month <= 12:
        return None, None, None
    year = None
    if len(digits) == 4:
        yy = int(digits[:2])
        year = 2000 + yy if yy < 50 else 1900 + yy
    return m.group(1).upper(), month, year


def _px(v):
    """价格标准化：返回正数浮点值；NaN / 空 / <=0（占位零值）统一视为「无效」返回 None。

    期货价格不可能为 0。数据源里存在「无成交占位行」（开高低收全为 0），
    以及少数只有结算参考价、开高低为 0 的行，这些 0 值都不是真实价格，
    一律不进入图表。
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f) or f <= 0:
        return None
    return f


def _valid_mask(g):
    """标记有效行情行：开高低收中至少有一个为正价格。"""
    m = pd.Series(False, index=g.index)
    for col in ("open", "high", "low", "close"):
        if col in g.columns:
            m = m | (pd.to_numeric(g[col], errors="coerce") > 0)
    return m.fillna(False)


def _contract_rows(sub):
    """列出该品种下的全部合约及其月份、年份、数据区间。

    只统计有效行情行；整份数据全是 0 值占位行的合约没有展示价值，直接跳过。
    """
    rows = []
    for sym, g in sub.groupby("symbol", sort=False):
        _, month, year = _parse_symbol(sym)
        if month is None:
            continue
        g = g.sort_values("date")
        g = g[_valid_mask(g)]
        if not len(g):
            continue
        last = str(g["date"].max())
        if year is None:
            # 郑商所 3 位代码：由最后一个交易日反推交割年份
            try:
                ly, lm = int(last[:4]), int(last[4:6])
            except Exception:
                ly, lm = 0, 0
            year = ly + (1 if lm > month else 0)
        rows.append({
            "symbol": str(sym),
            "month": month,
            "year": year,
            "delivery": f"{year}{month:02d}" if year else f"??{month:02d}",
            "rows": int(len(g)),
            "first": str(g["date"].min()),
            "last": last,
        })
    rows.sort(key=lambda r: (r["month"], r["year"], r["symbol"]))
    return rows


def _fmt_date(d):
    d = str(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 else d


def _series_of(g):
    """把某合约(或加权)的 DataFrame 转成前端用的点数组。

    零值处理：
      - 开高低收全部无效（0 / 缺失）的行 —— 整行不返回，不出现在图表上；
      - 单项为 0（如无成交、仅有结算参考价）—— 该字段返回 None，前端不绘制该项。
    """
    g = g.sort_values("date")
    out = []
    for r in g.itertuples(index=False):
        o, h, l, c = _px(r.open), _px(r.high), _px(r.low), _px(r.close)
        if o is None and h is None and l is None and c is None:
            continue                       # 零值占位行：不展示
        out.append({
            "d": _fmt_date(r.date),
            "o": None if o is None else round(o, 4),
            "h": None if h is None else round(h, 4),
            "l": None if l is None else round(l, 4),
            "c": None if c is None else round(c, 4),
            "v": 0.0 if pd.isna(r.volume) else round(float(r.volume), 2),
        })
    return out


def _weighted_series(sub):
    """持仓量加权合约（指数合约）日K。

    每个交易日：各合约以持仓量为权重做加权平均得到 OHLC；持仓量缺失或为 0 的
    合约退化为用成交量加权。成交量为各合约求和，持仓量为各合约求和。
    """
    d = sub.copy()
    if not len(d):
        return []
    w = d["open_interest"].fillna(0).clip(lower=0)
    w = w.where(w > 0, d["volume"].fillna(0).clip(lower=0)).fillna(0)
    d["_w"] = w
    d = d[d["_w"] > 0]
    if not len(d):
        return []

    for c in ["open", "high", "low", "close"]:
        ok = d[c].notna() & (d[c] > 0)        # 0 值为占位数据，不参与加权
        d["_pw_" + c] = d["_w"].where(ok, 0.0)
        d["_pn_" + c] = d[c].fillna(0.0).where(ok, 0.0) * d["_pw_" + c]

    agg = d.groupby("date").agg(
        wo=("_pw_open", "sum"), no=("_pn_open", "sum"),
        wh=("_pw_high", "sum"), nh=("_pn_high", "sum"),
        wl=("_pw_low", "sum"), nl=("_pn_low", "sum"),
        wc=("_pw_close", "sum"), nc=("_pn_close", "sum"),
        volume=("volume", "sum"), oi=("open_interest", "sum"),
        n=("symbol", "count"),
    ).reset_index().sort_values("date")

    def pr(wcol, ncol):
        den = agg[wcol].to_numpy(dtype="float64")
        num = agg[ncol].to_numpy(dtype="float64")
        return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)

    o, h, l, c = pr("wo", "no"), pr("wh", "nh"), pr("wl", "nl"), pr("wc", "nc")
    out = []
    for i, dt_s in enumerate(agg["date"].tolist()):
        # 加权结果同样只保留正价格，非正值/缺失一律返回 None（前端不绘制）
        vo, vh, vl, vc = _px(o[i]), _px(h[i]), _px(l[i]), _px(c[i])
        if vo is None and vh is None and vl is None and vc is None:
            continue                       # 该日无任何有效行情：不展示
        out.append({
            "d": _fmt_date(dt_s),
            "o": None if vo is None else round(vo, 4),
            "h": None if vh is None else round(vh, 4),
            "l": None if vl is None else round(vl, 4),
            "c": None if vc is None else round(vc, 4),
            "v": 0.0 if pd.isna(agg["volume"].iloc[i]) else round(float(agg["volume"].iloc[i]), 2),
            "oi": 0.0 if pd.isna(agg["oi"].iloc[i]) else round(float(agg["oi"].iloc[i]), 2),
            "n": int(agg["n"].iloc[i]),
        })
    return out


def _extrema(points, label="加权合约"):
    """在一组点中找出最高价 / 最低价（含日期与位置下标）。

    只统计正价格，避免零值/缺失把「历史最低价」拉到 0。
    """
    hi = lo = None
    for i, p in enumerate(points):
        ph, pl = _px(p.get("h")), _px(p.get("l"))
        if ph is not None and (hi is None or ph > hi["price"]):
            hi = {"price": ph, "date": p["d"], "index": i, "label": label}
        if pl is not None and (lo is None or pl < lo["price"]):
            lo = {"price": pl, "date": p["d"], "index": i, "label": label}
    return hi, lo


def _variety_payload(code):
    """组装某品种的完整明细载荷（带缓存）。"""
    df = _get_df()
    if df is None or not len(df):
        return None
    code = code.upper()
    p = _DF_CACHE["path"]
    key = (p, code)
    if key in _VAR_CACHE:
        return _VAR_CACHE[key]

    sub = df[df["variety"] == code]
    if not len(sub):
        return None

    contracts = _contract_rows(sub)
    groups = {}
    for c in contracts:
        groups.setdefault(str(c["month"]), []).append(c["symbol"])

    weighted = _weighted_series(sub)
    wh, wl = _extrema(weighted)

    # 全体合约的最大/最小（用于「全部合约」视图）
    payload = {
        "ok": True,
        "code": code,
        "name": core.VARIETY_NAME.get(code, code),
        "market": str(sub["market"].iloc[0]),
        "contracts": contracts,
        "groups": groups,
        "month_names": _MONTH_CN,
        "weighted": weighted,
        "weighted_high": wh,
        "weighted_low": wl,
        "total_rows": int(len(sub)),
    }
    _VAR_CACHE[key] = payload
    return payload


@app.route("/api/variety")
def api_variety():
    """品种明细总览：合约清单、按月分组、加权合约日K。"""
    code = (request.args.get("code") or "").upper()
    if not code:
        return jsonify(ok=False, reason="param", message="缺少品种代码。")
    with _LOCK:
        src = RESULT["source"]
    if src != "live":
        return jsonify(ok=False, reason="demo",
                       message="示例数据只含汇总统计；日K明细需实际抓取后查看。")
    payload = _variety_payload(code)
    if payload is None:
        return jsonify(ok=False, reason="nodata", message="该品种没有明细数据。")
    return jsonify(payload)


@app.route("/api/contracts")
def api_contracts():
    """取某品种某月份分组下全部（跨年同月）合约的日K序列。

    limit：只返回最近 N 个合约（避免「全部合约」视图一次传回上百个合约）。
    """
    code = (request.args.get("code") or "").upper()
    month = request.args.get("month")
    limit = request.args.get("limit", type=int)
    df = _get_df()
    if df is None:
        return jsonify(ok=False, reason="demo", message="日K明细需实际抓取后查看。")
    sub = df[df["variety"] == code]
    if not len(sub):
        return jsonify(ok=False, reason="nodata", message="该品种没有明细数据。")

    contracts = _contract_rows(sub)
    if month:
        mi = int(month)
        contracts = [c for c in contracts if c["month"] == mi]
    else:
        contracts.sort(key=lambda r: (r["year"], r["month"], r["symbol"]))

    total = len(contracts)
    truncated = False
    if limit and total > limit:
        contracts = contracts[-limit:]
        truncated = True

    series = {}
    kept = []
    hi = lo = None
    for c in contracts:
        g = sub[sub["symbol"] == c["symbol"]]
        pts = _series_of(g)
        if not pts:
            continue                    # 全是零值数据：不上图、也不列进合约清单
        series[c["symbol"]] = pts
        kept.append(c)
        h, l = _extrema(pts, c["symbol"])
        if h and (hi is None or h["price"] > hi["price"]):
            hi = h
        if l and (lo is None or l["price"] < lo["price"]):
            lo = l

    return jsonify(ok=True, code=code, month=month, contracts=kept,
                   series=series, high=hi, low=lo,
                   total_contracts=len(kept), truncated=truncated)


@app.route("/api/contract")
def api_contract():
    """取单个合约的日K序列。"""
    symbol = (request.args.get("symbol") or "").strip()
    df = _get_df()
    if df is None:
        return jsonify(ok=False, reason="demo", message="日K明细需实际抓取后查看。")
    g = df[df["symbol"].astype(str).str.lower() == symbol.lower()]
    if not len(g):
        return jsonify(ok=False, reason="nodata", message="未找到该合约。")
    pts = _series_of(g)
    if not pts:
        return jsonify(ok=False, reason="nodata",
                       message="该合约只有零值占位数据，无有效行情可展示。")
    hi, lo = _extrema(pts, symbol.upper())
    return jsonify(ok=True, symbol=symbol.upper(),
                   variety=str(g["variety"].iloc[0]),
                   market=str(g["market"].iloc[0]),
                   series=pts, high=hi, low=lo)


# ----------------------------------------------------------------------------
# 本机数据目录：读取既有抓取结果，避免每次启动重复下载
# ----------------------------------------------------------------------------
# 各品种 xlsx 的「日K线」sheet 中文列 -> 内部英文列
_XLS_BACK_MAP = {
    "合约": "symbol", "日期": "date", "开盘": "open", "最高": "high",
    "最低": "low", "收盘": "close", "成交量": "volume", "持仓量": "open_interest",
    "成交额": "turnover", "结算": "settle", "前结算": "pre_settle",
    "品种": "variety", "交易所": "market",
}

# 品种代码 -> 交易所（用于 xlsx 里缺「交易所」列时回填）
_VARIETY_MARKET = {}
for _m, _vs in core.MARKET_VARIETIES.items():
    for _v in _vs:
        _VARIETY_MARKET.setdefault(str(_v).upper(), _m)

_NEED_COLS = ["open", "high", "low", "close", "volume",
              "open_interest", "turnover", "settle", "pre_settle"]


def _read_prefs():
    try:
        with open(PREFS_JSON, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_prefs(**kw):
    d = _read_prefs()
    d.update(kw)
    try:
        with open(PREFS_JSON, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _dir_has_data(d):
    """该目录是否直接存放了可用数据。"""
    if os.path.exists(os.path.join(d, RESULT_PKL)):
        return True
    try:
        n = 0
        for fn in os.listdir(d):
            if fn.startswith("~$") or not fn.lower().endswith(".xlsx"):
                continue
            if fn == "汇总_全部品种.xlsx":
                continue
            n += 1
            if n >= 2:
                return True
    except Exception:
        return False
    return False


def _resolve_data_dir(path):
    """把用户选的目录解析为「真正存数据的目录」，支持指向上一级目录。"""
    if not path or not os.path.isdir(path):
        return None
    if _dir_has_data(path):
        return path
    for sub in _SUBDIRS:
        cand = os.path.join(path, sub)
        if os.path.isdir(cand) and _dir_has_data(cand):
            return cand
    try:
        for name in sorted(os.listdir(path))[:60]:
            cand = os.path.join(path, name)
            if os.path.isdir(cand) and _dir_has_data(cand):
                return cand
    except Exception:
        pass
    return None


def _scan_local(path):
    """扫描目录，返回数据清单；找不到可用数据则返回 None。"""
    d = _resolve_data_dir(path)
    if not d:
        return None
    names = [n for n in os.listdir(d) if not n.startswith("~$")]
    pkl = os.path.join(d, RESULT_PKL)
    has_pkl = os.path.exists(pkl)
    summ = os.path.join(d, "汇总_全部品种.xlsx")
    var_xls = [n for n in names
               if n.lower().endswith(".xlsx") and n != "汇总_全部品种.xlsx"]
    return {
        "input": path,
        "dir": d,
        "has_pkl": has_pkl,
        "has_summary": os.path.exists(summ),
        "summary_xlsx": summ if os.path.exists(summ) else None,
        "variety_files": var_xls,
        "variety_file_count": len(var_xls),
        "kind": "pickle" if has_pkl else ("xlsx" if var_xls else None),
    }


def _normalize_df(df):
    """把明细整理成与抓取结果一致的英文列结构。"""
    df = df.copy()
    if "variety" not in df.columns and "symbol" in df.columns:
        df["variety"] = (df["symbol"].astype(str)
                         .str.replace(r"\d+$", "", regex=True).str.upper())
    for c in ["symbol", "date", "variety"]:
        if c in df.columns:
            df[c] = df[c].astype(str)
    if "date" in df.columns:
        df["date"] = df["date"].str.replace(r"\D", "", regex=True).str.slice(0, 8)
        df = df[df["date"].str.len() == 8]
    if "variety" in df.columns:
        df["variety"] = (df["variety"].str.upper()
                         .str.replace(r"\d+$", "", regex=True).str.strip())
        df = df[df["variety"].ne("") & df["variety"].notna()]
    if "market" not in df.columns:
        df["market"] = ""
    df["market"] = df["market"].fillna("")
    miss = df["market"].eq("") | df["market"].isna()
    if miss.any():
        df.loc[miss, "market"] = df.loc[miss, "variety"].map(_VARIETY_MARKET).fillna("")
    for c in _NEED_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        else:
            df[c] = np.nan
    if "symbol" not in df.columns:
        df["symbol"] = df["variety"]
    df = df[df["volume"].fillna(0) > 0]
    sort_cols = [c for c in ["variety", "symbol", "date"] if c in df.columns]
    return df.sort_values(sort_cols).reset_index(drop=True)


def _read_detail_from_dir(d):
    """把目录里的数据还原成全量明细 DataFrame，返回 (df, kind)。"""
    pkl = os.path.join(d, RESULT_PKL)
    if os.path.exists(pkl):
        return _normalize_df(pd.read_pickle(pkl)), "pickle"

    frames, skipped = [], 0
    for fn in sorted(os.listdir(d)):
        if fn.startswith("~$") or not fn.lower().endswith(".xlsx"):
            continue
        if fn == "汇总_全部品种.xlsx":
            continue
        try:
            raw = pd.read_excel(os.path.join(d, fn), sheet_name="日K线")
        except Exception:
            try:
                raw = pd.read_excel(os.path.join(d, fn))
            except Exception:
                skipped += 1
                continue
        if not len(raw):
            continue
        frames.append(raw.rename(columns=_XLS_BACK_MAP))
    if not frames:
        return None, None
    return _normalize_df(pd.concat(frames, ignore_index=True)), "xlsx"


def _summary_from_df(df, d):
    """优先用目录里的汇总 xlsx；没有则由明细现算。"""
    summ = os.path.join(d, "汇总_全部品种.xlsx")
    if os.path.exists(summ):
        try:
            s = pd.read_excel(summ, sheet_name="汇总")
            if len(s):
                return json.loads(s.to_json(orient="records", force_ascii=False))
        except Exception:
            pass
    rows = []
    for var, vdf in df.groupby("variety"):
        var = str(var).upper()
        try:
            stats = core.compute_stats(vdf)
        except Exception:
            continue
        market = ""
        if "market" in vdf.columns and len(vdf):
            m = str(vdf["market"].iloc[0] or "").strip()
            market = m or _VARIETY_MARKET.get(var, "")
        rows.append({
            "品种代码": var,
            "品种名称": core.VARIETY_NAME.get(var, var),
            "交易所": market,
            **stats,
        })
    rows.sort(key=lambda r: (str(r.get("交易所") or ""), str(r.get("品种代码") or "")))
    return rows


def _use_local_dir(d, summary, pkl, origin_note):
    """把某目录的数据设为当前结果。"""
    markets = sorted({str(r.get("交易所")).strip()
                      for r in summary if str(r.get("交易所") or "").strip()})
    with _LOCK:
        RESULT.update(source="live", origin="local", summary=summary, out_dir=d,
                      finished=origin_note, markets=markets,
                      data_pkl=pkl if (pkl and os.path.exists(pkl)) else None)
    # 清空明细缓存，强制按新路径重新载入
    _DF_CACHE["path"] = None
    _DF_CACHE["df"] = None
    _VAR_CACHE.clear()


@app.route("/api/local-scan", methods=["POST"])
def api_local_scan():
    """预览某个目录里有什么数据（不载入，速度快）。"""
    body = request.get_json(silent=True) or {}
    path = (body.get("dir") or "").strip()
    info = _scan_local(path)
    if not info:
        return jsonify(ok=False, error="该目录里没有找到可用数据"
                                      "（需包含 _result.pkl 或各品种 xlsx 文件）。")
    info = dict(info)
    info.pop("summary_xlsx", None)
    return jsonify(ok=True, **info)


@app.route("/api/load-local", methods=["POST"])
def api_load_local():
    """读取本机已有数据目录，直接作为当前结果，免去重新联网抓取。"""
    if STATE["running"]:
        return jsonify(ok=False, error="已有抓取任务在运行，请先等待完成或点停止。")
    body = request.get_json(silent=True) or {}
    path = (body.get("dir") or "").strip()
    if not path:
        return jsonify(ok=False, error="请先选择数据目录。")

    info = _scan_local(path)
    if not info:
        return jsonify(ok=False,
                       error="该目录里没有找到可用数据。请选择包含「_result.pkl」"
                             "或各品种 xlsx（如 CU_沪铜.xlsx）的目录。")

    d = info["dir"]
    try:
        df, kind = _read_detail_from_dir(d)
    except Exception as e:
        return jsonify(ok=False, error=f"读取失败：{e}")
    if df is None or not len(df):
        return jsonify(ok=False, error="目录中没有可用的日K明细数据。")

    # 统一落盘一份 pickle，供「品种详情」按需快速读取
    pkl = os.path.join(d, RESULT_PKL)
    if kind == "xlsx" or not os.path.exists(pkl):
        try:
            df.to_pickle(pkl)
        except Exception as e:
            _log(f"(明细缓存写入失败，不影响使用：{e})")

    rows = _summary_from_df(df, d)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    _use_local_dir(d, rows, pkl, f"本地数据（{stamp} 载入）")
    _write_prefs(last_dir=d, last_out=d)
    _log(f"已载入本地数据：{d}")
    _log(f"  品种 {len(rows)} 个 · 日K明细 {len(df):,} 行 · 来源={'明细缓存' if kind == 'pickle' else '各品种 Excel'}")
    return jsonify(ok=True, dir=d, kind=kind, variety_count=len(rows),
                   rows=int(len(df)), finished=RESULT["finished"],
                   markets=RESULT["markets"],
                   scanned=info["variety_file_count"])


# ----------------------------------------------------------------------------
# 导出 / 保存到本机指定位置
# ----------------------------------------------------------------------------
def _summary_dataframe():
    with _LOCK:
        rows = list(RESULT["summary"])
    return pd.DataFrame(rows)


@app.route("/api/export", methods=["POST"])
def api_export():
    """把当前结果保存到用户指定的本机目录。

    body: {dir, format: xlsx|csv, scope: summary|all, filename}
    """
    body = request.get_json(silent=True) or {}
    target = (body.get("dir") or "").strip()
    fmt = (body.get("format") or "xlsx").lower()
    scope = (body.get("scope") or "summary").lower()
    filename = (body.get("filename") or "").strip()

    if not target:
        return jsonify(ok=False, error="请先选择保存位置。")
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        return jsonify(ok=False, error=f"无法创建目录：{e}")

    df = _summary_dataframe()
    if df.empty:
        return jsonify(ok=False, error="当前没有可保存的数据，请先抓取或载入示例数据。")

    written = []
    try:
        if scope == "all":
            with _LOCK:
                src = RESULT.get("out_dir")
            if not src or not os.path.isdir(src):
                return jsonify(ok=False, error="全量行情文件不存在，请先完成一次实际抓取。")
            for fn in os.listdir(src):
                if fn.endswith((".xlsx", ".csv")):
                    shutil.copy2(os.path.join(src, fn), os.path.join(target, fn))
                    written.append(os.path.join(target, fn))
            return jsonify(ok=True, written=written, count=len(written))

        # 仅汇总
        if fmt == "csv":
            name = filename or "汇总_全部品种.csv"
            path = os.path.join(target, name)
            df.to_csv(path, index=False, encoding="utf-8-sig")
        else:
            name = filename or "汇总_全部品种.xlsx"
            path = os.path.join(target, name)
            with pd.ExcelWriter(path, engine="openpyxl") as w:
                df.to_excel(w, sheet_name="汇总", index=False)
        written.append(path)
        return jsonify(ok=True, written=written, count=1)
    except Exception as e:
        return jsonify(ok=False, error=str(e), written=written)


@app.route("/api/files")
def api_files():
    with _LOCK:
        out = RESULT.get("out_dir")
    if not out or not os.path.isdir(out):
        return jsonify(ok=True, dir=None, files=[])
    files = []
    for fn in sorted(os.listdir(out)):
        p = os.path.join(out, fn)
        if os.path.isfile(p):
            files.append({"name": fn, "size": os.path.getsize(p)})
    return jsonify(ok=True, dir=out, files=files, count=len(files))


@app.route("/api/open-folder", methods=["POST"])
def api_open_folder():
    body = request.get_json(silent=True) or {}
    path = (body.get("dir") or "").strip()
    if not path or not os.path.isdir(path):
        return jsonify(ok=False, error="目录不存在。")
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


# ----------------------------------------------------------------------------
def _bootstrap_last_result():
    """启动时自动恢复上次的数据（免去每次启动重新抓取）。

    依次尝试：上次载入/输出过的目录 → 默认输出目录。
    只要目录里有汇总 xlsx 或明细缓存，就直接接上，不再联网。
    """
    prefs = _read_prefs()
    cands = []
    for c in (prefs.get("last_dir"), prefs.get("last_out"), DEFAULT_OUT):
        if c and c not in cands:
            cands.append(c)

    for raw in cands:
        info = _scan_local(raw)
        if not info:
            continue
        d = info["dir"]
        try:
            rows, stamp_src = None, None
            if info["has_summary"]:
                s = pd.read_excel(info["summary_xlsx"], sheet_name="汇总")
                if len(s):
                    rows = json.loads(s.to_json(orient="records", force_ascii=False))
                    stamp_src = info["summary_xlsx"]

            pkl = os.path.join(d, RESULT_PKL) if info["has_pkl"] else None
            if rows is None:
                if not pkl:
                    continue
                df, _k = _read_detail_from_dir(d)
                if df is None or not len(df):
                    continue
                rows = _summary_from_df(df, d)
                stamp_src = pkl

            try:
                stamp = dt.datetime.fromtimestamp(os.path.getmtime(stamp_src))
                stamp = stamp.strftime("%Y-%m-%d %H:%M")
            except Exception:
                stamp = "未知时间"

            _use_local_dir(d, rows, pkl, f"上次数据（{stamp}）")
            print(f"[启动] 已自动恢复数据：{len(rows)} 个品种，目录 {d}")
            return
        except Exception as e:
            print(f"[启动] 恢复 {raw} 失败：{e}")


def _set_console_title(text):
    """把控制台窗口标题改掉，方便用户在多窗口里找到它（仅 Windows）。"""
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception:
        pass


def _pick_port(preferred):
    """优先用 8770；被占用时依次往后找一个空闲端口，避免二次启动直接报错。"""
    import socket
    for p in [preferred] + list(range(preferred + 1, preferred + 21)):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            try:
                s.close()
            except Exception:
                pass
    return preferred


def main():
    preferred = int(os.environ.get("PORT", "8770"))
    port = _pick_port(preferred)
    url = f"http://127.0.0.1:{port}"
    frozen = bool(getattr(sys, "frozen", False))

    # 把工作目录切到程序所在目录，保证相对路径（缓存等）落在预期位置
    try:
        os.chdir(HERE)
    except Exception:
        pass

    _set_console_title("期货数据工作台 - 请勿关闭本窗口")
    _bootstrap_last_result()

    print("=" * 64)
    print(f"  国内期货全品种全合约日K数据工作台  v{VERSION}")
    print(f"  运行模式：{'独立程序 (exe)' if frozen else 'Python 源码'}")
    print(f"  工作目录：{HERE}")
    print(f"  访问地址：{url}")
    if port != preferred:
        print(f"  （{preferred} 端口被占用，已自动改用 {port}）")
    print("  关闭本窗口即停止服务")
    print("=" * 64)
    sys.stdout.flush()

    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
