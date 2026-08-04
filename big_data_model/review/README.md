# 知识复核台(review)

`cases.jsonl` 机器抽取的**人工复核台**:分诊队列(P0 错挂 UNKNOWN 优先)→ 对照证据改字段
→ 存 overlay(非破坏、机器重跑不丢)→ 导出干净合并版。决策与优先级口径见
`../knowledge_pipeline/DEPLOY.md`「三点六」。

## 结构

```
big_data_model/review/
  adapters/db.py        DB seam:本地 sqlite / 内网 select_sql,execute_sql
  adapters/identity.py  身份 seam:token -> 复核人
  priority.py           P0/P1/P2 分诊(纯函数)
  overlay.py            PG 修订层读写 + 乐观锁
  service.py            机器案例 + overlay 叠加 → 前端 DTO / 导出
  app.py                Flask,5 接口
  sql/schema.sql        PG 建表(两张)
review_frontend/        Vue3 SFC(搬进你现有 app 的一个路由)
tests/review/           后端测试(sqlite 桩,离线全跑)
```

## 本地起(离线,用桩,不碰内网)

```bash
pip install flask
# 后端(默认 sqlite overlay + 桩身份,读真实 cases.jsonl)
flask --app big_data_model.review.app:create_app run --port 8000
```
- `GET /api/review/cases` 返回 755 条(P0≈190);`GET /api/review/export` 导出合并版。
- overlay 落在 `big_data_model/review/review_overlay.sqlite3`(可删,`AGENT_REVIEW_DB_PATH` 改路径)。

前端:把 `review_frontend/*` 放进你的 Vue3 工程,`ReviewPage.vue` 挂一个路由;需要
`pinia`。跨源时改 `api.js` 里的 `BASE`。**前端架构 / 接入 / 部署注意事项见
`../../review_frontend/README.md`。**

## 内网部署(只改两处 seam + 建表)

1. **建表**:对目标库执行 `big_data_model/review/sql/schema.sql`(两张表)。
2. **DB seam**:设 `AGENT_REVIEW_DB_BACKEND=intranet`,把 `adapters/db.py` 的
   `_intranet_select` / `_intranet_execute` 换成现成 `select_sql` / `execute_sql` 封装
   (若封装不吃参数占位,在该层做参数化→安全转义的适配)。
3. **身份 seam**:设 `AGENT_REVIEW_IDENTITY=intranet`,把 `adapters/identity.py` 的
   `_intranet_user` 换成现成"token → 用户信息(用户名/账号ID/权限)"函数。
4. **词表**:确保 `incident/knowledge/vocab/systems.txt` 已用 `t_business_standard.system_name`
   快照替换(否则"系统名未入词表"P1 会偏多)。
5. 前端路由接进已鉴权站点即可,鉴权不由本服务处理。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/review/cases` | 全量 DTO(机器 + overlay 叠加 + 优先级 + 证据) |
| GET | `/api/review/meta` | 下拉源:类别枚举、系统名词表 |
| POST | `/api/review/case/<event_id>` | `{patch, reviewed, base_version}`;version 过期→409 |
| GET | `/api/review/export` | 已复核合并版(下载 JSONL) |
| POST | `/api/vocab/pending` | `{system_name, source_event_id}` 记待审新增系统名 |

`patch` 只接受 `系统/类别/定位对象/描述/有效性`;类别、有效性服务端校验枚举。

## 测试

```bash
python -m pytest tests/review/ -q      # 27 passed(sqlite 桩,离线)
```
