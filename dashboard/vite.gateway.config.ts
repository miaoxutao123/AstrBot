import { fileURLToPath, URL } from 'url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import vuetify from 'vite-plugin-vuetify';

export default defineConfig({
  base: '/ui/',
  plugins: [vue(), vuetify({ autoImport: true })],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  build: {
    outDir: '../gateway/gateway/ui',
    emptyOutDir: true,
    rollupOptions: { input: fileURLToPath(new URL('./gateway.html', import.meta.url)) }
  },
  server: {
    proxy: {
      '/v1': 'http://127.0.0.1:6186',
      '/.well-known': 'http://127.0.0.1:6186',
      '/docs': 'http://127.0.0.1:6186'
    }
  }
});
