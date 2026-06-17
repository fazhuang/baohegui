/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig(() => {
  const isAnalyze = process.env.ANALYZE === 'true';
  const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://backend:8000';

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
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      css: false,
      exclude: ['scripts/**', 'node_modules/**'],
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (!id.includes('node_modules')) return undefined;

            // React ecosystem — standalone, no circular deps
            if (id.includes('node_modules/react-dom/') || id.includes('node_modules/react-dom-')) return 'vendor-react-dom';
            if (id.includes('node_modules/react/') || id.includes('node_modules/react-jsx') || id.includes('node_modules/scheduler/')) return 'vendor-react';
            if (id.includes('node_modules/react-router/') || id.includes('node_modules/@remix-run/')) return 'vendor-router';
            if (id.includes('node_modules/axios/')) return 'vendor-axios';
            if (id.includes('node_modules/dayjs/')) return 'vendor-dayjs';
            if (id.includes('node_modules/zustand/')) return 'vendor-zustand';

            // antd icons — pure SVG data, zero circular risk
            if (id.includes('node_modules/@ant-design/icons/') ||
                id.includes('node_modules/@ant-design/icons-svg/')) return 'vendor-antd-icons';

            // antd core runtime (cssinjs, theme) — leaf deps, zero circular risk
            if (id.includes('node_modules/@ant-design/cssinjs/') ||
                id.includes('node_modules/@ant-design/fast-color/') ||
                id.includes('node_modules/@emotion/') ||
                id.includes('node_modules/stylis/')) return 'vendor-antd-runtime';

            // Let all other antd/rc-* components distribute naturally
            // across lazy page chunks via Rollup's automatic splitting.
            return undefined;
          },
        },
      },
    },
  };
});
