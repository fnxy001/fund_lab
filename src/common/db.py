"""数据库读写接口

通过 SQLAlchemy 连接 MySQL 8.0，提供与文件模式（utils.py）一致的 DataFrame 输出。
换环境只需改 .env 中的数据库连接信息。

表结构
------
holdings   : fund_name, trade_date, weight
nav        : fund_name, trade_date, unit_nav, acc_nav
benchmark  : benchmark_name, trade_date, nav
"""

from sqlalchemy import create_engine, text
import pandas as pd
from config import DB_URL, BENCHMARK_NAME


class DB:
    """MySQL 数据库连接（自动读取 .env 配置）。"""

    def __init__(self, db_url: str | None = None):
        self.db_url = db_url or DB_URL
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = create_engine(self.db_url)
        return self._engine

    def test_connection(self) -> bool:
        """测试数据库是否能连通。"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            print(f"数据库连接失败: {e}")
            return False

    def query(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        """执行 SQL 查询，返回 DataFrame。"""
        with self.engine.connect() as conn:
            return pd.read_sql_query(text(sql), conn, params=params or {})

    # ------------------------------------------------------------------
    # 持仓数据
    # ------------------------------------------------------------------

    def load_holdings(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        fund_names: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        加载持仓数据。
        返回 DataFrame: [fund_name, trade_date, weight]
        """
        sql = "SELECT fund_name, trade_date, weight FROM holdings WHERE 1=1"
        params = {}
        if start_date:
            sql += " AND trade_date >= :start_date"
            params["start_date"] = start_date
        if end_date:
            sql += " AND trade_date <= :end_date"
            params["end_date"] = end_date
        if fund_names:
            sql += " AND fund_name IN :fund_names"
            params["fund_names"] = tuple(fund_names)

        df = self.query(sql, params)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df.sort_values(["fund_name", "trade_date"]).reset_index(drop=True)

    # ------------------------------------------------------------------
    # 净值数据
    # ------------------------------------------------------------------

    def load_nav(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        fund_names: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        加载净值数据。
        返回 DataFrame: [fund_name, trade_date, unit_nav, acc_nav]
        """
        sql = "SELECT fund_name, trade_date, unit_nav, acc_nav FROM nav WHERE 1=1"
        params = {}
        if start_date:
            sql += " AND trade_date >= :start_date"
            params["start_date"] = start_date
        if end_date:
            sql += " AND trade_date <= :end_date"
            params["end_date"] = end_date
        if fund_names:
            sql += " AND fund_name IN :fund_names"
            params["fund_names"] = tuple(fund_names)

        df = self.query(sql, params)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values(["fund_name", "trade_date"]).reset_index(drop=True)
        return df

    # ------------------------------------------------------------------
    # 基准数据
    # ------------------------------------------------------------------

    def load_benchmark(
        self,
        benchmark_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """
        加载基准净值数据。
        返回 DataFrame: [trade_date, nav]
        """
        name = benchmark_name or BENCHMARK_NAME
        sql = "SELECT trade_date, nav FROM benchmark WHERE benchmark_name = :name"
        params = {"name": name}
        if start_date:
            sql += " AND trade_date >= :start_date"
            params["start_date"] = start_date
        if end_date:
            sql += " AND trade_date <= :end_date"
            params["end_date"] = end_date

        df = self.query(sql, params)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    # ------------------------------------------------------------------
    # 数据写入
    # ------------------------------------------------------------------

    def write_table(self, df: pd.DataFrame, table: str, if_exists: str = "replace"):
        """将 DataFrame 写入数据库表。"""
        df.to_sql(table, self.engine, if_exists=if_exists, index=False)

    # ------------------------------------------------------------------
    # 表结构初始化
    # ------------------------------------------------------------------

    def init_tables(self):
        """创建 fund_lab 所需的表结构（如果不存在）。"""
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS holdings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    fund_name VARCHAR(100) NOT NULL,
                    trade_date DATE NOT NULL,
                    weight DOUBLE NOT NULL,
                    INDEX idx_fund_date (fund_name, trade_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS nav (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    fund_name VARCHAR(100) NOT NULL,
                    trade_date DATE NOT NULL,
                    unit_nav DOUBLE NOT NULL,
                    acc_nav DOUBLE NOT NULL,
                    INDEX idx_fund_date (fund_name, trade_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS benchmark (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    benchmark_name VARCHAR(100) NOT NULL,
                    trade_date DATE NOT NULL,
                    nav DOUBLE NOT NULL,
                    INDEX idx_benchmark_date (benchmark_name, trade_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.commit()
        print("表结构初始化完成：holdings, nav, benchmark")
