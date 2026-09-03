/**
 * Regression test for ISSUE-1: PWA offline page shown on first load.
 *
 * Ensures the service worker NavigationRoute uses index.html (not offline.html)
 * as the navigate fallback. This prevents the bug where users see "You are offline"
 * even when online.
 */
import { test, expect } from "@playwright/test";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const VITE_CONFIG = resolve(__dirname, "../vite.config.ts");

test.describe("PWA navigateFallback regression", () => {
  test("vite.config.ts must NOT override navigateFallback to offline.html", () => {
    const config = readFileSync(VITE_CONFIG, "utf-8");

    // The broken config had this line:
    //   navigateFallback: "/offline.html",
    // It must NOT be present.
    expect(config).not.toContain('navigateFallback: "/offline.html"');
    expect(config).not.toContain("navigateFallback: '/offline.html'");
  });

  test("vite.config.ts must keep navigateFallbackDenylist for /api", () => {
    const config = readFileSync(VITE_CONFIG, "utf-8");

    // The denylist must remain to prevent SW from intercepting API routes.
    expect(config).toContain("navigateFallbackDenylist");
    expect(config).toContain("/^\\/api/");
  });

  test("vite.config.ts must NOT contain navigateFallback property at all", () => {
    const config = readFileSync(VITE_CONFIG, "utf-8");

    // The fix removes the navigateFallback override entirely,
    // letting Workbox default to 'index.html'.
    // Match navigateFallback as a property key (not inside a comment or string).
    const hasNavigateFallback = /navigateFallback\s*:/.test(config);
    expect(hasNavigateFallback).toBe(false);
  });
});
