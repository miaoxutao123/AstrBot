<template>
    <div class="memory-graph-tab">
        <v-card variant="outlined" class="graph-filter-card">
            <v-card-text class="pb-2">
                <v-row dense class="align-center">
                    <v-col cols="12" sm="6" md="3">
                        <v-select
                            v-model="filters.scope"
                            :items="scopeOptions"
                            :label="tm('graph.filters.scope')"
                            clearable
                            density="compact"
                            variant="solo-filled"
                            flat
                            hide-details
                        />
                    </v-col>
                    <v-col cols="12" sm="6" md="3">
                        <v-text-field
                            v-model="filters.scopeId"
                            :label="tm('graph.filters.scopeId')"
                            density="compact"
                            variant="solo-filled"
                            flat
                            hide-details
                            clearable
                        />
                    </v-col>
                    <v-col cols="12" sm="6" md="3">
                        <v-select
                            v-model="filters.status"
                            :items="statusOptions"
                            :label="tm('graph.filters.status')"
                            clearable
                            density="compact"
                            variant="solo-filled"
                            flat
                            hide-details
                        />
                    </v-col>
                    <v-col cols="12" sm="6" md="3">
                        <v-combobox
                            v-model="filters.predicate"
                            :items="predicateOptions"
                            :label="tm('graph.filters.predicate')"
                            clearable
                            density="compact"
                            variant="solo-filled"
                            flat
                            hide-details
                        />
                    </v-col>
                </v-row>

                <v-row dense class="align-center mt-1">
                    <v-col cols="12" md="4">
                        <v-slider
                            v-model="filters.minConfidence"
                            :label="tm('graph.filters.minConfidence')"
                            :min="0"
                            :max="1"
                            :step="0.05"
                            thumb-label="always"
                            hide-details
                            color="teal"
                        />
                    </v-col>
                    <v-col cols="12" md="3">
                        <v-select
                            v-model="filters.maxRelations"
                            :items="maxRelationOptions"
                            :label="tm('graph.filters.maxRelations')"
                            density="compact"
                            variant="solo-filled"
                            flat
                            hide-details
                        />
                    </v-col>
                    <v-col cols="12" md="5" class="d-flex justify-end ga-2 mt-2 mt-md-0">
                        <v-btn
                            color="primary"
                            variant="tonal"
                            prepend-icon="mdi-filter-check"
                            :loading="loading"
                            @click="fetchGraphData"
                        >
                            {{ tm('graph.actions.apply') }}
                        </v-btn>
                        <v-btn
                            color="info"
                            variant="tonal"
                            prepend-icon="mdi-refresh"
                            :loading="loading"
                            @click="refresh"
                        >
                            {{ tm('graph.actions.reload') }}
                        </v-btn>
                    </v-col>
                </v-row>
            </v-card-text>
        </v-card>

        <v-row dense class="mt-4">
            <v-col cols="12" md="8">
                <v-card class="graph-stage-card" flat>
                    <div class="graph-stage-header d-flex align-center px-4 py-3">
                        <div>
                            <div class="text-subtitle-1 font-weight-medium text-white">{{ tm('graph.canvasTitle') }}</div>
                            <div class="text-caption text-white text-opacity-80">{{ tm('graph.canvasHint') }}</div>
                        </div>
                        <v-spacer></v-spacer>
                        <div class="d-flex ga-2 flex-wrap justify-end align-center">
                            <v-chip size="small" color="teal" variant="flat">{{ tm('graph.stats.nodes', { count: graphStats.nodes }) }}</v-chip>
                            <v-chip size="small" color="orange" variant="flat">{{ tm('graph.stats.edges', { count: graphStats.edges }) }}</v-chip>
                            <v-chip size="small" color="cyan-darken-2" variant="flat">
                                {{ tm('graph.stats.predicates', { count: graphStats.predicates }) }}
                            </v-chip>
                            <v-btn-toggle
                                v-model="layoutMode"
                                density="compact"
                                variant="outlined"
                                mandatory
                                class="ml-1 layout-toggle"
                            >
                                <v-btn value="force" size="small" title="力导向布局">
                                    <v-icon size="15">mdi-graph-outline</v-icon>
                                </v-btn>
                                <v-btn value="bipartite" size="small" title="二分列布局">
                                    <v-icon size="15">mdi-view-column-outline</v-icon>
                                </v-btn>
                            </v-btn-toggle>
                            <v-btn
                                icon
                                variant="text"
                                size="small"
                                :title="zoom === 1 ? '放大' : '重置缩放'"
                                @click="resetZoom"
                            >
                                <v-icon size="16" color="white">{{ zoom === 1 ? 'mdi-magnify-plus-outline' : 'mdi-magnify-remove-outline' }}</v-icon>
                            </v-btn>
                        </div>
                    </div>

                    <div ref="graphViewport" class="graph-viewport" @wheel.prevent="onWheel">
                        <svg
                            class="memory-graph-svg"
                            :viewBox="`0 0 ${viewport.width} ${viewport.height}`"
                            preserveAspectRatio="xMidYMid meet"
                            :style="svgTransformStyle"
                            @click="clearSelection"
                            @mousedown="onSvgMouseDown"
                        >
                            <defs>
                                <linearGradient id="ltmGraphBackground" x1="0%" y1="0%" x2="100%" y2="100%">
                                    <stop offset="0%" stop-color="#08131f" />
                                    <stop offset="60%" stop-color="#0d2a33" />
                                    <stop offset="100%" stop-color="#13322a" />
                                </linearGradient>
                                <filter id="ltmGraphNodeGlow" x="-60%" y="-60%" width="220%" height="220%">
                                    <feGaussianBlur stdDeviation="3.2" result="blur" />
                                    <feMerge>
                                        <feMergeNode in="blur" />
                                        <feMergeNode in="SourceGraphic" />
                                    </feMerge>
                                </filter>
                            </defs>

                            <rect x="0" y="0" :width="viewport.width" :height="viewport.height" fill="url(#ltmGraphBackground)" />

                            <g class="graph-grid">
                                <line
                                    v-for="idx in 6"
                                    :key="`grid-${idx}`"
                                    x1="0"
                                    :y1="(viewport.height / 7) * idx"
                                    :x2="viewport.width"
                                    :y2="(viewport.height / 7) * idx"
                                />
                            </g>

                            <g v-if="graphLayout.edges.length > 0" class="graph-edge-layer">
                                <path
                                    v-for="edge in graphLayout.edges"
                                    :key="edge.relation_id"
                                    :d="edgePath(edge)"
                                    :stroke="edge.color"
                                    :stroke-width="edgeWidth(edge)"
                                    :stroke-opacity="edgeOpacity(edge)"
                                    fill="none"
                                    class="graph-edge"
                                    @click.stop="selectRelation(edge.relation_id)"
                                >
                                    <title>
                                        {{ edge.subjectLabel }}
                                        {{ edge.predicate }}
                                        {{ edge.objectLabel }}
                                    </title>
                                </path>
                            </g>

                            <g v-if="graphLayout.nodes.length > 0" class="graph-node-layer">
                                <g
                                    v-for="node in graphLayout.nodes"
                                    :key="node.id"
                                    :transform="`translate(${node.x}, ${node.y})`"
                                    class="graph-node"
                                    :class="{ 'is-selected': selectedNodeId === node.id }"
                                    @click.stop="selectNode(node.id)"
                                >
                                    <circle
                                        class="graph-node-halo"
                                        :r="node.r + 3"
                                        :fill="node.kind === 'subject' ? '#2be7d8' : '#ffc46b'"
                                        :opacity="nodeOpacity(node) * 0.22"
                                        filter="url(#ltmGraphNodeGlow)"
                                    />
                                    <circle
                                        :r="node.r"
                                        :fill="node.kind === 'subject' ? '#14b8a6' : '#f59e0b'"
                                        :opacity="nodeOpacity(node)"
                                        stroke="#f8fafc"
                                        stroke-opacity="0.9"
                                        :stroke-width="selectedNodeId === node.id ? 2.4 : 1.2"
                                    />
                                    <text
                                        v-if="showNodeLabel(node)"
                                        class="graph-node-label"
                                        :x="nodeLabelX(node)"
                                        :y="nodeLabelY(node)"
                                        :text-anchor="nodeLabelAnchor(node)"
                                    >
                                        {{ node.displayLabel }}
                                    </text>
                                </g>
                            </g>

                            <g v-if="graphLayout.edges.length === 0" class="graph-empty-state">
                                <text :x="viewport.width / 2" :y="viewport.height / 2 - 12">
                                    {{ tm('graph.empty.title') }}
                                </text>
                                <text :x="viewport.width / 2" :y="viewport.height / 2 + 18" class="graph-empty-hint">
                                    {{ tm('graph.empty.hint') }}
                                </text>
                            </g>
                        </svg>
                    </div>
                </v-card>
            </v-col>

            <v-col cols="12" md="4">
                <v-card variant="outlined" class="detail-panel">
                    <v-card-title class="text-subtitle-1 d-flex align-center">
                        <v-icon class="mr-2" color="primary">mdi-radar</v-icon>
                        {{ tm('graph.panels.details') }}
                    </v-card-title>
                    <v-divider></v-divider>
                    <v-card-text>
                        <template v-if="selectedRelation">
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.subject') }}</span>
                                <span>{{ selectedRelation.subjectLabel }}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.predicate') }}</span>
                                <v-chip size="small" :color="selectedRelation.color" variant="flat">{{ selectedRelation.predicate }}</v-chip>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.object') }}</span>
                                <span>{{ selectedRelation.objectLabel }}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.confidence') }}</span>
                                <span>{{ formatPercent(selectedRelation.confidence) }}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.scope') }}</span>
                                <span>{{ selectedRelation.scope }} / {{ selectedRelation.scope_id }}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.status') }}</span>
                                <v-chip size="small" label>{{ selectedRelation.status || '-' }}</v-chip>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.memoryType') }}</span>
                                <span>{{ selectedRelation.memory_type || '-' }}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.memoryId') }}</span>
                                <span class="text-truncate d-inline-block detail-mono">{{ selectedRelation.memory_id || '-' }}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.updatedAt') }}</span>
                                <span>{{ formatTimestamp(selectedRelation.updated_at) }}</span>
                            </div>
                        </template>

                        <template v-else-if="selectedNode">
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.nodeType') }}</span>
                                <v-chip size="small" :color="selectedNode.kind === 'subject' ? 'teal' : 'orange'" variant="flat">
                                    {{ selectedNode.kind === 'subject' ? tm('graph.legend.subject') : tm('graph.legend.object') }}
                                </v-chip>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.value') }}</span>
                                <span>{{ selectedNode.rawLabel }}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.connections') }}</span>
                                <span>{{ selectedNode.degree }}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">{{ tm('graph.fields.avgConfidence') }}</span>
                                <span>{{ formatPercent(selectedNode.avgConfidence) }}</span>
                            </div>

                            <v-divider class="my-3"></v-divider>
                            <div class="text-subtitle-2 mb-2">{{ tm('graph.fields.connectedEdges') }}</div>
                            <div v-if="selectedNodeEdges.length > 0" class="connected-list">
                                <v-chip
                                    v-for="edge in selectedNodeEdges"
                                    :key="edge.relation_id"
                                    size="small"
                                    class="mr-1 mb-1"
                                    :color="edge.color"
                                    variant="tonal"
                                    @click="selectRelation(edge.relation_id)"
                                >
                                    {{ edge.predicate }} · {{ edge.counterpartLabel }}
                                </v-chip>
                            </div>
                            <div v-else class="text-caption text-medium-emphasis">{{ tm('graph.empty.noConnections') }}</div>
                        </template>

                        <div v-else class="text-body-2 text-medium-emphasis py-2">
                            {{ tm('graph.panels.noneSelected') }}
                        </div>
                    </v-card-text>
                </v-card>

                <v-card variant="outlined" class="detail-panel mt-3">
                    <v-card-title class="text-subtitle-1 d-flex align-center">
                        <v-icon class="mr-2" color="primary">mdi-shape-outline</v-icon>
                        {{ tm('graph.panels.legend') }}
                    </v-card-title>
                    <v-divider></v-divider>
                    <v-card-text>
                        <div class="d-flex align-center mb-2">
                            <span class="legend-dot legend-subject"></span>
                            <span>{{ tm('graph.legend.subject') }}</span>
                        </div>
                        <div class="d-flex align-center mb-4">
                            <span class="legend-dot legend-object"></span>
                            <span>{{ tm('graph.legend.object') }}</span>
                        </div>

                        <div class="text-subtitle-2 mb-2">{{ tm('graph.legend.predicates') }}</div>
                        <div class="predicate-list">
                            <v-chip
                                v-for="entry in predicateLegend"
                                :key="entry.predicate"
                                size="small"
                                class="mr-1 mb-1"
                                :color="entry.color"
                                variant="tonal"
                            >
                                {{ entry.predicate }} ({{ entry.count }})
                            </v-chip>
                            <div v-if="predicateLegend.length === 0" class="text-caption text-medium-emphasis">
                                {{ tm('graph.empty.noPredicates') }}
                            </div>
                        </div>
                    </v-card-text>
                </v-card>
            </v-col>
        </v-row>

        <v-snackbar v-model="showMessage" :timeout="3000" :color="messageType" location="top">
            {{ message }}
        </v-snackbar>
    </div>
