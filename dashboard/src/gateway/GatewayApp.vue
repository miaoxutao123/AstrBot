<template>
  <v-app>
    <v-navigation-drawer permanent>
      <v-list-item title="AstrBot Gateway" subtitle="Control Plane" />
      <v-divider />
      <v-list nav density="compact">
        <v-list-item v-for="item in navigation" :key="item.value" :title="item.title" :prepend-icon="item.icon" :active="page === item.value" @click="page = item.value" />
      </v-list>
      <template #append><div class="pa-3"><v-text-field v-model="apiKey" label="Admin API key" type="password" density="compact" hide-details @update:model-value="saveKey" /></div></template>
    </v-navigation-drawer>
    <v-main><v-container fluid class="pa-6"><GatewayConnectionsPage v-if="page === 'connections'" /><GatewayAgentsPage v-else-if="page === 'agents'" /><section v-else><h1 class="text-h4 mb-4">{{ navigation.find(item => item.value === page)?.title }}</h1><v-alert type="info" variant="tonal">This Gateway control-plane view uses the same authenticated `/v1` API.</v-alert></section></v-container></v-main>
  </v-app>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import GatewayAgentsPage from './GatewayAgentsPage.vue';
import GatewayConnectionsPage from './GatewayConnectionsPage.vue';
import { setGatewayKey } from './api';
const page = ref('connections');
const apiKey = ref(sessionStorage.getItem('gateway-api-key') || '');
const navigation = [
  { value: 'overview', title: 'Overview', icon: 'mdi-view-dashboard-outline' },
  { value: 'connections', title: 'Connections', icon: 'mdi-lan-connect' },
  { value: 'agents', title: 'Agents', icon: 'mdi-robot-outline' },
  { value: 'endpoints', title: 'Endpoints', icon: 'mdi-transit-connection-variant' },
  { value: 'system', title: 'System', icon: 'mdi-cog-outline' }
];
function saveKey(value: string) { setGatewayKey(value); }
</script>
