"""事件行数据源:文件(xlsx/csv)主路径 + SQL 直连接口(内网填连接串)。

设计约束:
- 行以 ``dict`` 交付,键沿用原始列名(含 pandas 对重名列自动加的 ``.1`` 后缀),
  下游 ``原始`` 字段无损保留;取值统一做 NaN→None、Timestamp→ISO 字符串,
  以便 JSON 序列化与 LLM 阅读。
- SQL 与文件走同一 ``iter_rows`` 契约,Stage 1 不关心数据从哪来。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Protocol


def _clean_value(v: Any) -> Any:
    """NaN→None,pandas/py datetime→ISO 字符串,其余原样。"""
    # 延迟导入,避免非文件路径也强依赖 pandas
    try:
        import pandas as pd  # type: ignore

        if v is None:
            return None
        if isinstance(v, float) and pd.isna(v):
            return None
        if v is pd.NaT:
            return None
        if isinstance(v, pd.Timestamp):
            return None if pd.isna(v) else v.isoformat()
    except ImportError:
        if v is None:
            return None
    if hasattr(v, "isoformat"):  # datetime/date
        try:
            return v.isoformat()
        except Exception:
            return v
    return v


def _clean_row(row: dict) -> dict:
    return {k: _clean_value(v) for k, v in row.items()}


class RowSource(Protocol):
    def iter_rows(self) -> Iterable[dict]:
        ...


class FileSource:
    """从 xlsx / csv 导出文件读事件行(当前验证主路径)。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def iter_rows(self) -> Iterator[dict]:
        import pandas as pd  # type: ignore

        suffix = self.path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            df = pd.read_excel(self.path)
        elif suffix == ".csv":
            df = pd.read_csv(self.path)
        else:
            raise ValueError(f"不支持的文件类型: {suffix}(仅 .xlsx/.xls/.csv)")
        # pandas 读入的自增无名列去掉,不污染 原始
        df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
        for _, row in df.iterrows():
            yield _clean_row(row.to_dict())


# example.sql 的查询体(内网直连时用);与需求方 example.sql 保持一致,改这里即可
DEFAULT_SQL = Path(__file__).resolve().parents[2] / "example.sql"


class SqlSource:
    """内网直连数据库跑 example.sql 批量取行。

    公网环境连不上内网 DB,故此类仅提供接口:进内网后给一个 SQLAlchemy 连接串
    (``db_url``)即可启用,查询体默认读仓库根目录的 ``example.sql``。
    """

    def __init__(
        self,
        db_url: str,
        sql: Optional[str] = None,
        sql_file: str | Path | None = None,
    ):
        self.db_url = db_url
        if sql is not None:
            self.sql = sql
        else:
            path = Path(sql_file) if sql_file else DEFAULT_SQL
            self.sql = Path(path).read_text(encoding="utf-8")

    def iter_rows(self) -> Iterator[dict]:
        # 延迟导入:公网环境不装 sqlalchemy 也能 import 本模块
        from sqlalchemy import create_engine, text  # type: ignore

        engine = create_engine(self.db_url)
        with engine.connect() as conn:
            result = conn.execute(text(self.sql))
            cols = list(result.keys())
            for r in result:
                yield _clean_row(dict(zip(cols, r)))


def make_source(
    *, file: str | Path | None = None, db_url: str | None = None, sql_file: str | Path | None = None
) -> RowSource:
    if file:
        return FileSource(file)
    if db_url:
        return SqlSource(db_url, sql_file=sql_file)
    raise ValueError("必须提供 file 或 db_url 之一")
