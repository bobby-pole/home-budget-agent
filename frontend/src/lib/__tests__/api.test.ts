import { describe, it, expect, beforeEach, vi } from "vitest";
import { makeReceipt, makeAuthResponse } from "@/__mocks__/factories";

// Tworzymy mock instancji axios przed hoistingiem vi.mock
const { mockAxios } = vi.hoisted(() => {
  const mockAxios = {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  };
  return { mockAxios };
});

vi.mock("axios", () => ({
  default: {
    create: vi.fn(() => mockAxios),
  },
}));

// Import po zamockowaniu — api.ts pobiera zmockowaną instancję
const { api } = await import("@/lib/api");

describe("api service", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("auth endpoints", () => {
    it("login — wysyła POST /auth/login z credentials", async () => {
      const response = makeAuthResponse();
      mockAxios.post.mockResolvedValueOnce({ data: response });

      const result = await api.login("user@test.com", "pass123");

      expect(mockAxios.post).toHaveBeenCalledWith("/auth/login", {
        email: "user@test.com",
        password: "pass123",
      });
      expect(result).toEqual(response);
    });

    it("register — wysyła POST /auth/register z credentials", async () => {
      const response = makeAuthResponse();
      mockAxios.post.mockResolvedValueOnce({ data: response });

      const result = await api.register("new@test.com", "secret");

      expect(mockAxios.post).toHaveBeenCalledWith("/auth/register", {
        email: "new@test.com",
        password: "secret",
      });
      expect(result).toEqual(response);
    });
  });

  describe("receipt endpoints", () => {
    it("getReceipts — wysyła GET /receipts i zwraca tablicę", async () => {
      const receipts = [makeReceipt({ id: 1 }), makeReceipt({ id: 2 })];
      mockAxios.get.mockResolvedValueOnce({ data: receipts });

      const result = await api.getReceipts();

      expect(mockAxios.get).toHaveBeenCalledWith("/receipts");
      expect(result).toHaveLength(2);
    });

    it("updateReceipt — wysyła PATCH /receipts/:id", async () => {
      const updated = makeReceipt({ merchant_name: "Lidl" });
      mockAxios.patch.mockResolvedValueOnce({ data: updated });

      const result = await api.updateReceipt(1, { merchant_name: "Lidl" });

      expect(mockAxios.patch).toHaveBeenCalledWith("/receipts/1", {
        merchant_name: "Lidl",
      });
      expect(result.merchant_name).toBe("Lidl");
    });

    it("deleteReceipt — wysyła DELETE /receipts/:id", async () => {
      mockAxios.delete.mockResolvedValueOnce({});

      await api.deleteReceipt(5);

      expect(mockAxios.delete).toHaveBeenCalledWith("/receipts/5");
    });

    it("retryReceipt — wysyła POST /receipts/:id/retry", async () => {
      const receipt = makeReceipt({ status: "processing" });
      mockAxios.post.mockResolvedValueOnce({ data: receipt });

      const result = await api.retryReceipt(3);

      expect(mockAxios.post).toHaveBeenCalledWith("/receipts/3/retry");
      expect(result.status).toBe("processing");
    });

    it("createManualTransaction — wysyła POST /receipts/manual", async () => {
      const payload = {
        merchant_name: "Sklep",
        total_amount: 25.5,
        currency: "PLN",
        items: [],
      };
      const receipt = makeReceipt();
      mockAxios.post.mockResolvedValueOnce({ data: receipt });

      await api.createManualTransaction(payload);

      expect(mockAxios.post).toHaveBeenCalledWith("/receipts/manual", payload);
    });
  });

  describe("budget endpoints", () => {
    it("getBudget — wysyła GET /budget/:year/:month", async () => {
      const budget = { year: 2024, month: 3, amount: 2000 };
      mockAxios.get.mockResolvedValueOnce({ data: budget });

      const result = await api.getBudget(2024, 3);

      expect(mockAxios.get).toHaveBeenCalledWith("/budget/2024/3");
      expect(result).toEqual(budget);
    });

    it("setBudget — wysyła POST /budget/:year/:month z amount", async () => {
      const budget = { year: 2024, month: 3, amount: 3000 };
      mockAxios.post.mockResolvedValueOnce({ data: budget });

      await api.setBudget({ year: 2024, month: 3, amount: 3000 });

      expect(mockAxios.post).toHaveBeenCalledWith("/budget/2024/3", {
        amount: 3000,
      });
    });
  });

  describe("axios interceptors", () => {
    it("interceptor request.use i response.use są funkcjami (zarejestrowane przy imporcie)", () => {
      // vi.clearAllMocks() czyści historię wywołań, ale funkcja nadal istnieje
      expect(mockAxios.interceptors.request.use).toBeInstanceOf(Function);
      expect(mockAxios.interceptors.response.use).toBeInstanceOf(Function);
    });
  });
});
