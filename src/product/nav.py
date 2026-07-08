"""复权净值计算 & 频率转换"""

import pandas as pd
import numpy as np


def calc_adjusted_nav(nav: pd.DataFrame) -> pd.DataFrame:
    """
    计算复权净值。
    公式：
      首期: adj_nav[0] = acc_nav[0]
      后续: adj_nav[t] = adj_nav[t-1] * (1 + (acc_nav[t] - acc_nav[t-1]) / unit_nav[t-1])

    按每只基金独立计算。
    """
    nav = nav.sort_values(["fund_name", "trade_date"]).copy()
    nav["adj_nav"] = np.nan

    for fund, grp in nav.groupby("fund_name"):
        idx = grp.index
        acc = grp["acc_nav"].values
        unit = grp["unit_nav"].values
        adj = np.empty(len(grp))
        adj[0] = acc[0]
        for i in range(1, len(grp)):
            adj[i] = adj[i - 1] * (1 + (acc[i] - acc[i - 1]) / unit[i - 1])
        nav.loc[idx, "adj_nav"] = adj

    return nav


def _pick_weekly_dates(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """从交易日序列中选出周频代表日：每周最后一个交易日。"""
    iso = dates.isocalendar()
    week_last = dates.to_series().groupby([iso["year"], iso["week"]]).max()
    return pd.DatetimeIndex(week_last.sort_values())


def _pick_monthly_dates(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """从交易日序列中选出月频代表日：每月最后一个交易日。"""
    month_last = dates.to_series().groupby(dates.to_period("M")).max()
    return pd.DatetimeIndex(month_last.sort_values())


def resample_nav(nav: pd.DataFrame, freq: str) -> pd.DataFrame:
    """
    将净值数据重采样到指定频率。

    Parameters
    ----------
    nav : pd.DataFrame
        含 adj_nav 列的净值表。
    freq : str
        目标频率: "D"(不变), "W"(周频), "M"(月频)。

    Returns
    -------
    pd.DataFrame : 重采样后的净值表。
    """
    if freq == "D":
        return nav.copy()

    result = []
    for fund, grp in nav.groupby("fund_name"):
        grp = grp.set_index("trade_date").sort_index()
        all_dates = grp.index

        if freq == "W":
            pick_dates = _pick_weekly_dates(all_dates)
        elif freq == "M":
            pick_dates = _pick_monthly_dates(all_dates)
        else:
            raise ValueError(f"不支持的频率: {freq}")

        picked = grp.loc[grp.index.isin(pick_dates)].copy()
        picked["fund_name"] = fund
        result.append(picked.reset_index())

    if not result:
        return nav.copy()

    out = pd.concat(result, ignore_index=True)
    return out.sort_values(["fund_name", "trade_date"]).reset_index(drop=True)


def process_nav(nav: pd.DataFrame, freq: str = "W") -> pd.DataFrame:
    """
    一站式处理：计算复权净值 → 频率转换。
    """
    nav = calc_adjusted_nav(nav)
    nav = resample_nav(nav, freq)
    return nav