</template>

<script>
import axios from 'axios';

import { useModuleI18n } from '@/i18n/composables';

const EDGE_PALETTE = [
    '#38bdf8',
    '#22d3ee',
    '#34d399',
    '#f59e0b',
    '#fb7185',
    '#f97316',
    '#06b6d4',
    '#84cc16',
    '#ef4444',
    '#14b8a6',
];

function hashString(input) {
    const value = String(input || '');
    let hash = 0;
    for (let i = 0; i < value.length; i += 1) {
        hash = (hash << 5) - hash + value.charCodeAt(i);
        hash |= 0;
    }
    return Math.abs(hash);
}

function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

function toNumber(value, fallback = 0) {
    const num = Number(value);
    return Number.isFinite(num) ? num : fallback;
}

function truncateText(value, max = 30) {
    const text = String(value || '').trim();
    if (!text) return '-';
    if (text.length <= max) return text;
    return `${text.slice(0, Math.max(max - 1, 1))}…`;
}

function distributePositions(nodes, x, top, bottom) {
    if (nodes.length === 0) return;
    if (nodes.length === 1) {
        nodes[0].x = x;
        nodes[0].y = (top + bottom) / 2;
        return;
    }

    const span = Math.max(bottom - top, 1);
    const step = span / (nodes.length - 1);

    nodes.forEach((node, idx) => {
        const offset = ((hashString(node.id) % 19) - 9) * 1.8;
        const wobble = ((hashString(node.rawLabel) % 13) - 6) * 2.4;
        node.x = x + offset;
        node.y = clamp(top + idx * step + wobble, top, bottom);
    });
}

