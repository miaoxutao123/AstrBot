<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <v-card>
          <v-card-title class="d-flex align-center">
            <span>{{ tm('title') }}</span>
            <v-chip class="ml-2" size="small" color="primary">{{ tm('subtitle') }}</v-chip>
            <v-spacer></v-spacer>
            <v-text-field
              v-model="search"
              prepend-inner-icon="mdi-magnify"
              :placeholder="tm('search')"
              variant="outlined"
              density="compact"
              hide-details
              class="mr-4"
              style="max-width: 300px"
            ></v-text-field>
            <v-btn color="primary" @click="createWorkflow">
              <v-icon left>mdi-plus</v-icon>
              {{ tm('create') }}
            </v-btn>
          </v-card-title>
          <v-card-text>
            <v-row v-if="filteredWorkflows.length > 0">
              <v-col
                v-for="workflow in filteredWorkflows"
                :key="workflow.workflow_id"
                cols="12"
                md="6"
                lg="4"
              >
                <v-card variant="outlined" class="workflow-card">
                  <v-card-title class="d-flex align-center">
                    <v-icon color="primary" class="mr-2">mdi-sitemap</v-icon>
                    <span class="text-truncate">{{ workflow.name }}</span>
                    <v-spacer></v-spacer>
                    <v-chip
                      v-if="workflow.deployed"
                      size="x-small"
                      color="success"
                      class="mr-1"
                    >
                      {{ tm('deployed') }}
                    </v-chip>
                    <v-chip
                      size="x-small"
                      :color="workflow.enabled ? 'primary' : 'grey'"
                    >
                      {{ workflow.enabled ? tm('active') : tm('inactive') }}
                    </v-chip>
                  </v-card-title>
                  <v-card-text>
                    <p class="text-body-2 text-grey mb-2">
                      {{ workflow.description || 'No description' }}
                    </p>
                    <p class="text-caption text-grey">
                      Updated: {{ formatDate(workflow.updated_at) }}
                    </p>
                  </v-card-text>
                  <v-card-actions>
                    <v-btn
                      variant="text"
                      color="primary"
                      @click="editWorkflow(workflow)"
                    >
                      <v-icon left>mdi-pencil</v-icon>
                      {{ tm('edit') }}
                    </v-btn>
                    <v-btn
                      v-if="!workflow.deployed"
                      variant="text"
                      color="success"
                      :loading="deploying === workflow.workflow_id"
                      @click="deployWorkflow(workflow)"
                    >
                      <v-icon left>mdi-rocket-launch</v-icon>
                      {{ tm('deploy') }}
                    </v-btn>
                    <v-btn
                      v-else
                      variant="text"
                      color="warning"
                      :loading="deploying === workflow.workflow_id"
                      @click="undeployWorkflow(workflow)"
                    >
                      <v-icon left>mdi-rocket-launch-outline</v-icon>
                      {{ tm('undeploy') }}
                    </v-btn>
                    <v-spacer></v-spacer>
                    <v-btn
                      variant="text"
                      color="error"
                      @click="confirmDelete(workflow)"
                    >
                      <v-icon left>mdi-delete</v-icon>
                      {{ tm('delete') }}
                    </v-btn>
                  </v-card-actions>
                </v-card>
              </v-col>
            </v-row>
            <v-row v-else>
              <v-col cols="12" class="text-center py-12">
                <v-icon size="64" color="grey-lighten-1">mdi-sitemap</v-icon>
                <p class="text-h6 text-grey mt-4">{{ tm('empty') }}</p>
                <p class="text-body-2 text-grey">{{ tm('emptyHint') }}</p>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- Delete Confirmation Dialog -->
    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card>
        <v-card-title>{{ tm('deleteConfirm') }}</v-card-title>
        <v-card-text>
          {{ tm('deleteConfirmMessage').replace('{name}', workflowToDelete?.name || '') }}
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn variant="text" @click="deleteDialog = false">{{ t('actions.cancel') }}</v-btn>
          <v-btn color="error" variant="flat" @click="deleteWorkflow">{{ tm('delete') }}</v-btn>
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

