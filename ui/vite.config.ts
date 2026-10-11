import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The Python server serves the build from titan/ui and falls back to
// titan/web for shared assets (app icons, wallpapers, VM console).
const backend = process.env.TITAN_BACKEND || 'http://127.0.0.1:5089';
const shared = ['/api', '/app-icons', '/wallpapers', '/brand', '/logo.svg', '/console.html', '/classic', '/novnc', '/vendor'];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: '../titan/ui', emptyOutDir: true, assetsDir: 'ui-assets', modulePreload: { polyfill: false } },
  server: { port: 5173, proxy: Object.fromEntries(shared.map(path => [path, { target: backend, changeOrigin: false }])) },
});
