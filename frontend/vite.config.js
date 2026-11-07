import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const target = process.env.LEDGER_API_URL || process.env.VITE_OPERATIONAL_API || 'http://127.0.0.1:28751';
export default defineConfig({ plugins: [react()], server: { host: '127.0.0.1', proxy: { '/api': { target, changeOrigin: false } } } });
