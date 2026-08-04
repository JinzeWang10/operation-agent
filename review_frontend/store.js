// Pinia store:案例 + 复核状态 + 队列筛选/排序/进度。
// 755 条量小,全量拉到前端本地过滤,后端保持薄。
import { defineStore } from 'pinia'
import { api } from './api'

const PRIO_ORDER = { P0: 0, P1: 1, P2: 2, NONE: 3 }
const key = (c) => c.review.priority || 'NONE'

export const useReviewStore = defineStore('review', {
  state: () => ({
    cases: [],
    categories: [],
    systems: [],
    filters: { priority: 'ALL', category: 'ALL', system: 'ALL', onlyUnreviewed: true, search: '' },
    selectedId: null,
    loading: false,
    error: '',
  }),
  getters: {
    queue(state) {
      const f = state.filters
      let list = state.cases.slice()
      if (f.onlyUnreviewed) list = list.filter((c) => !c.review.reviewed)
      if (f.priority !== 'ALL') list = list.filter((c) => key(c) === f.priority)
      if (f.category !== 'ALL') list = list.filter((c) => c['类别'].value === f.category)
      if (f.system !== 'ALL')
        list = list.filter((c) => (c['系统'].canonical || c['系统'].value) === f.system)
      if (f.search) {
        const s = f.search.toLowerCase()
        list = list.filter((c) => JSON.stringify(c).toLowerCase().includes(s))
      }
      list.sort(
        (a, b) =>
          PRIO_ORDER[key(a)] - PRIO_ORDER[key(b)] || a.event_id.localeCompare(b.event_id),
      )
      return list
    },
    selected(state) {
      return state.cases.find((c) => c.event_id === state.selectedId) || null
    },
    progress(state) {
      const total = state.cases.length
      const reviewed = state.cases.filter((c) => c.review.reviewed).length
      const p0Left = state.cases.filter(
        (c) => c.review.priority === 'P0' && !c.review.reviewed,
      ).length
      return { total, reviewed, p0Left }
    },
  },
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const [cases, meta] = await Promise.all([api.cases(), api.meta()])
        if (!Array.isArray(cases)) throw new Error('后端 /review/cases 未返回数组,请检查 /api 代理与后端是否在跑')
        this.cases = cases
        this.categories = (meta && meta.categories) || []
        this.systems = (meta && meta.systems) || []
        if (!this.selectedId && this.queue.length) this.selectedId = this.queue[0].event_id
      } catch (e) {
        this.error = String(e)
      } finally {
        this.loading = false
      }
    },
    select(id) {
      this.selectedId = id
    },
    selectNext() {
      // 保存后自动跳到队列里下一条待复核,减少点击
      const q = this.queue
      this.selectedId = q.length ? q[0].event_id : null
    },
    async save(id, patch, reviewed) {
      const c = this.cases.find((x) => x.event_id === id)
      try {
        const { version } = await api.saveCase(id, patch, reviewed, c.review.version)
        for (const k of Object.keys(patch)) if (c[k]) c[k].value = patch[k]
        c.review.reviewed = reviewed
        c.review.version = version
        c.review.patched_fields = Object.keys(patch)
        return { ok: true }
      } catch (e) {
        if (e.status === 409) return { ok: false, conflict: true, latest: e.body && e.body.latest }
        throw e
      }
    },
    async addPending(name, sourceId) {
      await api.addPending(name, sourceId)
    },
  },
})
