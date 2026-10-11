# -*- coding: utf-8 -*-
"""国内期货全品种 · 全合约(含已到期/已退市) 日K线 抓取 + 分析 —— 核心模块

本模块由公众号文章《公歧工作流：从期交所获取全部品种日K数据并分析.py》中的
脚本改写而来，去掉了 argparse 命令行入口，改为可被 Web 后端(app.py)调用的
`run()` 函数，并新增：

  * 日志回调 log_cb(msg)      —— 实时把进度推送到网页
  * 进度回调 progress_cb(pct) —— 驱动网页进度条
  * 取消事件 cancel_event      —— 网页上点「停止」即可中断

数据源说明
----------
1) CFFEX(中金所) / SHFE(上期所) / CZCE(郑商所) / INE(上海国际能源中心) / GFEX(广期所)
   —— 直接调用 akshare 的 get_futures_daily()，读取各期货交易所官网公布的日行情，
      每次请求返回"某交易日该交易所全部合约"数据，按交易日并行抓取。
2) DCE(大商所)
   —— 大商所官网接口被瑞数(RiverSecurity) WAF 反爬封锁(返回 412)，
      改装脚本自动改用新浪财经"按合约"日K(futures_zh_daily_sina)，
      并枚举该品种上市以来每个交割月合约(含已退市)，保证"全合约"。
3) 只取期货，不含期权；并过滤掉交易所日K自带的"连续/指数"合成合约(0/88/888/99 结尾)。
"""

import datetime as dt
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

try:
    import akshare as ak
except Exception:  # 允许在无 akshare 环境下导入（演示模式）
    ak = None

# ----------------------------------------------------------------------------
# 网络稳定性补丁：强制 IPv4 + 默认超时
# ----------------------------------------------------------------------------
import socket as _socket

_orig_getaddrinfo = _socket.getaddrinfo


def _ipv4_only_getaddrinfo(*args, **kwargs):
    return [r for r in _orig_getaddrinfo(*args, **kwargs) if r[0] == _socket.AF_INET]


# 部分交易所域名会被解析到本网络不可达的 IPv6 地址，导连 TCP 长期 SYN_SENT 卡死。
if getattr(_socket.getaddrinfo, "__name__", "") != "_ipv4_only_getaddrinfo":
    _socket.getaddrinfo = _ipv4_only_getaddrinfo

try:
    import requests as _requests

    _requests_get = _requests.get
    _requests_post = _requests.post

    def _get_with_timeout(url, **kwargs):
        kwargs.setdefault("timeout", 20)
        return _requests_get(url, **kwargs)

    def _post_with_timeout(url, **kwargs):
        kwargs.setdefault("timeout", 20)
        return _requests_post(url, **kwargs)

    _requests.get = _get_with_timeout
    _requests.post = _post_with_timeout
except Exception:
    pass

# ----------------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------------
MARKETS = ["CFFEX", "SHFE", "CZCE", "DCE", "INE", "GFEX"]

MARKET_CN = {
    "CFFEX": "中金所",
    "SHFE": "上期所",
    "CZCE": "郑商所",
    "DCE": "大商所",
    "INE": "上海国际能源中心",
    "GFEX": "广期所",
}

# 各交易所数据源最早可用日期(避免对无数据的历史日期发起大量无效请求)
MARKET_START = {
    "CFFEX": "20100416",
    "SHFE": "20040601",
    # CZCE 自 2010-08-25 起走逐日接口；更早日期 akshare 走"整年 zip"且取不到逐日数据。
    "CZCE": "20100825",
    "DCE": None,  # DCE 走新浪按合约枚举，无需起始日期
    "INE": "20180326",
    "GFEX": "20221222",
}

STD_COLS = [
    "symbol", "date", "open", "high", "low", "close",
    "volume", "open_interest", "turnover", "settle", "pre_settle", "variety",
]

