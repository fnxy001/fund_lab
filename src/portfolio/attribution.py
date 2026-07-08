"""业绩归因

收益归因（几何累积，严格可加）
-------------------------------
每期贡献 = 上期组合净值 × 期初权重 × 本期基金收益
  dc_i[t] = nav[t-1] × w_i[t-1] × r_i[t]
  C_i = Σ dc_i[t],  Σ C_i = nav[T] - nav[0] = 组合总收益 （无需缩放）

风险归因（贡献序列波动 + 风险分散）
-----------------------------------
  - 组合年化波动 = std(r_p) × √annual_factor
  - 产品 i 波动贡献 = std(dc_i 序列) × √annual_factor
  - 风险分散 = 组合年化波动 - Σ 各产品波动贡献
  → 协方差交叉项归入"风险分散"

频率自适应：年化系数 √252(D) / √52(W) / √12(M)
D 频风险归因需要覆盖率 ≥ 50%
"""

import pandas as pd
import numpy as np
from config import ANNUAL_FACTOR, PERIOD_CALENDAR_DAYS, DAILY_MIN_COVERAGE
from src.portfolio.performance import slice_period


class AttributionAnalyzer:
    """
    业绩归因分析。

    Parameters
    ----------
    portfolio_result : dict
        PortfolioEngine.calc() 输出。
    freq : str  "D" / "W" / "M"
    calendar : pd.DatetimeIndex | None
    """

    def __init__(
        self,
        portfolio_result: dict,
        freq: str,
        calendar: pd.DatetimeIndex | None = None,
    ):
        self.portfolio_nav = portfolio_result["portfolio_nav"]
        self.weights_close = portfolio_result["weights_close"]
        self.fund_returns = portfolio_result["fund_returns"]
        self.fund_nav = portfolio_result["fund_nav"]
        self.freq = freq
        self.calendar = calendar
        self._factor = ANNUAL_FACTOR.get(freq, 52)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _get_period_data(
        self, period: str, obs_date: pd.Timestamp | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series] | None:
        """
        Returns (w_for, r, r_p, nav) 或 None。

        w_for[t] = t 期期初权重 (= w_close[t-1]，首期用首期收盘)
        r[t]     = t 期各基金收益率
        r_p[t]   = t 期组合收益率 = Σ(w_for[t] × r[t])
        nav[t]   = t 期组合净值
        """
        try:
            nav_sliced = slice_period(
                self.portfolio_nav, self.freq, period, obs_date, self.calendar,
            )
        except ValueError:
            return None

        start, end = nav_sliced.index[0], nav_sliced.index[-1]
        w = self.weights_close.loc[start:end]
        r = self.fund_returns.loc[start:end]

        common = w.index.intersection(r.index)
        if len(common) < 1:
            return None

        w = w.loc[common]
        r = r.loc[common]

        w_for = w.shift(1)
        w_for.iloc[0] = w.iloc[0]

        r_p = (w_for * r).sum(axis=1)
        nav = self.portfolio_nav.loc[common]

        return w_for, r, r_p, nav

    def _check_risk_coverage(self, data_len: int, period: str) -> bool:
        """D 频风险归因覆盖率校验。W/M 不在此校验（日历锚定已保证）。"""
        if self.freq != "D":
            return True
        cal_days = PERIOD_CALENDAR_DAYS.get(period)
        if cal_days is None:
            return True
        expected = max(1, cal_days * 253 / 365)
        return data_len >= DAILY_MIN_COVERAGE * expected

    # ------------------------------------------------------------------
    # 收益归因
    # ------------------------------------------------------------------

    def return_contribution(
        self,
        period: str,
        obs_date: pd.Timestamp | None = None,
    ) -> dict:
        """
        收益贡献分解（几何累积，不需要覆盖率校验）。

        Returns
        -------
        dict
            contributions     : pd.Series  各子基金收益贡献
            fund_returns       : pd.Series  各子基金区间收益率（几何）
            weights_start      : pd.Series  期初权重
            portfolio_return   : float      组合区间总收益
            contrib_series     : pd.DataFrame  逐期贡献 (date × fund)
        """
        pd_data = self._get_period_data(period, obs_date)
        if pd_data is None:
            funds = self.fund_returns.columns
            return {
                "contributions": pd.Series(np.nan, index=funds),
                "fund_returns": pd.Series(np.nan, index=funds),
                "weights_start": pd.Series(np.nan, index=funds),
                "portfolio_return": np.nan,
                "contrib_series": pd.DataFrame(),
            }

        w_for, r, r_p, nav = pd_data

        # 上期组合净值
        nav_prev = nav.shift(1)
        nav_prev.iloc[0] = 1.0

        # 每期贡献 = nav[t-1] × w[t-1] × r[t]
        contrib_series = nav_prev.values[:, None] * w_for * r

        contributions = contrib_series.sum()
        port_ret = nav.iloc[-1] - nav.iloc[0]
        fund_rets = (1 + r).prod() - 1
        w_start = w_for.iloc[0]

        return {
            "contributions": contributions,
            "fund_returns": fund_rets,
            "weights_start": w_start,
            "portfolio_return": port_ret,
            "contrib_series": contrib_series,
        }

    def return_attribution_table(
        self,
        period: str,
        obs_date: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """收益归因表。"""
        res = self.return_contribution(period, obs_date)
        total = res["portfolio_return"]

        df = pd.DataFrame({
            "期初权重": res["weights_start"],
            "区间收益率": res["fund_returns"],
            "收益贡献": res["contributions"],
        })
        if abs(total) > 1e-12:
            df["贡献占比(%)"] = res["contributions"] / total * 100
        else:
            df["贡献占比(%)"] = 0.0
        df.loc["合计"] = [
            res["weights_start"].sum(),
            total,
            res["contributions"].sum(),
            100.0 if abs(total) > 1e-12 else 0.0,
        ]
        df.index.name = "fund_name"
        return df

    # ------------------------------------------------------------------
    # 风险归因
    # ------------------------------------------------------------------

    def risk_contribution(
        self,
        period: str,
        obs_date: pd.Timestamp | None = None,
    ) -> dict:
        """
        风险归因（贡献序列波动法）。

        - 组合年化波动 = std(r_p) × √annual_factor
        - 产品 i 波动贡献 = std(dc_i) × √annual_factor
        - 风险分散 = 组合年化波动 - Σ 各产品波动贡献
        - D 频需要覆盖率校验，不足则返回 NaN
        """
        pd_data = self._get_period_data(period, obs_date)
        if pd_data is None:
            funds = self.fund_returns.columns
            return {
                "portfolio_vol": np.nan,
                "fund_vol_contrib": pd.Series(np.nan, index=funds),
                "diversification": np.nan,
                "contrib_series": pd.DataFrame(),
            }

        w_for, r, r_p, nav = pd_data

        # 覆盖率校验
        if not self._check_risk_coverage(len(r), period):
            funds = self.fund_returns.columns
            return {
                "portfolio_vol": np.nan,
                "fund_vol_contrib": pd.Series(np.nan, index=funds),
                "diversification": np.nan,
                "contrib_series": pd.DataFrame(),
            }

        # 收益贡献序列
        nav_prev = nav.shift(1)
        nav_prev.iloc[0] = 1.0
        contrib_series = nav_prev.values[:, None] * w_for * r

        port_vol = float(r_p.std(ddof=1) * np.sqrt(self._factor))
        fund_vol = contrib_series.std(ddof=1) * np.sqrt(self._factor)
        divers = port_vol - fund_vol.sum()

        return {
            "portfolio_vol": port_vol,
            "fund_vol_contrib": fund_vol,
            "diversification": divers,
            "contrib_series": contrib_series,
        }

    def risk_attribution_table(
        self,
        period: str,
        obs_date: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """风险归因表。"""
        res = self.risk_contribution(period, obs_date)
        port_vol = res["portfolio_vol"]

        df = pd.DataFrame({"波动贡献": res["fund_vol_contrib"]})
        df.loc["风险分散"] = res["diversification"]
        df.loc["合计"] = port_vol

        if abs(port_vol) > 1e-12:
            df["占比(%)"] = df["波动贡献"] / port_vol * 100
        else:
            df["占比(%)"] = np.nan

        df.index.name = "fund_name"
        return df

    # ------------------------------------------------------------------
    # 综合归因表
    # ------------------------------------------------------------------

    def combined_attribution(
        self,
        period: str,
        obs_date: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """收益 + 风险归因合并表。"""
        ret = self.return_attribution_table(period, obs_date)
        risk = self.risk_attribution_table(period, obs_date)

        for idx in risk.index:
            if idx in ret.index:
                ret.loc[idx, "波动贡献"] = risk.loc[idx, "波动贡献"]
                if "占比(%)" in risk.columns:
                    ret.loc[idx, "波动占比(%)"] = risk.loc[idx, "占比(%)"]
            else:
                ret.loc[idx, "波动贡献"] = risk.loc[idx, "波动贡献"]
                if "占比(%)" in risk.columns:
                    ret.loc[idx, "波动占比(%)"] = risk.loc[idx, "占比(%)"]

        return ret
