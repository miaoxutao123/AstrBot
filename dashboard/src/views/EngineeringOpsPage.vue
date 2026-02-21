<script setup lang="ts">
import axios from 'axios';
import { useModuleI18n } from '@/i18n/composables';
import { computed, onMounted, onUnmounted, ref } from 'vue';

interface ApiPayload<T> {
  status?: string;
  message?: string;
  data?: T;
}

interface ProjectSummary {
  stats?: {
    indexed_files?: number;
    total_lines?: number;
  };
  top_languages?: Array<[string, number]>;
  heavy_files?: Array<{ path: string; line_count: number; symbol_count: number }>;
  hot_dependencies?: Array<{ path: string; in_degree: number; out_degree: number }>;
}

interface ToolOverviewItem {
  tool_name: string;
  samples: number;
  success_rate: number;
  timeout_error_rate: number;
  active_policy: boolean;
}

interface TaskRecord {
  task_id: string;
  tool_name: string;
  status: string;
  attempt: number;
  max_attempts: number;
  created_at: string;
  finished_at?: string | null;
  last_error?: string | null;
}

interface EmbeddingProviderItem {
  id: string;
  model?: string;
  dim?: number;
}

interface EmbeddingProviderPayload {
  providers?: EmbeddingProviderItem[];
  default_provider_id?: string;
}

interface ResilienceSnapshot {
  stats?: Record<string, any>;
  recent_events?: Array<Record<string, any>>;
}

const pageLoading = ref(false);
const autoRefresh = ref(true);
const toast = ref('');
const snackbarVisible = ref(false);

const { tm } = useModuleI18n('features/engineering-ops');

const providerId = ref('');
const semanticPathPrefix = ref('dashboard/src/');

const projectInfo = ref<Record<string, any>>({});
const projectSummary = ref<ProjectSummary>({});
const semanticInfo = ref<Record<string, any>>({});
const embeddingProviders = ref<EmbeddingProviderItem[]>([]);
const backgroundTasks = ref<TaskRecord[]>([]);
const toolOverview = ref<ToolOverviewItem[]>([]);
const resilienceSnapshot = ref<ResilienceSnapshot>({});

const symbolQuery = ref('build_main_agent');
const symbolResults = ref<Array<Record<string, any>>>([]);
const semanticQuery = ref('frontend routing and chat page state management');
const semanticResults = ref<Array<Record<string, any>>>([]);
const searchTab = ref<'symbol' | 'semantic'>('symbol');

const selectedTool = ref('');
const policyPreview = ref<Record<string, any> | null>(null);
const policyApplyResult = ref<Record<string, any> | null>(null);

let refreshTimer: number | null = null;

const taskStatusSeries = computed(() => {
  const counter: Record<string, number> = {};
  for (const task of backgroundTasks.value) {
    counter[task.status] = (counter[task.status] || 0) + 1;
  }
  const labels = Object.keys(counter);
  const values = labels.map((key) => counter[key]);
  return { labels, values };
});

const taskStatusChartOptions = computed(() => ({
  chart: {
    type: 'donut',
    fontFamily: 'inherit',
    toolbar: { show: false }
  },
  labels: taskStatusSeries.value.labels,
  stroke: { width: 1 },
  legend: { position: 'bottom' },
  dataLabels: { enabled: true },
  colors: ['#009688', '#2196F3', '#FFC107', '#FB8C00', '#E53935', '#9E9E9E'],
}));

const toolSeries = computed(() => {
  const top = toolOverview.value.slice(0, 8);
  return [{
    name: 'success_rate',
    data: top.map((item) => Number((item.success_rate * 100).toFixed(2)))
  }];
});

const toolChartOptions = computed(() => ({
  chart: {
    type: 'bar',
    height: 300,
    fontFamily: 'inherit',
    toolbar: { show: false },
  },
  plotOptions: {
    bar: {
      borderRadius: 6,
      horizontal: true,
      distributed: true,
    }
  },
  dataLabels: {
    enabled: true,
    formatter: (v: number) => `${v}%`
  },
  xaxis: {
    categories: toolOverview.value.slice(0, 8).map((item) => item.tool_name),
    max: 100,
  },
  colors: ['#2e7d32', '#1976d2', '#7b1fa2', '#00838f', '#ef6c00', '#5d4037', '#6d4c41', '#3949ab'],
}));

