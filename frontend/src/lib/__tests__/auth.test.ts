import { describe, it, expect, beforeEach } from "vitest";
import {
  getToken,
  setToken,
  getStoredUser,
  setStoredUser,
  clearAuth,
} from "@/lib/auth";
import { makeUser } from "@/__mocks__/factories";

describe("auth helpers (localStorage)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe("getToken / setToken", () => {
    it("returns null when no token stored", () => {
      expect(getToken()).toBeNull();
    });

    it("returns stored token after setToken", () => {
      setToken("abc123");
      expect(getToken()).toBe("abc123");
    });

    it("overwrites previous token", () => {
      setToken("old-token");
      setToken("new-token");
      expect(getToken()).toBe("new-token");
    });
  });

  describe("getStoredUser / setStoredUser", () => {
    it("returns null when no user stored", () => {
      expect(getStoredUser()).toBeNull();
    });

    it("returns stored user after setStoredUser", () => {
      const user = makeUser();
      setStoredUser(user);
      expect(getStoredUser()).toEqual(user);
    });

    it("returns null for corrupted JSON in localStorage", () => {
      localStorage.setItem("budget_user", "invalid-json{{{");
      expect(getStoredUser()).toBeNull();
    });
  });

  describe("clearAuth", () => {
    it("removes token and user from storage", () => {
      setToken("token");
      setStoredUser(makeUser());

      clearAuth();

      expect(getToken()).toBeNull();
      expect(getStoredUser()).toBeNull();
    });

    it("does nothing when storage is already empty", () => {
      expect(() => clearAuth()).not.toThrow();
    });
  });
});
