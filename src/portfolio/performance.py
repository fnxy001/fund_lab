"""业绩指标计算

特性
----
- D（日频/实际频率）：自然日锚定 + 向后找数据点 + 50% 覆盖率门槛
- W/M（周频/月频）：交易日历定位 + bar 回看，资产日历日有数据则算，无则 NaN
- obs_date 指定观察点，区间以观察点为终点向前倒推
- 基准灵活分配：每产品可指定不同基准
- 指标可选：metrics_filter 按需计算
- 滚动指标：自定义窗口 + 观察区间
- 持有期收益分布
- 子基金对比：支持共同区间/全部区间/标准区间/自定义区间
"""

import pandas as pd
import numpy as np
from config import (
    ANNUAL_FACTOR, PERIOD_CALENDAR_DAYS, PERIOD_LOOKBACK_BARS,
    DAILY_MIN_COVERAGE, ALL_PERIODS,
)


# ======================================================================
# 时间区间切片
# ======================================================================

def _resolve_end_date(series: pd.Series, obs_date: pd.Timestamp | None) -> pd.Timestamp:
    if obs_date is None:
        return series.index[-1]
    mask = series.index <= obs_date
    if not mask.any():
        raise ValueError(f"obs_date={obs_date.date()} 早于序列最早日期")
    return series.index[mask][-1]


def slice_period(
    series: pd.Series,
    freq: str,
    period: str,
    obs_date: pd.Timestamp | None = None,
    calendar: pd.DatetimeIndex | None = None,
) -> pd.Series:
    if len(series) == 0:
        raise ValueError("序列为空")

    end_date = _resolve_end_date(series, obs_date)

    if period == "成立以来":
        return series.loc[:end_date]

    if period == "今年以来":
        prev_year_end = pd.Timestamp(f"{end_date.year - 1}-12-31")
        if freq in ("W", "M") and calendar is not None:
            cal_before = calendar[calendar <= prev_year_end]
            if len(cal_before) == 0:
                raise ValueError(f"交易日历中无 {end_date.year - 1} 年数据")
            start_dt = cal_before[-1]
        else:
            mask = series.index <= prev_year_end
            if not mask.any():
                raise ValueError(f"序列中无 {end_date.year - 1} 年数据")
            start_dt = series.index[mask][-1]
        return series.loc[start_dt:end_date]

    if ":" in period:
        parts = period.split(":")
        return series.loc[pd.Timestamp(parts[0]):pd.Timestamp(parts[1])]

    # W / M：交易日历定位 + bar 回看
    if freq in ("W", "M"):
        bar_map = PERIOD_LOOKBACK_BARS.get(freq, {})
        n_bars = bar_map.get(period) if bar_map else None
        if n_bars is None:
            raise ValueError(f"频率 {freq} 不支持区间 {period}")

        if calendar is not None:
            cal_subset = calendar[calendar <= end_date]
            end_pos = cal_subset.get_indexer([end_date])[0]
            if end_pos < 0:
                raise ValueError(f"end_date={end_date.date()} 不在交易日历中")
            start_pos = max(0, end_pos - n_bars)
            start_dt = cal_subset[start_pos]
            if start_dt not in series.index:
                raise ValueError(f"资产在起始日 {start_dt.date()} 无数据")
        else:
            pos = series.index.get_loc(end_date)
            if isinstance(pos, np.ndarray):
                idx = pos[-1]
            elif isinstance(pos, slice):
                idx = pos.stop - 1
            else:
                idx = pos
            start_dt = series.index[max(0, idx - n_bars)]

        return series.loc[start_dt:end_date]

    # D（日频 / 实际频率）：自然日锚定 + 向后找 + 覆盖率校验
    cal_days = PERIOD_CALENDAR_DAYS.get(period)
    if cal_days is None:
        raise ValueError(f"未知区间: {period}")

    target = end_date - pd.Timedelta(days=cal_days)
    candidates = series.index[series.index >= target]
    if len(candidates) == 0:
        raise ValueError(f"无数据点覆盖区间 {period}")

    start_dt = candidates[0]
    sliced = series.loc[start_dt:end_date]

    return sliced


# ======================================================================
# 子基金对比区间
# ======================================================================

COMPARISON_MODES = [
    "共同区间", "全部区间",
    "近1月", "近3月", "近半年", "今年以来",
    "近1年", "近2年", "近3年", "近5年", "成立以来",
]


