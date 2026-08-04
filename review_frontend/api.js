// 复核台 API 封装。
// - BASE:与 Flask 同源部署时用 '/api';跨源改成后端地址。
// - 身份:你的站点已鉴权。若用 header token,调 setTokenProvider(fn) 注入;
//   若用 cookie 会话,credentials:'include' 已带上,后端从会话解析即可。

const BASE = '/api'

let tokenProvider = () => ''
export function setTokenProvider(fn) {
  tokenProvider = fn
}

async function req(method, url, body) {
  const headers = { 'Content-Type': 'application/json' }
  const t = tokenProvider()
  if (t) headers['Authorization'] = t
  const res = await fetch(BASE + url, {
    method,
    headers,
    credentials: 'include',
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = new Error('HTTP ' + res.status)
    err.status = res.status
    try {
      err.body = await res.json()
    } catch {
      /* ignore */
    }
    throw err
  }
  // 这些接口都应回 JSON。若拿到 HTML/文本,通常是 /api 没代理到 Flask(或 BASE 配错),
  // 开发服务器把 SPA 的 index.html 当成响应返回了 —— 明确报出来,别让它变成
  // "xxx.filter is not a function" 之类的迷惑错误。
  const ct = res.headers.get('content-type') || ''
  if (!ct.includes('application/json')) {
    throw new Error(
      `后端返回了非 JSON(content-type=${ct || '空'})。多半是 /api 未代理到 Flask 或 api.js 的 BASE 配错。`,
    )
  }
  return res.json()
}

export const api = {
  cases: () => req('GET', '/review/cases'),
  meta: () => req('GET', '/review/meta'),
  saveCase: (id, patch, reviewed, baseVersion) =>
    req('POST', `/review/case/${encodeURIComponent(id)}`, {
      patch,
      reviewed,
      base_version: baseVersion,
    }),
  exportUrl: () => BASE + '/review/export',
  addPending: (system_name, source_event_id) =>
    req('POST', '/vocab/pending', { system_name, source_event_id }),
}
