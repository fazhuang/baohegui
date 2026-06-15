/**
 * useBreakpoint — 移动端断点检测 hook
 *
 * 从 Report.tsx 拆分，供多个页面复用。
 */

import { useState, useEffect } from 'react';

const MOBILE_BREAKPOINT = 768;

export function useBreakpoint(): boolean {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < MOBILE_BREAKPOINT : false
  );

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return isMobile;
}