def get_comparison_date_range(
    nav_dict: dict[str, pd.Series],
    mode: str,
    freq: str,
    obs_date: pd.Timestamp | None = None,
    calendar: pd.DatetimeIndex | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    确定子基金对比的起止日期。

    Parameters
    ----------
    nav_dict : dict[str, pd.Series]
    mode : str
        "共同区间" / "全部区间" / 标准区间 / "自定义:YYYY-MM-DD:YYYY-MM-DD"
    freq, obs_date, calendar : 同 slice_period

    Returns
    -------
    (start_date, end_date)
    """
    series_list = list(nav_dict.values())

    # ---- 自定义区间 ----
    if mode.startswith("自定义:"):
        parts = mode.split(":")[1:]
        return pd.Timestamp(parts[0]), pd.Timestamp(parts[1])

    # ---- 全部区间（并集） ----
    if mode == "全部区间":
        start = min(s.index[0] for s in series_list)
        end = max(s.index[-1] for s in series_list)
        if obs_date is not None and obs_date < end:
            end = obs_date
        return start, end

    # ---- 共同区间（交集） ----
    if mode == "共同区间":
        start = max(s.index[0] for s in series_list)
        end = min(s.index[-1] for s in series_list)
        if start > end:
            raise ValueError("子基金无共同区间")
        if obs_date is not None and obs_date < end:
            end = obs_date
        return start, end

    # ---- 标准区间（以共同终点为锚） ----
    # 终点取 obs_date 或共同最后一天
    if obs_date is not None:
        end = obs_date
    else:
        end = min(s.index[-1] for s in series_list)

    # 用主序列（第一只基金）的 slice_period 确定起点
    primary = series_list[0]
    sliced = slice_period(primary, freq, mode, end, calendar)
    return sliced.index[0], end


def fund_comparison_returns(
    nav_dict: dict[str, pd.Series],
    mode: str,
    freq: str,
    obs_date: pd.Timestamp | None = None,
    calendar: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """
    子基金在对比区间内的累计收益率。

    Returns
    -------
    pd.Series : fund_name → 累计收益率
    """
    try:
        start, end = get_comparison_date_range(nav_dict, mode, freq, obs_date, calendar)
    except ValueError:
        return pd.Series(np.nan, index=list(nav_dict.keys()))

    period_str = f"{start.strftime('%Y-%m-%d')}:{end.strftime('%Y-%m-%d')}"
    results = {}
    for name, nav in nav_dict.items():
        try:
            s = slice_period(nav, freq, period_str)
            results[name] = cumulative_return(s)
        except ValueError:
            results[name] = np.nan
    return pd.Series(results)


# ======================================================================
# 滚动窗口解析
# ======================================================================

def parse_window(window, freq: str) -> int:
    if isinstance(window, int):
        return window
    w = window.upper()
    annual = ANNUAL_FACTOR.get(freq, 52)
    if w.endswith("Y"):
        return int(round(float(w[:-1]) * annual))
    elif w.endswith("M"):
        return int(round(float(w[:-1]) / 12 * annual))
    elif w.endswith("W"):
        weeks = float(w[:-1])
        if freq == "W":
            return int(weeks)
        elif freq == "D":
            return int(weeks * 5)
        else:
            return int(round(weeks / 4.33))
    else:
        raise ValueError(f"无法解析窗口: {window}")


# ======================================================================
# 工具
# ======================================================================

def _returns(series: pd.Series) -> pd.Series:
    return series.pct_change().dropna()


def _nan_row(metrics_filter: list[str] | None = None) -> dict:
    if metrics_filter:
        return {k: np.nan for k in metrics_filter}
    return {name: np.nan for (_, name) in METRIC_REGISTRY}


# ======================================================================
# 收益指标
# ======================================================================

def cumulative_return(series: pd.Series) -> float:
    if len(series) < 2:
        return 0.0
    return float(series.iloc[-1] / series.iloc[0] - 1)


def annualized_return(series: pd.Series, freq: str, **kw) -> float:
    r = cumulative_return(series)
    if r <= -1 or len(series) < 2:
        return np.nan
    n_years = (series.index[-1] - series.index[0]).days / 365.25
    if n_years < 0.02:
        return np.nan
    return float((1 + r) ** (1 / n_years) - 1)


# ======================================================================
# 回撤指标
# ======================================================================

def max_drawdown(series: pd.Series) -> float:
    return float((series / series.expanding().max() - 1).min())


def drawdown_series(series: pd.Series) -> pd.Series:
    return series / series.expanding().max() - 1


def max_drawdown_recovery_periods(series: pd.Series) -> int | None:
    if len(series) < 2:
        return None
    peak = series.expanding().max()
    trough_iloc = (series / peak - 1).values.argmin()
    before = series.iloc[:trough_iloc + 1]
    peak_idx = before.idxmax()
    peak_val = series[peak_idx]
    after = series.iloc[trough_iloc:]
    recovered = after[after >= peak_val]
    if len(recovered) == 0:
        return None
    return len(series.loc[peak_idx:recovered.index[0]]) - 1


def longest_drawdown_recovery_periods(series: pd.Series) -> int | None:
    if len(series) < 2:
        return None
    dd = (series / series.expanding().max() - 1).values
    mx, in_dd, start = 0, False, 0
    for i in range(len(dd)):
        if not in_dd and dd[i] < 0:
            in_dd, start = True, i - 1
        elif in_dd and dd[i] >= 0:
            mx, in_dd = max(mx, i - start), False
    return mx if mx > 0 else None


def longest_no_new_high_periods(series: pd.Series) -> int:
    if len(series) < 2:
        return 0
    is_high = series == series.expanding().max()
    mx, cur = 0, 0
    for v in is_high:
        if not v:
            cur += 1
            mx = max(mx, cur)
        else:
            cur = 0
    return mx


def no_new_high_ratio(series: pd.Series) -> float:
    if len(series) < 2:
        return np.nan
    return float((series < series.expanding().max()).sum() / len(series))


# ======================================================================
# 波动 & 风险调整
# ======================================================================

def annualized_volatility(series: pd.Series, freq: str, **kw) -> float:
    r = _returns(series)
    if len(r) < 2:
        return np.nan
    return float(r.std(ddof=1) * np.sqrt(ANNUAL_FACTOR.get(freq, 252)))


def annualized_downside_vol(series: pd.Series, freq: str, **kw) -> float:
    d = _returns(series)
    d = d[d < 0]
    if len(d) < 2:
        return np.nan
    return float(d.std(ddof=1) * np.sqrt(ANNUAL_FACTOR.get(freq, 252)))


def sharpe_ratio(series: pd.Series, freq: str, rf: float = 0.0, **kw) -> float:
    a, v = annualized_return(series, freq), annualized_volatility(series, freq)
    return float((a - rf) / v) if not np.isnan(a) and not np.isnan(v) and v != 0 else np.nan


def sortino_ratio(series: pd.Series, freq: str, rf: float = 0.0, **kw) -> float:
    a, d = annualized_return(series, freq), annualized_downside_vol(series, freq)
    return float((a - rf) / d) if not np.isnan(a) and not np.isnan(d) and d != 0 else np.nan


def calmar_ratio(series: pd.Series, freq: str, rf: float = 0.0, **kw) -> float:
    a, m = annualized_return(series, freq), max_drawdown(series)
    return float(a / abs(m)) if not np.isnan(a) and abs(m) > 1e-10 else np.nan


# ======================================================================
# VaR / CVaR / 偏度 / 峰度
# ======================================================================

def var_95(series: pd.Series, freq: str, annualize: bool = False, **kw) -> float:
    r = _returns(series)
    if len(r) < 5:
        return np.nan
    v = float(np.percentile(r, 5))
    return v * np.sqrt(ANNUAL_FACTOR.get(freq, 252)) if annualize else v


def cvar_95(series: pd.Series, freq: str, annualize: bool = False, **kw) -> float:
    r = _returns(series)
    if len(r) < 5:
        return np.nan
    t = np.percentile(r, 5)
    c = float(r[r <= t].mean())
    return c * np.sqrt(ANNUAL_FACTOR.get(freq, 252)) if annualize else c


def skewness_var(series: pd.Series, freq: str, **kw) -> float:
    r = _returns(series)
    return float(r.skew()) if len(r) >= 3 else np.nan


def kurtosis_var(series: pd.Series, freq: str, **kw) -> float:
    r = _returns(series)
    return float(r.kurtosis()) if len(r) >= 4 else np.nan


# ======================================================================
# 基准相关指标
# ======================================================================

def _aligned_returns(s: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series] | None:
    r, br = _returns(s), _returns(b)
    c = r.index.intersection(br.index)
    return (r[c], br[c]) if len(c) >= 2 else None


def excess_return(series: pd.Series, freq: str, rf: float = 0.0,
                  benchmark: pd.Series | None = None) -> float:
    if benchmark is None:
        return np.nan
    s, b = annualized_return(series, freq), annualized_return(benchmark, freq)
    return float(s - b) if not np.isnan(s) and not np.isnan(b) else np.nan


def tracking_error(series: pd.Series, freq: str, rf: float = 0.0,
                   benchmark: pd.Series | None = None) -> float:
    if benchmark is None:
        return np.nan
    al = _aligned_returns(series, benchmark)
    if al is None:
        return np.nan
    r, b = al
    e = r - b
    return float(e.std(ddof=1) * np.sqrt(ANNUAL_FACTOR.get(freq, 252))) if len(e) >= 2 else np.nan


def information_ratio(series: pd.Series, freq: str, rf: float = 0.0,
                      benchmark: pd.Series | None = None) -> float:
    ex = excess_return(series, freq, rf, benchmark)
    te = tracking_error(series, freq, rf, benchmark)
    return float(ex / te) if not np.isnan(ex) and not np.isnan(te) and te != 0 else np.nan


def alpha(series: pd.Series, freq: str, rf: float = 0.0,
          benchmark: pd.Series | None = None) -> float:
    if benchmark is None:
        return np.nan
    al = _aligned_returns(series, benchmark)
    if al is None:
        return np.nan
    r, b = al
    cov = np.cov(r, b, ddof=1)
    if cov[1, 1] == 0:
        return np.nan
    bv = cov[0, 1] / cov[1, 1]
    factor = ANNUAL_FACTOR.get(freq, 252)
    pa = r.mean() - rf / factor - bv * b.mean()
    return float((1 + pa) ** factor - 1)


def beta(series: pd.Series, freq: str, rf: float = 0.0,
         benchmark: pd.Series | None = None) -> float:
    if benchmark is None:
        return np.nan
    al = _aligned_returns(series, benchmark)
    if al is None:
        return np.nan
    r, b = al
    cov = np.cov(r, b, ddof=1)
    return float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else np.nan


def up_capture(series: pd.Series, freq: str, rf: float = 0.0,
               benchmark: pd.Series | None = None) -> float:
    if benchmark is None:
        return np.nan
    al = _aligned_returns(series, benchmark)
    if al is None:
        return np.nan
    r, b = al
    up = b > 0
    return float(r[up].mean() / b[up].mean()) if up.sum() > 0 else np.nan


def down_capture(series: pd.Series, freq: str, rf: float = 0.0,
                 benchmark: pd.Series | None = None) -> float:
    if benchmark is None:
        return np.nan
    al = _aligned_returns(series, benchmark)
    if al is None:
        return np.nan
    r, b = al
    dn = b < 0
    return float(r[dn].mean() / b[dn].mean()) if dn.sum() > 0 else np.nan


# ======================================================================
# 胜率 / 盈亏比
# ======================================================================

def _resample_returns(series: pd.Series, target_freq: str) -> pd.Series:
    r = _returns(series)
    if len(r) == 0:
        return r
    rule = {"W": "W", "M": "M"}.get(target_freq)
    return (1 + r).resample(rule).prod() - 1 if rule else r


def win_rate(series: pd.Series, freq: str, rf: float = 0.0,
             target_freq: str | None = None, **kw) -> float:
    r = _resample_returns(series, target_freq) if target_freq else _returns(series)
    return float((r > 0).sum() / len(r)) if len(r) > 0 else np.nan


def profit_loss_ratio(series: pd.Series, freq: str, rf: float = 0.0,
                      target_freq: str | None = None, **kw) -> float:
    r = _resample_returns(series, target_freq) if target_freq else _returns(series)
    pos, neg = r[r > 0], r[r < 0]
    return float(pos.mean() / abs(neg.mean())) if len(pos) > 0 and len(neg) > 0 else np.nan


# ======================================================================
# 收益表 / 相关性
# ======================================================================

def annual_returns_table(series: pd.Series, freq: str) -> pd.Series:
    r = _returns(series)
    if len(r) == 0:
        return pd.Series(dtype=float)
    a = r.groupby(r.index.year).apply(lambda x: float(np.prod(1 + x) - 1))
    a.name = "年度收益率"
    return a


def period_returns_table(series: pd.Series, freq: str) -> pd.DataFrame:
    r = _returns(series)
    if len(r) == 0:
        return pd.DataFrame()
    df = r.to_frame("ret")
    df["year"] = df.index.year
    if freq == "W":
        df["week"] = df.index.isocalendar().week
        return df.pivot_table(values="ret", index="year", columns="week", aggfunc="sum")
    elif freq == "M":
        df["month"] = df.index.month
        return df.pivot_table(values="ret", index="year", columns="month", aggfunc="sum")
    else:
        df["month"] = df.index.month
        return df.pivot_table(values="ret", index="year", columns="month",
                              aggfunc=lambda x: float(np.prod(1 + x) - 1))


def correlation_matrix(returns_df: pd.DataFrame, freq: str | None = None,
                       obs_date: pd.Timestamp | None = None,
                       period: str | None = None,
                       calendar: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    df = returns_df.dropna(how="all")
    if period and period != "成立以来" and freq:
        nav_proxy = (1 + df.fillna(0)).cumprod().iloc[:, 0]
        sliced = slice_period(nav_proxy, freq, period, obs_date, calendar)
        df = df.loc[sliced.index.intersection(df.index)]
    return df.corr()


# ======================================================================
# 滚动指标
# ======================================================================

def _prepare_rolling(series: pd.Series, freq: str, window,
                     period: str | None, obs_date: pd.Timestamp | None,
                     calendar: pd.DatetimeIndex | None = None) -> tuple[pd.Series, int]:
    n = parse_window(window, freq)
    s = slice_period(series, freq, period, obs_date, calendar) if period else series
    return s, n


def rolling_return(series: pd.Series, freq: str, window,
                   period: str | None = None, obs_date: pd.Timestamp | None = None,
                   calendar: pd.DatetimeIndex | None = None) -> pd.Series:
    s, n = _prepare_rolling(series, freq, window, period, obs_date, calendar)
    r = _returns(s)
    return (1 + r).rolling(n).apply(np.prod, raw=True) - 1 if len(r) >= n else pd.Series(dtype=float)


def rolling_annualized_return(series: pd.Series, freq: str, window,
                              period: str | None = None, obs_date: pd.Timestamp | None = None,
                              calendar: pd.DatetimeIndex | None = None) -> pd.Series:
    s, n = _prepare_rolling(series, freq, window, period, obs_date, calendar)
    roll = rolling_return(s, freq, n)
    ny = n / ANNUAL_FACTOR.get(freq, 52)
    return (1 + roll) ** (1 / ny) - 1


def rolling_volatility(series: pd.Series, freq: str, window,
                       period: str | None = None, obs_date: pd.Timestamp | None = None,
                       calendar: pd.DatetimeIndex | None = None) -> pd.Series:
    s, n = _prepare_rolling(series, freq, window, period, obs_date, calendar)
    r = _returns(s)
    return r.rolling(n).std(ddof=1) * np.sqrt(ANNUAL_FACTOR.get(freq, 52)) if len(r) >= n else pd.Series(dtype=float)


def rolling_sharpe(series: pd.Series, freq: str, window, rf: float = 0.0,
                   period: str | None = None, obs_date: pd.Timestamp | None = None,
                   calendar: pd.DatetimeIndex | None = None) -> pd.Series:
    s, n = _prepare_rolling(series, freq, window, period, obs_date, calendar)
    rr = rolling_annualized_return(s, freq, n)
    rv = rolling_volatility(s, freq, n)
    return (rr - rf) / rv


def rolling_max_drawdown(series: pd.Series, freq: str, window,
                         period: str | None = None, obs_date: pd.Timestamp | None = None,
                         calendar: pd.DatetimeIndex | None = None) -> pd.Series:
    s, n = _prepare_rolling(series, freq, window, period, obs_date, calendar)
    vals = s.values
    n_pts = len(vals)
    result = np.full(n_pts, np.nan)
    for i in range(n - 1, n_pts):
        sub = vals[i - n + 1:i + 1]
        result[i] = float(np.min(sub / np.maximum.accumulate(sub) - 1))
    return pd.Series(result, index=s.index)


def rolling_correlation(returns_df: pd.DataFrame, freq: str, window,
                        period: str | None = None, obs_date: pd.Timestamp | None = None,
                        calendar: pd.DatetimeIndex | None = None) -> pd.Series:
    if period and freq:
        nav_proxy = (1 + returns_df.fillna(0)).cumprod().iloc[:, 0]
        sliced = slice_period(nav_proxy, freq, period, obs_date, calendar)
        df = returns_df.loc[sliced.index.intersection(returns_df.index)]
    else:
        df = returns_df

    n = parse_window(window, freq)
    if df.shape[1] < 2 or len(df) < n:
        return pd.Series(dtype=float)

    avg = pd.Series(np.nan, index=df.index)
    for i in range(n - 1, len(df)):
        sub = df.iloc[i - n + 1:i + 1].dropna(axis=1, how="any")
        if sub.shape[1] >= 2:
            triu = np.triu(sub.corr().values, k=1)
            mask = ~np.isnan(triu)
            if mask.sum() > 0:
                avg.iloc[i] = float(np.nansum(triu) / mask.sum())
    return avg


# ======================================================================
# 持有期收益分布
# ======================================================================

def holding_return_distribution(series: pd.Series, freq: str, hold_periods: int,
                                period: str | None = None,
                                obs_date: pd.Timestamp | None = None,
                                calendar: pd.DatetimeIndex | None = None) -> dict:
    s = slice_period(series, freq, period, obs_date, calendar) if period else series
    hr = (s.shift(-hold_periods) / s - 1).dropna()
    if hr.empty:
        return {}
    return {
        "均值": float(hr.mean()), "中位数": float(hr.median()),
        "最小值": float(hr.min()), "最大值": float(hr.max()),
        "25分位": float(hr.quantile(0.25)), "75分位": float(hr.quantile(0.75)),
        "正收益比例": float((hr > 0).sum() / len(hr)), "序列": hr,
    }


# ======================================================================
# 指标注册表  {(分类, 指标名): compute_fn}
# ======================================================================

METRIC_REGISTRY: dict[tuple[str, str], callable] = {
    ("收益",   "区间收益率"):          lambda s, f, **kw: cumulative_return(s),
    ("收益",   "年化收益率"):          lambda s, f, **kw: annualized_return(s, f),
    ("收益",   "超额收益(年化)"):      lambda s, f, benchmark=None, **kw: excess_return(s, f, benchmark=benchmark),
    ("风险",   "最大回撤"):            lambda s, f, **kw: max_drawdown(s),
    ("风险",   "最大回撤修复期数"):     lambda s, f, **kw: max_drawdown_recovery_periods(s),
    ("风险",   "最长回撤修复期数"):     lambda s, f, **kw: longest_drawdown_recovery_periods(s),
    ("风险",   "最长不创新高期数"):     lambda s, f, **kw: longest_no_new_high_periods(s),
    ("风险",   "不创新高比例"):        lambda s, f, **kw: no_new_high_ratio(s),
    ("风险",   "年化波动率"):          lambda s, f, **kw: annualized_volatility(s, f),
    ("风险",   "年化下行波动"):        lambda s, f, **kw: annualized_downside_vol(s, f),
    ("风险",   "跟踪误差"):            lambda s, f, benchmark=None, **kw: tracking_error(s, f, benchmark=benchmark),
    ("风险",   "VaR(95%)"):          lambda s, f, **kw: var_95(s, f),
    ("风险",   "CVaR(95%)"):         lambda s, f, **kw: cvar_95(s, f),
    ("风险",   "偏度"):               lambda s, f, **kw: skewness_var(s, f),
    ("风险",   "峰度"):               lambda s, f, **kw: kurtosis_var(s, f),
    ("风险调整", "夏普比率"):          lambda s, f, rf=0.0, **kw: sharpe_ratio(s, f, rf=rf),
    ("风险调整", "索提诺比率"):        lambda s, f, rf=0.0, **kw: sortino_ratio(s, f, rf=rf),
    ("风险调整", "卡玛比率"):          lambda s, f, rf=0.0, **kw: calmar_ratio(s, f, rf=rf),
    ("风险调整", "信息比率"):          lambda s, f, benchmark=None, **kw: information_ratio(s, f, benchmark=benchmark),
    ("基准归因", "Alpha(年化)"):      lambda s, f, rf=0.0, benchmark=None, **kw: alpha(s, f, rf=rf, benchmark=benchmark),
    ("基准归因", "Beta"):             lambda s, f, benchmark=None, **kw: beta(s, f, benchmark=benchmark),
    ("基准归因", "上行捕获率"):        lambda s, f, benchmark=None, **kw: up_capture(s, f, benchmark=benchmark),
    ("基准归因", "下行捕获率"):        lambda s, f, benchmark=None, **kw: down_capture(s, f, benchmark=benchmark),
    ("其他",   "胜率"):               lambda s, f, **kw: win_rate(s, f),
    ("其他",   "盈亏比"):             lambda s, f, **kw: profit_loss_ratio(s, f),
}

METRIC_CATEGORIES: dict[str, list[str]] = {}
for (_cat, _name) in METRIC_REGISTRY:
    METRIC_CATEGORIES.setdefault(_cat, []).append(_name)


# ======================================================================
# PerformanceAnalyzer
# ======================================================================

class PerformanceAnalyzer:
    """
    一站式业绩分析。

    Parameters
    ----------
    nav_dict : dict[str, pd.Series]
        name → 净值序列。第一个为主体（组合）。
    freq : str  "D" / "W" / "M"
    rf : float  年化无风险利率，默认 0
    benchmarks : dict[str, pd.Series] | None  各实体基准净值
    portfolio_benchmark : pd.Series | None  组合基准
    """

    def __init__(self, nav_dict: dict[str, pd.Series], freq: str, rf: float = 0.0,
                 benchmarks: dict[str, pd.Series] | None = None,
                 portfolio_benchmark: pd.Series | None = None):
        self.nav_dict = nav_dict
        self.freq = freq
        self.rf = rf
        self.benchmarks = benchmarks or {}
        self.portfolio_benchmark = portfolio_benchmark
        self.names = list(nav_dict.keys())

        if freq in ("W", "M"):
            all_dates = set()
            for s in nav_dict.values():
                all_dates.update(s.index)
            for s in self.benchmarks.values():
                all_dates.update(s.index)
            if portfolio_benchmark is not None:
                all_dates.update(portfolio_benchmark.index)
            self._calendar = pd.DatetimeIndex(sorted(all_dates))
        else:
            self._calendar = None

    # ------------------------------------------------------------------
    # 基准
    # ------------------------------------------------------------------

    def _get_benchmark(self, entity_name: str) -> pd.Series | None:
        if entity_name == self.names[0] and self.portfolio_benchmark is not None:
            return self.portfolio_benchmark
        return self.benchmarks.get(entity_name)

    def _slice_benchmark(self, entity_name: str, period: str,
                         obs_date: pd.Timestamp | None) -> pd.Series | None:
        bm = self._get_benchmark(entity_name)
        if bm is None:
            return None
        try:
            return slice_period(bm, self.freq, period, obs_date, self._calendar)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # 静态指标
    # ------------------------------------------------------------------

    def _compute_metrics(self, series: pd.Series, period: str,
                         obs_date: pd.Timestamp | None = None,
                         metrics_filter: list[str] | None = None,
                         benchmark: pd.Series | None = None) -> dict:
        try:
            s = slice_period(series, self.freq, period, obs_date, self._calendar)
        except ValueError:
            return _nan_row(metrics_filter)
        if len(s) < 2:
            return _nan_row(metrics_filter)

        # D 频覆盖率校验（风险类 / 风险调整类 / 基准归因类需要足够样本）
        risk_ok = True
        if self.freq == "D" and period in PERIOD_CALENDAR_DAYS:
            expected = max(1, PERIOD_CALENDAR_DAYS[period] * 253 / 365)
            if len(s) < DAILY_MIN_COVERAGE * expected:
                risk_ok = False

        result = {}
        for (cat, name), fn in METRIC_REGISTRY.items():
            if metrics_filter and name not in metrics_filter:
                continue
            if cat in ("风险", "风险调整", "基准归因") and not risk_ok:
                result[name] = np.nan
                continue
            try:
                result[name] = fn(s, self.freq, rf=self.rf, benchmark=benchmark)
            except Exception:
                result[name] = np.nan
        return result

    def metrics_table(self, period: str, obs_date: pd.Timestamp | None = None,
                      metrics_filter: list[str] | None = None) -> pd.DataFrame:
        """全部实体 × 单区间指标表（子基金横向对比）。"""
        rows = {}
        for name, nav in self.nav_dict.items():
            bm = self._slice_benchmark(name, period, obs_date)
            rows[name] = self._compute_metrics(nav, period, obs_date, metrics_filter, bm)
        return pd.DataFrame(rows).T

    def metrics_multi_period(self, periods: list[str] | None = None,
                             obs_date: pd.Timestamp | None = None,
                             metrics_filter: list[str] | None = None) -> pd.DataFrame:
        """主体多区间指标表。行=period, 列=metric。"""
        if periods is None:
            periods = ALL_PERIODS
        primary = self.names[0]
        nav = self.nav_dict[primary]
        rows = {}
        for p in periods:
            bm = self._slice_benchmark(primary, p, obs_date)
            rows[p] = self._compute_metrics(nav, p, obs_date, metrics_filter, bm)
        return pd.DataFrame(rows).T

    def all_funds_multi_period(self, periods: list[str] | None = None,
                               obs_date: pd.Timestamp | None = None,
                               metrics_filter: list[str] | None = None) -> pd.DataFrame:
        """全部实体 × 多区间。MultiIndex columns: (entity, metric), 行=period。"""
        if periods is None:
            periods = ALL_PERIODS
        frames = {}
        for name, nav in self.nav_dict.items():
            rows = {}
            for p in periods:
                bm = self._slice_benchmark(name, p, obs_date)
                rows[p] = self._compute_metrics(nav, p, obs_date, metrics_filter, bm)
            frames[name] = pd.DataFrame(rows).T
        return pd.concat(frames, axis=1, keys=frames.keys())

    # ------------------------------------------------------------------
    # 子基金对比
    # ------------------------------------------------------------------

    def get_comparison_range(
        self, mode: str = "共同区间", obs_date: pd.Timestamp | None = None,
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """
        确定子基金对比的起止日期。
        mode: "共同区间" / "全部区间" / 标准区间 / "自定义:YYYY-MM-DD:YYYY-MM-DD"
        """
        return get_comparison_date_range(
            self.nav_dict, mode, self.freq, obs_date, self._calendar,
        )

    def fund_comparison_returns(
        self, mode: str = "共同区间", obs_date: pd.Timestamp | None = None,
    ) -> pd.Series:
        """子基金在对比区间内的累计收益率。fund_name → 收益率。"""
        return fund_comparison_returns(
            self.nav_dict, mode, self.freq, obs_date, self._calendar,
        )

    def fund_comparison_metrics(
        self, mode: str = "共同区间", obs_date: pd.Timestamp | None = None,
        metrics_filter: list[str] | None = None,
    ) -> pd.DataFrame:
        """子基金在对比区间内的全部指标。fund_name × metric。"""
        try:
            start, end = self.get_comparison_range(mode, obs_date)
        except ValueError:
            return pd.DataFrame([_nan_row(metrics_filter)], index=self.names)

        period_str = f"{start.strftime('%Y-%m-%d')}:{end.strftime('%Y-%m-%d')}"
        return self.metrics_table(period_str, obs_date, metrics_filter)

    # ------------------------------------------------------------------
    # 收益表 / 回撤 / 相关性
    # ------------------------------------------------------------------

    def annual_returns(self, name: str | None = None) -> pd.Series:
        if name is None:
            name = self.names[0]
        return annual_returns_table(self.nav_dict[name], self.freq)

    def period_returns_pivot(self, name: str | None = None) -> pd.DataFrame:
        if name is None:
            name = self.names[0]
        return period_returns_table(self.nav_dict[name], self.freq)

    def drawdown_curves(self) -> dict[str, pd.Series]:
        return {name: drawdown_series(nav) for name, nav in self.nav_dict.items()}

    def correlation(self, returns_df: pd.DataFrame,
                    obs_date: pd.Timestamp | None = None,
                    period: str | None = None) -> pd.DataFrame:
        return correlation_matrix(returns_df, self.freq, obs_date, period, self._calendar)

    # ------------------------------------------------------------------
    # 滚动指标
    # ------------------------------------------------------------------

    def rolling_return(self, name: str, window, period: str | None = None,
                       obs_date: pd.Timestamp | None = None) -> pd.Series:
        return rolling_return(self.nav_dict[name], self.freq, window,
                              period, obs_date, self._calendar)

    def rolling_annualized_return(self, name: str, window, period: str | None = None,
                                  obs_date: pd.Timestamp | None = None) -> pd.Series:
        return rolling_annualized_return(self.nav_dict[name], self.freq, window,
                                         period, obs_date, self._calendar)

    def rolling_volatility(self, name: str, window, period: str | None = None,
                           obs_date: pd.Timestamp | None = None) -> pd.Series:
        return rolling_volatility(self.nav_dict[name], self.freq, window,
                                  period, obs_date, self._calendar)

    def rolling_sharpe(self, name: str, window, period: str | None = None,
                       obs_date: pd.Timestamp | None = None) -> pd.Series:
        return rolling_sharpe(self.nav_dict[name], self.freq, window, self.rf,
                              period, obs_date, self._calendar)

    def rolling_max_drawdown(self, name: str, window, period: str | None = None,
                             obs_date: pd.Timestamp | None = None) -> pd.Series:
        return rolling_max_drawdown(self.nav_dict[name], self.freq, window,
                                    period, obs_date, self._calendar)

    def rolling_correlation(self, returns_df: pd.DataFrame, window,
                            period: str | None = None,
                            obs_date: pd.Timestamp | None = None) -> pd.Series:
        return rolling_correlation(returns_df, self.freq, window,
                                   period, obs_date, self._calendar)

    # ------------------------------------------------------------------
    # 持有期收益分布
    # ------------------------------------------------------------------

    def holding_return_distribution(self, name: str, hold_periods: int,
                                    period: str | None = None,
                                    obs_date: pd.Timestamp | None = None) -> dict:
        return holding_return_distribution(
            self.nav_dict[name], self.freq, hold_periods,
            period, obs_date, self._calendar,
        )
