<template>
    <div class="long-term-memory-page">
        <v-container fluid class="pa-0">
            <!-- Guide Banner -->
            <v-card v-if="showGuide" flat class="mb-3">
                <v-card-title class="d-flex align-center py-3 px-4">
                    <v-icon color="primary" class="mr-2">mdi-lightbulb-on-outline</v-icon>
                    <span class="text-h6">{{ tm('guide.title') }}</span>
                    <v-spacer></v-spacer>
                    <v-btn variant="text" size="small" @click="dismissGuide">{{ tm('guide.dismiss') }}</v-btn>
                </v-card-title>
                <v-card-text class="pt-0 px-4 pb-4">
                    <v-row>
                        <v-col cols="12" sm="6" md="3" v-for="step in guideSteps" :key="step.key">
                            <v-card variant="tonal" :color="step.color" class="pa-3 h-100">
                                <div class="d-flex align-center mb-2">
                                    <v-icon size="20" class="mr-2">{{ step.icon }}</v-icon>
                                    <span class="text-subtitle-2 font-weight-bold">{{ tm('guide.steps.' + step.key + '.title') }}</span>
                                </div>
                                <div class="text-caption">{{ tm('guide.steps.' + step.key + '.desc') }}</div>
                            </v-card>
                        </v-col>
                    </v-row>
                </v-card-text>
            </v-card>

            <v-card flat>
                <v-card-title class="d-flex align-center py-3 px-4">
                    <span class="text-h4">{{ tm('title') }}</span>
                    <v-chip size="small" class="ml-2">{{ totalCount }}</v-chip>
                    <v-spacer></v-spacer>
                    <v-btn color="primary" prepend-icon="mdi-refresh" variant="tonal" @click="refreshCurrentTab"
                        :loading="loading" size="small">
                        {{ tm('actions.refresh') }}
                    </v-btn>
                </v-card-title>

                <v-tabs v-model="activeTab" color="primary" class="px-4">
                    <v-tab value="items">{{ tm('tabs.items') }}</v-tab>
                    <v-tab value="events">{{ tm('tabs.events') }}</v-tab>
                    <v-tab value="graph">{{ tm('tabs.graph') }}</v-tab>
                    <v-tab value="stats">{{ tm('tabs.stats') }}</v-tab>
                </v-tabs>

                <v-divider></v-divider>

                <!-- Memory Items Tab -->
                <v-window v-model="activeTab">
                    <v-window-item value="items">
                        <!-- Filters -->
                        <div class="d-flex align-center px-4 pt-3 ga-3 flex-wrap">
                            <v-select v-model="filters.scope" :label="tm('filters.scope')"
                                :items="scopeOptions" clearable variant="solo-filled" flat
                                density="compact" hide-details style="max-width: 160px;"
                                @update:model-value="onFilterChange"></v-select>
                            <v-text-field v-model="filters.scopeId" :label="tm('filters.scopeId')"
                                variant="solo-filled" flat density="compact" hide-details
                                style="max-width: 180px;" clearable
                                @update:model-value="debouncedFilterChange"></v-text-field>
                            <v-select v-model="filters.type" :label="tm('filters.type')"
                                :items="typeOptions" clearable variant="solo-filled" flat
                                density="compact" hide-details style="max-width: 160px;"
                                @update:model-value="onFilterChange"></v-select>
                            <v-select v-model="filters.status" :label="tm('filters.status')"
                                :items="statusOptions" clearable variant="solo-filled" flat
                                density="compact" hide-details style="max-width: 160px;"
                                @update:model-value="onFilterChange"></v-select>
                            <v-slider v-model="filters.minConfidence" :label="tm('filters.minConfidence')"
                                :min="0" :max="1" :step="0.1" thumb-label hide-details
                                style="max-width: 220px;" class="mt-1"
                                @end="onFilterChange"></v-slider>
                        </div>

                        <v-card-text class="pa-0">
                            <v-data-table :headers="itemHeaders" :items="items"
                                :loading="loading" style="font-size: 12px;" density="comfortable"
                                hide-default-footer class="elevation-0"
                                :items-per-page="itemsPagination.page_size">

                                <template v-slot:item.fact="{ item }">
                                    <span class="text-truncate d-inline-block" style="max-width: 280px;">{{ item.fact }}</span>
                                </template>

                                <template v-slot:item.scope="{ item }">
                                    <v-chip size="small" label>{{ tm('scopes.' + item.scope) }}</v-chip>
                                </template>

                                <template v-slot:item.type="{ item }">
                                    <v-chip size="small" label color="info">{{ tm('types.' + item.type) }}</v-chip>
                                </template>

                                <template v-slot:item.status="{ item }">
                                    <v-chip size="small" label :color="statusColor(item.status)">
                                        {{ tm('statuses.' + item.status) }}
                                    </v-chip>
                                </template>

                                <template v-slot:item.confidence="{ item }">
                                    <v-progress-linear :model-value="item.confidence * 100" :color="confidenceColor(item.confidence)"
                                        height="6" rounded style="min-width: 60px;"></v-progress-linear>
                                    <span class="text-caption">{{ (item.confidence * 100).toFixed(0) }}%</span>
                                </template>

                                <template v-slot:item.importance="{ item }">
                                    <span class="text-caption">{{ (item.importance * 100).toFixed(0) }}%</span>
                                </template>

                                <template v-slot:item.created_at="{ item }">
                                    {{ formatTimestamp(item.created_at) }}
                                </template>

                                <template v-slot:item.actions="{ item }">
                                    <div class="d-flex">
                                        <v-btn icon variant="plain" size="x-small" @click="viewItem(item)">
                                            <v-icon>mdi-eye</v-icon>
                                        </v-btn>
                                        <v-btn icon variant="plain" size="x-small" @click="editItem(item)">
                                            <v-icon>mdi-pencil</v-icon>
                                        </v-btn>
                                        <v-btn icon color="error" variant="plain" size="x-small" @click="confirmDeleteItem(item)">
                                            <v-icon>mdi-delete</v-icon>
                                        </v-btn>
                                    </div>
                                </template>

                                <template v-slot:no-data>
                                    <div class="d-flex flex-column align-center py-6">
                                        <v-icon size="64" color="grey lighten-1">mdi-brain</v-icon>
                                        <span class="text-subtitle-1 text-disabled mt-3">{{ tm('empty.items') }}</span>
                                        <span class="text-caption text-disabled">{{ tm('empty.itemsHint') }}</span>
                                    </div>
                                </template>
                            </v-data-table>

                            <div class="d-flex justify-center py-3">
                                <div class="d-flex align-center">
                                    <span class="text-caption mr-2">{{ tm('pagination.itemsPerPage') }}:</span>
                                    <v-select v-model="itemsPagination.page_size" :items="pageSizeOptions"
                                        variant="outlined" density="compact" hide-details style="max-width: 100px;"
                                        @update:model-value="onItemsPageSizeChange"></v-select>
                                </div>
                                <div class="text-caption ml-4 d-flex align-center">
                                    {{ tm('pagination.showingItems', {
                                        start: Math.min((itemsPagination.page - 1) * itemsPagination.page_size + 1, itemsPagination.total),
                                        end: Math.min(itemsPagination.page * itemsPagination.page_size, itemsPagination.total),
                                        total: itemsPagination.total
                                    }) }}
                                </div>
                                <v-pagination v-model="itemsPagination.page" :length="itemsTotalPages"
                                    @update:model-value="fetchItems" rounded="circle" :total-visible="7"></v-pagination>
                            </div>
                        </v-card-text>
                    </v-window-item>

                    <v-window-item value="events">
                        <div class="d-flex align-center px-4 pt-3 ga-3 flex-wrap">
                            <v-select v-model="eventsFilters.scope" :label="tm('filters.scope')"
                                :items="scopeOptions" clearable variant="solo-filled" flat
                                density="compact" hide-details style="max-width: 160px;"
                                @update:model-value="onEventsFilterChange"></v-select>
                            <v-text-field v-model="eventsFilters.scopeId" :label="tm('filters.scopeId')"
                                variant="solo-filled" flat density="compact" hide-details
                                style="max-width: 180px;" clearable
                                @update:model-value="debouncedEventsFilterChange"></v-text-field>
                        </div>

                        <v-card-text class="pa-0">
                            <v-data-table :headers="eventHeaders" :items="events"
                                :loading="loading" style="font-size: 12px;" density="comfortable"
                                hide-default-footer class="elevation-0"
                                :items-per-page="eventsPagination.page_size">

                                <template v-slot:item.scope="{ item }">
                                    <v-chip size="small" label>{{ tm('scopes.' + item.scope) }}</v-chip>
                                </template>

                                <template v-slot:item.source_type="{ item }">
                                    <v-chip size="small" label>{{ tm('events.sourceTypes.' + item.source_type) }}</v-chip>
                                </template>

                                <template v-slot:item.source_role="{ item }">
                                    <v-chip size="small" label>{{ tm('events.sourceRoles.' + item.source_role) }}</v-chip>
                                </template>

                                <template v-slot:item.content="{ item }">
                                    <span class="text-truncate d-inline-block" style="max-width: 300px;">
                                        {{ typeof item.content === 'object' ? JSON.stringify(item.content) : item.content }}
                                    </span>
                                </template>

                                <template v-slot:item.processed="{ item }">
                                    <v-chip size="small" :color="item.processed ? 'success' : 'warning'" label>
                                        {{ item.processed ? tm('events.processedStatus.yes') : tm('events.processedStatus.no') }}
                                    </v-chip>
                                </template>

                                <template v-slot:item.created_at="{ item }">
                                    {{ formatTimestamp(item.created_at) }}
                                </template>

                                <template v-slot:no-data>
                                    <div class="d-flex flex-column align-center py-6">
                                        <v-icon size="64" color="grey lighten-1">mdi-timeline-text</v-icon>
                                        <span class="text-subtitle-1 text-disabled mt-3">{{ tm('empty.events') }}</span>
                                        <span class="text-caption text-disabled">{{ tm('empty.eventsHint') }}</span>
                                    </div>
                                </template>
                            </v-data-table>

                            <div class="d-flex justify-center py-3">
                                <div class="d-flex align-center">
                                    <span class="text-caption mr-2">{{ tm('pagination.itemsPerPage') }}:</span>
                                    <v-select v-model="eventsPagination.page_size" :items="pageSizeOptions"
                                        variant="outlined" density="compact" hide-details style="max-width: 100px;"
                                        @update:model-value="onEventsPageSizeChange"></v-select>
                                </div>
                                <div class="text-caption ml-4 d-flex align-center">
                                    {{ tm('pagination.showingItems', {
                                        start: Math.min((eventsPagination.page - 1) * eventsPagination.page_size + 1, eventsPagination.total),
                                        end: Math.min(eventsPagination.page * eventsPagination.page_size, eventsPagination.total),
                                        total: eventsPagination.total
                                    }) }}
                                </div>
                                <v-pagination v-model="eventsPagination.page" :length="eventsTotalPages"
                                    @update:model-value="fetchEvents" rounded="circle" :total-visible="7"></v-pagination>
                            </div>
                        </v-card-text>
                    </v-window-item>

                    <v-window-item value="graph">
                        <v-card-text class="pa-4">
                            <MemoryGraphTab ref="memoryGraphTab" />
                        </v-card-text>
                    </v-window-item>

                    <v-window-item value="stats">
                        <v-card-text>
                            <v-row>
                                <v-col cols="12" sm="6" md="3">
                                    <v-card variant="tonal" color="primary" class="pa-4 text-center">
                                        <div class="text-h4">{{ stats.total || 0 }}</div>
                                        <div class="text-caption">{{ tm('stats.totalItems') }}</div>
                                    </v-card>
                                </v-col>
                                <v-col cols="12" sm="6" md="3">
                                    <v-card variant="tonal" color="success" class="pa-4 text-center">
                                        <div class="text-h4">{{ stats.by_status?.active || 0 }}</div>
                                        <div class="text-caption">{{ tm('stats.activeItems') }}</div>
                                    </v-card>
                                </v-col>
                                <v-col cols="12" sm="6" md="3">
                                    <v-card variant="tonal" color="warning" class="pa-4 text-center">
                                        <div class="text-h4">{{ stats.by_status?.shadow || 0 }}</div>
                                        <div class="text-caption">{{ tm('stats.shadowItems') }}</div>
                                    </v-card>
                                </v-col>
                                <v-col cols="12" sm="6" md="3">
                                    <v-card variant="tonal" color="info" class="pa-4 text-center">
                                        <div class="text-h4">{{ (stats.by_status?.disabled || 0) + (stats.by_status?.expired || 0) }}</div>
                                        <div class="text-caption">{{ tm('statuses.disabled') }} / {{ tm('statuses.expired') }}</div>
                                    </v-card>
                                </v-col>
                            </v-row>

                            <v-row class="mt-4">
                                <v-col cols="12" md="6">
                                    <v-card variant="outlined" class="pa-4">
                                        <div class="text-subtitle-1 mb-3">{{ tm('stats.byType') }}</div>
                                        <div v-if="stats.by_type && Object.keys(stats.by_type).length > 0">
                                            <div v-for="(count, type) in stats.by_type" :key="type"
                                                class="d-flex align-center mb-2">
                                                <v-chip size="small" label color="info" class="mr-3" style="min-width: 80px;">
                                                    {{ tm('types.' + type) }}
                                                </v-chip>
                                                <v-progress-linear :model-value="stats.total ? (count / stats.total) * 100 : 0"
                                                    color="info" height="8" rounded class="flex-grow-1 mr-2"></v-progress-linear>
                                                <span class="text-caption" style="min-width: 30px;">{{ count }}</span>
                                            </div>
                                        </div>
                                        <div v-else class="text-center text-disabled py-4">{{ tm('empty.items') }}</div>
                                    </v-card>
                                </v-col>
                                <v-col cols="12" md="6">
                                    <v-card variant="outlined" class="pa-4">
                                        <div class="text-subtitle-1 mb-3">{{ tm('stats.byStatus') }}</div>
                                        <div v-if="stats.by_status && Object.keys(stats.by_status).length > 0">
                                            <div v-for="(count, status) in stats.by_status" :key="status"
                                                class="d-flex align-center mb-2">
                                                <v-chip size="small" label :color="statusColor(status)" class="mr-3" style="min-width: 80px;">
                                                    {{ tm('statuses.' + status) }}
                                                </v-chip>
                                                <v-progress-linear :model-value="stats.total ? (count / stats.total) * 100 : 0"
                                                    :color="statusColor(status)" height="8" rounded class="flex-grow-1 mr-2"></v-progress-linear>
                                                <span class="text-caption" style="min-width: 30px;">{{ count }}</span>
                                            </div>
                                        </div>
                                        <div v-else class="text-center text-disabled py-4">{{ tm('empty.items') }}</div>
                                    </v-card>
                                </v-col>
                            </v-row>
                        </v-card-text>
                    </v-window-item>
                </v-window>
            </v-card>
        </v-container>
        <!-- Detail Dialog -->
        <v-dialog v-model="dialogDetail" max-width="700px" scrollable>
            <v-card>
                <v-card-title class="bg-primary text-white py-3">
                    <v-icon color="white" class="me-2">mdi-brain</v-icon>
                    <span>{{ tm('dialogs.detail.title') }}</span>
                </v-card-title>
                <v-card-text class="py-4" v-if="selectedItem">
                    <div class="text-subtitle-1 mb-2">{{ tm('dialogs.detail.basicInfo') }}</div>
                    <v-table density="compact">
                        <tbody>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.fact') }}</td><td>{{ selectedItem.fact }}</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.factKey') }}</td><td>{{ selectedItem.fact_key }}</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.scope') }}</td><td>{{ tm('scopes.' + selectedItem.scope) }} / {{ selectedItem.scope_id }}</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.type') }}</td><td>{{ tm('types.' + selectedItem.type) }}</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.status') }}</td><td>{{ tm('statuses.' + selectedItem.status) }}</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.confidence') }}</td><td>{{ (selectedItem.confidence * 100).toFixed(1) }}%</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.importance') }}</td><td>{{ (selectedItem.importance * 100).toFixed(1) }}%</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.evidenceCount') }}</td><td>{{ selectedItem.evidence_count }}</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.ttlDays') }}</td><td>{{ selectedItem.ttl_days ?? '-' }}</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.createdAt') }}</td><td>{{ formatTimestamp(selectedItem.created_at) }}</td></tr>
                            <tr><td class="font-weight-bold">{{ tm('table.headers.updatedAt') }}</td><td>{{ formatTimestamp(selectedItem.updated_at) }}</td></tr>
                        </tbody>
                    </v-table>

                    <div class="text-subtitle-1 mt-4 mb-2">{{ tm('dialogs.detail.evidenceTitle') }}</div>
                    <div v-if="selectedEvidence.length > 0">
                        <v-card v-for="ev in selectedEvidence" :key="ev.id" variant="outlined" class="mb-2 pa-3">
                            <div><span class="font-weight-bold">{{ tm('dialogs.detail.eventId') }}:</span> {{ ev.event_id }}</div>
                            <div><span class="font-weight-bold">{{ tm('dialogs.detail.extractionMethod') }}:</span> {{ ev.extraction_method }}</div>
                            <div v-if="ev.extraction_meta">
                                <span class="font-weight-bold">{{ tm('dialogs.detail.extractionMeta') }}:</span>
                                <pre class="text-caption mt-1">{{ JSON.stringify(ev.extraction_meta, null, 2) }}</pre>
                            </div>
                        </v-card>
                    </div>
                    <div v-else class="text-center text-disabled py-3">{{ tm('dialogs.detail.noEvidence') }}</div>
                </v-card-text>
                <v-card-actions class="pa-4">
                    <v-spacer></v-spacer>
                    <v-btn variant="text" @click="dialogDetail = false">{{ tm('dialogs.detail.close') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- Edit Dialog -->
        <v-dialog v-model="dialogEdit" max-width="500px">
            <v-card>
                <v-card-title class="bg-primary text-white py-3">
                    <v-icon color="white" class="me-2">mdi-pencil</v-icon>
                    <span>{{ tm('dialogs.edit.title') }}</span>
                </v-card-title>
                <v-card-text class="py-4">
                    <v-textarea v-model="editForm.fact" :label="tm('dialogs.edit.factLabel')"
                        variant="outlined" rows="3" class="mb-3"></v-textarea>
                    <v-select v-model="editForm.status" :label="tm('dialogs.edit.statusLabel')"
                        :items="editStatusOptions" variant="outlined" density="comfortable" class="mb-3"></v-select>
                    <v-slider v-model="editForm.importance" :label="tm('dialogs.edit.importanceLabel')"
                        :min="0" :max="1" :step="0.05" thumb-label class="mb-3"></v-slider>
                    <v-text-field v-model.number="editForm.ttl_days" :label="tm('dialogs.edit.ttlDaysLabel')"
                        :hint="tm('dialogs.edit.ttlDaysHint')" type="number" variant="outlined"
                        density="comfortable" clearable></v-text-field>
                </v-card-text>
                <v-divider></v-divider>
                <v-card-actions class="pa-4">
                    <v-spacer></v-spacer>
                    <v-btn variant="text" @click="dialogEdit = false">{{ tm('dialogs.edit.cancel') }}</v-btn>
                    <v-btn color="primary" @click="saveEdit" :loading="loading">{{ tm('dialogs.edit.save') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- Delete Dialog -->
        <v-dialog v-model="dialogDelete" max-width="450px">
            <v-card>
                <v-card-title class="bg-error text-white py-3">
                    <v-icon color="white" class="me-2">mdi-delete-alert</v-icon>
                    <span>{{ tm('dialogs.delete.title') }}</span>
                </v-card-title>
                <v-card-text class="py-4">
                    <p>{{ tm('dialogs.delete.message') }}</p>
                    <v-alert type="warning" variant="tonal" class="mt-3" v-if="deleteTarget">
                        {{ tm('dialogs.delete.factPreview', { fact: deleteTarget.fact }) }}
                    </v-alert>
                </v-card-text>
                <v-divider></v-divider>
                <v-card-actions class="pa-4">
                    <v-spacer></v-spacer>
                    <v-btn variant="text" @click="dialogDelete = false">{{ tm('dialogs.delete.cancel') }}</v-btn>
                    <v-btn color="error" @click="doDelete" :loading="loading">{{ tm('dialogs.delete.confirm') }}</v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <v-snackbar :timeout="3000" elevation="24" :color="messageType" v-model="showMessage" location="top">
            {{ message }}
        </v-snackbar>
    </div>
</template>

<script>
import axios from 'axios';
import { debounce } from 'lodash';
import { useModuleI18n } from '@/i18n/composables';
import MemoryGraphTab from '@/views/long-term-memory/MemoryGraphTab.vue';

export default {
    name: 'LongTermMemoryPage',
    components: {
        MemoryGraphTab,
    },

    setup() {
        const { tm } = useModuleI18n('features/long-term-memory');
        return { tm };
    },

    data() {
        return {
            activeTab: 'items',
            loading: false,

            // Items
            items: [],
            filters: { scope: null, scopeId: null, type: null, status: null, minConfidence: 0 },
            itemsPagination: { page: 1, page_size: 20, total: 0 },
            pageSizeOptions: [10, 20, 50, 100],

            // Events
            events: [],
            eventsFilters: { scope: null, scopeId: null },
            eventsPagination: { page: 1, page_size: 20, total: 0 },

            // Stats
            stats: {},

            // Dialogs
            dialogDetail: false,
            dialogEdit: false,
            dialogDelete: false,
            selectedItem: null,
            selectedEvidence: [],
            editForm: { fact: '', status: 'shadow', importance: 0.5, ttl_days: null },
            editTargetId: null,
            deleteTarget: null,

            // Messages
            showMessage: false,
            message: '',
            messageType: 'success',

            // Guide
            showGuide: !localStorage.getItem('ltm_guide_dismissed'),
            guideSteps: [
                { key: 'what', icon: 'mdi-brain', color: 'primary' },
                { key: 'how', icon: 'mdi-cog-transfer-outline', color: 'info' },
                { key: 'status', icon: 'mdi-toggle-switch-outline', color: 'warning' },
                { key: 'manage', icon: 'mdi-tune', color: 'success' },
            ],
        };
    },
    watch: {
        activeTab(val) {
            if (val === 'items' && this.items.length === 0) this.fetchItems();
            else if (val === 'events' && this.events.length === 0) this.fetchEvents();
            else if (val === 'stats') this.fetchStats();
        },
    },

    created() {
        this.debouncedFilterChange = debounce(() => {
            this.itemsPagination.page = 1;
            this.fetchItems();
        }, 300);
        this.debouncedEventsFilterChange = debounce(() => {
            this.eventsPagination.page = 1;
            this.fetchEvents();
        }, 300);
        this.fetchItems();
    },

    computed: {
        totalCount() {
            return this.itemsPagination.total || 0;
        },
        itemsTotalPages() {
            return Math.ceil(this.itemsPagination.total / this.itemsPagination.page_size) || 1;
        },
        eventsTotalPages() {
            return Math.ceil(this.eventsPagination.total / this.eventsPagination.page_size) || 1;
        },
        scopeOptions() {
            return [
                { title: this.tm('scopes.user'), value: 'user' },
                { title: this.tm('scopes.group'), value: 'group' },
                { title: this.tm('scopes.project'), value: 'project' },
                { title: this.tm('scopes.global'), value: 'global' },
            ];
        },
        typeOptions() {
            return [
                { title: this.tm('types.profile'), value: 'profile' },
                { title: this.tm('types.preference'), value: 'preference' },
                { title: this.tm('types.task_state'), value: 'task_state' },
                { title: this.tm('types.constraint'), value: 'constraint' },
                { title: this.tm('types.episode'), value: 'episode' },
            ];
        },
        statusOptions() {
            return [
                { title: this.tm('statuses.active'), value: 'active' },
                { title: this.tm('statuses.shadow'), value: 'shadow' },
                { title: this.tm('statuses.disabled'), value: 'disabled' },
                { title: this.tm('statuses.expired'), value: 'expired' },
            ];
        },
        editStatusOptions() {
            return this.statusOptions;
        },
        itemHeaders() {
            return [
                { title: this.tm('table.headers.fact'), key: 'fact', sortable: false },
                { title: this.tm('table.headers.scope'), key: 'scope', sortable: true, width: '100px' },
                { title: this.tm('table.headers.scopeId'), key: 'scope_id', sortable: true, width: '120px' },
                { title: this.tm('table.headers.type'), key: 'type', sortable: true, width: '100px' },
                { title: this.tm('table.headers.status'), key: 'status', sortable: true, width: '100px' },
                { title: this.tm('table.headers.confidence'), key: 'confidence', sortable: true, width: '130px' },
                { title: this.tm('table.headers.importance'), key: 'importance', sortable: true, width: '80px' },
                { title: this.tm('table.headers.createdAt'), key: 'created_at', sortable: true, width: '160px' },
                { title: this.tm('table.headers.actions'), key: 'actions', sortable: false, align: 'center', width: '120px' },
            ];
        },
        eventHeaders() {
            return [
                { title: this.tm('events.headers.eventId'), key: 'event_id', sortable: false, width: '120px' },
                { title: this.tm('events.headers.scope'), key: 'scope', sortable: true, width: '100px' },
                { title: this.tm('events.headers.scopeId'), key: 'scope_id', sortable: true, width: '120px' },
                { title: this.tm('events.headers.sourceType'), key: 'source_type', sortable: true, width: '110px' },
                { title: this.tm('events.headers.sourceRole'), key: 'source_role', sortable: true, width: '100px' },
                { title: this.tm('events.headers.content'), key: 'content', sortable: false },
                { title: this.tm('events.headers.processed'), key: 'processed', sortable: true, width: '100px' },
                { title: this.tm('events.headers.createdAt'), key: 'created_at', sortable: true, width: '160px' },
            ];
        },
    },
    methods: {
        dismissGuide() {
            this.showGuide = false;
            localStorage.setItem('ltm_guide_dismissed', '1');
        },

        async refreshCurrentTab() {
            if (this.activeTab === 'items') this.fetchItems();
            else if (this.activeTab === 'events') this.fetchEvents();
            else if (this.activeTab === 'graph') {
                const graphRef = this.$refs.memoryGraphTab;
                if (graphRef && typeof graphRef.refresh === 'function') {
                    this.loading = true;
                    try {
                        await graphRef.refresh();
                    } finally {
                        this.loading = false;
                    }
                }
            }
            else if (this.activeTab === 'stats') this.fetchStats();
        },

        onFilterChange() {
            this.itemsPagination.page = 1;
            this.fetchItems();
        },

        onEventsFilterChange() {
            this.eventsPagination.page = 1;
            this.fetchEvents();
        },

        onItemsPageSizeChange() {
            this.itemsPagination.page = 1;
            this.fetchItems();
        },

        onEventsPageSizeChange() {
            this.eventsPagination.page = 1;
            this.fetchEvents();
        },

        async fetchItems() {
            this.loading = true;
            try {
                const params = {
                    page: this.itemsPagination.page,
                    page_size: this.itemsPagination.page_size,
                };
                if (this.filters.scope) params.scope = this.filters.scope;
                if (this.filters.scopeId) params.scope_id = this.filters.scopeId;
                if (this.filters.type) params.type = this.filters.type;
                if (this.filters.status) params.status = this.filters.status;
                if (this.filters.minConfidence > 0) params.min_confidence = this.filters.minConfidence;

                const res = await axios.get('/api/ltm/items', { params });
                if (res.data.status === 'ok') {
                    this.items = res.data.data.items;
                    this.itemsPagination.total = res.data.data.total;
                }
            } catch (e) {
                this.showMsg(this.tm('messages.fetchError'), 'error');
            } finally {
                this.loading = false;
            }
        },

        async fetchEvents() {
            this.loading = true;
            try {
                const params = {
                    page: this.eventsPagination.page,
                    page_size: this.eventsPagination.page_size,
                };
                if (this.eventsFilters.scope) params.scope = this.eventsFilters.scope;
                if (this.eventsFilters.scopeId) params.scope_id = this.eventsFilters.scopeId;

                const res = await axios.get('/api/ltm/events', { params });
                if (res.data.status === 'ok') {
                    this.events = res.data.data.events;
                    this.eventsPagination.total = res.data.data.total;
                }
            } catch (e) {
                this.showMsg(this.tm('messages.fetchError'), 'error');
            } finally {
                this.loading = false;
            }
        },

        async fetchStats() {
            this.loading = true;
            try {
                const res = await axios.get('/api/ltm/stats');
                if (res.data.status === 'ok') {
                    this.stats = res.data.data;
                }
            } catch (e) {
                this.showMsg(this.tm('messages.statsError'), 'error');
            } finally {
                this.loading = false;
            }
        },

        async viewItem(item) {
            this.selectedItem = item;
            this.selectedEvidence = [];
            this.dialogDetail = true;
            try {
                const res = await axios.get(`/api/ltm/items/${item.memory_id}`);
                if (res.data.status === 'ok') {
                    this.selectedItem = res.data.data.item;
                    this.selectedEvidence = res.data.data.evidence || [];
                }
            } catch (e) { /* detail fetch failed silently */ }
        },

        editItem(item) {
            this.editTargetId = item.memory_id;
            this.editForm = {
                fact: item.fact,
                status: item.status,
                importance: item.importance,
                ttl_days: item.ttl_days,
            };
            this.dialogEdit = true;
        },

        async saveEdit() {
            this.loading = true;
            try {
                const res = await axios.patch(`/api/ltm/items/${this.editTargetId}`, this.editForm);
                if (res.data.status === 'ok') {
                    this.showMsg(this.tm('messages.updateSuccess'), 'success');
                    this.dialogEdit = false;
                    this.fetchItems();
                } else {
                    this.showMsg(res.data.message || this.tm('messages.updateError'), 'error');
                }
            } catch (e) {
                this.showMsg(this.tm('messages.updateError'), 'error');
            } finally {
                this.loading = false;
            }
        },

        confirmDeleteItem(item) {
            this.deleteTarget = item;
            this.dialogDelete = true;
        },

        async doDelete() {
            if (!this.deleteTarget) return;
            this.loading = true;
            try {
                const res = await axios.delete(`/api/ltm/items/${this.deleteTarget.memory_id}`);
                if (res.data.status === 'ok') {
                    this.showMsg(this.tm('messages.deleteSuccess'), 'success');
                    this.dialogDelete = false;
                    this.deleteTarget = null;
                    this.fetchItems();
                } else {
                    this.showMsg(res.data.message || this.tm('messages.deleteError'), 'error');
                }
            } catch (e) {
                this.showMsg(this.tm('messages.deleteError'), 'error');
            } finally {
                this.loading = false;
            }
        },

        statusColor(status) {
            const map = { active: 'success', shadow: 'warning', disabled: 'grey', expired: 'error' };
            return map[status] || 'grey';
        },

        confidenceColor(val) {
            if (val >= 0.7) return 'success';
            if (val >= 0.4) return 'warning';
            return 'error';
        },

        formatTimestamp(ts) {
            if (!ts) return '-';
            try {
                return new Date(ts).toLocaleString();
            } catch { return ts; }
        },

        showMsg(text, type = 'success') {
            this.message = text;
            this.messageType = type;
            this.showMessage = true;
        },
    },
};
</script>
