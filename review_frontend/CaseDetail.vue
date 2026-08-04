<script setup>
// 右侧详情:证据(只读) + 修订表单。按 event_id 加 key 让切换案例时表单重置。
import { useReviewStore } from './store'
import EvidencePanel from './EvidencePanel.vue'
import EditForm from './EditForm.vue'

const store = useReviewStore()
</script>

<template>
  <section class="detail" v-if="store.selected">
    <header class="head">
      <b class="eid">{{ store.selected.event_id }}</b>
      <span v-if="store.selected.review.reviewed" class="tag done">已复核</span>
      <span v-for="r in store.selected.review.reasons" :key="r" class="tag reason">{{ r }}</span>
    </header>
    <div class="body">
      <EvidencePanel :item="store.selected" />
      <EditForm :item="store.selected" :key="store.selected.event_id" />
    </div>
  </section>
  <section class="detail empty" v-else>← 从左侧选一条开始复核</section>
</template>

<style scoped>
.detail {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.detail.empty {
  align-items: center;
  justify-content: center;
  color: #57606a;
}
.head {
  padding: 10px 16px;
  border-bottom: 1px solid #d0d7de;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.eid {
  font-family: monospace;
}
.tag {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 10px;
}
.tag.reason {
  background: #fff8c5;
  color: #7d4e00;
}
.tag.done {
  background: #dafbe1;
  color: #1a7f37;
}
.body {
  display: flex;
  gap: 16px;
  padding: 16px;
  overflow-y: auto;
}
.body > * {
  flex: 1 1 0;
}
</style>
