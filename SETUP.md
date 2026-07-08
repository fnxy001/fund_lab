# Fund Lab — 环境配置说明书

换环境运行只需 **3 步**，零代码修改。

---

## 1. 快速开始

```bash
# ① 克隆项目
git clone git@github.com:fnxy001/fund_lab.git
cd fund_lab

# ② 安装依赖
pip install -r requirements.txt

# ③ 配置环境
cp .env.example .env
# 编辑 .env 填入数据库密码（如果只用文件模式，跳过）

# 开始使用
python
```

---

## 2. 环境要求

| 组件 | 最低版本 | 说明 |
|------|----------|------|
| Python | 3.10+ | |
| pip 包 | `pip install -r requirements.txt` | 一键安装 |
| MySQL | 8.0（可选） | 仅数据库模式需要 |

**依赖清单：**
```
pandas>=2.0          # 数据处理核心
numpy>=1.24          # 数值计算
plotly>=5.18         # 可视化
openpyxl>=3.1        # Excel 读写
pymysql>=1.1         # MySQL 连接
sqlalchemy>=2.0      # 数据库 ORM
python-dotenv>=1.0   # 环境变量管理
streamlit>=1.28      # Web UI（可选）
```

---

## 3. 配置说明（`.env` 文件）

所有环境差异集中在 `.env` 文件，**换环境只改这一个文件**：

```ini
# --- 数据库（数据库模式才需要）---
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password_here
DB_NAME=fund_lab

# --- 分析参数（通常不改）---
RISK_FREE_RATE=0.0
BENCHMARK_NAME=沪深300
DEFAULT_FREQ=W
DAILY_MIN_COVERAGE=0.5
```

**配置项说明：**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DB_HOST` | localhost | 数据库主机地址 |
| `DB_PORT` | 3306 | 数据库端口 |
| `DB_USER` | root | 数据库用户 |
| `DB_PASSWORD` | — | 数据库密码 |
| `DB_NAME` | fund_lab | 数据库名 |
| `RISK_FREE_RATE` | 0.0 | 年化无风险利率 |
| `BENCHMARK_NAME` | 沪深300 | 基准名称 |
| `DEFAULT_FREQ` | W | 默认频率（D/W/M） |

> ⚠️ `.env` 包含密码，**不会提交到 Git**。`.env.example` 是模板，可以提交。

---

## 4. 数据模式

项目支持两种数据来源，按需选择：

### 模式 A：文件模式（开发 / 快速验证）

数据放 `data/` 目录，直接加载 CSV / Excel：

```python
from src.common.utils import load

# 直接加载文件
holdings, nav, benchmark = load(
    "data/持仓.csv",
    "data/净值.csv",
    "data/基准.csv"        # 可选
)
```

不需要数据库，开箱即用。

### 模式 B：数据库模式（生产 / 全量数据）

需要 MySQL 8.0 运行中，且表结构已建好：

```python
from src.common.db import DB

db = DB()

# 加载持仓数据
holdings = db.load_holdings(start_date="2020-01-01")

# 加载净值数据
nav = db.load_nav(fund_names=["基金A", "基金B"])

# 加载基准数据
benchmark = db.load_benchmark("沪深300")
```

**换环境数据源不同？** 只需确保 `.env` 连到新数据库，或用文件模式。

---

## 5. 两种场景操作指南

### 场景一：本地开发（你的笔记本）

```
数据来源：data/ 目录的 CSV 文件
.env：    DB 参数随意填（文件模式不读数据库）
操作：    直接跑 Python 脚本，或 streamlit run app.py
```

### 场景二：数据服务器（有全量数据库）

```
数据来源：MySQL 8.0 数据库
.env：    填入真实 DB_HOST、DB_PASSWORD 等
操作：
  1. 确认 MySQL 服务运行中
  2. 确认 fund_lab 数据库已建表
  3. 用 db.py 接口读写数据
```

---

## 6. 项目结构速查

```
fund_lab/
├── SETUP.md              # ← 你正在看
├── CLAUDE.md             # 项目技术文档
├── requirements.txt      # pip 依赖清单
├── config.py             # 全局配置（自动读 .env）
├── .env.example          # 配置模板
├── .env                  # 你的本地配置（不提交）
├── src/
│   ├── common/
│   │   ├── db.py         # 数据库接口
│   │   └── utils.py      # 文件加载、数据校验
│   ├── product/
│   │   ├── nav.py        # 净值处理（复权 + 频率转换）
│   │   ├── info.py       # 产品基础信息
│   │   └── analytics.py  # 单产品分析
│   └── portfolio/
│       ├── engine.py     # 组合净值引擎
│       ├── performance.py # 业绩指标（25+指标）
│       └── attribution.py # 收益归因 + 风险归因
└── data/                 # 原始数据文件（文件模式用）
```

---

## 7. 常见操作

```python
# ---------- 完整分析流程 ----------

from src.common.utils import load
from src.product.nav import process_nav
from src.portfolio.engine import calc_portfolio_from_holdings
from src.portfolio.performance import PerformanceAnalyzer
from src.portfolio.attribution import AttributionAnalyzer

# 1. 加载数据
holdings, nav, benchmark = load("data/持仓.csv", "data/净值.csv")

# 2. 处理净值（复权 + 周频）
nav_processed = process_nav(nav, freq="W")

# 3. 计算组合净值
result = calc_portfolio_from_holdings(holdings, nav_processed)

# 4. 业绩分析
analyzer = PerformanceAnalyzer(
    nav_dict={"组合": result["portfolio_nav"], **result["fund_nav"]},
    freq="W",
    portfolio_benchmark=benchmark["nav"],
)
print(analyzer.metrics_table("近1年"))          # 单区间指标
print(analyzer.metrics_multi_period())           # 多区间指标

# 5. 归因分析
attr = AttributionAnalyzer(result, freq="W")
print(attr.return_attribution_table("近1年"))    # 收益归因
print(attr.combined_attribution("近1年"))         # 合并归因
```

---

## 8. 换环境检查清单

复制项目到新环境后，逐项确认：

- [ ] Python 3.10+ 已安装
- [ ] `pip install -r requirements.txt` 无报错
- [ ] `.env` 已从 `.env.example` 复制并编辑
- [ ] 文件模式：`data/` 目录有数据文件；或数据库模式：MySQL 可连接
- [ ] `python -c "import config; print('OK')"` 通过
- [ ] `python -c "from src.portfolio.engine import HoldingsEngine; print('OK')"` 通过

---

## 9. 注意事项

1. **`.env` 绝不提交 Git** —— 已在 `.gitignore` 中排除
2. **频率无关设计** —— 日/周/月频使用同一套 API，改 `DEFAULT_FREQ` 即可
3. **文件模式是过渡方案** —— 长期建议用数据库模式（数据更全、查询更灵活）
4. **MySQL 本地服务** —— Windows 上服务名为 `MySQL80`，默认开机自启
