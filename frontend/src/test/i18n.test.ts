import { describe, it, expect } from "vitest";
import { en } from "../i18n/en";
import { zh } from "../i18n/zh";

describe("i18n translations", () => {
  it("en and zh have same keys", () => {
    const enKeys = new Set(Object.keys(en));
    const zhKeys = new Set(Object.keys(zh));

    const missingInZh = [...enKeys].filter((k) => !zhKeys.has(k));
    const missingInEn = [...zhKeys].filter((k) => !enKeys.has(k));

    expect(missingInZh).toEqual([]);
    expect(missingInEn).toEqual([]);
  });

  it("no empty translation values", () => {
    const emptyEn = Object.entries(en).filter(([, v]) => !v.trim());
    const emptyZh = Object.entries(zh).filter(([, v]) => !v.trim());
    expect(emptyEn).toEqual([]);
    expect(emptyZh).toEqual([]);
  });

  it("settings theme keys exist", () => {
    expect(en["settings.theme"]).toBeDefined();
    expect(en["settings.themeDark"]).toBeDefined();
    expect(en["settings.themeLight"]).toBeDefined();
    expect(zh["settings.theme"]).toBeDefined();
  });

  it("nav keys exist for all routes", () => {
    for (const key of ["nav.dashboard", "nav.catalog", "nav.instances", "nav.settings"]) {
      expect(en[key]).toBeDefined();
      expect(zh[key]).toBeDefined();
    }
  });
});
