<template>
  <div class="d-flex align-center mb-5"><div><h1 class="text-h4">{{ t('features.gateway.connections') }}</h1><p class="text-medium-emphasis">{{ t('features.gateway.connectionsDescription') }}</p></div><v-spacer /><v-btn color="primary" prepend-icon="mdi-plus" @click="openCreate">{{ t('features.gateway.addConnection') }}</v-btn></div>
  <v-alert v-if="error" type="error" class="mb-4" closable @click:close="error = ''">{{ error }}</v-alert>
  <v-data-table :headers="headers" :items="instances" :loading="loading" item-value="id"><template #item.actions="{ item }"><v-btn size="small" variant="text" @click="lifecycle(item.id, 'start')">Start</v-btn><v-btn size="small" variant="text" @click="lifecycle(item.id, 'stop')">Stop</v-btn><v-btn size="small" variant="text" @click="lifecycle(item.id, 'restart')">Restart</v-btn><v-btn size="small" variant="text" @click="openAuth(item.id)">Auth</v-btn><v-btn v-if="item.source === 'managed'" size="small" color="error" variant="text" @click="remove(item.id)">Delete</v-btn></template></v-data-table>

  <v-dialog v-model="createDialog" max-width="620"><v-card><v-card-title>{{ t('features.gateway.addConnection') }}</v-card-title><v-card-text><v-select v-model="draft.type" :items="adapterTypes" item-title="name" item-value="type" :label="t('features.gateway.adapterType')" @update:model-value="resetFields" /><v-text-field v-model="draft.id" :label="t('features.gateway.adapterId')" required /><v-text-field v-for="field in selectedType?.fields || []" :key="field.name" v-model="draft.config[field.name]" :label="fieldLabel(field)" :type="field.secret ? 'password' : field.type === 'url' ? 'url' : 'text'" :required="field.required" :hint="field.secret ? 'Stored in the managed secret backend' : undefined" persistent-hint /></v-card-text><v-card-actions><v-spacer /><v-btn @click="createDialog = false">{{ t('features.gateway.cancel') }}</v-btn><v-btn color="primary" :loading="saving" @click="create">{{ t('features.gateway.save') }}</v-btn></v-card-actions></v-card></v-dialog>

  <v-dialog v-model="authDialog" max-width="460"><v-card><v-card-title>Authentication</v-card-title><v-card-text><div class="text-center"><QrCodeViewer v-if="auth.challenge?.qr_uri" :value="auth.challenge.qr_uri" alt="Gateway authentication QR code" :size="220" /><v-progress-circular v-else-if="auth.status === 'waiting_user'" indeterminate color="primary" /><p class="mt-4">{{ auth.status }}</p><p v-if="auth.challenge?.instructions">{{ auth.challenge.instructions }}</p><code v-if="auth.challenge?.verification_code">{{ auth.challenge.verification_code }}</code><p v-if="auth.reason" class="text-error">{{ auth.reason }}</p></div></v-card-text><v-card-actions><v-btn @click="cancelAuth">Cancel auth</v-btn><v-spacer /><v-btn color="primary" @click="startAuth">Start authentication</v-btn><v-btn @click="authDialog = false">Close</v-btn></v-card-actions></v-card></v-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useI18n } from '@/i18n/composables';
import QrCodeViewer from '@/components/shared/QrCodeViewer.vue';
import { gatewayApi, type AdapterType } from './api';
type Instance = { id: string; type: string; source: string; state?: string; enabled?: boolean };
const headers = computed(() => [{ title: 'ID', key: 'id' }, { title: t('features.gateway.type'), key: 'type' }, { title: t('features.gateway.source'), key: 'source' }, { title: t('features.gateway.state'), key: 'state' }, { title: '', key: 'actions', sortable: false }]);
const instances = ref<Instance[]>([]); const adapterTypes = ref<AdapterType[]>([]); const loading = ref(false); const saving = ref(false); const error = ref(''); const createDialog = ref(false); const authDialog = ref(false); const authAdapter = ref(''); let poller: ReturnType<typeof setInterval> | undefined;
const draft = reactive({ id: '', type: '', config: {} as Record<string, string> });
const auth = reactive<{ status: string; reason?: string; challenge?: { qr_uri?: string; instructions?: string; verification_code?: string } }>({ status: 'not_required' });
const selectedType = computed(() => adapterTypes.value.find(type => type.type === draft.type));
const { t } = useI18n();
function fieldLabel(field: AdapterType['fields'][number]): string { if (!field.label_key) return field.label; const translated = t(`features.${field.label_key}`); return translated.startsWith('[MISSING:') ? field.label : translated; }
async function refresh() { loading.value = true; try { instances.value = (await gatewayApi<{ instances: Instance[] }>('/adapter-instances')).instances; adapterTypes.value = (await gatewayApi<{ adapter_types: AdapterType[] }>('/adapter-types')).adapter_types; } catch (value) { error.value = String(value); } finally { loading.value = false; } }
function resetFields() { draft.config = Object.fromEntries((selectedType.value?.fields || []).map(field => [field.name, field.default || ''])); }
function openCreate() { draft.id = ''; draft.type = adapterTypes.value[0]?.type || ''; resetFields(); createDialog.value = true; }
async function create() { saving.value = true; try { await gatewayApi('/adapter-instances', { method: 'POST', body: JSON.stringify({ ...draft, enabled: true }) }); createDialog.value = false; await refresh(); } catch (value) { error.value = String(value); } finally { saving.value = false; } }
async function lifecycle(id: string, action: string) { try { await gatewayApi(`/adapters/${id}/${action}`, { method: 'POST' }); await refresh(); } catch (value) { error.value = String(value); } }
async function remove(id: string) { try { await gatewayApi(`/adapter-instances/${id}`, { method: 'DELETE' }); await refresh(); } catch (value) { error.value = String(value); } }
async function readAuth() { Object.assign(auth, await gatewayApi(`/adapters/${authAdapter.value}/auth`)); if (auth.status === 'authenticated') { authDialog.value = false; stopPolling(); await refresh(); } }
function stopPolling() { if (poller) clearInterval(poller); poller = undefined; }
async function openAuth(id: string) { authAdapter.value = id; authDialog.value = true; await readAuth(); stopPolling(); poller = setInterval(() => { if (authDialog.value && auth.status === 'waiting_user') void readAuth(); }, 1500); }
async function startAuth() { Object.assign(auth, await gatewayApi(`/adapters/${authAdapter.value}/auth/start`, { method: 'POST' })); }
async function cancelAuth() { Object.assign(auth, await gatewayApi(`/adapters/${authAdapter.value}/auth/cancel`, { method: 'POST' })); stopPolling(); }
onMounted(refresh); onBeforeUnmount(stopPolling);
</script>