const languageSeries = computed(() => {
  const langs = projectSummary.value.top_languages || [];
  return [{
    name: 'files',
    data: langs.map((item) => item[1]),
  }];
});

const languageChartOptions = computed(() => ({
  chart: {
    type: 'bar',
    height: 260,
    fontFamily: 'inherit',
    toolbar: { show: false },
  },
  plotOptions: {
    bar: {
      columnWidth: '48%',
      borderRadius: 8,
    }
  },
  xaxis: {
    categories: (projectSummary.value.top_languages || []).map((item) => item[0]),
  },
  dataLabels: { enabled: false },
  colors: ['#1565C0'],
}));

const providerOptions = computed(() => {
  return embeddingProviders.value.map((item) => ({
    title: item.model
      ? `${item.id} · ${item.model} · ${item.dim || '?'}d`
      : `${item.id} · ${item.dim || '?'}d`,
    value: item.id,
  }));
});

const indexNeedsBuild = computed(() => Boolean(projectInfo.value?.needs_build));
const semanticNeedsBuild = computed(() => Boolean(semanticInfo.value?.needs_build));
const semanticSkippedDocs = computed(() => Number(semanticInfo.value?.stats?.skipped_docs || 0));

const resilienceStats = computed<Record<string, any>>(() => {
  return resilienceSnapshot.value?.stats || {};
});

const resilienceEvents = computed<Array<Record<string, any>>>(() => {
  const events = resilienceSnapshot.value?.recent_events || [];
  return [...events].slice(-12).reverse();
});

const metricCards = computed(() => {
  const infoStats = projectInfo.value?.stats || {};
  const semStats = semanticInfo.value?.stats || {};
  const runningTasks = backgroundTasks.value.filter((item) =>
    ['queued', 'running', 'retrying'].includes(item.status)
  ).length;
  const activePolicies = toolOverview.value.filter((item) => item.active_policy).length;

  return [
    {
      title: tm('metrics.indexedFiles'),
      value: infoStats.indexed_files || 0,
      sub: tm('metrics.lines', { count: infoStats.total_lines || 0 }),
      icon: 'mdi-file-tree'
    },
    {
      title: tm('metrics.semanticDocs'),
      value: semStats.doc_count || 0,
      sub: tm('metrics.provider', {
        provider: semanticInfo.value?.provider_id || tm('labels.na'),
      }),
      icon: 'mdi-vector-polyline'
    },
    {
      title: tm('metrics.runningTasks'),
      value: runningTasks,
      sub: tm('metrics.total', { count: backgroundTasks.value.length }),
      icon: 'mdi-progress-clock'
    },
    {
      title: tm('metrics.activePolicies'),
      value: activePolicies,
      sub: tm('metrics.activePolicySub', {
        recovered: resilienceStats.value.recovered_count || 0,
        retries: resilienceStats.value.llm_retry_count || 0,
      }),
      icon: 'mdi-shield-refresh'
    }
  ];
});

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '-';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function statusColor(status: string): string {
  if (status === 'succeeded') return 'success';
  if (status === 'failed') return 'error';
  if (status === 'retrying') return 'warning';
  if (status === 'running') return 'info';
  return 'default';
}

function setToast(message: string): void {
  toast.value = message;
  snackbarVisible.value = true;
  window.setTimeout(() => {
    if (toast.value === message) {
      snackbarVisible.value = false;
    }
  }, 2600);
}

async function getApi<T>(url: string, params?: Record<string, any>): Promise<T> {
  const res = await axios.get(url, { params });
  const payload = res.data as ApiPayload<T>;
  if (payload.status !== 'ok') {
    throw new Error(payload.message || 'Request failed.');
  }
  return payload.data as T;
}

async function postApi<T>(url: string, body: Record<string, any>): Promise<T> {
  const res = await axios.post(url, body);
  const payload = res.data as ApiPayload<T>;
  if (payload.status !== 'ok') {
    throw new Error(payload.message || 'Request failed.');
  }
  return payload.data as T;
}

