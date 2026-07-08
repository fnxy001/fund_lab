# Fund Lab — 项目迁移指南

换电脑？换服务器？复制给同事？照着下面一步一步做就行。

---

## 开始之前

你需要确保新环境已经安装了 **Python**。

怎么检查？打开终端（Windows 上是命令提示符或 PowerShell），输入：

```
python --version
```

如果显示 `Python 3.10.x` 或更高版本，说明已安装，继续下一步。
如果提示"找不到命令"或版本低于 3.10，先去 [python.org](https://www.python.org/downloads/) 下载安装。

---

## 第一步：把项目代码拿到新电脑上

### 方式一：从 GitHub 下载（推荐）

打开终端，进入你想放项目的文件夹，输入：

```
git clone git@github.com:fnxy001/fund_lab.git
```

下载完成后，进入项目目录：

```
cd fund_lab
```

> 如果提示 `git: command not found`，说明没装 Git。去 [git-scm.com](https://git-scm.com/download/win) 下载安装。

### 方式二：直接复制文件夹

把整个 `fund_lab` 文件夹复制到新电脑上（U 盘、网盘、局域网都行）。

然后打开终端，进入这个文件夹：

```
cd 你放项目的路径/fund_lab
```

---

## 第二步：安装项目需要的 Python 包

在项目目录下，输入这一行命令：

```
pip install -r requirements.txt
```

它会自动安装项目依赖的所有包。看到进度条走完就可以了。

> 如果中途报错，通常是网络问题。试一下用国内镜像：
> ```
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

---

## 第三步：创建配置文件

项目里有一个配置模板叫 `.env.example`，把它复制一份叫 `.env`：

**Windows 上：**

```
copy .env.example .env
```

**Mac / Linux 上：**

```
cp .env.example .env
```

### 然后决定：你用哪种数据来源？

---

### 情况 A：你只是分析 CSV / Excel 文件（不用数据库）

恭喜，**什么都不用改，配置完成**。直接把你的数据文件放到 `data/` 目录下就行。

继续跳到"第四步：验证是否配置成功"。

---

### 情况 B：你要连接 MySQL 数据库

用记事本打开刚才创建的 `.env` 文件，修改里面的数据库信息：

```
DB_HOST=192.168.1.100      ← 改成数据库服务器的 IP 地址
DB_PORT=3306               ← 改成数据库的端口号
DB_USER=root               ← 改成数据库的用户名
DB_PASSWORD=你的真实密码    ← 改成你的数据库密码
DB_NAME=fund_lab           ← 改成你的数据库名称
```

改完保存，关闭文件。

> ⚠️ `.env` 文件里有密码，**不要**把它发给别人，**不要**提交到 Git。

---

## 第四步：验证是否配置成功

在终端里输入：

```
python -c "from config import DB_URL; print('配置读取成功')"
```

如果输出 `配置读取成功`，说明一切正常。

再输入：

```
python -c "from src.portfolio.engine import HoldingsEngine; print('模块加载成功')"
```

如果输出 `模块加载成功`，说明所有代码都能正常工作了。

> 如果这里报错，通常是第二步的包没装全，重新跑一次 `pip install -r requirements.txt`。

---

## 第五步：开始使用

打开 Python（在终端里输入 `python`），按下面的流程操作：

```python
# ---------- 第 1 步：加载你的数据 ----------

# 如果用文件模式（数据在 data/ 目录下）：
from src.common.utils import load
holdings, nav, benchmark = load("data/持仓.csv", "data/净值.csv")

# 如果用数据库模式：
from src.common.db import DB
db = DB()
holdings = db.load_holdings(start_date="2020-01-01")
nav = db.load_nav()
benchmark = db.load_benchmark("沪深300")


# ---------- 第 2 步：处理净值 ----------
from src.product.nav import process_nav
nav_processed = process_nav(nav, freq="W")   # W=周频，也可以改成 D=日频 M=月频


# ---------- 第 3 步：计算组合净值 ----------
from src.portfolio.engine import calc_portfolio_from_holdings
result = calc_portfolio_from_holdings(holdings, nav_processed)


# ---------- 第 4 步：看业绩指标 ----------
from src.portfolio.performance import PerformanceAnalyzer

analyzer = PerformanceAnalyzer(
    nav_dict={"组合": result["portfolio_nav"], **result["fund_nav"]},
    freq="W",
    portfolio_benchmark=benchmark["nav"],
)

print(analyzer.metrics_table("近1年"))           # 所有产品的一年表现
print(analyzer.metrics_multi_period())           # 组合在多个时间段的表现


# ---------- 第 5 步：看收益归因 ----------
from src.portfolio.attribution import AttributionAnalyzer

attr = AttributionAnalyzer(result, freq="W")
print(attr.return_attribution_table("近1年"))    # 哪只基金贡献了多少收益
print(attr.combined_attribution("近1年"))         # 收益 + 风险合在一起看
```

---

## 常见问题

### Q: pip 安装包特别慢怎么办？

用清华镜像加速：

```
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: 提示 `ModuleNotFoundError: No module named 'xxx'`

说明那个包没装上，手动装一下：

```
pip install 缺失的包名
```

### Q: 数据库连不上

先确认三件事：

1. MySQL 服务是不是在运行？（Windows 上搜"服务"，找 MySQL80，看看状态是不是"正在运行"）
2. `.env` 里的 `DB_HOST` 和 `DB_PASSWORD` 写对了没？
3. 网络能不能 ping 通数据库服务器？

在 Python 里测试一下：

```python
from src.common.db import DB
db = DB()
print(db.test_connection())   # True = 连上了，False = 没连上
```

### Q: 提示 `ModuleNotFoundError: No module named 'config'`

你当前不在项目目录下。先 `cd` 到 `fund_lab` 文件夹，再运行 Python。

### Q: GitHub 连不上怎么办？

项目同时备份在 Gitee（码云），国内可以直接访问：

```
git clone https://gitee.com/fnxy001/fund_lab.git
```

---

## 附录：项目里每个文件是干什么的

```
fund_lab/
├── SETUP.md               ← 你正在看的文档
├── requirements.txt       ← 需要安装哪些 Python 包
├── config.py              ← 全局配置（自动读 .env）
├── .env.example           ← 配置模板（可以提交到 git）
├── .env                   ← 你自己的配置（不要提交！）
├── data/                  ← 放你的原始数据文件
├── src/
│   ├── common/
│   │   ├── db.py          ← 从数据库读数据
│   │   └── utils.py       ← 从文件读数据（CSV/Excel）
│   ├── product/
│   │   └── nav.py         ← 净值处理（复权 + 日周月频）
│   └── portfolio/
│       ├── engine.py      ← 核心：计算组合净值
│       ├── performance.py ← 业绩指标（收益率、回撤、夏普等 25+）
│       └── attribution.py ← 归因分析（收益归因 + 风险归因）
```
