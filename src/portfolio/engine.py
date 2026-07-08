"""组合净值计算

频率无关：收益率按数据点之间的 pct_change 计算，净值数据可以是
日频、周频、月频或任意不规则频率，计算逻辑一致。

扩展架构
--------
所有引擎继承 PortfolioEngine，只需实现 _build_weight_matrix()。
基类 calc() 统一处理：收益率计算 → 组合净值累积 → 子基金净值。

已实现:
  HoldingsEngine         — 历史目标持仓权重 + 不定期调仓

后续可扩展:
  StrategicWeightEngine — 固定目标权重 + 定期再平衡（月度/季度/半年/年度）
  RiskParityEngine      — 风险平价模型 + 定期再平衡
  TransactionEngine     — 历史买卖记录（交易日、资产、交易金额）→ 重构持仓
  DailyPositionEngine   — 日度估值表（日度持仓记录）→ 直接读取权重
"""

import pandas as pd
import numpy as np


class PortfolioEngine:
    """
    组合净值计算引擎（基类）。

    计算流程（频率无关）
    -------------------
    1. 子类实现 _build_weight_matrix()，返回每个数据点收盘后的权重 w_close
    2. 组合收益率[t] = Σ(w_close[t-1] × fund_return[t])
       即：区间 t 的收益使用区间起点（上期收盘）的权重
    3. 组合净值 = 初始净值 × cumprod(1 + 组合收益率)

    Parameters
    ----------
    nav : pd.DataFrame
        已处理净值 [fund_name, trade_date, adj_nav]，频率已统一。
    initial_nav : float
        组合初始净值，默认 1.0。
    """

    def __init__(self, nav: pd.DataFrame, initial_nav: float = 1.0):
        self.nav = nav
        self.initial_nav = initial_nav

        self._nav_pivot: pd.DataFrame | None = None
        self._fund_returns: pd.DataFrame | None = None
        self._all_dates: pd.DatetimeIndex | None = None
        self._all_funds: list | None = None

    def _build_weight_matrix(self) -> pd.DataFrame:
        """
        子类实现。
        返回 w_close: index=trade_date, columns=fund_name, values=收盘权重。
        """
        raise NotImplementedError

    def calc(self) -> dict:
        """
        Returns
        -------
        dict
            portfolio_nav  : pd.Series  组合净值时间序列
            weights_close  : pd.DataFrame 各时点收盘权重矩阵
            fund_returns   : pd.DataFrame 子基金区间收益率矩阵
            fund_nav       : pd.DataFrame 子基金净值矩阵（从 1 起算）
        """
        self._nav_pivot = self.nav.pivot(
            index="trade_date", columns="fund_name", values="adj_nav"
        )
        self._all_dates = self._nav_pivot.index
        self._all_funds = list(self._nav_pivot.columns)
        self._fund_returns = self._nav_pivot.pct_change()

        w_close = self._build_weight_matrix()

        common = self._all_dates.intersection(w_close.index)
        w_close = w_close.loc[common]
        fund_returns = self._fund_returns.loc[common]

        w_for_return = w_close.shift(1)
        first_date = common[0]
        w_for_return.loc[first_date] = w_close.loc[first_date]

        port_return = (w_for_return * fund_returns).sum(axis=1)
        port_return.iloc[0] = 0.0

        port_nav = self.initial_nav * (1 + port_return).cumprod()
        port_nav.name = "portfolio"

        fund_nav = (1 + fund_returns.fillna(0)).cumprod()

        return {
            "portfolio_nav": port_nav,
            "weights_close": w_close,
            "fund_returns": fund_returns,
            "fund_nav": fund_nav,
        }


# ======================================================================
# HoldingsEngine: 历史目标持仓权重 + 不定期调仓
# ======================================================================

class HoldingsEngine(PortfolioEngine):
    """
    根据历史目标持仓权重计算组合净值。

    调仓逻辑
    -------
    - 调仓日当天收益使用旧权重（自然漂移后的权重），收盘后切换为目标权重
    - 下一期起使用新目标权重，之后继续自然漂移直到下一次调仓
    - 若调仓日不在净值数据时点中，向后找最近数据点作为实际再平衡时点
    """

    def __init__(
        self,
        nav: pd.DataFrame,
        holdings: pd.DataFrame,
        initial_nav: float = 1.0,
    ):
        super().__init__(nav, initial_nav)
        self.holdings = holdings

    def _build_weight_matrix(self) -> pd.DataFrame:
        holdings = self.holdings
        all_dates = self._all_dates
        all_funds = self._all_funds
        fund_returns = self._fund_returns

        raw_dates = sorted(holdings["trade_date"].unique())
        target_raw: dict[pd.Timestamp, pd.Series] = {}
        for d in raw_dates:
            h = holdings[holdings["trade_date"] == d]
            tw = pd.Series(0.0, index=all_funds)
            for _, row in h.iterrows():
                if row["fund_name"] in tw.index:
                    tw[row["fund_name"]] = row["weight"]
            target_raw[d] = tw

        start_date = min(target_raw.keys())

        # 调仓日映射到净值数据中最近的实际时点（向后取）
        target: dict[pd.Timestamp, pd.Series] = {}
        for rd, tw in target_raw.items():
            candidates = all_dates[all_dates >= rd]
            if len(candidates) > 0:
                target[candidates[0]] = tw

        w_close = pd.DataFrame(0.0, index=all_dates, columns=all_funds)
        prev_w: pd.Series | None = None

        for date in all_dates:
            if date < start_date:
                continue

            if prev_w is None:
                prev_w = target.get(date, pd.Series(0.0, index=all_funds))
                w_close.loc[date] = prev_w
                continue

            # 旧权重随区间涨跌漂移
            if date in fund_returns.index:
                r = fund_returns.loc[date].fillna(0.0)
                drifted = prev_w * (1 + r)
                s = drifted.sum()
                drifted = drifted / s if s > 0 else prev_w
            else:
                drifted = prev_w

            if date in target:
                w_close.loc[date] = target[date]
            else:
                w_close.loc[date] = drifted

            prev_w = w_close.loc[date]

        return w_close


# ----------------------------------------------------------------------
# 后续扩展引擎（骨架）
# ----------------------------------------------------------------------

# class StrategicWeightEngine(PortfolioEngine):
#     """固定目标权重 + 定期再平衡（M/Q/SA/A）"""
#     def __init__(self, nav, target_weights, rebalance_freq="M"):
#         ...
#     def _build_weight_matrix(self): ...

# class RiskParityEngine(PortfolioEngine):
#     """风险平价模型 + 定期再平衡，使用滚动协方差估计"""
#     def __init__(self, nav, rebalance_freq="M", lookback=52):
#         ...
#     def _build_weight_matrix(self): ...

# class TransactionEngine(PortfolioEngine):
#     """历史买卖记录（trade_date, fund_name, amount）→ 重构持仓权重"""
#     def __init__(self, nav, transactions, initial_cash):
#         ...
#     def _build_weight_matrix(self): ...

# class DailyPositionEngine(PortfolioEngine):
#     """日度估值表 → 直接读取每日持仓权重"""
#     def __init__(self, nav, daily_positions):
#         ...
#     def _build_weight_matrix(self): ...


# ======================================================================
# 快捷入口
# ======================================================================

def calc_portfolio_from_holdings(
    holdings: pd.DataFrame,
    nav: pd.DataFrame,
    initial_nav: float = 1.0,
) -> dict:
    """根据历史持仓计算组合净值。"""
    engine = HoldingsEngine(nav, holdings, initial_nav)
    return engine.calc()
