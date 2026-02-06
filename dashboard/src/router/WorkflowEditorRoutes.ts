const WorkflowEditorRoutes = {
    path: '/workflow-editor',
    component: () => import('@/layouts/blank/BlankLayout.vue'),
    children: [
        {
            name: 'WorkflowEditorFullscreen',
            path: '/workflow-editor',
            component: () => import('@/views/workflow/WorkflowEditorPage.vue'),
            children: [
                {
                    path: 'new',
                    name: 'WorkflowEditorFullscreenNew',
                    component: () => import('@/views/workflow/WorkflowEditorPage.vue'),
                    props: { id: null }
                },
                {
                    path: 'edit/:id',
                    name: 'WorkflowEditorFullscreenEdit',
                    component: () => import('@/views/workflow/WorkflowEditorPage.vue'),
                    props: true
                }
            ]
        }
    ]
};

export default WorkflowEditorRoutes;
