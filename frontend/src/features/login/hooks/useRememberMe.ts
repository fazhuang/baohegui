/**
 * useRememberMe — "记住我" 功能 hook
 *
 * 管理 localStorage 中 saved_username / remember_me 的读写。
 * 页面层禁止直接操作 localStorage 的 UI 状态键。
 */

import { useCallback } from 'react';

const KEY_REMEMBER = 'remember_me';
const KEY_SAVED_USERNAME = 'saved_username';

export function useRememberMe() {
  const isRemembered = (): boolean => localStorage.getItem(KEY_REMEMBER) === 'true';

  const getSavedUsername = (): string => localStorage.getItem(KEY_SAVED_USERNAME) || '';

  const persist = useCallback((username: string, remember: boolean) => {
    if (remember) {
      localStorage.setItem(KEY_REMEMBER, 'true');
      localStorage.setItem(KEY_SAVED_USERNAME, username);
    } else {
      localStorage.removeItem(KEY_REMEMBER);
      localStorage.removeItem(KEY_SAVED_USERNAME);
    }
  }, []);

  const clearRemember = useCallback(() => {
    localStorage.removeItem(KEY_REMEMBER);
    localStorage.removeItem(KEY_SAVED_USERNAME);
  }, []);

  return { isRemembered, getSavedUsername, persist, clearRemember };
}
