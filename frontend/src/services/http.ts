/**
 * 统一 HTTP 客户端 — 所有前端请求的唯一出口
 *
 * - 自动附加 Bearer token
 * - 统一 401 处理 (清理 token → 跳转登录)
 * - 支持 blob 下载
 * - 统一错误解析
 */

import axios from 'axios';

const http = axios.create({
  baseURL: '/api',
  timeout: 300000,
});

// ── Request interceptor ──
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor ──
http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('saved_username');
      // Only redirect if not already on login page
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  },
);

export default http;

// ── Blob download helper ──
export async function downloadBlob(url: string): Promise<string> {
  const token = localStorage.getItem('token');
  const resp = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) {
    if (resp.status === 401 || resp.status === 403) {
      throw new Error('无权访问');
    }
    throw new Error(`下载失败: ${resp.status}`);
  }
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
}
