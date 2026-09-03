<template>
  <div class="d-flex align-center mb-5"><div><h1 class="text-h4">{{ t('features.gateway.agents') }}</h1><p class="text-medium-emphasis">{{ t('features.gateway.agentsDescription') }}</p></div><v-spacer /><v-btn color="primary" prepend-icon="mdi-account-plus" @click="dialog = true">{{ t('features.gateway.createEnrollment') }}</v-btn></div>
  <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
  <v-data-table :headers="headers" :items="agents" :loading="loading"><template #item.scopes="{ item }"><v-chip v-for="scope in item.scopes" :key="scope" size="small" class="me-1">{{ scope }}</v-chip></template><template #item.actions="{ item }"><v-btn color="error" variant="text" size="small" @click="revoke(item.id)">{{ t('features.gateway.revoke') }}</v-btn></template></v-data-table>
  <v-dialog v-model="dialog" max-width="560"><v-card><v-card-title>{{ t('features.gateway.createEnrollment') }}</v-card-title><v-card-text><v-text-field v-model="nameHint" :label="t('features.gateway.nameHint')" /><v-text-field v-model.number="ttl" :label="t('features.gateway.expirySeconds')" type="number" min="1" max="3600" /><v-checkbox v-for="scope in scopes" :key="scope.value" v-model="selectedScopes" :value="scope.value" :label="scope.label" :disabled="scope.dangerous" :hint="scope.dangerous ? t('features.gateway.dangerousScopeHint') : undefined" persistent-hint /></v-card-text><v-card-actions><v-spacer /><v-btn @click="dialog = false">{{ t('features.gateway.cancel') }}</v-btn><v-btn color="primary" @click="enroll">{{ t('features.gateway.generate') }}</v-btn></v-card-actions></v-card></v-dialog>
  <v-dialog v-model="packageDialog" max-width="680"><v-card><v-card-title>{{ t('features.gateway.setupPackage') }}</v-card-title><v-card-text><v-alert type="warning" variant="tonal">{{ t('features.gateway.setupPackageWarning') }}</v-alert><v-textarea :label="t('features.gateway.environment')" readonly :model-value="environment" rows="3" /><v-textarea :label="t('features.gateway.bootstrapPrompt')" readonly :model-value="prompt" rows="5" /></v-card-text><v-card-actions><v-spacer /><v-btn @click="packageDialog = false">{{ t('features.gateway.done') }}</v-btn></v-card-actions></v-card></v-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from '@/i18n/composables';
import { gatewayApi } from './api';
type Agent = { id: string; display_name: string; status: string; scopes: string[]; last_seen_at?: number };
const agents = ref<Agent[]>([]); const loading = ref(false); const error = ref(''); const dialog = ref(false); const packageDialog = ref(false); const nameHint = ref('External Agent'); const ttl = ref(600); const selectedScopes = ref(['adapters:read', 'events:read', 'commands:send']); const enrollmentToken = ref('');
const { t } = useI18n();
const scopes = computed(() => [{ value: 'adapters:read', label: t('features.gateway.scopeAdaptersRead') }, { value: 'events:read', label: t('features.gateway.scopeEventsRead') }, { value: 'commands:send', label: t('features.gateway.scopeCommandsSend') }, { value: 'hardware:control', label: t('features.gateway.scopeHardwareControl'), dangerous: true }]);
const headers = computed(() => [{ title: t('features.gateway.name'), key: 'display_name' }, { title: t('features.gateway.status'), key: 'status' }, { title: t('features.gateway.scopes'), key: 'scopes' }, { title: '', key: 'actions' }]);
const environment = computed(() => `export GATEWAY_URL=${location.origin}\nexport GATEWAY_ENROLLMENT_TOKEN=${enrollmentToken.value}`);
const prompt = computed(() => t('features.gateway.bootstrapPromptText'));
async function refresh() { loading.value = true; try { agents.value = (await gatewayApi<{ agents: Agent[] }>('/agents')).agents; } catch (value) { error.value = String(value); } finally { loading.value = false; } }
async function enroll() { try { const result = await gatewayApi<{ token: string }>('/agent-enrollments', { method: 'POST', body: JSON.stringify({ name_hint: nameHint.value, ttl_seconds: ttl.value, scopes: selectedScopes.value }) }); enrollmentToken.value = result.token; dialog.value = false; packageDialog.value = true; } catch (value) { error.value = String(value); } }
async function revoke(id: string) { try { await gatewayApi(`/agents/${id}/revoke`, { method: 'POST' }); await refresh(); } catch (value) { error.value = String(value); } }
onMounted(refresh);
</script>
