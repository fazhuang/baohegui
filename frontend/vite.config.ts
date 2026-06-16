/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig(() => {
  const isAnalyze = process.env.ANALYZE === 'true';

  return {
    plugins: [
      react(),
      ...(isAnalyze ? [visualizer({
        filename: '.analyze/stats.html',
        open: false,
        gzipSize: true,
        brotliSize: true,
      })] : []),
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
          manualChunks(id: string) {
            if (!id.includes('node_modules')) {
              if (id.includes('src/pages/Report') || id.includes('src/features/report')) return 'page-report';
              if (id.includes('src/pages/Upload') || id.includes('src/features/upload')) return 'page-upload';
              if (id.includes('src/pages/AdminPanel') || id.includes('src/features/admin')) return 'page-admin';
              if (id.includes('src/pages/AdminRules') || id.includes('src/features/rules')) return 'page-rules';
              if (id.includes('src/pages/History') || id.includes('src/features/history')) return 'page-history';
              if (id.includes('src/pages/dashboards/')) return 'page-dashboard';
              return undefined;
            }

            // React ecosystem — standalone, no circular deps
            if (id.includes('node_modules/react-dom/') || id.includes('node_modules/react-dom-')) return 'vendor-react-dom';
            if (id.includes('node_modules/react/') || id.includes('node_modules/react-jsx') || id.includes('node_modules/scheduler/')) return 'vendor-react';
            if (id.includes('node_modules/react-router/') || id.includes('node_modules/@remix-run/')) return 'vendor-router';
            if (id.includes('node_modules/axios/')) return 'vendor-axios';
            if (id.includes('node_modules/dayjs/')) return 'vendor-dayjs';
            if (id.includes('node_modules/zustand/')) return 'vendor-zustand';

            // Ant Design — single chunk, zero cycles.
            // antd/ ↔ rc-* ↔ @ant-design/ ↔ @rc-component form a
            // dense dependency mesh; any split creates circular chunks.
            // 1.18 MB raw / 368 KB gzip — cached after first load.
            if (id.includes('node_modules/antd/') ||
                id.includes('node_modules/rc-') ||
                id.includes('node_modules/@ant-design/') ||
                id.includes('node_modules/@rc-component/')) return 'vendor-antd';

            return undefined;
          },
        },
      },
    },
  };
});
