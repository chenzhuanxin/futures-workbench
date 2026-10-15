<p align="center"><img src="assets/logo.png" width="120" alt="futures-workbench"></p>

# 期货数据工作台

把国内六大期货交易所的**全品种、全合约（含已退市）**日K数据抓下来，
用本地网页界面查看、分析与导出。数据落在你自己的硬盘上，不经过任何服务器。

本项目的抓取核心改写自公众号文章《公歧工作流：从期交所获取全部品种日K数据并分析.py》，
在其基础上加了 Web 界面、交互式 K 线图、技术指标、按月分组、加权合约、本地数据载入与导出。
数据只需抓一次：**重启会自动恢复上次结果**，也可以随时**指定任意已有数据目录直接载入**，不必重复下载。

> 设计：**公歧子** ｜ 微信：**gongqizi0**

[![Release](https://img.shields.io/badge/下载-Release%20v1.0.0-4a63e7?style=flat-square)](https://github.com/chenzhuanxin/futures-workbench/releases/latest)
[![Docs](https://img.shields.io/badge/在线文档-GitHub%20Pages-0ea5a5?style=flat-square)](https://chenzhuanxin.github.io/futures-workbench/)
[![License](https://img.shields.io/badge/license-MIT-12a150?style=flat-square)](LICENSE)

**📖 在线文档**

| 文档 | 内容 |
| --- | --- |
| [使用说明](https://chenzhuanxin.github.io/futures-workbench/guide.html) | 运行方式、界面总览、配置详解、耗时说明、本地数据载入、导出、K线图与指标用法、API、FAQ |
| [数据源说明](https://chenzhuanxin.github.io/futures-workbench/datasource.html) | 数据链路、六家交易所数据源、兜底源、字段口径、统计定义、加权算法、清洗规则、已知限制 |

---

## 下载即用（推荐）

到 [**Releases**](https://github.com/chenzhuanxin/futures-workbench/releases/latest) 下载
`FuturesWorkbench-v1.0.0-win64.exe`，放到任意目录（如 `D:\FuturesWorkbench\`）**双击运行**即可，
无需安装 Python。

程序会自动打开浏览器并跳转到 <http://127.0.0.1:8770>。
首次启动需解包内置依赖，约 10～40 秒，请耐心等待。

> ⚠️ 运行期间请保留那个黑色控制台窗口 —— 它是服务进程本体，关掉网页就打不开了。
> 数据目录（`期货日K数据` / `期货数据缓存`）会生成在 **exe 同目录**下。

### 🧩 附带完整行情数据包（免抓取）

不想等首次抓取（全量约需 1 个半小时）的话，可以直接下载 Release 附带的
**`futures-daily-k-data.zip`**（约 84 MB，解压后约 313 MB）：

1. 解压得到 `期货日K数据/` 目录，内含 **91 个品种 xlsx**（每个品种含「各月份合约」与「加权合约」两个 sheet）
   以及 **`汇总_全部品种.xlsx`** 汇总表；
2. 把 `期货日K数据/` 放到 **exe 同目录**（或任意位置都行）；
3. 打开网页 → 左侧「本地数据」面板 → 选择该文件夹 → 点 **载入本地数据**，
   **秒级**恢复全部结果，无需联网抓取。

> 数据为打包时的快照，行情截至 **2026-10-11**。需要最新数据时在左侧重新抓取一次即可。

---

## 从源码运行

双击目录里的 **`启动.bat`**，浏览器会自动打开 <http://127.0.0.1:8770>。
首次运行若缺少依赖，脚本会自动执行 `pip install -r requirements.txt`。

手动启动：

```bash
pip install -r requirements.txt
python app.py
```

换端口 / 不开浏览器：

```bash
set PORT=9000 && set NO_BROWSER=1 && python app.py
```

---

## 目录结构

```
futures-workbench/
├── 启动.bat              一键启动（自动装依赖 + 开浏览器）
├── build_exe.bat         打包成单文件 exe（PyInstaller）
├── app.py                Flask 后端：接口、任务调度、目录选择、导出、合约分组与加权合成
├── futures_core.py       抓取与分析核心（由文章脚本改写，加日志/进度/取消回调）
├── _pickdir.py           系统原生文件夹 / 另存为对话框（打包后走 --pickdir 快速通道）
├── demo_data.json        内置示例汇总数据（断网时预览界面用）
├── requirements.txt
├── LICENSE               MIT
├── app.py 等入口         （_prefs.json 为运行时生成，不入库）
├── templates/
│   └── index.html        页面结构
├── static/
│   ├── css/style.css     视觉样式（浅色玻璃拟态 + 光晕背景）
│   ├── js/kline.js       Canvas K线组件（平移/缩放/十字光标/指标/极值标注）
│   └── js/app.js         页面交互 + 总览 SVG 图表
├── docs/                 在线文档站（GitHub Pages）
│   ├── index.html        首页
│   ├── guide.html        使用说明
│   ├── datasource.html   数据源说明
│   └── assets/docs.css
├── 期货日K数据/           运行时生成 · 默认输出目录（Excel + _result.pkl）
└── 期货数据缓存/          运行时生成 · 默认缓存目录（每交易所一个 .pkl）
```

启动时会按 `_prefs.json` → 默认输出目录的顺序自动找回**上次的数据**并直接恢复，
不必重新抓一遍。

---

## 网页上能做什么

### 抓取配置（左侧）

| 项目 | 说明 |
| --- | --- |
| 本地数据 | **选一个已有数据目录，点「载入本地数据」即可直接查看，无需重新下载** |
| 交易所 | CFFEX / SHFE / CZCE / DCE / INE / GFEX，可多选 |
| 品种 | 按交易所分组勾选，支持搜索、分组全选、清空 |
| 日期区间 | 起始留空则用各交易所数据源最早日期；结束默认今天 |
| 并发线程 | 1~32，首次全量建议 16 |
| DCE 枚举起始年 | 大商所走新浪按合约枚举时的起始年份 |
| 输出 / 缓存目录 | 点「浏览…」弹出**系统原生文件夹选择框**，自动回填真实路径 |
| 仅用缓存 | 跳过缺失日期回补，缓存基本完整时更快 |

> ⏱ **首次全量抓取约需 1 个半小时**（六家交易所全品种）。
> 之后再次运行会自动增量更新，速度很快。

#### 本地数据（免重复下载）

点「浏览…」选择任意一个数据目录 → 「载入本地数据」，程序会自动识别并读取：

1. 目录里有 `_result.pkl` → 直接读全量明细（最快，秒级）；
2. 没有 `_result.pkl`，但有各品种的 `xxx_品种名.xlsx` → 逐个读取 `日K线` sheet
   合并还原（首次会顺手生成 `_result.pkl`，之后再载入就是秒级）；
3. 汇总优先用目录里的 `汇总_全部品种.xlsx`，没有就由明细现算。

支持指向**上一级目录**（如项目根目录），程序会自动下钻到 `期货日K数据` 之类的子目录。
载入成功后顶部标识会显示「**本地数据**」，品种详情、按月分组、加权合约、K线指标全部可用。
选过的目录会记进 `_prefs.json`，**下次启动自动恢复**。

### 总览

6 张 KPI 卡（品种数 / 交易所数 / 日K记录总数 / 累计交易天数 / 最早最晚上市）
+ 交易所品种分布环形图 + 各交易所品种数与数据规模明细。

### 品种汇总表

全部品种的统计字段（品种代码、名称、交易所、上市日期、总交易天数、总K线条数、
历史最高/最低价及日期与合约、主连平均收盘/结算价），点表头排序、搜索框过滤、点品种代码直达详情。

### 品种详情（本次重点）

- **合约按月分组浏览**：按交割月份分为 1~12 组，**跨年的同月合约归在同一组**对比展示
  （例如沪铜的 9 月组里同时有 CU2609 与 CU2709；沪金等品种同月多合约同样归组）。
- **加权合约**：每个品种独立合成一条加权合约日K ——
  每日以各合约**持仓量为权重**加权平均得到 OHLC（持仓量为 0 时退化为成交量加权），
  成交量、持仓量为各合约求和。
- **交互式日K线**：
  - 鼠标**拖拽左右平移**、**滚轮缩放**、**双击复位**
  - 十字光标 + 当日开高低收量提示
  - **历史最高价 / 历史最低价**自动在图上标注（虚线 + 标签显示价格与日期），
    顶部同时列出极值，并提供「📍历史最高 / 📍历史最低」一键定位
- **技术指标勾选切换**：`MA(5/10/20/60)`、`EXPMA(12/50)`、`BOLL(20,2)`、
  `BBIBOLL(11,6)`、`SAR(0.02/0.02/0.2)`，可任意组合叠加。
- **合约清单**：按月分组列出该品种全部合约（含已退市）的代码、交割年月、
  首末交易日、K线条数；点击任一合约即可切换为**单合约K线**。
- 月份分组内若只有一个合约，直接显示蜡烛图；多个合约则以折线叠加对比（图例可点选开关）。

#### 零值数据的处理（不展示）

数据源里存在两类「价格 = 0」的占位数据（例如郑煤 ZC、玉米淀粉 CY、普麦 PM 等品种的历史数据），
它们不是真实价格，图表上一律不显示：

| 情形 | 处理方式 |
| --- | --- |
| 开高低收**全部为 0**（无成交占位行） | 该行整条不返回，不占用日期轴、不画蜡烛、不连线 |
| 开高低为 0、**仅收盘价有值** | 日期轴保留（便于看出当日无成交），蜡烛不绘制；折线模式下用有效收盘价绘制 |
| 折线叠加模式下某合约某日收盘为 0 | 该点断开（不连线），也不参与纵轴范围计算 |

由此也保证：

- **纵轴范围不被拉到 0** —— 否则所有合约的折线会被压缩到顶部一条线上；
- **历史最高/最低价不被污染** —— 原先部分品种的「历史最低价」会显示为 `0`，
  现在按有效价格统计（如郑煤最低 277.881 @2015-11-24）；
- **技术指标不被稀释** —— MA / EXPMA / BOLL / BBIBOLL / SAR 计算时把零值视为缺失；
- 合约清单里**全是零值数据的合约不再列出**（本身没有可展示的行情）。
- 十字光标移到无有效行情的日期会提示「该日无有效行情（零值数据，未绘制）」。

> 导出的 Excel / CSV 仍保留原始数据（信息无损），仅在图表展示层面过滤。

### 保存到本机

底部输入框 / 「选择位置…」选定目录后，可导出：

- **汇总表** → Excel（.xlsx）或 UTF-8 CSV
- **全部行情文件** → 整个输出目录的 Excel 一起拷贝过去

> 「载入文章示例数据」按钮可在不联网时载入文章附带的 88 品种汇总数据先看界面；
> 该示例只含汇总统计，逐日K线需实际抓取后查看。

### 数据源说明（底部，默认折叠）

底部操作条上方有一栏「数据源说明」，点击展开（默认收起），内含带链接的数据源清单：

| 类别 | 来源 | 链接 |
| --- | --- | --- |
| 数据引擎 | AKShare 开源财经数据接口库 | <https://akshare.akfamily.xyz/> |
| | pandas / NumPy | <https://pandas.pydata.org/> |
| 交易所官网日行情 | 中国金融期货交易所 CFFEX | <http://www.cffex.com.cn/> |
| | 上海期货交易所 SHFE | <https://www.shfe.com.cn/> |
| | 郑州商品交易所 CZCE | <http://www.czce.com.cn/> |
| | 上海国际能源交易中心 INE | <https://www.ine.cn/> |
| | 广州期货交易所 GFEX | <http://www.gfex.com.cn/> |
| | 大连商品交易所 DCE | <http://www.dce.com.cn/> |
| 兜底 | 新浪财经 · 期货（DCE 被 WAF 拦截时按合约取日K） | <https://finance.sina.com.cn/futures/quotes/> |

---

## 抓取逻辑（与文章一致）

- **主要数据源**：`akshare.get_futures_daily()`，按交易日取某交易所当天全部合约
  （CFFEX / SHFE / CZCE / INE / GFEX）。
- **大商所 DCE**：官网接口被瑞数 WAF 反爬（返回 412），自动改用
  `ak.futures_zh_daily_sina()` 按合约枚举抓取，覆盖含已到期合约。
- **能源中心 INE**：官网不可达时同样走新浪兜底。
- **合成合约过滤**：合约代码去掉字母后以 `0 / 88 / 888 / 99` 结尾者剔除；
  额外剔除 `OP`、`SC_TAS` 等非真实品种。
- **稳定性**：强制 IPv4、请求默认 20 秒超时、每个请求重试 3 次、
  抓取前对最近 3 个交易日做连通性预检、`ThreadPoolExecutor` 并发下载。
- **缓存与增量**：每交易所一个 `.pkl`，再次运行只抓新增交易日/合约。
- **统计口径**：上市日期、总交易天数、总K线条数、历史最高/最低价（含日期与合约）、
  主连平均收盘价/结算价（每日取持仓量最大合约拼接）。极值只取正价格，
  输出前剔除 `volume == 0` 的非交易行。

## 输出文件

- `{品种代码}_{品种名称}.xlsx`：含 `品种汇总` 与 `日K线` 两个 sheet
- `汇总_全部品种.xlsx`：全品种汇总表
- `_result.pkl`：全量明细缓存，供网页「品种详情」按需读取
- `{market}.pkl`（缓存目录）：交易所级增量缓存

---

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/config` | 交易所、品种、默认目录等配置 |
| POST | `/api/pick` | 弹出系统原生目录对话框，返回所选路径 |
| POST | `/api/run` | 启动抓取任务 |
| GET | `/api/progress` | 进度、日志、状态 |
| POST | `/api/stop` | 中断任务 |
| POST | `/api/demo` | 载入文章示例数据 |
| POST | `/api/local-scan` | 预览某个本地目录里有什么数据（不载入） |
| POST | `/api/load-local` | 读取本机已有数据目录，作为当前结果（免重新抓取） |
| GET | `/api/summary` | 当前汇总结果 |
| GET | `/api/variety?code=CU` | 合约清单 + 按月分组 + 加权合约日K |
| GET | `/api/contracts?code=CU&month=9` | 某月份分组下全部（跨年同月）合约序列 |
| GET | `/api/contract?symbol=CU2709` | 单合约日K序列 |
| POST | `/api/export` | 导出到本机指定目录（xlsx / csv，汇总 / 全部） |
| GET | `/api/files` | 列出输出目录文件 |
| POST | `/api/open-folder` | 在资源管理器中打开目录 |

---

## 使用建议

- 首次全量抓取约 **1 个半小时**，建议并发线程调到 **16** 并保持页面开启。
- **不想再抓**：直接「载入本地数据」选已有目录，或什么都不做 —— 重启会自动恢复上次数据。
- 之后定期运行即为增量更新，速度很快。
- 只需要部分交易所时，在左侧关掉其余交易所，可显著节省时间。
- 若某交易所接口临时不可达，脚本会自动沿用已有缓存，不会中断整体任务。

## 环境要求

- **免安装 exe**：Windows 64 位，无需任何依赖。
- **源码运行**：Python 3.9+（已用 3.14 验证），依赖 `flask pandas numpy akshare requests openpyxl`。
- 需联网访问各期货交易所官网 / 新浪财经接口。

## 自己打包 exe

```bash
# 方式一：双击
build_exe.bat

# 方式二：手动
pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --console ^
  --name FuturesWorkbench ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "demo_data.json;." ^
  --add-data "_pickdir.py;." ^
  --collect-all akshare ^
  app.py
```

产物在 `dist/FuturesWorkbench.exe`（约 80 MB），首次打包约需 5～15 分钟。

打包相关的两点设计：

- **资源与数据分离**：`templates / static / demo_data.json` 打进 exe 内部（只读），
  而输出、缓存、`_prefs.json` 落在 **exe 同目录**（可写）。这样升级 exe 不会丢数据。
- **原生对话框快速通道**：点「浏览…」时以 `本程序 --pickdir ...` 再起一个自身进程弹窗，
  该分支在导入 pandas / flask 之前就 `sys.exit`，所以弹窗很快，不用等整个应用加载完。

## 相关项目

- [AKShare](https://akshare.akfamily.xyz/) —— 开源财经数据接口库，本项目的取数基础
- [pandas](https://pandas.pydata.org/) / [NumPy](https://numpy.org/) —— 数据处理与数值计算

## 免责声明

本项目仅用于**技术学习与数据研究**。数据来自公开的交易所官网与第三方数据接口，
不对其准确性、完整性、及时性作任何保证；**不构成任何投资建议**。
行情数据版权归各期货交易所所有，请勿用于商业转售，并遵守数据源网站的使用条款。
详见 [LICENSE](LICENSE) 与 [数据源说明](https://chenzhuanxin.github.io/futures-workbench/datasource.html)。
