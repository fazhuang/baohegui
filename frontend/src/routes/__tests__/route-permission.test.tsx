/**
 * Route-Permission Integration Tests
 *
 * Tests:
 * 1. Route config — all menu items have corresponding routes
 * 2. Role-based access — route requiredRoles match real role model
 * 3. No stale roles in config (only admin/user allowed)
 */

import { describe, it, expect } from 'vitest';
import { routeConfig, flattenRoutes, extractMenuItems } from '../routeConfig';

describe('routeConfig', () => {
  const flat = flattenRoutes(routeConfig);

  describe('route uniqueness', () => {
    it('should have no duplicate paths', () => {
      const paths = flat.filter(r => !r.index).map(r => r.path);
      const dupes = paths.filter((p, i) => paths.indexOf(p) !== i);
      expect(dupes).toEqual([]);
    });

    it('should have elements for all non-parent routes', () => {
      for (const r of flat) {
        // parent routes may have children instead of element, but in our config all have elements
        expect(r.element).toBeDefined();
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
          `Menu path "${item.path}" (key: ${item.key}) has no matching route`).toBe(true);
      }
    });

    it('every menu item should have requiredRoles', () => {
      for (const item of menuItems) {
        expect(item.requiredRoles.length,
          `Menu item "${item.key}" has empty requiredRoles`).toBeGreaterThan(0);
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

    it('ops route should be inaccessible (empty requiredRoles)', () => {
      const ops = flat.find(r => r.path === '/ops');
      expect(ops).toBeDefined();
      expect(ops!.requiredRoles).toEqual([]);
    });

    it('no route should declare non-existent super_admin role', () => {
      for (const r of flat) {
        if (r.requiredRoles) {
          expect(r.requiredRoles).not.toContain('super_admin');
          expect(r.requiredRoles).not.toContain('reviewer');
          expect(r.requiredRoles).not.toContain('agent');
          expect(r.requiredRoles).not.toContain('enterprise');
        }
      }
    });
  });
});
