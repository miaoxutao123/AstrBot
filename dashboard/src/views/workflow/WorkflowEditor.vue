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
          <v-tooltip location="bottom">
            <template v-slot:activator="{ props }">
              <v-btn icon size="small" variant="text" v-bind="props" @click="showHelp = !showHelp">
                <v-icon>mdi-help-circle-outline</v-icon>
              </v-btn>
            </template>
            <span>{{ tm('canvasHelp') }}</span>
          </v-tooltip>
          <v-divider vertical class="mx-1"></v-divider>
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

        <!-- Help Overlay -->
        <v-fade-transition>
          <div v-if="showHelp" class="help-overlay" @click="showHelp = false">
            <v-card class="help-card" max-width="320" @click.stop>
              <v-card-title class="text-subtitle-1">
                <v-icon class="mr-2">mdi-gesture</v-icon>
                {{ tm('canvasControls') }}
              </v-card-title>
              <v-card-text class="text-body-2">
                <div class="help-item">
                  <v-icon size="small" class="mr-2">mdi-mouse</v-icon>
                  <span>{{ tm('helpScroll') }}</span>
                </div>
                <div class="help-item">
                  <v-icon size="small" class="mr-2">mdi-gesture-swipe</v-icon>
                  <span>{{ tm('helpZoom') }}</span>
                </div>
                <div class="help-item">
                  <v-icon size="small" class="mr-2">mdi-mouse-right-click</v-icon>
                  <span>{{ tm('helpPan') }}</span>
                </div>
                <div class="help-item">
                  <v-icon size="small" class="mr-2">mdi-keyboard-space</v-icon>
                  <span>{{ tm('helpSpacePan') }}</span>
                </div>
              </v-card-text>
              <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn variant="text" size="small" @click="showHelp = false">{{ t('actions.close') }}</v-btn>
              </v-card-actions>
            </v-card>
          </div>
        </v-fade-transition>
        <div
          ref="canvasRef"
          class="workflow-canvas"
          :class="{ 'is-panning': isPanning, 'space-panning': spacePressed || middleButtonHeld, 'is-dragging': draggingNode || drawingEdge }"
          @drop="onDrop"
          @dragover.prevent
          @click="onCanvasClick"
          @wheel="onWheel"
          @mousedown="onCanvasMouseDown"
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
              :data-node-id="node.id"
              :class="['workflow-node', `node-${node.type}`, { selected: selectedNodeId === node.id }]"
              :style="{ left: node.position.x + 'px', top: node.position.y + 'px' }"
              @click.stop="selectNode(node.id)"
              @mousedown.stop="startDrag($event, node)"
              @mouseup="onNodeMouseUp($event, node)"
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
                <template v-else-if="node.type === 'llmJudge'">
                  <span class="text-caption">{{ tm('nodeTypes.llmJudge') }}</span>
                </template>
                <template v-else-if="node.type === 'pluginCommand'">
                  <span class="text-caption">{{ getPluginCommandName(node.data.handler_full_name) || tm('selectPluginCommand') }}</span>
                </template>
                <template v-else-if="node.type === 'platformAction'">
                  <span class="text-caption">{{ getPlatformName(node.data.platform_id) || tm('selectPlatform') }}</span>
                </template>
              </div>
              <!-- Connection points -->
              <!-- Regular output point for non-conditional nodes -->
              <div
                v-if="node.type !== 'end' && !isConditionalNode(node.type)"
                class="connection-point output"
                @mousedown.stop="startConnection($event, node.id, 'output')"
              ></div>
              <!-- Conditional nodes have two output points: true and false -->
              <template v-if="isConditionalNode(node.type)">
                <div
                  class="connection-point output-true"
                  :title="tm('trueBranch')"
                  @mousedown.stop="startConnection($event, node.id, 'output-true')"
                ></div>
                <div
                  class="connection-point output-false"
                  :title="tm('falseBranch')"
                  @mousedown.stop="startConnection($event, node.id, 'output-false')"
                ></div>
              </template>
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
                :class="getEdgeClass(edge)"
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
                class="mb-3"
              ></v-text-field>
              
              <!-- Vision Settings -->
              <v-divider class="my-3"></v-divider>
              <h5 class="text-caption mb-2">{{ tm('visionSettings') }}</h5>
              <v-switch
                v-model="selectedNode.data.enable_vision"
                :label="tm('enableVision')"
                density="compact"
                color="primary"
                class="mb-2"
              ></v-switch>
              <v-text-field
                v-if="selectedNode.data.enable_vision"
                v-model="selectedNode.data.input_image_variable"
                :label="tm('inputImageVariable')"
                :hint="tm('inputImageVariableHint')"
                variant="outlined"
                density="compact"
                placeholder="input"
                persistent-hint
                class="mb-3"
              ></v-text-field>
              
              <!-- Tool Settings -->
              <v-divider class="my-3"></v-divider>
              <h5 class="text-caption mb-2">{{ tm('toolSettings') }}</h5>
              <v-switch
                v-model="selectedNode.data.enable_tools"
                :label="tm('enableTools')"
                density="compact"
                color="primary"
                class="mb-2"
              ></v-switch>
              <v-select
                v-if="selectedNode.data.enable_tools"
                v-model="selectedNode.data.allowed_tools"
                :items="tools"
                item-title="name"
                item-value="name"
                :label="tm('allowedTools')"
                :no-data-text="tm('noTools')"
                variant="outlined"
                density="compact"
                multiple
                chips
                closable-chips
                :hint="tm('allowedToolsHint')"
                persistent-hint
              >
                <template v-slot:item="{ item, props }">
                  <v-list-item v-bind="props">
                    <template v-slot:prepend>
                      <v-icon size="small">mdi-wrench</v-icon>
                    </template>
                  </v-list-item>
                </template>
              </v-select>
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
                <v-expansion-panels variant="accordion" class="mb-3">
                  <v-expansion-panel>
                    <v-expansion-panel-title>
                      <div class="d-flex align-center">
                        <v-icon size="small" class="mr-2">mdi-cog</v-icon>
                        {{ tm('arguments') }}
                        <v-chip size="x-small" class="ml-2">
                          {{ Object.keys(selectedToolSchema.properties).length }}
                        </v-chip>
                      </div>
                    </v-expansion-panel-title>
                    <v-expansion-panel-text>
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
                    </v-expansion-panel-text>
                  </v-expansion-panel>
                </v-expansion-panels>
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
              <div class="d-flex align-center mb-2">
                <span class="text-caption">{{ tm('condition') }}</span>
                <v-spacer></v-spacer>
                <v-btn size="x-small" variant="text" @click="applyConditionTemplate">
                  <v-icon size="small" class="mr-1">mdi-code-tags</v-icon>
                  {{ tm('useTemplate') }}
                </v-btn>
              </div>
              <v-textarea
                v-model="selectedNode.data.condition"
                :hint="tm('conditionHint')"
                variant="outlined"
                density="compact"
                rows="5"
                style="font-family: monospace; font-size: 12px;"
              ></v-textarea>
              <v-alert type="info" variant="tonal" density="compact" class="text-caption mt-3">
                {{ tm('conditionBranchInfo') }}
              </v-alert>
            </template>

            <!-- LLM Judge Node Properties -->
            <template v-else-if="selectedNode.type === 'llmJudge'">
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
              <div class="d-flex align-center mb-2">
                <span class="text-caption">{{ tm('judgePrompt') }}</span>
                <v-spacer></v-spacer>
                <v-btn size="x-small" variant="text" @click="applyLlmJudgeTemplate">
                  <v-icon size="small" class="mr-1">mdi-lightbulb-outline</v-icon>
                  {{ tm('useTemplate') }}
                </v-btn>
              </div>
              <v-textarea
                v-model="selectedNode.data.judge_prompt"
                :hint="tm('judgePromptHint')"
                variant="outlined"
                density="compact"
                rows="4"
                class="mb-3"
              ></v-textarea>
              <v-text-field
                v-model="selectedNode.data.true_keywords"
                :label="tm('trueKeywords')"
                :hint="tm('trueKeywordsHint')"
                variant="outlined"
                density="compact"
                placeholder="是,yes,true,正确"
                persistent-hint
                class="mb-3"
              ></v-text-field>
              <v-alert type="info" variant="tonal" density="compact" class="text-caption">
                {{ tm('llmJudgeInfo') }}
              </v-alert>
            </template>

            <!-- Plugin Command Node Properties -->
            <template v-else-if="selectedNode.type === 'pluginCommand'">
              <v-select
                v-model="selectedNode.data.handler_full_name"
                :items="pluginCommands"
                item-title="handler_name"
                item-value="handler_full_name"
                :label="tm('pluginCommand')"
                :no-data-text="tm('noPluginCommands')"
                variant="outlined"
                density="compact"
                class="mb-3"
              >
                <template v-slot:item="{ item, props }">
                  <v-list-item v-bind="props">
                    <template v-slot:prepend>
                      <v-icon size="small">mdi-puzzle</v-icon>
                    </template>
                    <v-list-item-subtitle>
                      {{ item.raw.plugin_name }} - {{ item.raw.command_name || item.raw.handler_name }}
                    </v-list-item-subtitle>
                  </v-list-item>
                </template>
              </v-select>
              
              <v-alert type="info" variant="tonal" density="compact" class="mb-3 text-caption">
                {{ tm('pluginCommandHint') }}
              </v-alert>

              <v-text-field
                v-model="selectedNode.data.output_variable"
                :label="tm('outputVariable')"
                variant="outlined"
                density="compact"
                placeholder="_plugin_result"
              ></v-text-field>
            </template>

            <!-- Platform Action Node Properties -->
            <template v-else-if="selectedNode.type === 'platformAction'">
              <v-select
                v-model="selectedNode.data.platform_id"
                :items="platforms"
                item-title="display_name"
                item-value="id"
                :label="tm('platform')"
                :no-data-text="tm('noPlatforms')"
                variant="outlined"
                density="compact"
                class="mb-3"
              >
                <template v-slot:item="{ item, props }">
                  <v-list-item v-bind="props">
                    <template v-slot:prepend>
                      <v-icon size="small">mdi-send</v-icon>
                    </template>
                    <v-list-item-subtitle>{{ item.raw.name }} ({{ item.raw.status }})</v-list-item-subtitle>
                  </v-list-item>
                </template>
              </v-select>

              <v-text-field
                v-model="selectedNode.data.session"
                :label="tm('session')"
                :hint="tm('sessionHint')"
                variant="outlined"
                density="compact"
                persistent-hint
                placeholder="platform_id:message_type:session_id"
                class="mb-3"
              ></v-text-field>

              <v-text-field
                v-model="selectedNode.data.message"
                :label="tm('messageContent')"
                :hint="tm('messageContentHint')"
                variant="outlined"
                density="compact"
                persistent-hint
                placeholder="{{output}}"
                class="mb-3"
              ></v-text-field>

              <v-text-field
                v-model="selectedNode.data.output_variable"
                :label="tm('outputVariable')"
                variant="outlined"
                density="compact"
                placeholder="_send_result"
              ></v-text-field>
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
    <v-dialog v-model="testDialog" max-width="800">
      <v-card>
        <v-card-title>{{ tm('testWorkflow') }}</v-card-title>
        <v-card-text>
          <v-textarea
            v-model="testInput"
            :label="tm('testInput')"
            variant="outlined"
            rows="3"
            class="mb-3"
          ></v-textarea>
          
          <!-- Image Upload for Vision Testing -->
          <div class="mb-4">
            <h5 class="text-caption mb-2">{{ tm('testImages') }}</h5>
            <v-file-input
              @update:model-value="onTestImageSelect"
              :label="tm('uploadImages')"
              accept="image/*"
              multiple
              prepend-icon="mdi-image"
              variant="outlined"
              density="compact"
              class="mb-2"
            ></v-file-input>
            <div v-if="testImageUrls.length > 0" class="d-flex flex-wrap gap-2">
              <v-chip
                v-for="(url, index) in testImageUrls"
                :key="index"
                closable
                @click:close="removeTestImage(index)"
                size="small"
              >
                <v-avatar start size="24">
                  <v-img :src="url"></v-img>
                </v-avatar>
                {{ tm('image') }} {{ index + 1 }}
              </v-chip>
            </div>
          </div>
          
          <div v-if="testResult !== null">
            <h4 class="text-subtitle-2 mb-2">{{ tm('testResult') }}</h4>
            <v-alert :type="testResultSuccess ? 'success' : 'error'" variant="tonal">
              <div class="markdown-result">
                <MarkdownRender :content="testResult" :typewriter="false" />
              </div>
            </v-alert>
            
            <!-- Display result components (images, etc.) -->
            <div v-if="testResultComponents.length > 0" class="mt-3">
              <h5 class="text-caption mb-2">{{ tm('resultComponents') }}</h5>
              <div class="d-flex flex-wrap gap-2">
                <template v-for="(comp, idx) in testResultComponents" :key="idx">
                  <v-img
                    v-if="comp.type === 'Image'"
                    :src="comp.url || comp.file"
                    max-width="200"
                    max-height="200"
                    class="rounded"
                  ></v-img>
                  <v-chip v-else-if="comp.type !== 'Plain'" size="small">
                    {{ comp.type }}
                  </v-chip>
                </template>
              </div>
            </div>
          </div>
          
          <div v-if="testLogs.length > 0 || testStructuredLogs.length > 0" class="mt-4">
            <h4 class="text-subtitle-2 mb-2">{{ tm('executionLogs') }}</h4>
            
            <!-- Structured Tool/Plugin Calls Display (like LLM tool calling UI) -->
            <div v-if="filteredStructuredLogs.length > 0" class="mb-3">
              <div class="d-flex align-center justify-space-between mb-2">
                <h5 class="text-caption">{{ tm('toolCalls') }}</h5>
                <v-btn
                  size="x-small"
                  variant="text"
                  @click="showSystemLogs = !showSystemLogs"
                >
                  <v-icon size="small" class="mr-1">{{ showSystemLogs ? 'mdi-eye-off' : 'mdi-eye' }}</v-icon>
                  {{ showSystemLogs ? tm('hideSystemLogs') : tm('showSystemLogs') }}
                </v-btn>
              </div>
              
              <v-expansion-panels variant="accordion">
                <v-expansion-panel
                  v-for="(log, idx) in filteredStructuredLogs"
                  :key="idx"
                >
                  <v-expansion-panel-title>
                    <div class="d-flex align-center">
                      <v-icon
                        :color="getLogTypeColor(log.type)"
                        size="small"
                        class="mr-2"
                      >{{ getLogTypeIcon(log.type) }}</v-icon>
                      <v-chip
                        :color="getLogTypeColor(log.type)"
                        size="x-small"
                        label
                        class="mr-2"
                      >{{ tm(`logTypes.${log.type}`) || log.type }}</v-chip>
                      <span class="text-body-2">{{ log.call_name || log.message }}</span>
                      <v-chip
                        v-if="log.metadata && log.metadata.error"
                        color="error"
                        size="x-small"
                        class="ml-2"
                      >Error</v-chip>
                    </div>
                  </v-expansion-panel-title>
                  <v-expansion-panel-text>
                    <!-- Plugin/Tool Info -->
                    <div v-if="log.metadata && log.metadata.plugin_name" class="mb-2">
                      <span class="text-caption text-grey">{{ tm('pluginName') }}:</span>
                      <span class="text-body-2 ml-1">{{ log.metadata.plugin_name }}</span>
                    </div>
                    
                    <!-- Call Arguments -->
                    <div v-if="log.call_args && Object.keys(log.call_args).length > 0" class="mb-2">
                      <div class="text-caption text-grey mb-1">{{ tm('callArgs') }}:</div>
                      <pre class="text-caption pa-2 rounded" style="background: rgba(var(--v-theme-surface-variant), 0.3); white-space: pre-wrap; word-break: break-word;">{{ JSON.stringify(log.call_args, null, 2) }}</pre>
                    </div>
                    
                    <!-- Call Result -->
                    <div v-if="log.call_result" class="mb-2">
                      <div class="text-caption text-grey mb-1">{{ tm('callResult') }}:</div>
                      <pre class="text-caption pa-2 rounded" style="background: rgba(var(--v-theme-surface-variant), 0.3); white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto;">{{ log.call_result }}</pre>
                    </div>
                    
                    <!-- Additional Metadata -->
                    <div v-if="log.metadata && Object.keys(log.metadata).filter(k => !['error', 'plugin_name', 'output_variable'].includes(k)).length > 0" class="text-caption text-grey">
                      <span>Node ID: {{ log.node_id }}</span>
                      <span v-if="log.metadata.output_variable" class="ml-3">Output: {{ log.metadata.output_variable }}</span>
                    </div>
                  </v-expansion-panel-text>
                </v-expansion-panel>
              </v-expansion-panels>
            </div>
            
            <div v-else-if="testStructuredLogs.length === 0 && testLogs.length === 0" class="text-caption text-grey mb-2">
              {{ tm('noToolCalls') }}
            </div>
            
            <!-- Raw Logs (hidden by default, in expansion panel) -->
            <v-expansion-panels variant="accordion">
              <v-expansion-panel>
                <v-expansion-panel-title>{{ tm('showLogs') }} ({{ testLogs.length }})</v-expansion-panel-title>
                <v-expansion-panel-text>
                  <pre class="text-caption" style="white-space: pre-wrap; max-height: 300px; overflow-y: auto;">{{ testLogs.join('\n') }}</pre>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn variant="text" @click="closeTestDialog">{{ t('core.actions.cancel') }}</v-btn>
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
import { useCustomizerStore } from '@/stores/customizer';
import { MarkdownRender } from 'markstream-vue';

