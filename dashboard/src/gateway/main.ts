import { createApp } from 'vue';
import vuetify from '@/plugins/vuetify';
import GatewayApp from './GatewayApp.vue';
import { setupI18n } from '@/i18n/composables';
import '@/scss/style.scss';

setupI18n().finally(() => createApp(GatewayApp).use(vuetify).mount('#app'));
