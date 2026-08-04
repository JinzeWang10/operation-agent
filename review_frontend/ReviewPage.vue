<script setup>
// 知识复核台:接入现有 Vue3 站点的一个路由。左队列 + 右详情。
import { onMounted } from 'vue'
import { useReviewStore } from './store'
import QueueSidebar from './QueueSidebar.vue'
import CaseDetail from './CaseDetail.vue'

const store = useReviewStore()
onMounted(() => store.load())
</script>

<template>
  <div class="review-page">
    <div v-if="store.loading" class="banner">加载中…</div>
    <div v-else-if="store.error" class="banner err">加载失败:{{ store.error }}</div>
    <template v-else>
      <QueueSidebar />
      <CaseDetail />
    </template>
  </div>
</template>

<style scoped>
.review-page {
  display: flex;
  height: 100%;
  min-height: 640px;
  font-size: 14px;
  color: #1f2328;
}
.banner {
  padding: 16px;
  color: #57606a;
}
.banner.err {
  color: #cf222e;
}
</style>
