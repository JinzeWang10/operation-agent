<script setup>
// 修订表单:类别▼/系统▼(词表)/定位对象/描述/有效性;显示机器原值;
// 多数一键「确认无误」,改过则「保存修订」。系统不在词表可加待审。409 提示刷新。
import { reactive, ref, computed } from 'vue'
import { useReviewStore } from './store'

const props = defineProps({ item: { type: Object, required: true } })
const store = useReviewStore()

const FIELDS = ['系统', '类别', '定位对象', '描述', '有效性']
const form = reactive({})
FIELDS.forEach((f) => (form[f] = props.item[f].value))
const msg = ref('')
const saving = ref(false)

const dirty = computed(() => FIELDS.some((f) => form[f] !== props.item[f].machine))
const systemInVocab = computed(() => store.systems.includes(form['系统']))

function patchObj() {
  const p = {}
  FIELDS.forEach((f) => {
    if (form[f] !== props.item[f].machine) p[f] = form[f]
  })
  return p
}

async function save() {
  saving.value = true
  msg.value = ''
  try {
    const r = await store.save(props.item.event_id, dirty.value ? patchObj() : {}, true)
    if (r.conflict) {
      msg.value = '⚠ 已被他人修改,请刷新后再改'
    } else {
      msg.value = '✓ 已保存'
      if (store.filters.onlyUnreviewed) store.selectNext()
    }
  } catch (e) {
    msg.value = '保存失败:' + e
  } finally {
    saving.value = false
  }
}

async function addPending() {
  await store.addPending(form['系统'], props.item.event_id)
  msg.value = '已加入待审词表'
}
</script>

<template>
  <div class="edit">
    <h4>修订</h4>

    <div class="f">
      <label>类别</label>
      <select v-model="form['类别']">
        <option v-for="c in store.categories" :key="c.code" :value="c.code" :title="c.desc">
          {{ c.code }}
        </option>
      </select>
      <small v-if="form['类别'] !== item['类别'].machine" class="orig"
        >原:{{ item['类别'].machine }}</small
      >
    </div>

    <div class="f">
      <label>系统</label>
      <select v-model="form['系统']">
        <option v-for="s in store.systems" :key="s" :value="s">{{ s }}</option>
        <option v-if="!systemInVocab" :value="form['系统']">{{ form['系统'] }}(不在词表)</option>
      </select>
      <button v-if="!systemInVocab" class="link" type="button" @click="addPending">
        加入待审词表
      </button>
    </div>

    <div class="f">
      <label>定位对象</label>
      <input v-model="form['定位对象']" />
    </div>

    <div class="f">
      <label>描述</label>
      <textarea v-model="form['描述']" rows="2" />
    </div>

    <div class="f">
      <label>有效性</label>
      <select v-model="form['有效性']">
        <option value="valid">valid</option>
        <option value="invalid">invalid</option>
      </select>
    </div>

    <div class="actions">
      <button v-if="!dirty" :disabled="saving" @click="save">确认无误</button>
      <button v-else class="primary" :disabled="saving" @click="save">保存修订</button>
      <span class="msg">{{ msg }}</span>
    </div>
  </div>
</template>

<style scoped>
.edit {
  border: 1px solid #d0d7de;
  border-radius: 6px;
  padding: 12px;
}
h4 {
  margin: 0 0 10px;
}
.f {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.f label {
  flex: 0 0 64px;
  color: #57606a;
}
.f select,
.f input,
.f textarea {
  flex: 1;
  padding: 5px 6px;
  font: inherit;
}
.orig {
  color: #bc4c00;
  flex: 0 0 auto;
}
.link {
  border: none;
  background: none;
  color: #0969da;
  cursor: pointer;
  flex: 0 0 auto;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}
.actions button {
  padding: 6px 16px;
  cursor: pointer;
}
.actions button.primary {
  background: #1f883d;
  color: #fff;
  border: 1px solid #1a7f37;
  border-radius: 6px;
}
.msg {
  color: #57606a;
}
</style>
