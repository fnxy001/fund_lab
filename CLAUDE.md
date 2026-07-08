# Fund Lab — 产品研究与组合分析平台

## 项目定位

**产品研究底座 + 组合分析**，分层架构：
- **产品层**：净值处理、产品基础信息、策略标签、单产品分析
- **组合层**（当前聚焦）：组合净值拟合、持仓分析、收益归因、风险归因

核心功能：
- 组合净值拟合（根据持仓/交易数据 + 子成分净值，重建组合净值序列）
- 组合持仓分析
- 组合收益归因（Modified Dietz 资金加权 / 几何累积法）
- 组合风险归因（贡献序列波动法 + 风险分散）

## 输入数据

### ① 组合持仓/交易数据（四种场景）
| 场景 | 输入 | 说明 |
|------|------|------|
| 模型再平衡 | 均值方差/风险平价模型定期调仓结果 | 得到每期目标权重 |
| 固定权重再平衡 | 目标权重 + 再平衡频率（月/季/半年/年） | 定期自动调回目标权重 |
| 具体申赎交易 | 标的、申购日期、申购金额、赎回日期、赎回份额 | 通过交易记录反推持仓 |
| 不定期目标调仓 | 调仓日 + 标的 + 目标持仓比例 | 类似现有 HoldingsEngine 模式 |

### ② 标的信息
- 净值数据（单位净值、累计净值 → 复权净值）
- 基础信息（策略类型、基金类别等标签）
- 标的范围：公募基金、私募基金、ETF、指数

## 技术栈

- Python 3.x
- pandas >= 2.0, numpy >= 1.24
- plotly >= 5.18（可视化）
- openpyxl >= 3.1（Excel 读写）
- **MySQL 8.0**（已安装，本地服务 MySQL80 运行中）— 数据存储
- SQLAlchemy / pymysql — 数据库接口

## 设计原则

1. **数据准确第一** — 口径明确，数据校验优先，所有计算需可验证
2. **频率无关** — 净值计算按 pct_change，日/周/月频逻辑统一
3. **可扩展引擎架构** — PortfolioEngine 基类，子类只需实现 _build_weight_matrix()
4. **组合层面优先** — 当前聚焦组合分析，但需预留产品分析的扩展空间
5. **两套环境通用** — 代码在此开发，复制到无 Claude Code 的空间直接跑（配置分离）

## 项目结构（目标）

```
fund_lab/
├── CLAUDE.md
├── requirements.txt
├── config.py              # 数据库连接 & 全局配置（环境变量分离）
├── src/
│   ├── common/            # 共享工具
│   │   ├── db.py          #   数据库读写接口
│   │   └── utils.py       #   通用工具函数
│   ├── product/           # 产品底座层
│   │   ├── nav.py         #   净值处理
│   │   ├── info.py        #   产品基础信息 & 策略标签
│   │   └── analytics.py   #   单产品分析
│   └── portfolio/         # 组合层（当前聚焦）
│       ├── engine.py      #   组合净值引擎
│       ├── performance.py #   业绩指标（20+指标）
│       └── attribution.py #   收益归因 + 风险归因
└── data/                  # 原始文件数据（临时过渡，长期走数据库）
```

## 数据流 & 模块依赖链

```
原始数据（CSV/Excel）
    │
    ▼
src/common/utils.py          load() + validate()
    │  holdings: [fund_name, trade_date, weight]
    │  nav:       [fund_name, trade_date, unit_nav, acc_nav]
    │  benchmark: [trade_date, nav] (optional)
    ▼
src/product/nav.py           process_nav(nav, freq)
    │  calc_adjusted_nav()  → adj_nav = 复权净值
    │  resample_nav()       → D/W/M 频率统一
    ▼
src/portfolio/engine.py      HoldingsEngine(nav, holdings).calc()
    │  → { portfolio_nav, weights_close, fund_returns, fund_nav }
    ▼
    ├── src/portfolio/performance.py   PerformanceAnalyzer(nav_dict, freq)
    │     25+ 指标 / 多区间 / 滚动 / 子基金对比 / 持有期分布
    │
    └── src/portfolio/attribution.py   AttributionAnalyzer(portfolio_result, freq)
          收益归因（几何累积） + 风险归因（贡献序列波动法）
```

## 核心 API 入口

```python
from src.common.utils import load
from src.product.nav import process_nav
from src.portfolio.engine import calc_portfolio_from_holdings
from src.portfolio.performance import PerformanceAnalyzer
from src.portfolio.attribution import AttributionAnalyzer

# 1. 加载数据
holdings, nav, benchmark = load("持仓.csv", "净值.csv")

# 2. 处理净值
nav_processed = process_nav(nav, freq="W")

# 3. 计算组合净值
result = calc_portfolio_from_holdings(holdings, nav_processed)

# 4. 业绩分析
analyzer = PerformanceAnalyzer(
    nav_dict={"组合": result["portfolio_nav"], **result["fund_nav"]},
    freq="W",
    portfolio_benchmark=benchmark["nav"],
)
analyzer.metrics_table("近1年")          # 全部实体 × 单区间
analyzer.metrics_multi_period()          # 主体 × 多区间
analyzer.fund_comparison_metrics("共同区间")  # 子基金横向对比

# 5. 归因分析
attr = AttributionAnalyzer(result, freq="W")
attr.return_attribution_table("近1年")   # 收益归因
attr.risk_attribution_table("近1年")     # 风险归因
attr.combined_attribution("近1年")       # 合并表
```

## Git 远程配置

- **双远程**：`origin` (GitHub SSH) + `gitee` (Gitee HTTPS)
- 用户：GitHub/Gitee 均为 `fnxy001`，邮箱 `fnxy001@163.com`

## 当前状态

- ✅ 组合层代码完整（engine / performance / attribution）
- ✅ 净值处理（复权净值 + 频率转换）
- ⚠️ 数据加载走文件模式（`src/common/utils.py`），`db.py` 为占位符
- ❌ 产品层未建设（`info.py` / `analytics.py` 为 TODO）
- ❌ 无测试、无 CLI 入口、无 main script
- ❌ 数据库表结构未定义
