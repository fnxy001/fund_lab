"""数据加载与校验"""

import pandas as pd
from pathlib import Path


def read_table(path: str) -> pd.DataFrame:
    """读取 CSV 或 Excel 文件，返回标准 DataFrame。"""
    path = Path(path)
    if path.suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    elif path.suffix == ".csv":
        return pd.read_csv(path)
    else:
        raise ValueError(f"不支持的文件格式: {path.suffix}")


def _ensure_datetime(df: pd.DataFrame, col: str = "trade_date") -> pd.DataFrame:
    """将 trade_date 列转为 datetime 并排序。"""
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values(["fund_name", "trade_date"]).reset_index(drop=True)


def validate(
    holdings: pd.DataFrame,
    nav: pd.DataFrame,
    benchmark: pd.DataFrame | None = None,
) -> dict:
    """
    校验输入数据，返回校验结果字典。
    - holdings: columns [fund_name, trade_date, weight]
    - nav: columns [fund_name, trade_date, unit_nav, acc_nav]
    - benchmark: columns [trade_date, nav] (optional)
    """
    issues = []

    # --- 必要列检查 ---
    for col in ["fund_name", "trade_date", "weight"]:
        if col not in holdings.columns:
            issues.append(f"持仓表缺少必要列: {col}")
    for col in ["fund_name", "trade_date", "unit_nav", "acc_nav"]:
        if col not in nav.columns:
            issues.append(f"净值表缺少必要列: {col}")

    if issues:
        return {"valid": False, "issues": issues}

    # --- 类型转换 ---
    holdings = _ensure_datetime(holdings)
    nav = _ensure_datetime(nav)

    # --- 产品覆盖校验 ---
    h_funds = set(holdings["fund_name"].unique())
    n_funds = set(nav["fund_name"].unique())
    missing = h_funds - n_funds
    if missing:
        issues.append(f"持仓中的产品在净值表中不存在: {missing}")

    # --- 净值日期覆盖校验 ---
    h_dates = holdings.groupby("fund_name")["trade_date"]
    n_dates = nav.groupby("fund_name")["trade_date"]
    for fund in h_funds & n_funds:
        h_min = h_dates.min()[fund]
        h_max = h_dates.max()[fund]
        n_min = n_dates.min()[fund]
        n_max = n_dates.max()[fund]
        if n_min > h_min:
            issues.append(f"{fund}: 净值最早日期({n_min.date()})晚于建仓日({h_min.date()})")
        if n_max < h_max:
            issues.append(f"{fund}: 净值最晚日期({n_max.date()})早于最后调仓日({h_max.date()})")

    # --- 权重校验 ---
    weight_check = holdings.groupby("trade_date")["weight"].sum()
    bad = weight_check[(weight_check < 0.99) | (weight_check > 1.01)]
    if len(bad) > 0:
        issues.append(f"以下调仓日权重之和不为1: {dict(bad.round(4))}")

    # --- 基准校验 ---
    if benchmark is not None:
        if "trade_date" not in benchmark.columns or "nav" not in benchmark.columns:
            issues.append("基准表缺少必要列: trade_date, nav")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "holdings": holdings,
        "nav": nav,
        "holdings_funds": sorted(h_funds),
        "nav_funds": sorted(n_funds),
    }


def load(
    holdings_path: str,
    nav_path: str,
    benchmark_path: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    """
    加载并校验数据，返回 (holdings, nav, benchmark)。
    校验不通过时抛出 ValueError。
    """
    holdings = _ensure_datetime(read_table(holdings_path))
    nav = _ensure_datetime(read_table(nav_path))
    benchmark = None
    if benchmark_path:
        benchmark = _ensure_datetime(read_table(benchmark_path), col="trade_date")
        # benchmark 没有 fund_name，需要特殊处理
        benchmark = pd.read_csv(benchmark_path) if benchmark_path.endswith(".csv") else pd.read_excel(benchmark_path)
        benchmark["trade_date"] = pd.to_datetime(benchmark["trade_date"])
        benchmark = benchmark.sort_values("trade_date").reset_index(drop=True)

    result = validate(holdings, nav, benchmark)
    if not result["valid"]:
        raise ValueError("数据校验未通过:\n" + "\n".join(f"  - {i}" for i in result["issues"]))

    return holdings, nav, benchmark
