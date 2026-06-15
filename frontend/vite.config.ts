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
      // 仅在 ANALYZE=true 时启用 bundle 分析，产物输出到 .analyze/
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

            // React ecosystem
            if (id.includes('node_modules/react-dom/') || id.includes('node_modules/react-dom-')) return 'vendor-react-dom';
            if (id.includes('node_modules/react/') || id.includes('node_modules/react-jsx') || id.includes('node_modules/scheduler/')) return 'vendor-react';
            if (id.includes('node_modules/react-router/') || id.includes('node_modules/@remix-run/')) return 'vendor-router';
            if (id.includes('node_modules/axios/')) return 'vendor-axios';
            if (id.includes('node_modules/dayjs/')) return 'vendor-dayjs';
            if (id.includes('node_modules/zustand/')) return 'vendor-zustand';

            // antd CSS-in-JS runtime — @ant-design/cssinjs / cssinjs-utils
            if (id.includes('node_modules/@ant-design/cssinjs') ||
                id.includes('node_modules/@ant-design/fast-color/')) return 'vendor-antd-styles';

            // antd icons SVG data — large pure-data module
            if (id.includes('node_modules/@ant-design/icons-svg/') ||
                id.includes('node_modules/@ant-design/icons/es/')) return 'vendor-antd-icons';

            // antd heavy component families
            if (id.includes('node_modules/rc-picker/') ||
                id.includes('node_modules/antd/es/date-picker/') ||
                id.includes('node_modules/antd/es/calendar/') ||
                id.includes('node_modules/antd/es/time-picker/') ||
                id.includes('node_modules/antd/es/color-picker/')) return 'vendor-antd-picker';

            if (id.includes('node_modules/rc-table/') ||
                id.includes('node_modules/antd/es/table/')) return 'vendor-antd-table';

            if (id.includes('node_modules/rc-select/') ||
                id.includes('node_modules/antd/es/select/')) return 'vendor-antd-select';

            if (id.includes('node_modules/rc-field-form/') ||
                id.includes('node_modules/antd/es/form/')) return 'vendor-antd-form';

            if (id.includes('node_modules/rc-tree/') ||
                id.includes('node_modules/antd/es/tree/') ||
                id.includes('node_modules/rc-tree-select/') ||
                id.includes('node_modules/antd/es/tree-select/')) return 'vendor-antd-tree';

            if (id.includes('node_modules/rc-tabs/') ||
                id.includes('node_modules/antd/es/tabs/')) return 'vendor-antd-tabs';

            if (id.includes('node_modules/rc-menu/') ||
                id.includes('node_modules/antd/es/menu/')) return 'vendor-antd-menu';

            if (id.includes('node_modules/rc-input/') ||
                id.includes('node_modules/antd/es/input/') ||
                id.includes('node_modules/rc-input-number/') ||
                id.includes('node_modules/antd/es/input-number/')) return 'vendor-antd-input';

            if (id.includes('node_modules/rc-slider/') ||
                id.includes('node_modules/antd/es/slider/')) return 'vendor-antd-slider';

            if (id.includes('node_modules/rc-upload/') ||
                id.includes('node_modules/antd/es/upload/')) return 'vendor-antd-upload';

            // antd medium-weight utilities — trigger, virtual-list, motion, pagination, notification
            if (id.includes('node_modules/@rc-component/trigger/') ||
                id.includes('node_modules/rc-virtual-list/') ||
                id.includes('node_modules/rc-motion/') ||
                id.includes('node_modules/rc-pagination/') ||
                id.includes('node_modules/rc-notification/') ||
                id.includes('node_modules/rc-dialog/') ||
                id.includes('node_modules/rc-drawer/') ||
                id.includes('node_modules/rc-tooltip/') ||
                id.includes('node_modules/rc-overflow/') ||
                id.includes('node_modules/rc-resize-observer/') ||
                id.includes('node_modules/@rc-component/portal/') ||
                id.includes('node_modules/@rc-component/async-validator/') ||
                id.includes('node_modules/resize-observer-polyfill/')) return 'vendor-antd-utils';

            // vendor-antd: remaining rc-* / antd / @ant-design / @rc-component
            if (id.includes('node_modules/antd/') ||
                id.includes('node_modules/rc-') ||
                id.includes('node_modules/@ant-design/') ||
                id.includes('node_modules/@rc-component/')) {
              return 'vendor-antd';
            }

            return undefined;
          },
        },
      },
    },
  };
});
