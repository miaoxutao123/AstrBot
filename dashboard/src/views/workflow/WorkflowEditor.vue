<template>
  <v-container fluid class="workflow-editor pa-0">
    <!-- Toolbar -->
    <v-toolbar density="compact" class="workflow-toolbar">
      <v-btn icon="mdi-arrow-left" variant="text" @click="goBack"></v-btn>
      <v-text-field
        v-model="workflowName"
        variant="plain"
        density="compact"
        hide-details
        :placeholder="tm('untitled')"
        class="workflow-name-input mx-2"
      ></v-text-field>
      <v-spacer></v-spacer>
      <v-btn variant="text" @click="testWorkflow" :loading="testing" :disabled="!canTest">
        <v-icon left>mdi-play</v-icon>
        {{ tm('test') }}
      </v-btn>
      <v-btn color="primary" variant="flat" @click="saveWorkflow" :loading="saving">
        <v-icon left>mdi-content-save</v-icon>
        {{ tm('save') }}
      </v-btn>
    </v-toolbar>

    <v-row no-gutters class="workflow-content">
      <!-- Node Palette -->
      <v-col cols="2" class="node-palette">
        <div class="pa-3">
          <h4 class="text-subtitle-2 mb-3">{{ tm('nodes') }}</h4>
          <div
            v-for="nodeType in nodeTypes"
            :key="nodeType.type"
            class="node-item mb-2"
            draggable="true"
            @dragstart="onDragStart($event, nodeType)"
          >
            <v-icon :color="nodeType.color" size="small" class="mr-2">{{ nodeType.icon }}</v-icon>
            <span>{{ tm(`nodeTypes.${nodeType.type}`) }}</span>
          </div>
        </div>
      </v-col>

      <!-- Canvas Area -->
      <v-col cols="7" class="canvas-area">
        <!-- Zoom Controls -->
        <div class="zoom-controls">
          <v-btn icon size="small" variant="text" @click="zoomIn" :disabled="scale >= maxScale">
            <v-icon>mdi-plus</v-icon>
          </v-btn>
          <span class="zoom-label">{{ Math.round(scale * 100) }}%</span>
          <v-btn icon size="small" variant="text" @click="zoomOut" :disabled="scale <= minScale">
            <v-icon>mdi-minus</v-icon>
          </v-btn>
          <v-btn icon size="small" variant="text" @click="resetZoom" :disabled="scale === 1">
            <v-icon>mdi-fit-to-screen</v-icon>
          </v-btn>
        </div>
        <div
          ref="canvasRef"
          class="workflow-canvas"
          :class="{ 'is-panning': isPanning, 'space-panning': spacePressed }"
          @drop="onDrop"
          @dragover.prevent
          @click="selectNode(null)"
          @wheel.prevent="onWheel"
          @mousedown="startCanvasPan"
          @contextmenu.prevent
        >
          <!-- Scalable inner container -->
          <div
            class="canvas-inner"
            :style="{
              transform: `translate(${canvasOffset.x}px, ${canvasOffset.y}px) scale(${scale})`,
              transformOrigin: '0 0'
            }"
          >
            <!-- Render nodes -->
            <div
              v-for="node in nodes"
              :key="node.id"
              :class="['workflow-node', `node-${node.type}`, { selected: selectedNodeId === node.id }]"
              :style="{ left: node.position.x + 'px', top: node.position.y + 'px' }"
              @click.stop="selectNode(node.id)"
              @mousedown.stop="startDrag($event, node)"
            >
              <div class="node-header">
                <v-icon size="small" class="mr-1">{{ getNodeIcon(node.type) }}</v-icon>
                <span>{{ tm(`nodeTypes.${node.type}`) }}</span>
                <v-btn
                  v-if="node.type !== 'start'"
                  icon="mdi-close"
                  size="x-small"
                  variant="text"
                  class="delete-btn"
                  @click.stop="deleteNode(node.id)"
                ></v-btn>
              </div>
              <div class="node-content">
                <template v-if="node.type === 'start'">
                  <span class="text-caption">{{ tm('userInput') }}</span>
                </template>
                <template v-else-if="node.type === 'end'">
                  <span class="text-caption">{{ tm('output') }}</span>
                </template>
                <template v-else-if="node.type === 'llm'">
                  <span class="text-caption">{{ node.data.provider_id || tm('defaultProvider') }}</span>
                </template>
                <template v-else-if="node.type === 'tool'">
                  <span class="text-caption">{{ node.data.tool_name || tm('selectTool') }}</span>
                </template>
                <template v-else-if="node.type === 'knowledgeBase'">
                  <span class="text-caption">{{ getKnowledgeBaseName(node.data.kb_id) || tm('selectKnowledgeBase') }}</span>
                </template>
              </div>
              <!-- Connection points -->
              <div
                v-if="node.type !== 'end'"
                class="connection-point output"
                @mousedown.stop="startConnection($event, node.id, 'output')"
              ></div>
              <div
                v-if="node.type !== 'start'"
                class="connection-point input"
                @mouseup="endConnection($event, node.id, 'input')"
              ></div>
            </div>

            <!-- Render edges (connections) -->
            <svg class="edges-layer" width="100%" height="100%">
              <path
                v-for="edge in edges"
                :key="edge.id"
                :d="getEdgePath(edge)"
                class="edge-path"
                :class="{ selected: selectedEdgeId === edge.id }"
                @click.stop="selectEdge(edge.id)"
              ></path>
              <!-- Drawing edge -->
              <path
                v-if="drawingEdge"
                :d="drawingEdgePath"
                class="edge-path drawing"
              ></path>
            </svg>
          </div>
        </div>
      </v-col>

      <!-- Properties Panel -->
      <v-col cols="3" class="properties-panel">
        <div class="pa-3">
          <template v-if="selectedNode">
            <h4 class="text-subtitle-2 mb-3">{{ tm('properties') }}</h4>

            <!-- Start Node Properties -->
            <template v-if="selectedNode.type === 'start'">
              <v-alert type="info" variant="tonal" density="compact">
                {{ tm('startNodeInfo') }}
              </v-alert>
            </template>

            <!-- End Node Properties -->
            <template v-else-if="selectedNode.type === 'end'">
              <v-alert type="info" variant="tonal" density="compact">
                {{ tm('endNodeInfo') }}
              </v-alert>
            </template>

            <!-- LLM Node Properties -->
            <template v-else-if="selectedNode.type === 'llm'">
              <v-select
                v-model="selectedNode.data.provider_id"
                :items="providers"
                item-title="id"
                item-value="id"
                :label="tm('provider')"
                :no-data-text="tm('noProviders')"
                variant="outlined"
                density="compact"
                class="mb-3"
                clearable
              ></v-select>
              <v-textarea
                v-model="selectedNode.data.prompt"
                :label="tm('prompt')"
                :hint="tm('promptHint')"
                variant="outlined"
                density="compact"
                rows="4"
                class="mb-3"
              ></v-textarea>
              <v-textarea
                v-model="selectedNode.data.system_prompt"
                :label="tm('systemPrompt')"
                variant="outlined"
                density="compact"
                rows="3"
                class="mb-3"
              ></v-textarea>
              <v-text-field
                v-model="selectedNode.data.output_variable"
                :label="tm('outputVariable')"
                variant="outlined"
                density="compact"
                placeholder="output"
              ></v-text-field>
            </template>

            <!-- Tool Node Properties -->
            <template v-else-if="selectedNode.type === 'tool'">
              <v-select
                v-model="selectedNode.data.tool_name"
                :items="tools"
                item-title="name"
                item-value="name"
                :label="tm('tool')"
                :no-data-text="tm('noTools')"
                variant="outlined"
                density="compact"
                class="mb-3"
              >
                <template v-slot:item="{ item, props }">
                  <v-list-item v-bind="props">
                    <v-list-item-subtitle>{{ item.raw.description }}</v-list-item-subtitle>
                  </v-list-item>
                </template>
              </v-select>

              <!-- Tool Arguments -->
              <template v-if="selectedToolSchema && selectedToolSchema.properties">
                <h5 class="text-caption mb-2">{{ tm('arguments') }}</h5>
                <v-alert type="info" variant="tonal" density="compact" class="mb-3">
                  {{ tm('variableHint') }}
                </v-alert>
                <template v-for="(param, name) in selectedToolSchema.properties" :key="name">
                  <v-text-field
                    :model-value="getToolArgument(name)"
                    @update:model-value="setToolArgument(name, $event)"
                    :label="String(name) + (isRequiredParam(name) ? ' *' : '')"
                    :hint="param.description"
                    :placeholder="'{{input}}'"
                    variant="outlined"
                    density="compact"
                    persistent-hint
                    class="mb-2"
                  ></v-text-field>
                </template>
              </template>

              <v-text-field
                v-model="selectedNode.data.output_variable"
                :label="tm('outputVariable')"
                variant="outlined"
                density="compact"
                placeholder="_tool_result"
              ></v-text-field>
            </template>

            <!-- Knowledge Base Node Properties -->
            <template v-else-if="selectedNode.type === 'knowledgeBase'">
              <v-select
                v-model="selectedNode.data.kb_id"
                :items="knowledgeBases"
                item-title="name"
                item-value="kb_id"
                :label="tm('selectKnowledgeBase')"
                :no-data-text="tm('noKnowledgeBases')"
                variant="outlined"
                density="compact"
                class="mb-3"
              >
                <template v-slot:item="{ item, props }">
                  <v-list-item v-bind="props">
                    <v-list-item-subtitle>{{ item.raw.description }}</v-list-item-subtitle>
                  </v-list-item>
                </template>
              </v-select>

              <v-text-field
                v-model="selectedNode.data.query"
                :label="tm('prompt')"
                :hint="tm('knowledgeBaseHint')"
                :placeholder="'{{input}}'"
                variant="outlined"
                density="compact"
                persistent-hint
                class="mb-3"
              ></v-text-field>

              <v-text-field
                v-model.number="selectedNode.data.top_k"
                :label="tm('topK')"
                type="number"
                variant="outlined"
                density="compact"
                :min="1"
                :max="20"
                class="mb-3"
              ></v-text-field>

              <v-text-field
                v-model.number="selectedNode.data.score_threshold"
                :label="tm('scoreThreshold')"
                type="number"
                variant="outlined"
                density="compact"
                :min="0"
                :max="1"
                :step="0.1"
                class="mb-3"
              ></v-text-field>

              <v-text-field
                v-model="selectedNode.data.output_variable"
                :label="tm('outputVariable')"
                variant="outlined"
                density="compact"
                placeholder="_kb_result"
              ></v-text-field>
            </template>

            <!-- Condition Node Properties -->
            <template v-else-if="selectedNode.type === 'condition'">
              <v-textarea
                v-model="selectedNode.data.condition"
                :label="tm('condition')"
                :hint="tm('conditionHint')"
                variant="outlined"
                density="compact"
                rows="3"
              ></v-textarea>
            </template>
          </template>

          <!-- Edge Selected -->
          <template v-else-if="selectedEdgeId">
            <h4 class="text-subtitle-2 mb-3">{{ tm('edgeProperties') }}</h4>
            <v-btn color="error" variant="text" @click="deleteSelectedEdge">
              <v-icon left>mdi-delete</v-icon>
              {{ tm('deleteConnection') }}
            </v-btn>
          </template>

          <!-- No Selection -->
          <template v-else>
            <p class="text-body-2 text-grey">{{ tm('selectNodeHint') }}</p>
          </template>
        </div>
      </v-col>
    </v-row>

    <!-- Test Dialog -->
    <v-dialog v-model="testDialog" max-width="700">
      <v-card>
        <v-card-title>{{ tm('testWorkflow') }}</v-card-title>
        <v-card-text>
          <v-textarea
            v-model="testInput"
            :label="tm('testInput')"
            variant="outlined"
            rows="3"
            class="mb-4"
          ></v-textarea>
          <div v-if="testResult !== null">
            <h4 class="text-subtitle-2 mb-2">{{ tm('testResult') }}</h4>
            <v-alert type="success" variant="tonal">
              <pre class="text-body-2" style="white-space: pre-wrap;">{{ testResult }}</pre>
            </v-alert>
          </div>
          <div v-if="testLogs.length > 0" class="mt-4">
            <h4 class="text-subtitle-2 mb-2">Execution Logs</h4>
            <v-expansion-panels variant="accordion">
              <v-expansion-panel>
                <v-expansion-panel-title>Show logs ({{ testLogs.length }} entries)</v-expansion-panel-title>
                <v-expansion-panel-text>
                  <pre class="text-caption" style="white-space: pre-wrap; max-height: 300px; overflow-y: auto;">{{ testLogs.join('\n') }}</pre>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn variant="text" @click="testDialog = false">{{ t('actions.cancel') }}</v-btn>
          <v-btn color="primary" variant="flat" @click="runTest" :loading="testing">
            {{ tm('run') }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="3000">
      {{ snackbar.message }}
    </v-snackbar>
  </v-container>
</template>

<script>
import axios from 'axios';
import { useI18n, useModuleI18n } from '@/i18n/composables';

const NODE_TYPES = [
  { type: 'start', icon: 'mdi-play-circle', color: 'success' },
  { type: 'end', icon: 'mdi-stop-circle', color: 'error' },
  { type: 'llm', icon: 'mdi-brain', color: 'primary' },
  { type: 'tool', icon: 'mdi-wrench', color: 'warning' },
  { type: 'knowledgeBase', icon: 'mdi-book-open-variant', color: 'purple' },
  { type: 'condition', icon: 'mdi-source-branch', color: 'info' },
];

export default {
  name: 'WorkflowEditor',
  props: {
    id: {
      type: String,
      default: null
    }
  },
  setup() {
    const { t } = useI18n();
    const { tm } = useModuleI18n('features/workflow');
    return { t, tm };
  },
  data() {
    return {
      nodeTypes: NODE_TYPES,
      workflowId: null,
      workflowName: '',
      workflowDescription: '',
      nodes: [],
      edges: [],
      selectedNodeId: null,
      selectedEdgeId: null,
      providers: [],
      tools: [],
      knowledgeBases: [],
      loading: false,
      saving: false,
      testing: false,
      testDialog: false,
      testInput: '',
      testResult: null,
      testLogs: [],
      draggingNode: null,
      dragOffset: { x: 0, y: 0 },
      drawingEdge: false,
      drawingEdgeStart: { nodeId: '', x: 0, y: 0 },
      drawingEdgeEnd: { x: 0, y: 0 },
      // Canvas zoom and pan
      scale: 1,
      targetScale: 1,
      minScale: 0.25,
      maxScale: 2,
      isPanning: false,
      panStart: { x: 0, y: 0 },
      canvasOffset: { x: 0, y: 0 },
      targetOffset: { x: 0, y: 0 },
      // Momentum for smooth panning
      velocity: { x: 0, y: 0 },
      lastMoveTime: 0,
      // Animation frame
      animationFrameId: null,
      isAnimating: false,
      // Space key for panning
      spacePressed: false,
      // Variable menu
      variableMenuOpen: false,
      variableMenuTarget: null,
      variableMenuPosition: { x: 0, y: 0 },
      snackbar: {
        show: false,
        message: '',
        color: 'success'
      }
    };
  },

  computed: {
    selectedNode() {
      if (!this.selectedNodeId) return null;
      return this.nodes.find(n => n.id === this.selectedNodeId) || null;
    },
    selectedToolSchema() {
      if (!this.selectedNode || this.selectedNode.type !== 'tool') return null;
      const toolName = this.selectedNode.data.tool_name;
      if (!toolName) return null;
      const tool = this.tools.find(t => t.name === toolName);
      return tool?.parameters || null;
    },
    canTest() {
      return this.nodes.some(n => n.type === 'start') && this.nodes.some(n => n.type === 'end');
    },
    drawingEdgePath() {
      if (!this.drawingEdge) return '';
      return `M ${this.drawingEdgeStart.x} ${this.drawingEdgeStart.y} L ${this.drawingEdgeEnd.x} ${this.drawingEdgeEnd.y}`;
    },
    // Get available variables based on upstream nodes
    availableVariables() {
      const vars = [
        { name: 'input', description: '用户输入 / User Input' }
      ];

      // Find all nodes that output variables
      for (const node of this.nodes) {
        if (node.type === 'llm') {
          const varName = node.data.output_variable || 'output';
          vars.push({
            name: varName,
            description: `LLM 输出 (${node.data.provider_id || 'default'})`
          });
        } else if (node.type === 'knowledgeBase') {
          const varName = node.data.output_variable || '_kb_result';
          const kbName = this.getKnowledgeBaseName(node.data.kb_id) || 'KB';
          vars.push({
            name: varName,
            description: `知识库结果 (${kbName})`
          });
        } else if (node.type === 'tool') {
          const varName = node.data.output_variable || '_tool_result';
          vars.push({
            name: varName,
            description: `工具结果 (${node.data.tool_name || 'tool'})`
          });
        }
      }

      return vars;
    }
  },

  watch: {
    'selectedNode.data.tool_name'(newTool) {
      if (this.selectedNode && newTool) {
        if (!this.selectedNode.data.arguments) {
          this.selectedNode.data.arguments = {};
        }
      }
    }
  },

  async mounted() {
    await Promise.all([this.loadProviders(), this.loadTools(), this.loadKnowledgeBases()]);

    const id = this.id || this.$route.params.id;
    if (id) {
      await this.loadWorkflow(id);
    } else {
      // Create default start and end nodes
      this.nodes = [
        {
          id: this.generateId(),
          type: 'start',
          position: { x: 50, y: 150 },
          data: {}
        },
        {
          id: this.generateId(),
          type: 'end',
          position: { x: 500, y: 150 },
          data: {}
        }
      ];
    }

    // Add keyboard listeners for space key panning
    window.addEventListener('keydown', this.onKeyDown);
    window.addEventListener('keyup', this.onKeyUp);

    // Start animation loop
    this.startAnimationLoop();
  },

  beforeUnmount() {
    // Clean up listeners
    window.removeEventListener('keydown', this.onKeyDown);
    window.removeEventListener('keyup', this.onKeyUp);

    // Cancel animation frame
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
    }
  },

  methods: {
    getNodeIcon(type) {
      const nodeType = this.nodeTypes.find(n => n.type === type);
      return nodeType?.icon || 'mdi-circle';
    },

    getKnowledgeBaseName(kbId) {
      if (!kbId) return null;
      const kb = this.knowledgeBases.find(k => k.kb_id === kbId);
      return kb?.name || kbId;
    },

    // Zoom methods with smooth animation
    zoomIn() {
      this.targetScale = Math.min(this.maxScale, this.targetScale + 0.15);
      this.startAnimating();
    },

    zoomOut() {
      this.targetScale = Math.max(this.minScale, this.targetScale - 0.15);
      this.startAnimating();
    },

    resetZoom() {
      this.targetScale = 1;
      this.targetOffset = { x: 0, y: 0 };
      this.startAnimating();
    },

    onWheel(event) {
      event.preventDefault();

      // Get mouse position relative to canvas
      const rect = this.$refs.canvasRef.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;

      // Calculate zoom with smooth factor
      const zoomFactor = event.deltaY > 0 ? 0.9 : 1.1;
      const newScale = Math.max(this.minScale, Math.min(this.maxScale, this.targetScale * zoomFactor));

      if (newScale !== this.targetScale) {
        // Zoom towards mouse position
        const scaleChange = newScale / this.targetScale;

        // Adjust offset to zoom towards cursor
        this.targetOffset.x = mouseX - (mouseX - this.targetOffset.x) * scaleChange;
        this.targetOffset.y = mouseY - (mouseY - this.targetOffset.y) * scaleChange;

        this.targetScale = newScale;
        this.startAnimating();
      }
    },

    // Animation loop for smooth transitions
    startAnimationLoop() {
      const animate = () => {
        this.animationFrameId = requestAnimationFrame(animate);

        // Smooth interpolation factor (higher = faster)
        const smoothFactor = 0.15;

        // Interpolate scale
        const scaleDiff = this.targetScale - this.scale;
        if (Math.abs(scaleDiff) > 0.001) {
          this.scale += scaleDiff * smoothFactor;
          this.isAnimating = true;
        } else {
          this.scale = this.targetScale;
        }

        // Interpolate offset
        const offsetXDiff = this.targetOffset.x - this.canvasOffset.x;
        const offsetYDiff = this.targetOffset.y - this.canvasOffset.y;

        if (Math.abs(offsetXDiff) > 0.1 || Math.abs(offsetYDiff) > 0.1) {
          this.canvasOffset.x += offsetXDiff * smoothFactor;
          this.canvasOffset.y += offsetYDiff * smoothFactor;
          this.isAnimating = true;
        } else {
          this.canvasOffset.x = this.targetOffset.x;
          this.canvasOffset.y = this.targetOffset.y;
        }

        // Apply momentum for panning
        if (!this.isPanning && (Math.abs(this.velocity.x) > 0.1 || Math.abs(this.velocity.y) > 0.1)) {
          this.targetOffset.x += this.velocity.x;
          this.targetOffset.y += this.velocity.y;

          // Apply friction
          this.velocity.x *= 0.92;
          this.velocity.y *= 0.92;
          this.isAnimating = true;
        }
      };

      animate();
    },

    startAnimating() {
      this.isAnimating = true;
    },

    // Keyboard handlers for space key panning
    onKeyDown(event) {
      if (event.code === 'Space' && !event.repeat && !this.isInputFocused()) {
        event.preventDefault();
        this.spacePressed = true;
      }
    },

    onKeyUp(event) {
      if (event.code === 'Space') {
        this.spacePressed = false;
      }
    },

    isInputFocused() {
      const active = document.activeElement;
      return active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable);
    },

    // Canvas panning with space + drag or middle mouse button
    startCanvasPan(event) {
      // Only pan with space key held, middle mouse button, or right mouse button
      if (this.spacePressed || event.button === 1 || event.button === 2) {
        event.preventDefault();
        this.isPanning = true;
        this.panStart = {
          x: event.clientX - this.canvasOffset.x,
          y: event.clientY - this.canvasOffset.y
        };
        this.lastMoveTime = Date.now();
        this.velocity = { x: 0, y: 0 };

        const onMouseMove = (e) => {
          if (this.isPanning) {
            const now = Date.now();
            const dt = Math.max(1, now - this.lastMoveTime);

            const newX = e.clientX - this.panStart.x;
            const newY = e.clientY - this.panStart.y;

            // Calculate velocity for momentum
            this.velocity.x = (newX - this.targetOffset.x) / dt * 16;
            this.velocity.y = (newY - this.targetOffset.y) / dt * 16;

            this.targetOffset.x = newX;
            this.targetOffset.y = newY;

            this.lastMoveTime = now;
            this.startAnimating();
          }
        };

        const onMouseUp = () => {
          this.isPanning = false;
          document.removeEventListener('mousemove', onMouseMove);
          document.removeEventListener('mouseup', onMouseUp);
        };

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
      }
    },

    generateId() {
      return 'node_' + Math.random().toString(36).substr(2, 9);
    },

    onDragStart(event, nodeType) {
      event.dataTransfer?.setData('nodeType', nodeType.type);
    },

    onDrop(event) {
      const nodeType = event.dataTransfer?.getData('nodeType');
      if (!nodeType || !this.$refs.canvasRef) return;

      const rect = this.$refs.canvasRef.getBoundingClientRect();
      const x = (event.clientX - rect.left - this.canvasOffset.x) / this.scale - 75;
      const y = (event.clientY - rect.top - this.canvasOffset.y) / this.scale - 25;

      if (nodeType === 'start' && this.nodes.some(n => n.type === 'start')) {
        this.showSnackbar(this.tm('startNodeExists'), 'warning');
        return;
      }

      const newNode = {
        id: this.generateId(),
        type: nodeType,
        position: { x: Math.max(0, x), y: Math.max(0, y) },
        data: this.getDefaultNodeData(nodeType)
      };

      this.nodes.push(newNode);
      this.selectNode(newNode.id);
    },

    getDefaultNodeData(type) {
      switch (type) {
        case 'llm':
          return {
            provider_id: '',
            prompt: '{{input}}',
            system_prompt: '',
            output_variable: 'output'
          };
        case 'tool':
          return {
            tool_name: '',
            arguments: {},
            output_variable: '_tool_result'
          };
        case 'knowledgeBase':
          return {
            kb_id: '',
            query: '{{input}}',
            top_k: 5,
            score_threshold: 0.5,
            output_variable: '_kb_result'
          };
        case 'condition':
          return {
            condition: 'len(output) > 0'
          };
        default:
          return {};
      }
    },

    selectNode(nodeId) {
      this.selectedNodeId = nodeId;
      this.selectedEdgeId = null;
    },

    selectEdge(edgeId) {
      this.selectedEdgeId = edgeId;
      this.selectedNodeId = null;
    },

    deleteNode(nodeId) {
      this.nodes = this.nodes.filter(n => n.id !== nodeId);
      this.edges = this.edges.filter(e => e.source !== nodeId && e.target !== nodeId);
      if (this.selectedNodeId === nodeId) {
        this.selectedNodeId = null;
      }
    },

    deleteSelectedEdge() {
      if (this.selectedEdgeId) {
        this.edges = this.edges.filter(e => e.id !== this.selectedEdgeId);
        this.selectedEdgeId = null;
      }
    },

    startDrag(event, node) {
      if (!this.$refs.canvasRef || this.spacePressed) return;

      this.draggingNode = node;
      const rect = this.$refs.canvasRef.getBoundingClientRect();

      const mouseX = (event.clientX - rect.left - this.canvasOffset.x) / this.scale;
      const mouseY = (event.clientY - rect.top - this.canvasOffset.y) / this.scale;

      this.dragOffset = {
        x: mouseX - node.position.x,
        y: mouseY - node.position.y
      };

      // Track pending position update
      let pendingUpdate = null;
      let rafId = null;

      const updatePosition = () => {
        if (pendingUpdate && this.draggingNode) {
          this.draggingNode.position.x = pendingUpdate.x;
          this.draggingNode.position.y = pendingUpdate.y;
          pendingUpdate = null;
        }
        rafId = null;
      };

      const onMouseMove = (e) => {
        if (this.draggingNode && this.$refs.canvasRef) {
          const rect = this.$refs.canvasRef.getBoundingClientRect();
          const mouseX = (e.clientX - rect.left - this.canvasOffset.x) / this.scale;
          const mouseY = (e.clientY - rect.top - this.canvasOffset.y) / this.scale;

          // Queue position update
          pendingUpdate = {
            x: Math.max(0, mouseX - this.dragOffset.x),
            y: Math.max(0, mouseY - this.dragOffset.y)
          };

          // Use requestAnimationFrame for smooth updates
          if (!rafId) {
            rafId = requestAnimationFrame(updatePosition);
          }
        }
      };

      const onMouseUp = () => {
        // Apply any pending update
        if (pendingUpdate && this.draggingNode) {
          this.draggingNode.position.x = pendingUpdate.x;
          this.draggingNode.position.y = pendingUpdate.y;
        }
        if (rafId) {
          cancelAnimationFrame(rafId);
        }
        this.draggingNode = null;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
      };

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    },

    startConnection(event, nodeId) {
      if (!this.$refs.canvasRef) return;

      const node = this.nodes.find(n => n.id === nodeId);
      if (!node) return;

      this.drawingEdge = true;
      this.drawingEdgeStart = {
        nodeId,
        x: node.position.x + 150,
        y: node.position.y + 25
      };

      const rect = this.$refs.canvasRef.getBoundingClientRect();
      this.drawingEdgeEnd = {
        x: (event.clientX - rect.left - this.canvasOffset.x) / this.scale,
        y: (event.clientY - rect.top - this.canvasOffset.y) / this.scale
      };

      let rafId = null;
      let pendingEnd = null;

      const updateDrawingEdge = () => {
        if (pendingEnd) {
          this.drawingEdgeEnd = pendingEnd;
          pendingEnd = null;
        }
        rafId = null;
      };

      const onMouseMove = (e) => {
        if (this.drawingEdge && this.$refs.canvasRef) {
          const rect = this.$refs.canvasRef.getBoundingClientRect();
          pendingEnd = {
            x: (e.clientX - rect.left - this.canvasOffset.x) / this.scale,
            y: (e.clientY - rect.top - this.canvasOffset.y) / this.scale
          };

          if (!rafId) {
            rafId = requestAnimationFrame(updateDrawingEdge);
          }
        }
      };

      const onMouseUp = () => {
        if (rafId) {
          cancelAnimationFrame(rafId);
        }
        this.drawingEdge = false;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
      };

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    },

    endConnection(event, nodeId) {
      if (!this.drawingEdge) return;

      const sourceId = this.drawingEdgeStart.nodeId;
      if (sourceId === nodeId) return;

      const exists = this.edges.some(e => e.source === sourceId && e.target === nodeId);
      if (exists) return;

      const newEdge = {
        id: `edge_${sourceId}_${nodeId}`,
        source: sourceId,
        target: nodeId
      };

      this.edges.push(newEdge);
      this.drawingEdge = false;
    },

    getEdgePath(edge) {
      const sourceNode = this.nodes.find(n => n.id === edge.source);
      const targetNode = this.nodes.find(n => n.id === edge.target);

      if (!sourceNode || !targetNode) return '';

      const x1 = sourceNode.position.x + 150;
      const y1 = sourceNode.position.y + 25;
      const x2 = targetNode.position.x;
      const y2 = targetNode.position.y + 25;

      const controlX = (x1 + x2) / 2;
      return `M ${x1} ${y1} C ${controlX} ${y1}, ${controlX} ${y2}, ${x2} ${y2}`;
    },

    goBack() {
      this.$router.push('/workflow');
    },

    async saveWorkflow() {
      if (!this.workflowName.trim()) {
        this.showSnackbar(this.tm('nameRequired'), 'warning');
        return;
      }

      this.saving = true;
      try {
        const data = {
          workflow_id: this.workflowId,
          name: this.workflowName,
          description: this.workflowDescription,
          data: {
            nodes: this.nodes,
            edges: this.edges
          }
        };

        const response = await axios.post('/api/workflow/save', data);
        if (response.data.status === 'ok') {
          this.workflowId = response.data.data.workflow.workflow_id;
          this.showSnackbar(this.tm('saved'), 'success');
          if (!this.$route.params.id) {
            this.$router.replace(`/workflow/editor/${this.workflowId}`);
          }
        } else {
          this.showSnackbar(response.data.message || this.tm('saveFailed'), 'error');
        }
      } catch (error) {
        console.error('Failed to save workflow:', error);
        this.showSnackbar(this.tm('saveFailed'), 'error');
      } finally {
        this.saving = false;
      }
    },

    async loadWorkflow(id) {
      this.loading = true;
      try {
        const response = await axios.get(`/api/workflow/get/${id}`);
        if (response.data.status === 'ok' && response.data.data) {
          const workflow = response.data.data;
          this.workflowId = workflow.workflow_id;
          this.workflowName = workflow.name;
          this.workflowDescription = workflow.description || '';
          if (workflow.data) {
            this.nodes = workflow.data.nodes || [];
            this.edges = workflow.data.edges || [];
          }
        } else {
          this.showSnackbar(this.tm('loadFailed'), 'error');
        }
      } catch (error) {
        console.error('Failed to load workflow:', error);
        this.showSnackbar(this.tm('loadFailed'), 'error');
      } finally {
        this.loading = false;
      }
    },

    async loadProviders() {
      try {
        const response = await axios.get('/api/workflow/providers/available');
        if (response.data.status === 'ok') {
          this.providers = response.data.data || [];
        }
      } catch (error) {
        console.error('Failed to load providers:', error);
      }
    },

    async loadTools() {
      try {
        const response = await axios.get('/api/workflow/tools/available');
        if (response.data.status === 'ok') {
          this.tools = (response.data.data || []).filter(t => t.active);
        }
      } catch (error) {
        console.error('Failed to load tools:', error);
      }
    },

    async loadKnowledgeBases() {
      try {
        const response = await axios.get('/api/workflow/knowledge-bases/available');
        if (response.data.status === 'ok') {
          this.knowledgeBases = response.data.data || [];
        }
      } catch (error) {
        console.error('Failed to load knowledge bases:', error);
      }
    },

    getToolArgument(name) {
      if (!this.selectedNode || !this.selectedNode.data.arguments) {
        return '';
      }
      return this.selectedNode.data.arguments[name] || '';
    },

    setToolArgument(name, value) {
      if (!this.selectedNode) return;
      if (!this.selectedNode.data.arguments) {
        this.selectedNode.data.arguments = {};
      }
      this.selectedNode.data.arguments[name] = value;
    },

    isRequiredParam(name) {
      if (!this.selectedToolSchema || !this.selectedToolSchema.required) {
        return false;
      }
      return this.selectedToolSchema.required.includes(name);
    },

    testWorkflow() {
      this.testDialog = true;
      this.testResult = null;
    },

    async runTest() {
      this.testing = true;
      this.testLogs = [];
      try {
        const response = await axios.post('/api/workflow/test', {
          workflow_data: {
            nodes: this.nodes,
            edges: this.edges
          },
          input: this.testInput
        });
        if (response.data.status === 'ok') {
          this.testResult = response.data.data.result;
          this.testLogs = response.data.data.logs || [];
        } else {
          this.showSnackbar(response.data.message || 'Test failed', 'error');
        }
      } catch (error) {
        console.error('Failed to test workflow:', error);
        this.showSnackbar('Test failed', 'error');
      } finally {
        this.testing = false;
      }
    },

    showSnackbar(message, color = 'success') {
      this.snackbar = { show: true, message, color };
    }
  }
};
</script>

