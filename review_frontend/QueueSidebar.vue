<script setup>
// 复核队列:进度 + 筛选 + P0→P1→P2 排序列表。默认只看未复核。
import { useReviewStore } from './store'

const store = useReviewStore()
const PRIO_LABEL = { P0: 'P0', P1: 'P1', P2: 'P2', NONE: '免审' }
const badge = (c) => c.review.priority || 'NONE'
</script>

<template>
  <aside class="queue">
    <div class="progress">
      已复核 <b>{{ store.progress.reviewed }}</b> / {{ store.progress.total }} ·
      P0 待办 <b class="p0">{{ store.progress.p0Left }}</b>
    </div>

    <div class="filters">
      <label class="chk"
        ><input type="checkbox" v-model="store.filters.onlyUnreviewed" /> 只看未复核</label
      >
      <select v-model="store.filters.priority">
        <option value="ALL">全部优先级</option>
        <option value="P0">P0 高</option>
        <option value="P1">P1 中</option>
        <option value="P2">P2 低</option>
        <option value="NONE">免审</option>
      </select>
      <select v-model="store.filters.category">
        <option value="ALL">全部类别</option>
        <option v-for="c in store.categories" :key="c.code" :value="c.code">{{ c.code }}</option>
      </select>
      <input v-model="store.filters.search" placeholder="搜索 事件ID/系统/文本…" />
    </div>

    <ul class="list">
      <li
        v-for="c in store.queue"
        :key="c.event_id"
        :class="{ active: c.event_id === store.selectedId, done: c.review.reviewed }"
        @click="store.select(c.event_id)"
      >
        <span class="badge" :class="badge(c)">{{ PRIO_LABEL[badge(c)] }}</span>
        <span class="eid">{{ c.event_id }}</span>
        <span class="meta">{{ c['系统'].value }} · {{ c['类别'].value }}</span>
      </li>
      <li v-if="!store.queue.length" class="empty">没有符合条件的待复核项 🎉</li>
    </ul>
  </aside>
</template>

<style scoped>
.queue {
  width: 320px;
  flex: 0 0 320px;
  border-right: 1px solid #d0d7de;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.progress {
  padding: 10px 12px;
  border-bottom: 1px solid #d0d7de;
  background: #f6f8fa;
}
.progress .p0 {
  color: #cf222e;
}
.filters {
  padding: 8px 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-bottom: 1px solid #d0d7de;
}
.filters select,
.filters input {
  flex: 1 1 45%;
  min-width: 0;
  padding: 4px 6px;
}
.chk {
  flex: 1 1 100%;
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  flex: 1;
}
.list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #eaeef2;
  cursor: pointer;
}
.list li.active {
  background: #ddf4ff;
}
.list li.done {
  opacity: 0.5;
}
.badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  color: #fff;
  flex: 0 0 auto;
}
.badge.P0 {
  background: #cf222e;
}
.badge.P1 {
  background: #bc4c00;
}
.badge.P2 {
  background: #8250df;
}
.badge.NONE {
  background: #6e7781;
}
.eid {
  font-family: monospace;
  font-size: 12px;
}
.meta {
  color: #57606a;
  font-size: 12px;
  margin-left: auto;
  text-align: right;
}
.empty {
  padding: 24px 12px;
  color: #57606a;
  text-align: center;
}
</style>