# 品种代码 -> 中文名(覆盖六大交易所；未知品种回退为代码本身)
VARIETY_NAME = {
    # 上期所
    "RU": "橡胶", "CU": "沪铜", "AL": "沪铝", "FU": "燃料油", "ZN": "沪锌",
    "AU": "沪金", "RB": "螺纹钢", "WR": "线材", "PB": "沪铅", "AG": "沪银",
    "BU": "沥青", "HC": "热卷", "SN": "沪锡", "NI": "沪镍", "SP": "纸浆",
    "SS": "不锈钢", "AO": "氧化铝", "BR": "丁二烯橡胶",
    # 能源中心
    "SC": "原油", "NR": "20号胶", "LU": "低硫燃料油", "BC": "国际铜", "EC": "集运指数欧线",
    # 郑商所
    "CF": "郑棉", "SR": "白糖", "TA": "PTA", "PM": "普麦", "FG": "玻璃",
    "RM": "菜粕", "RS": "菜籽", "OI": "菜油", "RI": "早籼稻", "WH": "强麦",
    "ZC": "动力煤", "JR": "粳稻", "LR": "晚籼稻", "SM": "锰硅", "SF": "硅铁",
    "MA": "甲醇", "CY": "棉纱", "AP": "苹果", "CJ": "红枣", "UR": "尿素",
    "SA": "纯碱", "PF": "短纤", "PK": "花生", "SH": "烧碱", "PX": "对二甲苯", "PR": "瓶片",
    # 大商所
    "A": "豆一", "B": "豆二", "C": "玉米", "CS": "玉米淀粉", "M": "豆粕",
    "Y": "豆油", "P": "棕榈油", "L": "塑料", "V": "PVC", "J": "焦炭",
    "JM": "焦煤", "I": "铁矿石", "JD": "鸡蛋", "FB": "纤维板", "BB": "胶合板",
    "PP": "聚丙烯", "EG": "乙二醇", "RR": "粳米", "EB": "苯乙烯", "PG": "液化石油气",
    "LH": "生猪", "LG": "原木",
    # 广期所
    "SI": "工业硅", "LC": "碳酸锂", "PS": "多晶硅", "PD": "钯", "PT": "铂",
    # 郑商所 2025 年新上市品种
    "PL": "丙烯",
    # 上期所 2026 年新上市品种
    "AD": "铸造铝",
    # 中金所
    "IF": "沪深300股指", "IH": "上证50股指", "IC": "中证500股指", "IM": "中证1000股指",
    "TS": "2年期国债", "TF": "5年期国债", "T": "10年期国债", "TL": "30年期国债",
}

DCE_VARIETIES = [
    "A", "B", "C", "CS", "M", "Y", "P", "L", "V", "J", "JM",
    "I", "JD", "FB", "BB", "PP", "EG", "RR", "EB", "PG", "LH", "LG",
]
INE_VARIETIES = ["SC", "NR", "LU", "BC", "EC"]

# 交易所官网接口不可用(反爬/网络不可达)时，改用新浪按合约日K兜底的交易所及其品种
SINA_FALLBACK = {"DCE": DCE_VARIETIES, "INE": INE_VARIETIES}

# 合成连续/指数合约后缀，需从"真实期货合约"中剔除
SYNTHETIC_SUFFIX = {"0", "88", "888", "99"}

# 交易所日K中自带的非真实可交易品种(合成/特殊序列)，剔除
EXCLUDE_VARIETIES = {"OP", "SC_TAS"}

# 各交易所下的品种全集（用于前端勾选，来源：VARIETY_NAME 分组 + DCE/INE 枚举）
MARKET_VARIETIES = {
    "SHFE": ["RU", "CU", "AL", "FU", "ZN", "AU", "RB", "WR", "PB", "AG", "BU", "HC",
             "SN", "NI", "SP", "SS", "AO", "BR", "AD"],
    "INE": ["SC", "NR", "LU", "BC", "EC"],
    "CZCE": ["CF", "SR", "TA", "PM", "FG", "RM", "RS", "OI", "RI", "WH", "ZC", "JR",
             "LR", "SM", "SF", "MA", "CY", "AP", "CJ", "UR", "SA", "PF", "PK", "SH",
             "PX", "PR", "PL"],
    "DCE": DCE_VARIETIES,
    "GFEX": ["SI", "LC", "PS", "PD", "PT"],
    "CFFEX": ["IF", "IH", "IC", "IM", "TS", "TF", "T", "TL"],
}


# ----------------------------------------------------------------------------
# 通用工具
# ----------------------------------------------------------------------------
def to_yyyymmdd(d):
    """将 str / datetime / Timestamp 统一成 'YYYYMMDD' 字符串。"""
    if isinstance(d, str):
        s = d.strip()
        if len(s) == 8 and s.isdigit():
            return s
        return dt.datetime.strptime(s[:10], "%Y-%m-%d").strftime("%Y%m%d")
    return pd.Timestamp(d).strftime("%Y%m%d")