<style scoped lang="scss">
.workflow-editor {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.workflow-toolbar {
  flex-shrink: 0;
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.workflow-name-input {
  max-width: 300px;
}

.workflow-content {
  flex: 1;
  overflow: hidden;
}

.node-palette {
  border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  overflow-y: auto;
  background: rgb(var(--v-theme-surface));
}

.node-item {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 4px;
  cursor: grab;
  background: rgba(var(--v-theme-primary), 0.05);
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  transition: all 0.2s;

  &:hover {
    background: rgba(var(--v-theme-primary), 0.1);
  }

  &:active {
    cursor: grabbing;
  }
}

.canvas-area {
  position: relative;
  overflow: hidden;
}

.zoom-controls {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 4px;
  background: rgb(var(--v-theme-surface));
  padding: 4px 8px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.zoom-label {
  font-size: 12px;
  min-width: 40px;
  text-align: center;
  color: rgb(var(--v-theme-on-surface));
}

.workflow-canvas {
  width: 100%;
  height: 100%;
  position: relative;
  background:
    linear-gradient(rgba(var(--v-border-color), 0.1) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--v-border-color), 0.1) 1px, transparent 1px);
  background-size: 20px 20px;
  overflow: hidden;
  cursor: default;

  &.space-panning {
    cursor: grab;
  }

  &.is-panning {
    cursor: grabbing;
  }
}

.canvas-inner {
  position: relative;
  width: 4000px;
  height: 3000px;
  min-width: 100%;
  min-height: 100%;
  will-change: transform;
}

.edges-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: visible;

  .edge-path {
    fill: none;
    stroke: rgb(var(--v-theme-primary));
    stroke-width: 2;
    pointer-events: stroke;
    cursor: pointer;
    transition: stroke 0.2s ease, stroke-width 0.2s ease;

    &:hover {
      stroke-width: 3;
      filter: drop-shadow(0 0 4px rgba(var(--v-theme-primary), 0.5));
    }

    &.selected {
      stroke: rgb(var(--v-theme-error));
      stroke-width: 3;
      filter: drop-shadow(0 0 6px rgba(var(--v-theme-error), 0.6));
    }

    &.drawing {
      stroke-dasharray: 8, 4;
      stroke-width: 2;
      opacity: 0.7;
      animation: dash-animation 0.5s linear infinite;
    }
  }
}

