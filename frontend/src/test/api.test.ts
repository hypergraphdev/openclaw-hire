import { describe, it, expect, vi, beforeEach } from "vitest";

// Test the API client helper functions (token management, request construction)
// These don't make actual HTTP requests

describe("API token management", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores and retrieves token", async () => {
    const { storeToken, getStoredToken } = await import("../api");
    storeToken("test-token-123");
    expect(getStoredToken()).toBe("test-token-123");
  });

  it("clears token", async () => {
    const { storeToken, clearToken, getStoredToken } = await import("../api");
    storeToken("test-token-123");
    clearToken();
    expect(getStoredToken()).toBeNull();
  });

  it("returns null when no token stored", async () => {
    const { getStoredToken } = await import("../api");
    expect(getStoredToken()).toBeNull();
  });
});

describe("API type safety", () => {
  it("exports expected methods", async () => {
    const { api } = await import("../api");
    // Auth
    expect(typeof api.login).toBe("function");
    expect(typeof api.register).toBe("function");
    expect(typeof api.me).toBe("function");
    // Instances
    expect(typeof api.listInstances).toBe("function");
    expect(typeof api.getInstance).toBe("function");
    // MyOrg
    expect(typeof api.myOrg).toBe("function");
    expect(typeof api.myOrgChatSend).toBe("function");
    expect(typeof api.myOrgChatInfo).toBe("function");
    // Catalog
    expect(typeof api.catalog).toBe("function");
  });
});
