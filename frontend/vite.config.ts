/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig({
  plugins: [
    react(),
    visualizer({
      filename: 'dist/stats.html',
      open: false,
      gzipSize: true,
      brotliSize: true,
    }),
  ],
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
        // Splitting strategy:
        // - antd ecosystem (~1.2MB minified) stays as one chunk because
        //   rc-* ↔ antd form circular imports. gzip = 368 KB.
        // - All individual page chunks are well under 50 KB.
        // - Users only download vendor-antd once, then each page is tiny.
        manualChunks(id: string) {
          if (!id.includes('node_modules')) {
            if (id.includes('src/pages/Report') || id.includes('src/features/report')) return 'page-report';
            if (id.includes('src/pages/Upload') || id.includes('src/features/upload')) return 'page-upload';
            if (id.includes('src/pages/AdminPanel') || id.includes('src/features/admin')) return 'page-admin';
            if (id.includes('src/pages/AdminRules') || id.includes('src/features/rules')) return 'page-rules';
            if (id.includes('src/pages/History') || id.includes('src/features/history')) return 'page-history';
            return undefined;
          }

          // React ecosystem
          if (id.includes('node_modules/react-dom/')) return 'vendor-react-dom';
          if (id.includes('node_modules/react-router/') || id.includes('node_modules/@remix-run/')) return 'vendor-router';
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-jsx') || id.includes('node_modules/scheduler/')) return 'vendor-react';

          // Ant Design — avoid circular chunk warnings by keeping together
          if (id.includes('node_modules/rc-') ||
              id.includes('node_modules/antd/') ||
              id.includes('node_modules/@ant-design/') ||
              id.includes('node_modules/@rc-component/')) {
            return 'vendor-antd';
          }

          // Other small vendors
          if (id.includes('node_modules/axios/')) return 'vendor-axios';
          if (id.includes('node_modules/dayjs/')) return 'vendor-dayjs';
          if (id.includes('node_modules/zustand/')) return 'vendor-zustand';

          return undefined;
        },
      },
    },
  },
})