@keyframes dash-animation {
  to {
    stroke-dashoffset: -12;
  }
}

.workflow-node {
  position: absolute;
  width: 150px;
  background: rgb(var(--v-theme-surface));
  border: 2px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  cursor: move;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: box-shadow 0.2s ease, border-color 0.2s ease, transform 0.1s ease;
  will-change: transform, box-shadow;
  user-select: none;

  &:hover {
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
    transform: translateY(-1px);
  }

  &:active {
    transform: translateY(0);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.2);
  }

  &.selected {
    border-color: rgb(var(--v-theme-primary));
    box-shadow: 0 0 0 3px rgba(var(--v-theme-primary), 0.25), 0 4px 16px rgba(0, 0, 0, 0.15);
  }

  .node-header {
    display: flex;
    align-items: center;
    padding: 8px;
    border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
    font-size: 12px;
    font-weight: 500;

    .delete-btn {
      margin-left: auto;
      opacity: 0;
      transition: opacity 0.2s;
    }
  }

  &:hover .delete-btn {
    opacity: 1;
  }

  .node-content {
    padding: 8px;
  }

  .connection-point {
    position: absolute;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: rgb(var(--v-theme-primary));
    border: 2px solid rgb(var(--v-theme-surface));
    cursor: crosshair;
    transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;

    &:hover {
      transform: scale(1.3);
      box-shadow: 0 0 8px rgba(var(--v-theme-primary), 0.6);
    }

    &:active {
      transform: scale(1.1);
      background: rgba(var(--v-theme-primary), 0.8);
    }

    &.input {
      left: -6px;
      top: 50%;
      margin-top: -6px;
    }

    &.output {
      right: -6px;
      top: 50%;
      margin-top: -6px;
    }
  }
}

.node-start .node-header {
  background: rgba(var(--v-theme-success), 0.1);
}

.node-end .node-header {
  background: rgba(var(--v-theme-error), 0.1);
}

.node-llm .node-header {
  background: rgba(var(--v-theme-primary), 0.1);
}

.node-tool .node-header {
  background: rgba(var(--v-theme-warning), 0.1);
}

.node-knowledgeBase .node-header {
  background: rgba(128, 0, 128, 0.1);
}

.node-condition .node-header {
  background: rgba(var(--v-theme-info), 0.1);
}

.properties-panel {
  border-left: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  overflow-y: auto;
  background: rgb(var(--v-theme-surface));
}
</style>