async function refreshProjectPanels(): Promise<void> {
  const [info, summary] = await Promise.all([
    getApi<Record<string, any>>('/api/project_context/info'),
    getApi<ProjectSummary>('/api/project_context/summary', { top_n: 10 }),
  ]);
  projectInfo.value = info;
  projectSummary.value = summary;

  try {
    semanticInfo.value = await getApi<Record<string, any>>('/api/project_context/semantic/info');
  } catch {
    semanticInfo.value = {};
  }

  try {
    const providerPayload = await getApi<EmbeddingProviderPayload>('/api/project_context/semantic/providers');
    embeddingProviders.value = providerPayload.providers || [];
    if (!providerId.value && providerPayload.default_provider_id) {
      providerId.value = providerPayload.default_provider_id;
    }
  } catch {
    embeddingProviders.value = [];
  }
}

async function refreshRuntimePanels(): Promise<void> {
  const [tasks, evolution, resilience] = await Promise.all([
    getApi<TaskRecord[]>('/api/background_task/list', { limit: 80 }),
    getApi<{ tools: ToolOverviewItem[] }>('/api/tool_evolution/overview', { window: 280 }),
    getApi<ResilienceSnapshot>('/api/tool_evolution/resilience'),
  ]);
  backgroundTasks.value = tasks;
  toolOverview.value = evolution.tools || [];
  resilienceSnapshot.value = resilience || {};
  if (!selectedTool.value && toolOverview.value.length > 0) {
    selectedTool.value = toolOverview.value[0].tool_name;
  }
}

async function refreshAll(): Promise<void> {
  pageLoading.value = true;
  try {
    await Promise.all([refreshProjectPanels(), refreshRuntimePanels()]);
  } catch (error: any) {
    setToast(tm('toast.refreshFailed', { error: error?.message || String(error) }));
  } finally {
    pageLoading.value = false;
  }
}

async function buildProjectIndex(root = ''): Promise<void> {
  try {
    const payload = await postApi<Record<string, any>>('/api/project_context/build', {
      root,
      max_files: 12000,
      max_file_bytes: 1500000,
    });
    setToast(tm('toast.indexRebuilt', { count: payload.indexed_files || 0 }));
    await refreshProjectPanels();
  } catch (error: any) {
    setToast(tm('toast.indexBuildFailed', { error: error?.message || String(error) }));
  }
}

async function buildSemanticIndex(): Promise<void> {
  try {
    const payload = await postApi<Record<string, any>>('/api/project_context/semantic/build', {
      provider_id: providerId.value,
      max_docs: 1800,
      max_doc_chars: 1200,
      path_prefix: semanticPathPrefix.value,
    });
    const builtCount = Number(payload.doc_count || 0);
    const skippedCount = Number(payload.skipped_docs || 0);
    if (skippedCount > 0) {
      setToast(tm('toast.semanticRebuiltWithSkips', { count: builtCount, skipped: skippedCount }));
    } else {
      setToast(tm('toast.semanticRebuilt', { count: builtCount }));
    }
    await refreshProjectPanels();
  } catch (error: any) {
    setToast(tm('toast.semanticBuildFailed', { error: error?.message || String(error) }));
  }
}

async function runSymbolSearch(): Promise<void> {
  if (!symbolQuery.value.trim()) {
    symbolResults.value = [];
    return;
  }
  try {
    symbolResults.value = await getApi<Array<Record<string, any>>>('/api/project_context/symbols', {
      query: symbolQuery.value,
      limit: 24,
      path_prefix: semanticPathPrefix.value,
    });
  } catch (error: any) {
    setToast(tm('toast.symbolSearchFailed', { error: error?.message || String(error) }));
  }
}

async function runSemanticSearch(): Promise<void> {
  if (!semanticQuery.value.trim()) {
    semanticResults.value = [];
    return;
  }
  try {
    semanticResults.value = await getApi<Array<Record<string, any>>>('/api/project_context/semantic/search', {
      query: semanticQuery.value,
      top_k: 12,
      path_prefix: semanticPathPrefix.value,
      provider_id: providerId.value,
    });
  } catch (error: any) {
    setToast(tm('toast.semanticSearchFailed', { error: error?.message || String(error) }));
  }
}

