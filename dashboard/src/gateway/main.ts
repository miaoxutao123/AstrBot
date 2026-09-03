import { createApp } from 'vue';
import vuetify from '@/plugins/vuetify';
import GatewayApp from './GatewayApp.vue';
import '@/scss/style.scss';

createApp(GatewayApp).use(vuetify).mount('#app');
