<template>
  <div class="d-flex align-center mb-5"><div><h1 class="text-h4">Agents</h1><p class="text-medium-emphasis">External Agent identity, scopes, and presence.</p></div><v-spacer /><v-btn color="primary" prepend-icon="mdi-account-plus" @click="dialog = true">Create enrollment</v-btn></div>
  <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
  <v-data-table :headers="headers" :items="agents" :loading="loading"><template #item.scopes="{ item }"><v-chip v-for="scope in item.scopes" :key="scope" size="small" class="me-1">{{ scope }}</v-chip></template><template #item.actions="{ item }"><v-btn color="error" variant="text" size="small" @click="revoke(item.id)">Revoke</v-btn></template></v-data-table>
  <v-dialog v-model="dialog" max-width="560"><v-card><v-card-title>Create Agent Enrollment</v-card-title><v-card-text><v-text-field v-model="nameHint" label="Name hint" /><v-text-field v-model.number="ttl" label="Expiry (seconds)" type="number" min="1" max="3600" /><v-checkbox v-for="scope in scopes" :key="scope.value" v-model="selectedScopes" :value="scope.value" :label="scope.label" :disabled="scope.dangerous" :hint="scope.dangerous ? 'Dangerous scope: enable only through an explicit administrator flow.' : undefined" persistent-hint /></v-card-text><v-card-actions><v-spacer /><v-btn @click="dialog = false">Cancel</v-btn><v-btn color="primary" @click="enroll">Generate</v-btn></v-card-actions></v-card></v-dialog>
  <v-dialog v-model="packageDialog" max-width="680"><v-card><v-card-title>One-time Agent Setup Package</v-card-title><v-card-text><v-alert type="warning" variant="tonal">Copy the token into an Agent environment variable. Do not put it in an LLM prompt.</v-alert><v-textarea label="Environment" readonly :model-value="environment" rows="3" /><v-textarea label="Bootstrap prompt" readonly :model-value="prompt" rows="5" /></v-card-text><v-card-actions><v-spacer /><v-btn @click="packageDialog = false">Done</v-btn></v-card-actions></v-card></v-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { gatewayApi } from './api';
type Agent = { id: string; display_name: string; status: string; scopes: string[]; last_seen_at?: number };
const agents = ref<Agent[]>([]); const loading = ref(false); const error = ref(''); const dialog = ref(false); const packageDialog = ref(false); const nameHint = ref('External Agent'); const ttl = ref(600); const selectedScopes = ref(['adapters:read', 'events:read', 'commands:send']); const enrollmentToken = ref('');
const scopes = [{ value: 'adapters:read', label: 'Read adapters and discovery' }, { value: 'events:read', label: 'Receive events' }, { value: 'commands:send', label: 'Send commands' }, { value: 'hardware:control', label: 'Hardware control', dangerous: true }];
const headers = [{ title: 'Name', key: 'display_name' }, { title: 'Status', key: 'status' }, { title: 'Scopes', key: 'scopes' }, { title: '', key: 'actions' }];
const environment = computed(() => `export GATEWAY_URL=${location.origin}\nexport GATEWAY_ENROLLMENT_TOKEN=${enrollmentToken.value}`);
const prompt = 'Register yourself with the current AstrBot-Gateway. Read GATEWAY_URL and GATEWAY_ENROLLMENT_TOKEN from your environment; read /.well-known/astrbot-gateway, register, configure Bridge/MCP, run doctor, then report heartbeat. Do not modify Gateway source code.';
async function refresh() { loading.value = true; try { agents.value = (await gatewayApi<{ agents: Agent[] }>('/agents')).agents; } catch (value) { error.value = String(value); } finally { loading.value = false; } }
async function enroll() { try { const result = await gatewayApi<{ token: string }>('/agent-enrollments', { method: 'POST', body: JSON.stringify({ name_hint: nameHint.value, ttl_seconds: ttl.value, scopes: selectedScopes.value }) }); enrollmentToken.value = result.token; dialog.value = false; packageDialog.value = true; } catch (value) { error.value = String(value); } }
async function revoke(id: string) { try { await gatewayApi(`/agents/${id}/revoke`, { method: 'POST' }); await refresh(); } catch (value) { error.value = String(value); } }
onMounted(refresh);
</script>
