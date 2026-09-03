<template>
  <v-app>
    <v-navigation-drawer permanent>
      <v-list-item title="AstrBot Gateway" :subtitle="t('features.gateway.controlPlane')" />
      <v-divider />
      <v-list nav density="compact">
        <v-list-item v-for="item in navigation" :key="item.value" :title="item.title" :prepend-icon="item.icon" :active="page === item.value" @click="page = item.value" />
      </v-list>
      <template #append><div class="pa-3"><v-btn-toggle mandatory density="compact" class="mb-3" @update:model-value="changeLanguage"><v-btn value="zh-CN">简体中文</v-btn><v-btn value="en-US">English</v-btn></v-btn-toggle><v-text-field v-model="apiKey" :label="t('features.gateway.adminApiKey')" type="password" density="compact" hide-details @update:model-value="saveKey" /></div></template>
    </v-navigation-drawer>
    <v-main><v-container fluid class="pa-6"><GatewayConnectionsPage v-if="page === 'connections'" /><GatewayAgentsPage v-else-if="page === 'agents'" /><section v-else><h1 class="text-h4 mb-4">{{ navigation.find(item => item.value === page)?.title }}</h1><v-alert type="info" variant="tonal">This Gateway control-plane view uses the same authenticated `/v1` API.</v-alert></section></v-container></v-main>
  </v-app>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n, useLanguageSwitcher } from '@/i18n/composables';
import type { Locale } from '@/i18n/types';
import GatewayAgentsPage from './GatewayAgentsPage.vue';
import GatewayConnectionsPage from './GatewayConnectionsPage.vue';
import { setGatewayKey } from './api';
const page = ref('connections');
const apiKey = ref(sessionStorage.getItem('gateway-api-key') || '');
const { t } = useI18n();
const { switchLanguage } = useLanguageSwitcher();
const navigation = computed(() => [
  { value: 'overview', title: t('features.gateway.overview'), icon: 'mdi-view-dashboard-outline' },
  { value: 'connections', title: t('features.gateway.connections'), icon: 'mdi-lan-connect' },
  { value: 'agents', title: t('features.gateway.agents'), icon: 'mdi-robot-outline' },
  { value: 'endpoints', title: t('features.gateway.endpoints'), icon: 'mdi-transit-connection-variant' },
  { value: 'system', title: t('features.gateway.system'), icon: 'mdi-cog-outline' }
]);
function saveKey(value: string) { setGatewayKey(value); }
function changeLanguage(value: unknown) { if (value === 'zh-CN' || value === 'en-US') void switchLanguage(value as Locale); }
</script>
