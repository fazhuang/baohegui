/**
 * Route-Permission Integration Tests
 *
 * Tests:
 * 1. Route config — all menu items have corresponding routes
 * 2. Role-based access — route requiredRoles match real role model
 * 3. No stale roles in config (only admin/user allowed)
 * 4. All required app paths are covered
 * 5. /ops is blocked (requiredRoles=[])
 * 6. Render functions produce valid React elements
 */

import { describe, it, expect } from 'vitest';
import React from 'react';
import { routeConfig, flattenRoutes, extractMenuItems } from '../routeConfig';
import { renderRoute, renderRouteTree } from '../renderRoutes';

describe('routeConfig', () => {
  const flat = flattenRoutes(routeConfig);

  describe('route coverage', () => {
    const requiredPaths = [
      '/', '/login', '/forgot-password', '/reset-password',
      '/review', '/review/history',
      '/report/:id',
      '/reports', '/reports/feedback',
      '/kg', '/kg/cases', '/kg/legal',
      '/announcements', '/announcements/manage',
      '/account', '/account/subscription',
      '/rules', '/rules/editor', '/rules/versions', '/rules/sync', '/rules/industry',
      '/manage', '/manage/audit', '/manage/quota',
      '/upload', '/history', '/admin/rules', '/admin/panel',
    ];

    it('should have all required paths in routeConfig', () => {
      const paths = new Set(flat.map(r => r.path));
      for (const p of requiredPaths) {
        expect(paths.has(p), `Missing path: ${p}`).toBe(true);
      }
    });

    it('should have no duplicate paths', () => {
      const paths = flat.filter(r => !r.index).map(r => r.path);
      const dupes = paths.filter((p, i) => paths.indexOf(p) !== i);
      expect(dupes).toEqual([]);
    });

    it('redirect routes should have a redirect target', () => {
      const redirects = flat.filter(r => r.redirect);
      for (const r of redirects) {
        expect(r.redirect).toBeTruthy();
        expect(flat.some(rr => rr.path === r.redirect || `/${rr.path}` === r.redirect),
          `Redirect target "${r.redirect}" from "${r.path}" not found in routeConfig`).toBe(true);
      }
    });
  });

  describe('menu-route consistency', () => {
    const menuItems = extractMenuItems(routeConfig);

    it('every menu item key should be unique', () => {
      const keys = menuItems.map(m => m.key);
      const dupes = keys.filter((k, i) => keys.indexOf(k) !== i);
      expect(dupes).toEqual([]);
    });

    it('every menu item path should exist in route config', () => {
      const routePaths = new Set(flat.map(r => r.path));
      for (const item of menuItems) {
        expect(routePaths.has(item.path),
          `Menu "${item.key}" path "${item.path}" has no matching route`).toBe(true);
      }
    });

    it('every menu item should have requiredRoles', () => {
      for (const item of menuItems) {
        expect(item.requiredRoles.length,
          `Menu "${item.key}" has empty requiredRoles`).toBeGreaterThan(0);
      }
    });
  });

  describe('role validation', () => {
    const VALID_ROLES = ['admin', 'user'];

    it('all requiredRoles should use only valid roles (admin/user)', () => {
      for (const r of flat) {
        if (r.requiredRoles && r.requiredRoles.length > 0) {
          for (const role of r.requiredRoles) {
            expect(VALID_ROLES).toContain(role);
          }
        }
      }
    });

    it('no route should declare non-existent roles (super_admin, reviewer, agent, enterprise)', () => {
      for (const r of flat) {
        if (r.requiredRoles) {
          expect(r.requiredRoles).not.toContain('super_admin');
          expect(r.requiredRoles).not.toContain('reviewer');
          expect(r.requiredRoles).not.toContain('agent');
          expect(r.requiredRoles).not.toContain('enterprise');
        }
      }
    });

    it('admin-only routes should not include user', () => {
      const adminOnlyPaths = [
        '/rules', '/rules/editor', '/rules/versions', '/rules/sync',
        '/manage', '/manage/audit', '/manage/quota',
      ];
      for (const r of flat) {
        if (adminOnlyPaths.includes(r.path)) {
          expect(r.requiredRoles).toBeDefined();
          expect(r.requiredRoles).not.toContain('user');
          expect(r.requiredRoles).toContain('admin');
        }
      }
    });

    it('/ops should use requiredRoles=[] (authenticated but forbidden → 403)', () => {
      const ops = flat.find(r => r.path === '/ops');
      expect(ops).toBeDefined();
      expect(ops!.requiredRoles).toEqual([]);
      // Must not be a redirect
      expect(ops!.redirect).toBeUndefined();
    });

    it('public routes should have undefined requiredRoles', () => {
      const publicRoutes = flat.filter(r => ['/login', '/forgot-password', '/reset-password'].includes(r.path));
      for (const r of publicRoutes) {
        expect(r.requiredRoles, `${r.path} should be public (requiredRoles=undefined)`).toBeUndefined();
      }
    });
  });

  describe('renderRoutes output', () => {
    it('renderRoute returns a valid React element for each config', () => {
      for (const r of flat) {
        const el = renderRoute(r);
        expect(React.isValidElement(el)).toBe(true);
      }
    });

    it('renderRouteTree returns an array of React elements', () => {
      const tree = renderRouteTree(routeConfig);
      expect(Array.isArray(tree)).toBe(true);
      expect(tree.length).toBeGreaterThan(0);
      for (const el of tree) {
        expect(React.isValidElement(el)).toBe(true);
      }
    });

    it('rendered route tree contains 404 catch-all', () => {
      const tree = renderRouteTree(routeConfig);
      const starRoute = tree.find(el => (el as any).props?.path === '*');
      expect(starRoute).toBeDefined();
    });
  });
});
