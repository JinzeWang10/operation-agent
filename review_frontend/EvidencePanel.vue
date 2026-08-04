<script setup>
// 只读证据区:复核人对照它判断机器抽取对不对。
defineProps({ item: { type: Object, required: true } })
</script>

<template>
  <div class="evidence">
    <h4>证据(只读)</h4>
    <div class="row"><label>标题</label><span>{{ item.证据.标题 || '(空)' }}</span></div>
    <div class="row"><label>工单描述</label><span>{{ item.证据.工单描述 || '(空)' }}</span></div>
    <div class="row hl"><label>根因文本</label><span>{{ item.证据.根因文本 || '(空)' }}</span></div>
    <div class="row"><label>处置文本</label><span>{{ item.证据.处置文本 || '(空)' }}</span></div>
    <div class="row"><label>现场摘要</label><span>{{ item.证据.现场摘要 || '(空)' }}</span></div>
    <div class="row">
      <label>症状标签</label><span>{{ (item.证据.症状标签 || []).join(', ') || '(无)' }}</span>
    </div>
    <div class="row"><label>影响范围</label><span>{{ item.证据.影响范围 || '(空)' }}</span></div>
    <div class="row"><label>发生时间</label><span>{{ item.证据.发生时间 || '(空)' }}</span></div>
  </div>
</template>

<style scoped>
.evidence {
  background: #f6f8fa;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  padding: 12px;
}
h4 {
  margin: 0 0 10px;
}
.row {
  display: flex;
  gap: 8px;
  padding: 5px 0;
  border-top: 1px solid #eaeef2;
}
.row label {
  flex: 0 0 72px;
  color: #57606a;
}
.row span {
  flex: 1;
  white-space: pre-wrap;
  word-break: break-word;
}
.row.hl span {
  font-weight: 600;
}
</style>
