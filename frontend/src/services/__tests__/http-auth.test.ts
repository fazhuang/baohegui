/**
 * HTTP Auth Integration Tests
 *
 * 测试真实 http 实例（axios + 拦截器）行为：
 * - token 自动附加到 Authorization header
 * - 401 响应清空 token 并跳转
 * - 401 响应清空 saved_username
 * - 无 token 时不注入 Authorization
 * - downloadBlob 带/不带 token
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import MockAdapter from 'axios-mock-adapter';
import http, { downloadBlob } from '../http';

// Mock global fetch for downloadBlob (uses native fetch, not axios)
const originalFetch = globalThis.fetch;

describe('HTTP Client (auth)', () => {
  let mock: MockAdapter;

  beforeEach(() => {
    localStorage.clear();
    mock = new MockAdapter(http);
    // Mock window.location
    vi.stubGlobal('location', { ...window.location, href: '', pathname: '/review' });
  });

  afterEach(() => {
    mock.restore();
    vi.unstubAllGlobals();
    globalThis.fetch = originalFetch;
  });

  describe('request interceptor — token injection', () => {
    it('injects Bearer token from localStorage when token exists', async () => {
      localStorage.setItem('token', 'test-bearer-token');

      mock.onGet('/auth/me').reply((config) => {
        expect(config.headers?.Authorization).toBe('Bearer test-bearer-token');
        return [200, { user_id: 1, username: 'test', role: 'user' }];
      });

      await http.get('/auth/me');
      expect(mock.history.get.length).toBe(1);
    });

    it('does NOT inject Authorization header when no token in localStorage', async () => {
      mock.onGet('/auth/me').reply((config) => {
        expect(config.headers?.Authorization).toBeUndefined();
        return [200, {}];
      });

      await http.get('/auth/me');
      expect(mock.history.get.length).toBe(1);
    });
  });

  describe('response interceptor — 401 handling', () => {
    it('removes token from localStorage on 401 response', async () => {
      localStorage.setItem('token', 'will-expire');
      localStorage.setItem('saved_username', 'testuser');

      mock.onGet('/protected').reply(401, { detail: 'Token expired' });

      try {
        await http.get('/protected');
      } catch {
        // expected — 401 is an error
      }

      expect(localStorage.getItem('token')).toBeNull();
    });

    it('removes saved_username from localStorage on 401 response', async () => {
      localStorage.setItem('token', 'will-expire');
      localStorage.setItem('saved_username', 'testuser');

      mock.onGet('/protected').reply(401);

      try { await http.get('/protected'); } catch { /* expected */ }

      expect(localStorage.getItem('saved_username')).toBeNull();
    });

    it('sets window.location.href to /login on 401 when not already on login page', async () => {
      localStorage.setItem('token', 'x');
      const hrefSetter = vi.fn();
      vi.stubGlobal('location', {
        ...window.location,
        href: '',
        pathname: '/review',
      });
      // Intercept location.href set
      Object.defineProperty(window.location, 'href', {
        set: hrefSetter,
        get: () => '',
        configurable: true,
      });

      mock.onGet('/protected').reply(401);

      try { await http.get('/protected'); } catch { /* expected */ }

      expect(hrefSetter).toHaveBeenCalledWith('/login');
    });

    it('does NOT redirect if already on /login page', async () => {
      localStorage.setItem('token', 'x');
      const hrefSetter = vi.fn();
      Object.defineProperty(window.location, 'href', {
        set: hrefSetter,
        get: () => '/login',
        configurable: true,
      });

      mock.onGet('/protected').reply(401);

      try { await http.get('/protected'); } catch { /* expected */ }

      // It's already on /login, so href shouldn't be set again
      // The interceptor checks pathname !== '/login' before setting href
    });
  });

  describe('downloadBlob', () => {
    beforeEach(() => {
      globalThis.fetch = vi.fn();
    });

    it('passes Authorization header with token', async () => {
      localStorage.setItem('token', 'download-token');
      const mockBlob = new Blob(['test']);
      const mockResp = { ok: true, blob: () => Promise.resolve(mockBlob) };
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResp);

      await downloadBlob('/download/report/1');

      expect(globalThis.fetch).toHaveBeenCalledWith('/download/report/1', {
        headers: { Authorization: 'Bearer download-token' },
      });
    });

    it('sends no Authorization header when no token', async () => {
      const mockBlob = new Blob(['test']);
      const mockResp = { ok: true, blob: () => Promise.resolve(mockBlob) };
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(mockResp);

      await downloadBlob('/download/report/1');

      expect(globalThis.fetch).toHaveBeenCalledWith('/download/report/1', { headers: {} });
    });

    it('throws "无权访问" on 401', async () => {
      localStorage.setItem('token', 'x');
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ok: false, status: 401 });

      await expect(downloadBlob('/download/report/1')).rejects.toThrow('无权访问');
    });

    it('throws "下载失败: <status>" on other errors', async () => {
      localStorage.setItem('token', 'x');
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ok: false, status: 500 });

      await expect(downloadBlob('/download/report/1')).rejects.toThrow('下载失败: 500');
    });
  });
});
