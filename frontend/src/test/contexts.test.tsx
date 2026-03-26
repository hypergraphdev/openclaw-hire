import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { ThemeProvider, useTheme } from "../contexts/ThemeContext";
import { LanguageProvider, useT, useLang } from "../contexts/LanguageContext";

// ── ThemeContext ──────────────────────────────────────────────────────────────

describe("ThemeContext", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("defaults to dark theme", () => {
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    expect(result.current.theme).toBe("dark");
  });

  it("persists to localStorage", () => {
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    act(() => result.current.setTheme("light"));
    expect(result.current.theme).toBe("light");
    expect(localStorage.getItem("theme")).toBe("light");
  });

  it("restores from localStorage", () => {
    localStorage.setItem("theme", "light");
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    expect(result.current.theme).toBe("light");
  });

  it("sets data-theme attribute on html", () => {
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    act(() => result.current.setTheme("light"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("ignores invalid stored value", () => {
    localStorage.setItem("theme", "rainbow");
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    expect(result.current.theme).toBe("dark");
  });
});

// ── LanguageContext ───────────────────────────────────────────────────────────

describe("LanguageContext", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("provides translation function", () => {
    const { result } = renderHook(() => useT(), { wrapper: LanguageProvider });
    // Should return a function
    expect(typeof result.current).toBe("function");
  });

  it("translates known keys", () => {
    localStorage.setItem("lang", "en");
    const { result } = renderHook(() => useT(), { wrapper: LanguageProvider });
    expect(result.current("settings.title")).toBe("Settings");
  });

  it("switches language", () => {
    const { result } = renderHook(() => useLang(), { wrapper: LanguageProvider });
    act(() => result.current.setLang("zh"));
    expect(result.current.lang).toBe("zh");
    expect(localStorage.getItem("lang")).toBe("zh");
  });

  it("returns key for unknown translations", () => {
    const { result } = renderHook(() => useT(), { wrapper: LanguageProvider });
    expect(result.current("nonexistent.key")).toBe("nonexistent.key");
  });
});