def business_days(start, end):
    """返回 [start, end] 之间的工作日(周一~周五) 'YYYYMMDD' 列表；节假日由接口自动跳过。"""
    s = pd.Timestamp(to_yyyymmdd(start))
    e = pd.Timestamp(to_yyyymmdd(end))
    idx = pd.bdate_range(s, e)
    return [d.strftime("%Y%m%d") for d in idx]


def standardize(df, market):
    """统一字段、剔除交易所返回的杂项列与连续/指数合成合约。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=STD_COLS + ["market"])
    df = df.copy()
    for c in list(df.columns):
        if c not in STD_COLS:
            df = df.drop(columns=[c])
    for c in ["open", "high", "low", "close", "volume", "open_interest",
              "turnover", "settle", "pre_settle"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["symbol", "date", "variety"]:
        if c not in df.columns:
            df[c] = pd.NA
    df["date"] = df["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    df["variety"] = df["variety"].astype(str).str.upper().str.strip()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    # 只保留真实期货合约，剔除 0/88/888/99 结尾的连续/指数合成合约
    core = df["symbol"].str.replace(r"^[A-Za-z]+", "", regex=True)
    df = df[~core.isin(SYNTHETIC_SUFFIX)]
    df["market"] = market
    return df[STD_COLS + ["market"]]


def load_cache(path):
    if path and os.path.exists(path):
        try:
            return pd.read_pickle(path)
        except Exception:
            return None
    return None


def save_cache(df, path):
    if path and df is not None and not df.empty:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.reset_index(drop=True).to_pickle(path)


# ----------------------------------------------------------------------------
# 抓取：交易所日K（CFFEX/SHFE/CZCE/INE/GFEX）
# ----------------------------------------------------------------------------
def fetch_exchange_market(market, start, end, cache_dir, workers,
                          retries=3, no_repair=False, log=print,
                          cancel_event=None, progress=None):
    cache_path = os.path.join(cache_dir, f"{market}.pkl")
    cached = load_cache(cache_path)

    if no_repair and cached is not None and len(cached):
        log(f"[{market}] --no-repair：沿用缓存 {len(cached):,} 条数据(不回补缺失日期)。")
        return cached

    cached_dates = set(cached["date"].astype(str)) if cached is not None and len(cached) else set()
    mstart = MARKET_START.get(market, start)
    start = to_yyyymmdd(mstart) if to_yyyymmdd(start) < to_yyyymmdd(mstart) else to_yyyymmdd(start)
    dates = business_days(start, to_yyyymmdd(end))
    todo = [d for d in dates if d not in cached_dates]

    if not todo:
        log(f"[{market}] 无新增交易日(缓存已覆盖)，直接使用缓存。")
        return cached

    # 连通性预检：最近 3 个交易日都取不到 → 判定接口当前不可达
    probe_ok = False
    if ak is not None:
        for probe_d in dates[-3:]:
            try:
                dft = ak.get_futures_daily(start_date=probe_d, end_date=probe_d, market=market)
                if dft is not None and len(dft):
                    probe_ok = True
                    break
            except Exception:
                continue
    if not probe_ok:
        if cached is not None and len(cached):
            log(f"[{market}] 预检失败：交易所接口当前不可达，沿用缓存中已有的 {len(cached):,} 条数据。")
            return cached
        log(f"[{market}] 预检失败：交易所接口当前不可达，跳过该交易所。")
        return None

    log(f"[{market}] 待抓取 {len(todo)} 个交易日(共 {len(dates)} 个)，开始并行下载...")

    def worker(d):
        for attempt in range(1, retries + 1):
            if cancel_event is not None and cancel_event.is_set():
                return d, None
            try:
                df = ak.get_futures_daily(start_date=d, end_date=d, market=market)
                return d, df
            except Exception:
                if attempt < retries:
                    time.sleep(1.0 * attempt)
                else:
                    return d, None
        return d, None

    new_dfs = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, d) for d in todo]
        for fut in as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                log(f"[{market}] 已收到停止指令，中断抓取。")
                for f in futures:
                    f.cancel()
                break
            d, df = fut.result()
            done += 1
            if df is not None and not df.empty:
                new_dfs.append(standardize(df, market))
            if done % 200 == 0 or done == len(todo):
                log(f"  [{market}] 进度 {done}/{len(todo)}")
            if progress:
                progress(done / max(len(todo), 1))

    if new_dfs:
        new = pd.concat(new_dfs, ignore_index=True)
        if cached is not None and len(cached):
            combined = pd.concat([cached, new], ignore_index=True)
            combined = combined.drop_duplicates(subset=["symbol", "date"]).sort_values(["symbol", "date"])
        else:
            combined = new.sort_values(["symbol", "date"])
        save_cache(combined, cache_path)
        return combined
    return cached


# ----------------------------------------------------------------------------
# 抓取：DCE / INE 新浪按合约枚举（含已到期合约）
# ----------------------------------------------------------------------------
def sina_to_schema(df, symbol, variety, market):
    df = df.copy()
    out = pd.DataFrame(index=df.index)
    out["symbol"] = symbol
    out["date"] = df["date"].astype(str).str.replace("-", "", regex=False).str[:8]
    for c in ["open", "high", "low", "close", "volume"]:
        out[c] = pd.to_numeric(df[c], errors="coerce")
    out["open_interest"] = pd.to_numeric(df["hold"], errors="coerce")
    out["turnover"] = np.nan
    out["settle"] = pd.to_numeric(df["settle"], errors="coerce")
    out["pre_settle"] = np.nan
    out["variety"] = variety
    out["market"] = market
    return out


def fetch_via_sina(market, start_year, end_year, cache_dir, workers,
                   retries=3, varieties=None, no_repair=False, log=print,
                   cancel_event=None, progress=None):
    """枚举指定交易所各品种各交割月合约(含已到期)，经新浪按合约抓取日K兜底。"""
    cache_path = os.path.join(cache_dir, f"{market}.pkl")
    cached = load_cache(cache_path)

    if no_repair and cached is not None and len(cached):
        log(f"[{market}] --no-repair：沿用缓存 {len(cached):,} 条数据(不再重抓)。")
        return cached

    cached_syms = set(cached["symbol"].astype(str)) if cached is not None and len(cached) else set()
    varieties = varieties or []
    cutoff = dt.date.today() - dt.timedelta(days=7)  # 距今不足 7 日视为"仍需更新"

    tasks = []
    for var in varieties:
        v = var.lower()
        for yy in range(max(2000, int(start_year)), int(end_year) + 1):
            for mm in range(1, 13):
                sym = f"{v}{yy % 100:02d}{mm:02d}"
                tasks.append((sym, var))

    todo = []
    for sym, var in tasks:
        if sym in cached_syms:
            sub = cached[cached["symbol"].astype(str) == sym]
            if len(sub) and sub["date"].astype(str).max() >= cutoff.strftime("%Y%m%d"):
                continue
        todo.append((sym, var))

    if not todo:
        log(f"[{market}] 无新增合约(缓存已覆盖)，直接使用缓存。")
        return cached

    log(f"[{market}] 枚举 {len(tasks)} 个候选合约，待抓取 {len(todo)} 个，开始并行下载...")

    def worker(item):
        sym, var = item
        for attempt in range(1, retries + 1):
            if cancel_event is not None and cancel_event.is_set():
                return sym, var, None
            try:
                df = ak.futures_zh_daily_sina(symbol=sym)
                if df is not None and len(df) > 0:
                    return sym, var, sina_to_schema(df, sym, var.upper(), market)
                return sym, var, None
            except Exception:
                if attempt < retries:
                    time.sleep(0.5 * attempt)
                else:
                    return sym, var, None
        return sym, var, None

    new_dfs = []
    fetched = 0
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, it) for it in todo]
        for fut in as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                log(f"[{market}] 已收到停止指令，中断抓取。")
                for f in futures:
                    f.cancel()
                break
            sym, var, df = fut.result()
            done += 1
            if df is not None:
                fetched += 1
                new_dfs.append(df)
            if done % 400 == 0 or done == len(todo):
                log(f"  [{market}] 进度 {done}/{len(todo)}，已取到 {fetched} 个合约")
            if progress:
                progress(done / max(len(todo), 1))

    if new_dfs:
        new = pd.concat(new_dfs, ignore_index=True)
        if cached is not None and len(cached):
            combined = pd.concat([cached, new], ignore_index=True)
            combined = combined.drop_duplicates(subset=["symbol", "date"]).sort_values(["symbol", "date"])
        else:
            combined = new.sort_values(["symbol", "date"])
        save_cache(combined, cache_path)
        return combined
    return cached


# ----------------------------------------------------------------------------
# 分析：每品种统计
# ----------------------------------------------------------------------------
def compute_stats(vdf):
    vdf = vdf.sort_values("date")
    dates = vdf["date"].unique()
    trading_days = int(len(dates))
    total_k = int(len(vdf))
    listing = vdf["date"].min()

    # 极值只取正价格(排除残留的 0/缺失伪影)；期货价格不可能为 0。
    ihv = vdf["high"].dropna()
    ihv = ihv[ihv > 0]
    if len(ihv):
        ih = ihv.idxmax()
        hist_high = float(vdf.loc[ih, "high"])
        hh_date = vdf.loc[ih, "date"]
        hh_symbol = vdf.loc[ih, "symbol"]
    else:
        hist_high, hh_date, hh_symbol = None, "", ""

    ilv = vdf["low"].dropna()
    ilv = ilv[ilv > 0]
    if len(ilv):
        il = ilv.idxmin()
        hist_low = float(vdf.loc[il, "low"])
        ll_date = vdf.loc[il, "date"]
        ll_symbol = vdf.loc[il, "symbol"]
    else:
        hist_low, ll_date, ll_symbol = None, "", ""

    # 主连：每日取持仓量最大的合约为当日主力，拼接后求平均价
    main = vdf.dropna(subset=["open_interest"]).sort_values("open_interest", ascending=False)
    main = main.drop_duplicates(subset=["date"])[["date", "close", "settle"]]
    main_close_avg = float(main["close"].mean()) if len(main) else np.nan
    main_settle_avg = float(main["settle"].mean()) if len(main) else np.nan

    return {
        "上市日期": to_yyyymmdd(listing),
        "总交易天数": trading_days,
        "总K线条数": total_k,
        "历史最高价": hist_high,
        "最高价日期": to_yyyymmdd(hh_date),
        "最高价合约": hh_symbol,
        "历史最低价": hist_low,
        "最低价日期": to_yyyymmdd(ll_date),
        "最低价合约": ll_symbol,
        "主连平均收盘价": round(main_close_avg, 2) if main_close_avg == main_close_avg else None,
        "主连平均结算价": round(main_settle_avg, 2) if main_settle_avg == main_settle_avg else None,
    }


# ----------------------------------------------------------------------------
# 输出 Excel
# ----------------------------------------------------------------------------
def pretty_date(d):
    return f"{str(d)[:4]}-{str(d)[4:6]}-{str(d)[6:8]}" if d else ""


def write_outputs(all_df, out_dir, log=print, cancel_event=None):
    os.makedirs(out_dir, exist_ok=True)
    # 剔除"非交易日"伪影：volume=0 的行是未成交日(OHLC 常为 0 或 close 结转)
    n_before = len(all_df)
    all_df = all_df[all_df["volume"].fillna(0) > 0].copy()
    n_after = len(all_df)
    if n_after < n_before:
        log(f"(剔除 volume=0 的非交易行 {n_before - n_after:,} 条，保留真实K线 {n_after:,} 条)")

    varieties = sorted(all_df["variety"].unique().tolist())
    log(f"共 {len(varieties)} 个品种，开始生成 Excel ...")

    summary_rows = []
    for var in varieties:
        if cancel_event is not None and cancel_event.is_set():
            log("已停止，输出中断。")
            break
        vdf = all_df[all_df["variety"] == var]
        name = VARIETY_NAME.get(var, var)
        exchange = vdf["market"].iloc[0]
        stats = compute_stats(vdf)

        out = vdf[STD_COLS + ["market"]].rename(columns={
            "symbol": "合约", "date": "日期", "open": "开盘", "high": "最高",
            "low": "最低", "close": "收盘", "volume": "成交量",
            "open_interest": "持仓量", "turnover": "成交额", "settle": "结算",
            "pre_settle": "前结算", "variety": "品种", "market": "交易所",
        })
        out["日期"] = out["日期"].apply(pretty_date)
        out = out.sort_values(["合约", "日期"])

        fname = f"{var}_{name}.xlsx"
        fpath = os.path.join(out_dir, fname)
        summary_df = pd.DataFrame({
            "指标": list(stats.keys()),
            "数值": list(stats.values()),
        })
        summary_df.loc[len(summary_df)] = ["品种名称", name]
        summary_df.loc[len(summary_df)] = ["交易所", exchange]
        with pd.ExcelWriter(fpath, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="品种汇总", index=False)
            out.to_excel(writer, sheet_name="日K线", index=False)
        log(f"  已生成 {fname}")

        summary_rows.append({
            "品种代码": var, "品种名称": name, "交易所": exchange, **stats,
        })

    summary = pd.DataFrame(summary_rows)
    if len(summary):
        summary = summary[["品种代码", "品种名称", "交易所", "上市日期", "总交易天数",
                           "总K线条数", "历史最高价", "最高价日期", "最高价合约",
                           "历史最低价", "最低价日期", "最低价合约",
                           "主连平均收盘价", "主连平均结算价"]]
    summary_path = os.path.join(out_dir, "汇总_全部品种.xlsx")
    with pd.ExcelWriter(summary_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="汇总", index=False)
    log("  已生成 汇总_全部品种.xlsx")
    return summary


# ----------------------------------------------------------------------------
# 主流程（供 Web 后端调用）
# ----------------------------------------------------------------------------
def run(markets=None, start=None, end=None, out_dir=None, cache_dir=None,
        workers=10, no_repair=False, dce_start_year=2000,
        log=None, progress=None, cancel_event=None, keep=None):
    """执行抓取 + 分析，返回 (summary_df, out_dir)。

    log(str)       日志回调
    progress(pct)  总进度回调（0~1）
    cancel_event   threading.Event，置位则中断
    keep           需要保留的品种代码列表(None=全部)
    """
    log = log or (lambda m: None)
    progress = progress or (lambda p: None)
    cancel_event = cancel_event or threading.Event()

    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = out_dir or os.path.join(here, "期货日K数据")
    cache_dir = cache_dir or os.path.join(here, "期货数据缓存")
    os.makedirs(cache_dir, exist_ok=True)

    end = to_yyyymmdd(end or dt.date.today().strftime("%Y%m%d"))
    markets = [m.upper() for m in (markets or MARKETS)]
    markets = [m for m in markets if m in MARKET_START]
    if not markets:
        raise ValueError("没有可用的交易所，请至少选择一个。")

    log(f"启动抓取：交易所={','.join(markets)}｜区间=*~{end}｜并发={workers}｜"
        f"{'仅用缓存' if no_repair else '增量回补'}")
    log(f"输出目录：{out_dir}")
    log(f"缓存目录：{cache_dir}")

    all_dfs = []
    n = len(markets)
    for idx, market in enumerate(markets):
        if cancel_event.is_set():
            log("已停止。")
            break

        def sub_progress(p, idx=idx):
            progress((idx + p) / n)

        if market in SINA_FALLBACK:
            df = fetch_via_sina(market, dce_start_year, int(end[:4]),
                                cache_dir, workers, varieties=SINA_FALLBACK[market],
                                no_repair=no_repair, log=log,
                                cancel_event=cancel_event, progress=sub_progress)
        else:
            mstart = start or MARKET_START.get(market) or "20040101"
            df = fetch_exchange_market(market, mstart, end, cache_dir, workers,
                                       no_repair=no_repair, log=log,
                                       cancel_event=cancel_event, progress=sub_progress)

        if df is not None and len(df):
            all_dfs.append(df)
            log(f"[{market}] 累计 {len(df):,} 条记录。")
        else:
            log(f"[{market}] 未取到数据。")
        progress((idx + 1) / n)

    if not all_dfs:
        raise RuntimeError("没有任何数据，请检查网络或参数后重试。")

    all_df = pd.concat(all_dfs, ignore_index=True)
    all_df = all_df.dropna(subset=["variety"])
    all_df = all_df[all_df["variety"] != ""]
    # 剔除交易所日K中自带的非真实可交易品种(合成/特殊序列)
    all_df = all_df[~all_df["variety"].isin(EXCLUDE_VARIETIES)]
    # 只保留用户在网页上勾选的品种
    if keep:
        keep = {k.upper() for k in keep}
        all_df = all_df[all_df["variety"].isin(keep)]

    log(f"原始日K记录合计: {len(all_df):,} 行。")
    if not len(all_df):
        raise RuntimeError("筛选后没有数据，请检查品种勾选。")

    # 落盘一份全量明细(pickle)，供网页「品种详情」按需读取，避免重复抓取。
    try:
        all_df.reset_index(drop=True).to_pickle(os.path.join(out_dir, "_result.pkl"))
    except Exception as e:
        log(f"(明细缓存写入失败，不影响 Excel 输出：{e})")

    summary = write_outputs(all_df, out_dir, log=log, cancel_event=cancel_event)
    progress(1.0)
    log(f"全部完成，输出目录：{os.path.abspath(out_dir)}")
    return summary, out_dir