/**
 * Force-directed layout simulation (pure JS, no dependencies).
 * Mutates node.x / node.y in place.
 * Time: O(N² * iters) – acceptable for N ≤ 500 on modern hardware.
 */
function runForceLayout(nodes, edges, width, height) {
    const N = nodes.length;
    if (N === 0) return;

    const PAD = 55;
    const w = Math.max(width, 500);
    const h = Math.max(height, 300);
    const cx = w / 2;
    const cy = h / 2;
    // Ideal edge length scales with canvas area per node
    const IDEAL_LEN = clamp(Math.sqrt((w * h) / Math.max(N, 1)) * 0.85, 70, 220);
    const REPULSION = IDEAL_LEN * IDEAL_LEN * 1.4;
    const SPRING_K = 0.05;
    const CENTER_K = 0.018;
    const DAMPING = 0.82;
    const ITERS = clamp(Math.floor(14000 / Math.max(N, 1) + 60), 80, 320);

    // Deterministic initial positions – spiral to avoid all-at-center singularity
    const phi = (1 + Math.sqrt(5)) / 2; // golden angle
    for (let i = 0; i < N; i++) {
        const node = nodes[i];
        const t = i / Math.max(N - 1, 1);
        const angle = i * phi * Math.PI * 2 + (hashString(node.id) % 100) * 0.01;
        const r = IDEAL_LEN * (0.6 + t * 1.8);
        node.x = clamp(cx + Math.cos(angle) * r, PAD, w - PAD);
        node.y = clamp(cy + Math.sin(angle) * r, PAD, h - PAD);
        node.vx = 0;
        node.vy = 0;
    }

    // Index: node.id → array index
    const idx = new Map();
    nodes.forEach((n, i) => idx.set(n.id, i));

    const fx = new Float64Array(N);
    const fy = new Float64Array(N);

    for (let iter = 0; iter < ITERS; iter++) {
        const alpha = Math.max(0.04, 1 - iter / (ITERS * 0.85)); // cooling factor
        fx.fill(0);
        fy.fill(0);

        // Node–node repulsion
        for (let i = 0; i < N; i++) {
            for (let j = i + 1; j < N; j++) {
                const dx = nodes[i].x - nodes[j].x;
                const dy = nodes[i].y - nodes[j].y;
                const dist2 = dx * dx + dy * dy + 0.25;
                const dist = Math.sqrt(dist2);
                const force = (REPULSION / dist2) * Math.min(dist, IDEAL_LEN * 2) / Math.max(dist, 1);
                const fx_ij = force * dx / dist;
                const fy_ij = force * dy / dist;
                fx[i] += fx_ij;
                fy[i] += fy_ij;
                fx[j] -= fx_ij;
                fy[j] -= fy_ij;
            }
        }

        // Edge spring forces
        for (const edge of edges) {
            const si = idx.get(edge.source);
            const ti = idx.get(edge.target);
            if (si === undefined || ti === undefined || si === ti) continue;
            const dx = nodes[ti].x - nodes[si].x;
            const dy = nodes[ti].y - nodes[si].y;
            const dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
            const force = SPRING_K * (dist - IDEAL_LEN);
            fx[si] += force * dx / dist;
            fy[si] += force * dy / dist;
            fx[ti] -= force * dx / dist;
            fy[ti] -= force * dy / dist;
        }

        // Centering gravity
        for (let i = 0; i < N; i++) {
            fx[i] += CENTER_K * (cx - nodes[i].x) * alpha;
            fy[i] += CENTER_K * (cy - nodes[i].y) * alpha;
        }

        // Integrate
        for (let i = 0; i < N; i++) {
            nodes[i].vx = (nodes[i].vx + fx[i] * alpha) * DAMPING;
            nodes[i].vy = (nodes[i].vy + fy[i] * alpha) * DAMPING;
            nodes[i].x = clamp(nodes[i].x + nodes[i].vx, PAD, w - PAD);
            nodes[i].y = clamp(nodes[i].y + nodes[i].vy, PAD, h - PAD);
        }
    }
}