export default {
  name: 'WorkflowList',
  setup() {
    const { t } = useI18n();
    const { tm } = useModuleI18n('features/workflow');
    return { t, tm };
  },
  data() {
    return {
      workflows: [],
      search: '',
      loading: false,
      deploying: null,
      deleteDialog: false,
      workflowToDelete: null,
      snackbar: {
        show: false,
        message: '',
        color: 'success'
      }
    };
  },
  computed: {
    filteredWorkflows() {
      if (!this.search) return this.workflows;
      const searchLower = this.search.toLowerCase();
      return this.workflows.filter(
        w => w.name.toLowerCase().includes(searchLower) ||
             (w.description && w.description.toLowerCase().includes(searchLower))
      );
    }
  },
  mounted() {
    this.fetchWorkflows();
  },
  methods: {
    async fetchWorkflows() {
      this.loading = true;
      try {
        const response = await axios.get('/api/workflow/list');
        if (response.data.status === 'ok') {
          this.workflows = response.data.data || [];
        }
      } catch (error) {
        console.error('Failed to fetch workflows:', error);
        this.showSnackbar('Failed to load workflows', 'error');
      } finally {
        this.loading = false;
      }
    },
    createWorkflow() {
      this.$router.push('/workflow/editor');
    },
    editWorkflow(workflow) {
      this.$router.push(`/workflow/editor/${workflow.workflow_id}`);
    },
    confirmDelete(workflow) {
      this.workflowToDelete = workflow;
      this.deleteDialog = true;
    },
    async deleteWorkflow() {
      if (!this.workflowToDelete) return;
      try {
        await axios.delete(`/api/workflow/delete/${this.workflowToDelete.workflow_id}`);
        this.workflows = this.workflows.filter(
          w => w.workflow_id !== this.workflowToDelete.workflow_id
        );
        this.showSnackbar(this.tm('deleted'), 'success');
      } catch (error) {
        console.error('Failed to delete workflow:', error);
        this.showSnackbar('Failed to delete workflow', 'error');
      } finally {
        this.deleteDialog = false;
        this.workflowToDelete = null;
      }
    },
    formatDate(dateString) {
      if (!dateString) return 'N/A';
      return new Date(dateString).toLocaleString();
    },
    async deployWorkflow(workflow) {
      this.deploying = workflow.workflow_id;
      try {
        const response = await axios.post(`/api/workflow/deploy/${workflow.workflow_id}`);
        if (response.data.status === 'ok') {
          workflow.deployed = true;
          this.showSnackbar(this.tm('deploySuccess'), 'success');
        } else {
          this.showSnackbar(response.data.message || this.tm('deployFailed'), 'error');
        }
      } catch (error) {
        console.error('Failed to deploy workflow:', error);
        this.showSnackbar(this.tm('deployFailed'), 'error');
      } finally {
        this.deploying = null;
      }
    },
    async undeployWorkflow(workflow) {
      this.deploying = workflow.workflow_id;
      try {
        const response = await axios.post(`/api/workflow/undeploy/${workflow.workflow_id}`);
        if (response.data.status === 'ok') {
          workflow.deployed = false;
          this.showSnackbar(this.tm('undeploySuccess'), 'success');
        } else {
          this.showSnackbar(response.data.message || this.tm('undeployFailed'), 'error');
        }
      } catch (error) {
        console.error('Failed to undeploy workflow:', error);
        this.showSnackbar(this.tm('undeployFailed'), 'error');
      } finally {
        this.deploying = null;
      }
    },
    showSnackbar(message, color = 'success') {
      this.snackbar = { show: true, message, color };
    }
  }
};
</script>

<style scoped>
.workflow-card {
  transition: all 0.2s ease;
}
.workflow-card:hover {
  border-color: rgb(var(--v-theme-primary));
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}
</style>