const NODE_TYPES = [
  { type: 'start', icon: 'mdi-play-circle', color: 'success' },
  { type: 'end', icon: 'mdi-stop-circle', color: 'error' },
  { type: 'llm', icon: 'mdi-brain', color: 'primary' },
  { type: 'tool', icon: 'mdi-wrench', color: 'warning' },
  { type: 'knowledgeBase', icon: 'mdi-book-open-variant', color: 'purple' },
  { type: 'condition', icon: 'mdi-source-branch', color: 'info' },
  { type: 'llmJudge', icon: 'mdi-head-question', color: 'cyan' },
  { type: 'pluginCommand', icon: 'mdi-puzzle', color: 'teal' },
  { type: 'platformAction', icon: 'mdi-send', color: 'deep-purple' },
];

export default {
  name: 'WorkflowEditor',
  components: {
    MarkdownRender
  },
  props: {
    id: {
      type: String,
      default: null
    },
    fullscreenMode: {
      type: Boolean,
      default: false
    }
  },
  setup() {
    const { t } = useI18n();
    const { tm } = useModuleI18n('features/workflow');
    const customizer = useCustomizerStore();
    return { t, tm, customizer };
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
      pluginCommands: [],
      platforms: [],
      loading: false,
      saving: false,
      testing: false,
      testDialog: false,
      testInput: '',
      testResult: null,
      testResultComponents: [],
      testImageUrls: [],
      testImagePreview: null,
      testLogs: [],
      testStructuredLogs: [],
      showSystemLogs: false,
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
      // Middle button for panning
      middleButtonHeld: false,
      // Show help overlay
      showHelp: false,
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
    testResultSuccess() {
      return this.testResult !== null;
    },
    drawingEdgePath() {
      if (!this.drawingEdge) return '';
      return this.buildEdgePath(this.drawingEdgeStart, this.drawingEdgeEnd);
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
    },
    // Filter structured logs to show only tool/plugin calls (non-system logs)
    filteredStructuredLogs() {
      if (!this.testStructuredLogs || this.testStructuredLogs.length === 0) {
        return [];
      }
      
      // If showSystemLogs is true, show all; otherwise filter out system type
      return this.testStructuredLogs.filter(log => {
        if (this.showSystemLogs) {
          return true;
        }
        // Hide system logs by default, show tool_call, plugin_command, kb_query, etc.
        return log.type !== 'system';
      });
    },
    // Get icon for log type
    getLogTypeIcon() {
      return (type) => {
        const iconMap = {
          'tool_call': 'mdi-wrench',
          'plugin_command': 'mdi-puzzle',
          'kb_query': 'mdi-book-open-variant',
          'llm_call': 'mdi-brain',
          'condition': 'mdi-source-branch',
          'platform_action': 'mdi-send',
          'system': 'mdi-cog',
          'node_start': 'mdi-play',
          'node_end': 'mdi-stop'
        };
        return iconMap[type] || 'mdi-information';
      };
    },
    // Get color for log type
    getLogTypeColor() {
      return (type) => {
        const colorMap = {
          'tool_call': 'warning',
          'plugin_command': 'teal',
          'kb_query': 'purple',
          'llm_call': 'primary',
          'condition': 'info',
          'platform_action': 'deep-purple',
          'system': 'grey',
          'node_start': 'success',
          'node_end': 'error'
        };
        return colorMap[type] || 'grey';
      };
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
    await Promise.all([
      this.loadProviders(), 
      this.loadTools(), 
      this.loadKnowledgeBases(),
      this.loadPluginCommands(),
      this.loadPlatforms()
    ]);

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

    isConditionalNode(type) {
      return type === 'condition' || type === 'llmJudge';
    },

    getKnowledgeBaseName(kbId) {
      if (!kbId) return null;
      const kb = this.knowledgeBases.find(k => k.kb_id === kbId);
      return kb?.name || kbId;
    },

    getPluginCommandName(handlerFullName) {
      if (!handlerFullName) return null;
      const cmd = this.pluginCommands.find(c => c.handler_full_name === handlerFullName);
      if (cmd) {
        return cmd.command_name || cmd.handler_name;
      }
      return handlerFullName;
    },

    getPlatformName(platformId) {
      if (!platformId) return null;
      const platform = this.platforms.find(p => p.id === platformId);
      return platform?.display_name || platformId;
    },

    getNodeElement(nodeId) {
      if (!this.$refs.canvasRef) return null;
      return this.$refs.canvasRef.querySelector(`[data-node-id="${nodeId}"]`);
    },

    getNodeRect(nodeId) {
      const nodeEl = this.getNodeElement(nodeId);
      return nodeEl ? nodeEl.getBoundingClientRect() : null;
    },

    getHandlePosition(nodeId, handleType) {
      if (!this.$refs.canvasRef) return null;
      const nodeEl = this.getNodeElement(nodeId);
      if (!nodeEl) return null;

      let selector = '.connection-point.output';
      if (handleType === 'input') {
        selector = '.connection-point.input';
      } else if (handleType === 'output-true') {
        selector = '.connection-point.output-true';
      } else if (handleType === 'output-false') {
        selector = '.connection-point.output-false';
      }

      const handleEl = nodeEl.querySelector(selector);
      if (!handleEl) return null;

      const handleRect = handleEl.getBoundingClientRect();
      const canvasRect = this.$refs.canvasRef.getBoundingClientRect();

      return {
        x: (handleRect.left + handleRect.width / 2 - canvasRect.left - this.canvasOffset.x) / this.scale,
        y: (handleRect.top + handleRect.height / 2 - canvasRect.top - this.canvasOffset.y) / this.scale
      };
    },

    buildEdgePath(start, end) {
      if (!start || !end) return '';
      const controlX = (start.x + end.x) / 2;
      return `M ${start.x} ${start.y} C ${controlX} ${start.y}, ${controlX} ${end.y}, ${end.x} ${end.y}`;
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
      // Prevent default scrolling behavior
      event.preventDefault();

      // Check if Ctrl key is pressed for zooming, otherwise pan
      if (event.ctrlKey || event.metaKey) {
        // Zoom with Ctrl + scroll (like many design tools)
        const rect = this.$refs.canvasRef.getBoundingClientRect();
        const mouseX = event.clientX - rect.left;
        const mouseY = event.clientY - rect.top;

        // Calculate zoom with smooth factor
        const zoomFactor = event.deltaY > 0 ? 0.92 : 1.08;
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
      } else {
        // Pan with scroll wheel (like ComfyUI)
        // Shift + scroll = horizontal pan
        if (event.shiftKey) {
          this.targetOffset.x -= event.deltaY * 0.5;
        } else {
          this.targetOffset.x -= event.deltaX * 0.5;
          this.targetOffset.y -= event.deltaY * 0.5;
        }
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

    // Handle canvas click
    onCanvasClick(event) {
      // Only deselect if not panning
      if (!this.isPanning) {
        this.selectNode(null);
      }
    },

    // Handle canvas mouse down
    onCanvasMouseDown(event) {
      // Middle mouse button (wheel click) or right mouse button for panning
      if (event.button === 1 || event.button === 2) {
        this.startCanvasPan(event, true);
        return;
      }

      // Left mouse button
      if (event.button === 0) {
        // If space is pressed, pan the canvas
        if (this.spacePressed) {
          this.startCanvasPan(event, false);
          return;
        }
        // Otherwise, do nothing special (clicking on empty canvas will deselect via onCanvasClick)
      }
    },

    // Canvas panning with space + drag or middle mouse button
    startCanvasPan(event, isMiddleOrRight = false) {
      event.preventDefault();
      this.isPanning = true;
      if (isMiddleOrRight) {
        this.middleButtonHeld = true;
      }

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
        this.middleButtonHeld = false;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
      };

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
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
        position: { x: x, y: y },
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
            output_variable: 'output',
            enable_vision: true,
            input_image_variable: 'input',
            enable_tools: false,
            allowed_tools: []
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
        case 'llmJudge':
          return {
            provider_id: '',
            judge_prompt: '',
            true_keywords: '是,yes,true,正确'
          };
        case 'pluginCommand':
          return {
            handler_full_name: '',
            arguments: {},
            output_variable: '_plugin_result'
          };
        case 'platformAction':
          return {
            platform_id: '',
            session: '',
            message: '{{output}}',
            output_variable: '_send_result'
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

      // Prevent text selection during drag
      event.preventDefault();

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
        e.preventDefault(); // Prevent text selection during drag
        if (this.draggingNode && this.$refs.canvasRef) {
          const rect = this.$refs.canvasRef.getBoundingClientRect();
          const mouseX = (e.clientX - rect.left - this.canvasOffset.x) / this.scale;
          const mouseY = (e.clientY - rect.top - this.canvasOffset.y) / this.scale;

          // Queue position update
          pendingUpdate = {
            x: mouseX - this.dragOffset.x,
            y: mouseY - this.dragOffset.y
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

    startConnection(event, nodeId, handleType) {
      if (!this.$refs.canvasRef) return;

      const node = this.nodes.find(n => n.id === nodeId);
      if (!node) return;

      // Prevent text selection during connection drawing
      event.preventDefault();

      this.drawingEdge = true;

      const handlePos = this.getHandlePosition(nodeId, handleType);
      const nodeRect = this.getNodeRect(node.id);
      const nodeWidth = nodeRect?.width || 150;
      const nodeHeight = nodeRect?.height || 70;

      // Calculate starting position based on handle type
      let startX = node.position.x + nodeWidth;
      let startY = node.position.y + nodeHeight / 2;

      if (handleType === 'output-true') {
        startY = node.position.y + nodeHeight * 0.3;
      } else if (handleType === 'output-false') {
        startY = node.position.y + nodeHeight * 0.7;
      }

      if (handlePos) {
        startX = handlePos.x;
        startY = handlePos.y;
      }
      
      this.drawingEdgeStart = {
        nodeId,
        handleType,  // Store the handle type (output, output-true, output-false)
        x: startX,
        y: startY
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
        e.preventDefault(); // Prevent text selection during connection drawing
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

    // Handle mouseup on node - for easier connection
    onNodeMouseUp(event, node) {
      // If we're drawing an edge, try to connect to this node
      if (this.drawingEdge && node.type !== 'start') {
        this.endConnection(event, node.id);
      }
    },

    endConnection(event, nodeId) {
      if (!this.drawingEdge) return;

      const sourceId = this.drawingEdgeStart.nodeId;
      const sourceHandle = this.drawingEdgeStart.handleType || 'output';
      if (sourceId === nodeId) return;

      // Check for existing connection with same source handle
      const exists = this.edges.some(e => 
        e.source === sourceId && 
        e.target === nodeId && 
        (e.sourceHandle || 'output') === sourceHandle
      );
      if (exists) return;

      const newEdge = {
        id: `edge_${sourceId}_${sourceHandle}_${nodeId}`,
        source: sourceId,
        target: nodeId,
        sourceHandle: sourceHandle  // Store which handle was used (output, output-true, output-false)
      };

      this.edges.push(newEdge);
      this.drawingEdge = false;
    },

    getEdgePath(edge) {
      const sourceNode = this.nodes.find(n => n.id === edge.source);
      const targetNode = this.nodes.find(n => n.id === edge.target);

      if (!sourceNode || !targetNode) return '';

      const sourceHandle = edge.sourceHandle || 'output';
      let start = this.getHandlePosition(sourceNode.id, sourceHandle);
      if (!start) {
        const sourceRect = this.getNodeRect(sourceNode.id);
        const sourceWidth = sourceRect?.width || 150;
        const sourceHeight = sourceRect?.height || 70;
        let yRatio = 0.5;
        if (sourceHandle === 'output-true') {
          yRatio = 0.3;
        } else if (sourceHandle === 'output-false') {
          yRatio = 0.7;
        }
        start = {
          x: sourceNode.position.x + sourceWidth,
          y: sourceNode.position.y + sourceHeight * yRatio
        };
      }

      let end = this.getHandlePosition(targetNode.id, 'input');
      if (!end) {
        const targetRect = this.getNodeRect(targetNode.id);
        const targetHeight = targetRect?.height || 70;
        end = {
          x: targetNode.position.x,
          y: targetNode.position.y + targetHeight / 2
        };
      }

      return this.buildEdgePath(start, end);
    },
    
    getEdgeClass(edge) {
      let classes = ['edge-path'];
      if (this.selectedEdgeId === edge.id) {
        classes.push('selected');
      }
      if (edge.sourceHandle === 'output-true') {
        classes.push('edge-true');
      } else if (edge.sourceHandle === 'output-false') {
        classes.push('edge-false');
      }
      return classes.join(' ');
    },

    goBack() {
      if (this.fullscreenMode) {
        // In fullscreen mode, close the window/tab or go back to workflow view mode
        if (window.opener) {
          window.close();
        } else {
          // Switch back to workflow view mode instead of routing
          this.customizer.SET_VIEW_MODE('workflow');
          this.$router.push('/');
        }
      } else {
        // Switch to workflow view mode
        this.customizer.SET_VIEW_MODE('workflow');
        this.$router.push('/');
      }
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
            this.$router.replace(`/workflow/edit/${this.workflowId}`);
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

    async loadPluginCommands() {
      try {
        const response = await axios.get('/api/workflow/plugin-commands/available');
        if (response.data.status === 'ok') {
          this.pluginCommands = response.data.data || [];
        }
      } catch (error) {
        console.error('Failed to load plugin commands:', error);
      }
    },

    async loadPlatforms() {
      try {
        const response = await axios.get('/api/workflow/platforms/available');
        if (response.data.status === 'ok') {
          this.platforms = response.data.data || [];
        }
      } catch (error) {
        console.error('Failed to load platforms:', error);
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

    // Apply default condition template
    applyConditionTemplate() {
      if (!this.selectedNode || this.selectedNode.type !== 'condition') return;
      this.selectedNode.data.condition = `# 判断 input 是否满足条件
# 可用变量: input, output, 及其他工作流变量
# 返回 True 走"是"分支, 返回 False 走"否"分支

def check(variables):
    input_text = variables.get('input', '')
    # 示例: 检查输入长度
    if len(input_text) > 10:
        return True
    return False

result = check(variables)`;
    },

    // Apply default LLM judge template
    applyLlmJudgeTemplate() {
      if (!this.selectedNode || this.selectedNode.type !== 'llmJudge') return;
      this.selectedNode.data.judge_prompt = `请判断以下内容是否满足条件。

用户输入: {{input}}
上一步输出: {{output}}

如果满足条件请回答"是"，否则回答"否"。只需回答一个字。`;
      this.selectedNode.data.true_keywords = '是,yes,true,对,正确,满足';
    },

    testWorkflow() {
      this.testDialog = true;
      this.testResult = null;
      this.testResultComponents = [];
    },

    closeTestDialog() {
      this.testDialog = false;
      this.testResult = null;
      this.testResultComponents = [];
      this.testImageUrls = [];
      this.testStructuredLogs = [];
      this.showSystemLogs = false;
    },

    onTestImageSelect(files) {
      if (!files || files.length === 0) return;
      
      // Convert files to data URLs for preview and sending
      for (const file of files) {
        const reader = new FileReader();
        reader.onload = (e) => {
          if (e.target?.result) {
            this.testImageUrls.push(e.target.result);
          }
        };
        reader.readAsDataURL(file);
      }
    },

    removeTestImage(index) {
      this.testImageUrls.splice(index, 1);
    },

    async runTest() {
      this.testing = true;
      this.testLogs = [];
      this.testStructuredLogs = [];
      this.testResultComponents = [];
      try {
        const response = await axios.post('/api/workflow/test', {
          workflow_data: {
            nodes: this.nodes,
            edges: this.edges
          },
          input: this.testInput,
          image_urls: this.testImageUrls
        });
        if (response.data.status === 'ok') {
          this.testResult = response.data.data.result;
          this.testResultComponents = response.data.data.result_components || [];
          this.testLogs = response.data.data.logs || [];
          this.testStructuredLogs = response.data.data.structured_logs || [];
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
  height: 0; /* Force flex item to shrink and allow overflow */
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
  height: 100%;
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
    linear-gradient(rgba(var(--v-border-color), 0.15) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--v-border-color), 0.15) 1px, transparent 1px);
  background-size: 20px 20px;
  overflow: hidden;
  cursor: default;
  touch-action: none;
  user-select: none;

  &.space-panning {
    cursor: grab;
  }

  &.is-panning {
    cursor: grabbing !important;

    * {
      cursor: grabbing !important;
      user-select: none !important;
    }
  }

  &.is-dragging {
    * {
      user-select: none !important;
      -webkit-user-select: none !important;
    }
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
    
    &.edge-true {
      stroke: rgb(var(--v-theme-success));
      
      &:hover {
        filter: drop-shadow(0 0 4px rgba(var(--v-theme-success), 0.5));
      }
    }
    
    &.edge-false {
      stroke: rgb(var(--v-theme-error));
      
      &:hover {
        filter: drop-shadow(0 0 4px rgba(var(--v-theme-error), 0.5));
      }
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
    
    &.output-true {
      right: -6px;
      top: 25%;
      margin-top: -3px;
      background: rgb(var(--v-theme-success));
      
      &:hover {
        box-shadow: 0 0 8px rgba(var(--v-theme-success), 0.6);
      }
    }
    
    &.output-false {
      right: -6px;
      top: 75%;
      margin-top: -3px;
      background: rgb(var(--v-theme-error));
      
      &:hover {
        box-shadow: 0 0 8px rgba(var(--v-theme-error), 0.6);
      }
    }
  }
}

.node-start .node-header {
  background: rgba(var(--v-theme-success), 0.1);
}
.node-start {
  border-color: rgba(var(--v-theme-success), 0.5);
}

.node-end .node-header {
  background: rgba(var(--v-theme-error), 0.1);
}
.node-end {
  border-color: rgba(var(--v-theme-error), 0.5);
}

.node-llm .node-header {
  background: rgba(var(--v-theme-primary), 0.1);
}
.node-llm {
  border-color: rgba(var(--v-theme-primary), 0.5);
}

.node-tool .node-header {
  background: rgba(var(--v-theme-warning), 0.1);
}
.node-tool {
  border-color: rgba(var(--v-theme-warning), 0.5);
}

.node-knowledgeBase .node-header {
  background: rgba(128, 0, 128, 0.1);
}
.node-knowledgeBase {
  border-color: rgba(128, 0, 128, 0.5);
}

.node-condition .node-header {
  background: rgba(var(--v-theme-info), 0.1);
}
.node-condition {
  border-color: rgba(var(--v-theme-info), 0.5);
}

.node-llmJudge .node-header {
  background: rgba(0, 188, 212, 0.1);
}
.node-llmJudge {
  border-color: rgba(0, 188, 212, 0.5);
}

.node-pluginCommand .node-header {
  background: rgba(0, 150, 136, 0.1);
}
.node-pluginCommand {
  border-color: rgba(0, 150, 136, 0.5);
}

.node-platformAction .node-header {
  background: rgba(103, 58, 183, 0.1);
}
.node-platformAction {
  border-color: rgba(103, 58, 183, 0.5);
}

.properties-panel {
  border-left: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  overflow-y: auto;
  overflow-x: hidden;
  background: rgb(var(--v-theme-surface));
  height: 100%;
  max-height: 100%;
}

.markdown-result {
  :deep(p) {
    margin-bottom: 0.5em;
  }
  :deep(ul), :deep(ol) {
    padding-left: 1.5em;
    margin-bottom: 0.5em;
  }
  :deep(pre) {
    background: rgba(0, 0, 0, 0.05);
    padding: 8px;
    border-radius: 4px;
    overflow-x: auto;
  }
  :deep(code) {
    font-family: monospace;
    font-size: 0.9em;
  }
}

.help-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding: 60px 20px 20px;
  z-index: 200;
}

.help-card {
  border-radius: 12px;
}

.help-item {
  display: flex;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));

  &:last-child {
    border-bottom: none;
  }
}
</style>