export default {
    name: 'MemoryGraphTab',

    setup() {
        const { tm } = useModuleI18n('features/long-term-memory');
        return { tm };
    },

    data() {
        return {
            loading: false,
            relations: [],
            predicateOptions: [],
            layoutMode: 'force',
            zoom: 1,
            panX: 0,
            panY: 0,
            _pan: { active: false, startX: 0, startY: 0, originX: 0, originY: 0 },
            filters: {
                scope: null,
                scopeId: '',
                status: 'active',
                predicate: null,
                minConfidence: 0.25,
                maxRelations: 140,
            },
            maxRelationOptions: [80, 140, 220, 320, 500],
            viewport: {
                width: 1100,
                height: 620,
            },
            resizeObserver: null,
            selectedNodeId: null,
            selectedRelationId: null,
            showMessage: false,
            message: '',
            messageType: 'success',
        };
    },

    computed: {
        scopeOptions() {
            return [
                { title: this.tm('scopes.user'), value: 'user' },
                { title: this.tm('scopes.group'), value: 'group' },
                { title: this.tm('scopes.project'), value: 'project' },
                { title: this.tm('scopes.global'), value: 'global' },
            ];
        },

        statusOptions() {
            return [
                { title: this.tm('statuses.active'), value: 'active' },
                { title: this.tm('graph.statuses.superseded'), value: 'superseded' },
                { title: this.tm('statuses.disabled'), value: 'disabled' },
            ];
        },

        graphLayout() {
            const minConfidence = toNumber(this.filters.minConfidence, 0);
            const maxRelations = toNumber(this.filters.maxRelations, 140);

            const filteredRelations = [...this.relations]
                .filter((rel) => toNumber(rel.confidence, 0) >= minConfidence)
                .sort((a, b) => {
                    const confDelta = toNumber(b.confidence, 0) - toNumber(a.confidence, 0);
                    if (Math.abs(confDelta) > 1e-9) return confDelta;
                    return String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
                })
                .slice(0, maxRelations);

            const nodesMap = new Map();
            const edges = [];

            for (const rel of filteredRelations) {
                const subjectRaw = String(rel.subject_key || '').trim() || this.tm('graph.defaults.unknownSubject');
                const objectRaw = String(rel.object_text || '').trim() || this.tm('graph.defaults.unknownObject');
                const predicate = String(rel.predicate || '').trim() || this.tm('graph.defaults.unknownPredicate');

                const subjectId = `s:${subjectRaw}`;
                const objectId = `o:${objectRaw}`;

                if (!nodesMap.has(subjectId)) {
                    nodesMap.set(subjectId, {
                        id: subjectId,
                        kind: 'subject',
                        rawLabel: subjectRaw,
                        displayLabel: truncateText(subjectRaw, 28),
                        degree: 0,
                        confidenceTotal: 0,
                        avgConfidence: 0,
                        x: 0,
                        y: 0,
                        r: 10,
                    });
                }

                if (!nodesMap.has(objectId)) {
                    nodesMap.set(objectId, {
                        id: objectId,
                        kind: 'object',
                        rawLabel: objectRaw,
                        displayLabel: truncateText(objectRaw, 28),
                        degree: 0,
                        confidenceTotal: 0,
                        avgConfidence: 0,
                        x: 0,
                        y: 0,
                        r: 10,
                    });
                }

                const subjectNode = nodesMap.get(subjectId);
                const objectNode = nodesMap.get(objectId);
                const confidence = toNumber(rel.confidence, 0);

                subjectNode.degree += 1;
                objectNode.degree += 1;
                subjectNode.confidenceTotal += confidence;
                objectNode.confidenceTotal += confidence;

                const color = EDGE_PALETTE[hashString(predicate) % EDGE_PALETTE.length];
                const curvature = ((hashString(`${predicate}-${rel.relation_id}`) % 15) - 7) * 6.5;

                edges.push({
                    ...rel,
                    relation_id: rel.relation_id,
                    source: subjectId,
                    target: objectId,
                    predicate,
                    color,
                    confidence,
                    curvature,
                    subjectLabel: subjectRaw,
                    objectLabel: objectRaw,
                });
            }

            const nodes = Array.from(nodesMap.values());

            const subjectNodes = nodes
                .filter((node) => node.kind === 'subject')
                .sort((a, b) => b.degree - a.degree || a.rawLabel.localeCompare(b.rawLabel));
            const objectNodes = nodes
                .filter((node) => node.kind === 'object')
                .sort((a, b) => b.degree - a.degree || a.rawLabel.localeCompare(b.rawLabel));

            const width = Math.max(toNumber(this.viewport.width, 1100), 720);
            const height = Math.max(toNumber(this.viewport.height, 620), 360);

            const topPadding = 58;
            const bottomPadding = height - 44;

            if (this.layoutMode === 'bipartite') {
                distributePositions(subjectNodes, width * 0.28, topPadding, bottomPadding);
                distributePositions(objectNodes, width * 0.72, topPadding, bottomPadding);
            } else {
                // Force-directed: subjects and objects mix freely
                runForceLayout(nodes, edges, width, height);
            }

            for (const node of nodes) {
                node.r = clamp(8 + Math.sqrt(Math.max(node.degree, 1)) * 2.6, 8, 22);
                node.avgConfidence = node.degree > 0 ? node.confidenceTotal / node.degree : 0;
            }

            const nodeIndex = {};
            for (const node of nodes) {
                nodeIndex[node.id] = node;
            }

            const laidOutEdges = edges
                .map((edge) => ({
                    ...edge,
                    sourceNode: nodeIndex[edge.source],
                    targetNode: nodeIndex[edge.target],
                }))
                .filter((edge) => edge.sourceNode && edge.targetNode);

            return {
                nodes,
                edges: laidOutEdges,
                nodeIndex,
            };
        },

        graphStats() {
            const predicateSet = new Set(this.graphLayout.edges.map((edge) => edge.predicate));
            return {
                nodes: this.graphLayout.nodes.length,
                edges: this.graphLayout.edges.length,
                predicates: predicateSet.size,
            };
        },

        svgTransformStyle() {
            // CSS transform for zoom/pan – purely visual, SVG coordinates unchanged
            return {
                transform: `scale(${this.zoom}) translate(${this.panX}px, ${this.panY}px)`,
                transformOrigin: 'center center',
                cursor: this.zoom > 1 ? 'grab' : 'default',
            };
        },

        selectedNode() {
            if (!this.selectedNodeId) return null;
            return this.graphLayout.nodeIndex[this.selectedNodeId] || null;
        },

        selectedRelation() {
            if (!this.selectedRelationId) return null;
            return this.graphLayout.edges.find((edge) => edge.relation_id === this.selectedRelationId) || null;
        },

        selectedNodeEdges() {
            if (!this.selectedNode) return [];
            return this.graphLayout.edges
                .filter((edge) => edge.source === this.selectedNode.id || edge.target === this.selectedNode.id)
                .map((edge) => ({
                    ...edge,
                    counterpartLabel: edge.source === this.selectedNode.id ? edge.objectLabel : edge.subjectLabel,
                }))
                .sort((a, b) => b.confidence - a.confidence)
                .slice(0, 8);
        },

        predicateLegend() {
            const countMap = new Map();
            for (const edge of this.graphLayout.edges) {
                const prev = countMap.get(edge.predicate);
                if (prev) {
                    prev.count += 1;
                } else {
                    countMap.set(edge.predicate, {
                        predicate: edge.predicate,
                        count: 1,
                        color: edge.color,
                    });
                }
            }
            return Array.from(countMap.values()).sort((a, b) => b.count - a.count).slice(0, 14);
        },
    },

    watch: {
        graphLayout(newLayout) {
            if (this.selectedNodeId && !newLayout.nodeIndex[this.selectedNodeId]) {
                this.selectedNodeId = null;
            }
            if (
                this.selectedRelationId
                && !newLayout.edges.some((edge) => edge.relation_id === this.selectedRelationId)
            ) {
                this.selectedRelationId = null;
            }
        },
    },

    mounted() {
        this.observeViewport();
        this.fetchGraphData();
    },

    beforeUnmount() {
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
    },

    methods: {
        async refresh() {
            await this.fetchGraphData();
        },

        async fetchGraphData() {
            this.loading = true;
            try {
                const pageSize = 200;
                const requestedLimit = Math.max(toNumber(this.filters.maxRelations, 140) * 3, 240);
                const maxPages = Math.ceil(requestedLimit / pageSize) + 2;

                const collected = [];
                let page = 1;
                let total = Number.POSITIVE_INFINITY;

                while (page <= maxPages && collected.length < requestedLimit && collected.length < total) {
                    const params = {
                        page,
                        page_size: pageSize,
                    };

                    if (this.filters.scope) params.scope = this.filters.scope;
                    if (this.filters.scopeId && this.filters.scopeId.trim()) params.scope_id = this.filters.scopeId.trim();
                    if (this.filters.status) params.status = this.filters.status;
                    if (this.filters.predicate && String(this.filters.predicate).trim()) {
                        params.predicate = String(this.filters.predicate).trim();
                    }

                    const response = await axios.get('/api/ltm/relations', { params });
                    if (response.data.status !== 'ok') {
                        throw new Error(response.data.message || this.tm('graph.messages.fetchError'));
                    }

                    const payload = response.data.data || {};
                    const rows = Array.isArray(payload.relations) ? payload.relations : [];
                    total = toNumber(payload.total, rows.length);
                    collected.push(...rows);

                    if (rows.length === 0 || collected.length >= total) break;
                    page += 1;
                }

                this.relations = collected;

                const predicates = new Set();
                for (const relation of collected) {
                    const predicate = String(relation.predicate || '').trim();
                    if (predicate) predicates.add(predicate);
                }
                this.predicateOptions = Array.from(predicates).sort();
                this.clearSelection();
            } catch (error) {
                this.showMsg(this.tm('graph.messages.fetchError'), 'error');
            } finally {
                this.loading = false;
            }
        },

        clearSelection() {
            this.selectedNodeId = null;
            this.selectedRelationId = null;
        },

        selectNode(nodeId) {
            this.selectedNodeId = nodeId;
            this.selectedRelationId = null;
        },

        selectRelation(relationId) {
            this.selectedRelationId = relationId;
            this.selectedNodeId = null;
        },

        edgePath(edge) {
            const source = edge.sourceNode;
            const target = edge.targetNode;
            if (!source || !target) return '';

            if (this.layoutMode === 'force') {
                // Quadratic Bezier with perpendicular offset – works for any angle
                const sx = source.x;
                const sy = source.y;
                const tx = target.x;
                const ty = target.y;
                const mx = (sx + tx) / 2;
                const my = (sy + ty) / 2;
                const len = Math.sqrt((tx - sx) ** 2 + (ty - sy) ** 2) + 0.1;
                const bend = edge.curvature * 0.55;
                // Perpendicular vector (normalized), scaled by bend
                const nx = -(ty - sy) / len * bend;
                const ny = (tx - sx) / len * bend;
                return `M ${sx} ${sy} Q ${mx + nx} ${my + ny} ${tx} ${ty}`;
            }

            // Bipartite: horizontal cubic Bezier
            const dx = target.x - source.x;
            const c1x = source.x + dx * 0.34;
            const c2x = source.x + dx * 0.66;
            const bend = edge.curvature;
            return `M ${source.x} ${source.y} C ${c1x} ${source.y + bend}, ${c2x} ${target.y - bend}, ${target.x} ${target.y}`;
        },

        edgeWidth(edge) {
            const baseWidth = 1 + edge.confidence * 2.8;
            if (this.selectedRelationId === edge.relation_id) return baseWidth + 1.6;
            if (this.selectedNodeId && (edge.source === this.selectedNodeId || edge.target === this.selectedNodeId)) {
                return baseWidth + 0.9;
            }
            return baseWidth;
        },

        edgeOpacity(edge) {
            if (this.selectedRelationId) {
                return this.selectedRelationId === edge.relation_id ? 0.96 : 0.08;
            }
            if (this.selectedNodeId) {
                return edge.source === this.selectedNodeId || edge.target === this.selectedNodeId ? 0.88 : 0.1;
            }
            return 0.6;
        },

        nodeOpacity(node) {
            if (this.selectedNodeId) {
                if (node.id === this.selectedNodeId) return 1;
                const connected = this.graphLayout.edges.some(
                    (edge) => (edge.source === node.id && edge.target === this.selectedNodeId)
                        || (edge.target === node.id && edge.source === this.selectedNodeId),
                );
                return connected ? 0.88 : 0.22;
            }

            if (this.selectedRelationId) {
                const relation = this.graphLayout.edges.find((edge) => edge.relation_id === this.selectedRelationId);
                if (!relation) return 0.35;
                if (relation.source === node.id || relation.target === node.id) return 1;
                return 0.2;
            }

            return 0.9;
        },

        showNodeLabel(node) {
            if (this.selectedNodeId || this.selectedRelationId) return true;
            if (this.viewport.width < 860) return node.degree >= 3;
            return node.degree >= 2;
        },

        formatTimestamp(ts) {
            if (!ts) return '-';
            try {
                return new Date(ts).toLocaleString();
            } catch {
                return String(ts);
            }
        },

        formatPercent(val) {
            return `${(toNumber(val, 0) * 100).toFixed(0)}%`;
        },

        showMsg(text, type = 'success') {
            this.message = text;
            this.messageType = type;
            this.showMessage = true;
        },

        // ── Node label positioning ────────────────────────────────────────
        nodeLabelX(node) {
            if (this.layoutMode !== 'force') {
                // Bipartite: label to the side
                return node.kind === 'subject' ? -(node.r + 8) : node.r + 8;
            }
            // Force: label below node, horizontally centered
            return 0;
        },

        nodeLabelY(node) {
            if (this.layoutMode !== 'force') {
                return 0; // vertically centered (dominant-baseline: middle)
            }
            return node.r + 13;
        },

        nodeLabelAnchor(node) {
            if (this.layoutMode !== 'force') {
                return node.kind === 'subject' ? 'end' : 'start';
            }
            return 'middle';
        },

        // ── Zoom / Pan ────────────────────────────────────────────────────
        onWheel(e) {
            const factor = e.deltaY < 0 ? 1.12 : 0.9;
            this.zoom = Math.min(Math.max(this.zoom * factor, 0.25), 5);
        },

        onSvgMouseDown(e) {
            // Only plain left-click drag (not on a node/edge – those use .stop)
            if (e.button !== 0) return;
            const startX = e.clientX;
            const startY = e.clientY;
            const originX = this.panX;
            const originY = this.panY;
            const vp = this.$refs.graphViewport;
            const cssW = vp ? vp.clientWidth : 1;
            const scale = (this.viewport.width / cssW) / this.zoom;

            const onMove = (me) => {
                this.panX = originX + (me.clientX - startX) * scale;
                this.panY = originY + (me.clientY - startY) * scale;
            };
            const onUp = () => {
                window.removeEventListener('mousemove', onMove);
                window.removeEventListener('mouseup', onUp);
            };
            window.addEventListener('mousemove', onMove);
            window.addEventListener('mouseup', onUp);
        },

        resetZoom() {
            this.zoom = 1;
            this.panX = 0;
            this.panY = 0;
        },

        observeViewport() {
            const target = this.$refs.graphViewport;
            if (!target) return;

            const updateSize = () => {
                const width = Math.max(Math.floor(target.clientWidth), 720);
                const height = Math.max(Math.floor(target.clientHeight), 360);
                this.viewport = { width, height };
            };

            updateSize();

            this.resizeObserver = new ResizeObserver(() => {
                updateSize();
            });

            this.resizeObserver.observe(target);
        },
    },
};
</script>

