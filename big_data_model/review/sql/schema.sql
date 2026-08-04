-- 知识复核台 overlay 层(PostgreSQL)
-- 内网执行一次建表。本地测试用 sqlite 等价 DDL(见 adapters/db.py),无需跑这里。

-- 人工修订层:append-only,同 event_id 取最新行(id 最大)为当前值;cases.jsonl 不动。
CREATE TABLE IF NOT EXISTS kp_review_overlay (
  id         BIGSERIAL PRIMARY KEY,
  event_id   TEXT        NOT NULL,
  patch      JSONB       NOT NULL,             -- 改动字段子集:系统/类别/定位对象/描述/有效性
  reviewed   BOOLEAN     NOT NULL DEFAULT TRUE,
  reviewer   TEXT,                             -- 从 token 解出的复核人
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_overlay_event ON kp_review_overlay (event_id, id DESC);

-- 复核中遇到不在词表的系统名 → 待审新增(用于养 vocab/systems.txt)
CREATE TABLE IF NOT EXISTS kp_vocab_pending (
  id              BIGSERIAL   PRIMARY KEY,
  system_name     TEXT        NOT NULL,
  source_event_id TEXT,
  proposed_by     TEXT,
  status          TEXT        NOT NULL DEFAULT 'pending',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
