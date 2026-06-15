/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) {
            // Feature-based page chunking
            if (id.includes('src/pages/Report') || id.includes('src/features/report')) return 'page-report';
            if (id.includes('src/pages/Upload') || id.includes('src/features/upload')) return 'page-upload';
            if (id.includes('src/pages/AdminPanel') || id.includes('src/features/admin')) return 'page-admin';
            if (id.includes('src/pages/AdminRules') || id.includes('src/features/rules')) return 'page-rules';
            if (id.includes('src/pages/History') || id.includes('src/features/history')) return 'page-history';
            return undefined;
          }

          // Vendor splits
          if (id.includes('node_modules/react-dom') || id.includes('node_modules/react-router')) return 'vendor-react';
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-jsx') || id.includes('node_modules/scheduler')) return 'vendor-react-core';
          if (id.includes('node_modules/@ant-design/icons') || id.includes('node_modules/@ant-design/cssinjs') || id.includes('node_modules/@ant-design/colors') || id.includes('node_modules/@ant-design/fast-color')) return 'vendor-icons';
          if (id.includes('node_modules/antd') || id.includes('node_modules/rc-') || id.includes('node_modules/@rc-component')) return 'vendor-antd';
          if (id.includes('node_modules/axios')) return 'vendor-axios';
          if (id.includes('node_modules/dayjs')) return 'vendor-dayjs';
          if (id.includes('node_modules/zustand')) return 'vendor-zustand';

          return undefined;
        },
      },
    },
  },
})