<style scoped>
.memory-graph-tab {
    min-height: 660px;
}

.graph-filter-card {
    border-color: rgba(15, 23, 42, 0.08);
    background: linear-gradient(120deg, rgba(45, 212, 191, 0.06), rgba(56, 189, 248, 0.08));
}

.graph-stage-card {
    border-radius: 18px;
    overflow: hidden;
    box-shadow: 0 20px 40px rgba(2, 22, 34, 0.26);
}

.graph-stage-header {
    background: linear-gradient(120deg, #0f766e, #0f4c5c, #155e75);
    border-bottom: 1px solid rgba(255, 255, 255, 0.15);
}

.graph-viewport {
    position: relative;
    width: 100%;
    height: clamp(360px, 60vh, 700px);
    overflow: hidden;
}

.memory-graph-svg {
    width: 100%;
    height: 100%;
    display: block;
}

.graph-grid line {
    stroke: rgba(255, 255, 255, 0.09);
    stroke-width: 1;
}

.graph-edge {
    cursor: pointer;
    transition: stroke-opacity 0.2s ease, stroke-width 0.2s ease;
    stroke-linecap: round;
    animation: edgePulse 5.5s ease-in-out infinite;
}

.graph-node {
    cursor: pointer;
    transition: transform 0.2s ease;
}

.graph-node.is-selected {
    transform: scale(1.04);
}

.graph-node-label {
    fill: rgba(241, 245, 249, 0.96);
    font-size: 11px;
    dominant-baseline: middle;
    paint-order: stroke;
    stroke: rgba(8, 47, 73, 0.88);
    stroke-width: 3;
    stroke-linejoin: round;
    pointer-events: none;
    user-select: none;
}

.layout-toggle {
    border-color: rgba(255, 255, 255, 0.3) !important;
}

.layout-toggle .v-btn {
    color: rgba(255, 255, 255, 0.7) !important;
    min-width: 32px !important;
}

.layout-toggle .v-btn--active {
    color: #2dd4bf !important;
    background: rgba(45, 212, 191, 0.2) !important;
}

.graph-empty-state text {
    fill: rgba(241, 245, 249, 0.95);
    text-anchor: middle;
    font-size: 16px;
}

.graph-empty-state .graph-empty-hint {
    font-size: 13px;
    fill: rgba(226, 232, 240, 0.7);
}

.detail-panel {
    border-color: rgba(15, 23, 42, 0.1);
    background: linear-gradient(160deg, rgba(248, 250, 252, 0.94), rgba(235, 244, 251, 0.92));
}

.detail-item {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 10px;
    font-size: 13px;
}

.detail-label {
    color: rgba(15, 23, 42, 0.68);
    font-weight: 600;
    white-space: nowrap;
}

.detail-mono {
    max-width: 190px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.legend-dot {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    display: inline-block;
    margin-right: 8px;
}

.legend-subject {
    background: #14b8a6;
}

.legend-object {
    background: #f59e0b;
}

.predicate-list {
    min-height: 40px;
}

.connected-list {
    max-height: 160px;
    overflow-y: auto;
}

@keyframes edgePulse {
    0%,
    100% {
        stroke-dasharray: 3 6;
        stroke-dashoffset: 0;
    }
    50% {
        stroke-dasharray: 2 8;
        stroke-dashoffset: -10;
    }
}

@media (max-width: 960px) {
    .memory-graph-tab {
        min-height: unset;
    }

    .graph-viewport {
        height: 420px;
    }
}
</style>
