<script setup lang="ts">
import { useRoute } from 'vue-router';
import { computed } from 'vue';
import WorkflowEditor from './WorkflowEditor.vue';
import { useCustomizerStore } from '@/stores/customizer';

const route = useRoute();
const customizer = useCustomizerStore();

// Get workflow ID from route params
const workflowId = computed(() => {
  return route.params.id as string | undefined;
});

// Determine if this is a new workflow or editing existing
const isNewWorkflow = computed(() => {
  return route.path.includes('/new') || !workflowId.value;
});
</script>

<template>
  <v-app :theme="customizer.uiTheme" style="height: 100%; width: 100%;">
    <div class="workflow-editor-fullscreen">
      <WorkflowEditor 
        :id="workflowId" 
        :fullscreen-mode="true"
      />
    </div>
  </v-app>
</template>

<style scoped>
.workflow-editor-fullscreen {
  width: 100%;
  height: 100vh;
  overflow: hidden;
}
</style>