async function previewPolicy(): Promise<void> {
  if (!selectedTool.value) return;
  try {
    policyPreview.value = await postApi<Record<string, any>>('/api/tool_evolution/propose', {
      tool_name: selectedTool.value,
      min_samples: 12,
    });
  } catch (error: any) {
    setToast(tm('toast.policyPreviewFailed', { error: error?.message || String(error) }));
  }
}

async function applyPolicy(): Promise<void> {
  if (!selectedTool.value) return;
  try {
    policyApplyResult.value = await postApi<Record<string, any>>('/api/tool_evolution/apply', {
      tool_name: selectedTool.value,
      dry_run: false,
      min_samples: 12,
    });
    setToast(tm('toast.policyApplyFinished'));
    await refreshRuntimePanels();
  } catch (error: any) {
    setToast(tm('toast.policyApplyFailed', { error: error?.message || String(error) }));
  }
}

async function resetResilienceStats(): Promise<void> {
  try {
    const payload = await postApi<ResilienceSnapshot>('/api/tool_evolution/resilience/reset', {});
    resilienceSnapshot.value = payload || {};
    setToast(tm('toast.resilienceReset'));
  } catch (error: any) {
    setToast(tm('toast.resilienceResetFailed', { error: error?.message || String(error) }));
  }
}

async function cancelTask(taskId: string): Promise<void> {
  try {
    await postApi('/api/background_task/cancel/' + taskId, {});
    await refreshRuntimePanels();
    setToast(tm('toast.taskCancelled', { taskId: taskId.slice(0, 8) }));
  } catch (error: any) {
    setToast(tm('toast.cancelFailed', { error: error?.message || String(error) }));
  }
}

onMounted(async () => {
  await refreshAll();
  refreshTimer = window.setInterval(async () => {
    if (!autoRefresh.value) {
      return;
    }
    await Promise.all([refreshRuntimePanels(), refreshProjectPanels()]);
  }, 7000);
});

onUnmounted(() => {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
});
</script>

