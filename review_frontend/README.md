# 知识复核台 前端(Vue 3)

## 定位

**不是独立应用**,是嵌入你**现有已鉴权 Vue3 站点**的一个路由页。鉴权、导航外壳、
用户会话都由宿主站点提供;本前端只负责"复核台"这一个页面。

## 架构与数据流

```
ReviewPage.vue            路由页,挂载即 store.load()
 ├─ QueueSidebar.vue      左:进度 + 筛选 + P0→P1→P2 队列
 └─ CaseDetail.vue        右:选中案例
     ├─ EvidencePanel.vue   只读证据(工单原文/摘要/症状)
     └─ EditForm.vue        可编辑(类别/系统/定位/描述/有效性)

store.js (Pinia)   单一数据源:全量 cases 拉到本地,队列/进度都是 getter(本地算)
api.js             唯一后端出口(fetch 封装)
```

**数据流**
- 加载:`store.load()` → `api.cases()` + `api.meta()` → `state.cases` → `queue` getter(筛选+按优先级排序)→ 渲染。
- 编辑:`EditForm` → `store.save(id, patch)` → `api.saveCase()` →(成功)本地把 `字段.value` 叠上、`reviewed=true`、`version` 更新 →(冲突 409)提示刷新。
- 全量 755 条量小,一次拉全、前端过滤,后端保持薄。

## 依赖

- **Vue 3 + Pinia**(必需)。若工程还没装:`npm i pinia`,入口 `app.use(createPinia())`。
- **无其它 UI 库依赖**——纯原生组件 + scoped CSS,不需要 Element/Ant 等,规避内网框架限制。

## 接入 3 步

1. 拷贝 `review_frontend/*` 到你工程(如 `src/views/knowledge-review/`)。
2. 注册路由:
   ```js
   { path: '/knowledge-review', component: () => import('@/views/knowledge-review/ReviewPage.vue') }
   ```
3. 确保 `pinia` 已 `app.use`(store 才能用)。

## 后端地址与鉴权(只在 `api.js` 两个点)

- **`BASE`**(默认 `'/api'`):前后端**同源/同域反代**时不用改。跨源改成后端全地址(需后端开 CORS + 允许 credentials)。

  ⚠️ **开发环境必须把 `/api` 代理到 Flask**,否则 dev 服务器会把 SPA 的 `index.html`
  当成响应返回,页面报"后端返回了非 JSON / 加载失败"。Vite 配置:
  ```js
  // vite.config.js
  export default { server: { proxy: { '/api': 'http://localhost:5000' } } }
  ```
  (vue-cli 则在 `vue.config.js` 的 `devServer.proxy` 里配 `/api`。)生产环境由站点反代 `/api → Flask`。

  ⚠️ **Windows 上代理目标写 `http://127.0.0.1:5000`,不要写 `localhost`** —— Flask 默认只绑
  IPv4,`localhost` 可能被 Node 解析成 IPv6 `::1` 导致 502/500。

- **页面高度**:`ReviewPage` 用 `height:100%` 填充宿主容器,所以**挂载它的路由容器要有确定高度**
  (否则 755 条队列会把页面撑到无限高、无法内部滚动)。宿主是全屏内容区一般没问题;若不是,给外层容器一个高度即可。
- **身份**:后端从 `Authorization` 头或会话解出复核人。二选一:
  - **cookie 会话**(推荐):`credentials:'include'` 已带上,无需前端额外配置。
  - **header token**:入口处调 `setTokenProvider(() => 你的token)` 注入,api.js 会塞进 `Authorization`。

## 部署形态

- **推荐同源**:站点反代 `/api → Flask`。无 CORS、cookie 自动带、最省心。
- **跨源**:改 `BASE` + Flask 装 `flask-cors` 放行来源与 credentials。

## 注意事项 / 坑

- **必须有 pinia**,否则 store 报错。
- **乐观锁**:保存返回 409 = "已被他人修改,请刷新",多人同审时是正常保护,不是 bug。
- **切换案例表单重置**:靠 `CaseDetail.vue` 里 `<EditForm :key="event_id">`,**不要删这个 key**,否则改到一半切换会串。
- **系统名不在词表**:下拉会多出一条"xxx(不在词表)"并给"加入待审词表"按钮 → 落 `kp_vocab_pending`,不直接改词表。
- **导出**:后端 `GET /api/review/export` 是浏览器下载(`api.exportUrl()` 给的就是地址)。
  ⚠️ 当前 UI **还没放导出按钮**,需要的话在 `QueueSidebar` 加一个 `<a :href="api.exportUrl()">导出</a>` 即可(告诉我可以帮你加)。
- **数据量**:755 条本地全量无压力;若以后涨到几千条再改后端分页。
- **样式**:scoped + 朴素配色,可自行套站点主题。

## 构建

用你现有 Vue 工程的构建链(vite/webpack),这些 SFC 无特殊构建要求。