<template>
  <v-container fluid class="engineering-ops-page pa-4">
    <v-card class="hero-panel" elevation="2" rounded="xl">
      <v-card-text class="d-flex flex-column flex-md-row align-md-center justify-space-between ga-4">
        <div>
          <div class="hero-title">{{ tm('hero.title') }}</div>
          <div class="hero-subtitle">
            {{ tm('hero.subtitle') }}
          </div>
        </div>
        <div class="d-flex flex-wrap ga-2 align-center">
          <v-switch
            v-model="autoRefresh"
            color="teal"
            hide-details
            density="compact"
            inset
            :label="tm('actions.autoRefresh')"
          />
          <v-btn color="primary" variant="flat" prepend-icon="mdi-refresh" :loading="pageLoading" @click="refreshAll">
            {{ tm('actions.refresh') }}
          </v-btn>
        </div>
      </v-card-text>
    </v-card>

    <v-row class="mt-2" dense>
      <v-col v-for="item in metricCards" :key="item.title" cols="12" sm="6" md="3">
        <v-card class="metric-card" rounded="xl" elevation="1">
          <v-card-text class="d-flex justify-space-between align-center">
            <div>
              <div class="metric-title">{{ item.title }}</div>
              <div class="metric-value">{{ item.value }}</div>
              <div class="metric-sub">{{ item.sub }}</div>
            </div>
            <v-avatar color="primary" variant="tonal" size="44">
              <v-icon>{{ item.icon }}</v-icon>
            </v-avatar>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row v-if="indexNeedsBuild || semanticNeedsBuild" class="mt-1" dense>
      <v-col cols="12">
        <v-alert type="warning" variant="tonal" border="start" density="comfortable" class="bootstrap-hint">
          <div class="d-flex flex-column flex-md-row align-md-center justify-space-between ga-2">
            <div>
              <div v-if="indexNeedsBuild">{{ tm('alerts.projectIndexMissing') }}</div>
              <div v-if="semanticNeedsBuild">{{ tm('alerts.semanticIndexMissing') }}</div>
            </div>
            <div class="d-flex flex-wrap ga-2">
              <v-btn v-if="indexNeedsBuild" size="small" color="primary" variant="flat" @click="buildProjectIndex('')">
                {{ tm('alerts.buildIndexNow') }}
              </v-btn>
              <v-btn v-if="semanticNeedsBuild" size="small" color="teal" variant="outlined" @click="buildSemanticIndex">
                {{ tm('alerts.buildSemanticNow') }}
              </v-btn>
            </div>
          </div>
        </v-alert>
      </v-col>
    </v-row>


    <v-row v-if="semanticSkippedDocs > 0" class="mt-1" dense>
      <v-col cols="12">
        <v-alert type="info" variant="tonal" border="start" density="comfortable" class="bootstrap-hint">
          {{ tm('alerts.semanticSkippedDocs', { count: semanticSkippedDocs }) }}
        </v-alert>
      </v-col>
    </v-row>

    <v-row class="mt-1" dense>
      <v-col cols="12" lg="8">
        <v-card rounded="xl" elevation="1" class="pa-2">
          <v-card-title class="d-flex align-center justify-space-between ga-2 flex-wrap">
            <span>{{ tm('sections.projectIndex') }}</span>
            <div class="d-flex flex-wrap ga-2">
              <v-btn size="small" color="primary" variant="outlined" @click="buildProjectIndex('')">
                {{ tm('actions.rebuildFullIndex') }}
              </v-btn>
              <v-btn size="small" color="indigo" variant="outlined" @click="buildProjectIndex('dashboard/src')">
                {{ tm('actions.rebuildFrontendIndex') }}
              </v-btn>
              <v-btn size="small" color="teal" variant="flat" @click="buildSemanticIndex">
                {{ tm('actions.buildSemanticIndex') }}
              </v-btn>
            </div>
          </v-card-title>
          <v-card-text>
            <v-row dense>
              <v-col cols="12" md="6">
                <v-select
                  v-model="providerId"
                  :items="providerOptions"
                  item-title="title"
                  item-value="value"
                  :label="tm('labels.embeddingProvider')"
                  density="comfortable"
                  variant="outlined"
                  hide-details
                  clearable
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model="semanticPathPrefix"
                  :label="tm('labels.pathPrefix')"
                  density="comfortable"
                  variant="outlined"
                  hide-details
                />
              </v-col>
            </v-row>
            <v-row class="mt-2" dense>
              <v-col cols="12" md="6">
                <div class="section-caption">{{ tm('sections.languageDistribution') }}</div>
                <apexchart type="bar" height="260" :options="languageChartOptions" :series="languageSeries" />
              </v-col>
              <v-col cols="12" md="6">
                <div class="section-caption">{{ tm('sections.topHeavyFiles') }}</div>
                <v-list density="compact" class="file-list">
                  <v-list-item
                    v-for="item in (projectSummary.heavy_files || []).slice(0, 7)"
                    :key="item.path"
                    :title="item.path"
                    :subtitle="tm('list.heavyFileSubtitle', { lines: item.line_count, symbols: item.symbol_count })"
                  />
                </v-list>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" lg="4">
        <v-card rounded="xl" elevation="1" class="pa-2 h-100">
          <v-card-title class="d-flex align-center justify-space-between">
            <span>{{ tm('sections.backgroundTasks') }}</span>
            <v-chip color="info" variant="tonal">{{ backgroundTasks.length }}</v-chip>
          </v-card-title>
          <v-card-text>
            <apexchart
              type="donut"
              height="230"
              :options="taskStatusChartOptions"
              :series="taskStatusSeries.values"
            />
            <v-table density="compact" class="mt-2 task-table" fixed-header height="250">
              <thead>
                <tr>
                  <th>{{ tm('table.task') }}</th>
                  <th>{{ tm('table.status') }}</th>
                  <th>{{ tm('table.attempt') }}</th>
                  <th>{{ tm('table.action') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="task in backgroundTasks.slice(0, 10)" :key="task.task_id">
                  <td>
                    <div class="mono">{{ task.tool_name }}</div>
                    <div class="task-time">{{ formatDateTime(task.created_at) }}</div>
                  </td>
                  <td>
                    <v-chip :color="statusColor(task.status)" size="x-small" variant="tonal">
                      {{ task.status }}
                    </v-chip>
                  </td>
                  <td>{{ task.attempt }}/{{ task.max_attempts }}</td>
                  <td>
                    <v-btn
                      v-if="['queued', 'running', 'retrying'].includes(task.status)"
                      size="x-small"
                      color="error"
                      variant="text"
                      @click="cancelTask(task.task_id)"
                    >
                      {{ tm('actions.cancel') }}
                    </v-btn>
                  </td>
                </tr>
              </tbody>
            </v-table>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="mt-1" dense>
      <v-col cols="12" lg="7">
        <v-card rounded="xl" elevation="1" class="pa-2 h-100">
          <v-card-title>{{ tm('sections.hybridRetrieval') }}</v-card-title>
          <v-card-text>
            <v-btn-toggle v-model="searchTab" mandatory color="primary" variant="outlined" class="mb-3">
              <v-btn value="symbol">{{ tm('tabs.symbol') }}</v-btn>
              <v-btn value="semantic">{{ tm('tabs.semantic') }}</v-btn>
            </v-btn-toggle>

            <div v-if="searchTab === 'symbol'">
              <div class="d-flex ga-2 mt-1">
                <v-text-field v-model="symbolQuery" :label="tm('labels.symbolKeyword')" variant="outlined" hide-details />
                <v-btn color="primary" @click="runSymbolSearch">{{ tm('actions.search') }}</v-btn>
              </div>
              <v-table density="compact" class="mt-3" fixed-header height="280">
                <thead>
                  <tr>
                    <th>{{ tm('table.symbol') }}</th>
                    <th>{{ tm('table.path') }}</th>
                    <th>{{ tm('table.line') }}</th>
                    <th>{{ tm('table.score') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in symbolResults" :key="`${row.path}:${row.line}:${row.name}`">
                    <td class="mono">{{ row.name }}</td>
                    <td class="mono">{{ row.path }}</td>
                    <td>{{ row.line }}</td>
                    <td>{{ row.score }}</td>
                  </tr>
                </tbody>
              </v-table>
            </div>

            <div v-else>
              <div class="d-flex ga-2 mt-1">
                <v-text-field v-model="semanticQuery" :label="tm('labels.semanticQuery')" variant="outlined" hide-details />
                <v-btn color="teal" @click="runSemanticSearch">{{ tm('actions.search') }}</v-btn>
              </div>
              <v-table density="compact" class="mt-3" fixed-header height="280">
                <thead>
                  <tr>
                    <th>{{ tm('table.path') }}</th>
                    <th>{{ tm('table.score') }}</th>
                    <th>{{ tm('table.excerpt') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in semanticResults" :key="`${row.path}:${row.score}`">
                    <td class="mono">{{ row.path }}</td>
                    <td>{{ row.score }}</td>
                    <td>{{ row.excerpt }}</td>
                  </tr>
                </tbody>
              </v-table>
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" lg="5">
        <v-card rounded="xl" elevation="1" class="pa-2 h-100">
          <v-card-title>{{ tm('sections.toolEvolution') }}</v-card-title>
          <v-card-text>
            <apexchart type="bar" height="300" :options="toolChartOptions" :series="toolSeries" />

            <v-sheet class="resilience-strip mt-3" rounded="lg">
              <div class="d-flex flex-wrap ga-2 align-center">
                <v-chip size="small" color="primary" variant="tonal">
                  {{ tm('resilience.llmRetries') }} {{ resilienceStats.llm_retry_count || 0 }}
                </v-chip>
                <v-chip size="small" color="teal" variant="tonal">
                  {{ tm('resilience.streamFallback') }} {{ resilienceStats.stream_fallback_count || 0 }}
                </v-chip>
                <v-chip size="small" color="success" variant="tonal">
                  {{ tm('resilience.recovered') }} {{ resilienceStats.recovered_count || 0 }}
                </v-chip>
                <v-chip size="small" color="error" variant="tonal">
                  {{ tm('resilience.failed') }} {{ resilienceStats.failed_count || 0 }}
                </v-chip>
                <v-spacer />
                <v-btn size="x-small" variant="text" color="primary" @click="resetResilienceStats">
                  {{ tm('actions.resetCounters') }}
                </v-btn>
              </div>
              <div v-if="resilienceStats.last_error" class="resilience-error mt-2">
                {{ tm('resilience.lastFailure', { error: resilienceStats.last_error }) }}
              </div>
            </v-sheet>

            <div class="d-flex ga-2 mt-4">
              <v-select
                v-model="selectedTool"
                :items="toolOverview.map((item) => item.tool_name)"
                :label="tm('labels.targetTool')"
                variant="outlined"
                hide-details
              />
              <v-btn color="primary" variant="outlined" @click="previewPolicy">{{ tm('actions.preview') }}</v-btn>
              <v-btn color="success" variant="flat" @click="applyPolicy">{{ tm('actions.apply') }}</v-btn>
            </div>

            <v-expansion-panels class="mt-3" variant="accordion">
              <v-expansion-panel :title="tm('panels.policyPreview')">
                <v-expansion-panel-text>
                  <pre class="json-box">{{ JSON.stringify(policyPreview, null, 2) }}</pre>
                </v-expansion-panel-text>
              </v-expansion-panel>
              <v-expansion-panel :title="tm('panels.policyApplyResult')">
                <v-expansion-panel-text>
                  <pre class="json-box">{{ JSON.stringify(policyApplyResult, null, 2) }}</pre>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>

            <div class="section-caption mt-3">{{ tm('sections.recentResilienceEvents') }}</div>
            <v-table density="compact" class="task-table" fixed-header height="180">
              <thead>
                <tr>
                  <th>{{ tm('table.time') }}</th>
                  <th>{{ tm('table.event') }}</th>
                  <th>{{ tm('table.detail') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in resilienceEvents" :key="`${item.ts}:${item.event}:${item.detail}`">
                  <td class="task-time">{{ formatDateTime(item.ts) }}</td>
                  <td class="mono">{{ item.event }}</td>
                  <td>{{ item.detail }}</td>
                </tr>
              </tbody>
            </v-table>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-snackbar v-model="snackbarVisible" timeout="2600" color="primary" location="top right">
      {{ toast }}
    </v-snackbar>
  </v-container>
</template>

<script lang="ts">
export default {
  name: 'EngineeringOpsPage'
};
</script>

<style scoped>
.engineering-ops-page {
  background: radial-gradient(1200px 380px at 80% -20%, rgba(33, 150, 243, 0.18), transparent),
    radial-gradient(1000px 320px at -10% -10%, rgba(0, 150, 136, 0.14), transparent);
}

.hero-panel {
  border: 1px solid rgba(21, 101, 192, 0.12);
  background: linear-gradient(130deg, rgba(236, 248, 255, 0.92), rgba(243, 250, 255, 0.85));
}

.hero-title {
  font-size: 1.2rem;
  font-weight: 700;
  color: #0d47a1;
}

.hero-subtitle {
  margin-top: 6px;
  color: #455a64;
  max-width: 840px;
  line-height: 1.45;
}

.metric-card {
  border: 1px solid rgba(38, 50, 56, 0.08);
}

.metric-title {
  font-size: 0.82rem;
  color: #607d8b;
}

.metric-value {
  font-size: 1.35rem;
  font-weight: 700;
  color: #1f2937;
  margin-top: 4px;
}

.metric-sub {
  margin-top: 2px;
  font-size: 0.78rem;
  color: #6b7280;
}

.section-caption {
  margin-bottom: 6px;
  font-size: 0.82rem;
  color: #546e7a;
  font-weight: 600;
}

.file-list {
  max-height: 260px;
  overflow: auto;
}

.task-table {
  font-size: 0.78rem;
}

.task-time {
  color: #78909c;
  font-size: 0.72rem;
}

.mono {
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', monospace;
  font-size: 0.78rem;
}

.json-box {
  margin: 0;
  padding: 10px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.92);
  color: #e2e8f0;
  max-height: 230px;
  overflow: auto;
  font-size: 0.76rem;
}

.resilience-strip {
  padding: 10px 12px;
  border: 1px solid rgba(21, 101, 192, 0.15);
  background: rgba(227, 242, 253, 0.55);
}

.resilience-error {
  font-size: 0.75rem;
  color: #b71c1c;
  line-height: 1.4;
}

.bootstrap-hint {
  border: 1px solid rgba(255, 143, 0, 0.25);
}

@media (max-width: 959px) {
  .hero-subtitle {
    max-width: none;
  }
}
</style>
