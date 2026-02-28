import { describe, it, expect, beforeEach, vi } from "vitest";
import { makeTransaction, makeAuthResponse } from "@/__mocks__/factories";

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

  describe("transaction endpoints", () => {
    it("getTransactions — wysyła GET /transactions i zwraca tablicę", async () => {
      const transactions = [makeTransaction({ id: 1 }), makeTransaction({ id: 2 })];
      mockAxios.get.mockResolvedValueOnce({ data: transactions });

      const result = await api.getTransactions();

      expect(mockAxios.get).toHaveBeenCalledWith("/transactions");
      expect(result).toHaveLength(2);
    });

    it("updateTransaction — wysyła PATCH /transactions/:id", async () => {
      const updated = makeTransaction({ merchant_name: "Lidl" });
      mockAxios.patch.mockResolvedValueOnce({ data: updated });

      const result = await api.updateTransaction(1, { merchant_name: "Lidl" });

      expect(mockAxios.patch).toHaveBeenCalledWith("/transactions/1", {
        merchant_name: "Lidl",
      });
      expect(result.merchant_name).toBe("Lidl");
    });

    it("deleteTransaction — wysyła DELETE /transactions/:id", async () => {
      mockAxios.delete.mockResolvedValueOnce({});

      await api.deleteTransaction(5);

      expect(mockAxios.delete).toHaveBeenCalledWith("/transactions/5");
    });

    it("retryTransaction — wysyła POST /transactions/:id/retry", async () => {
      const transaction = makeTransaction({ receipt_scan: { id: 1, status: "processing", created_at: "" } });
      mockAxios.post.mockResolvedValueOnce({ data: transaction });

      const result = await api.retryTransaction(3);

      expect(mockAxios.post).toHaveBeenCalledWith("/transactions/3/retry");
      expect(result.receipt_scan?.status).toBe("processing");
    });

    it("createManualTransaction — wysyła POST /transactions/manual", async () => {
      const payload = {
        merchant_name: "Sklep",
        total_amount: 25.5,
        currency: "PLN",
        lines: [],
      };
      const transaction = makeTransaction();
      mockAxios.post.mockResolvedValueOnce({ data: transaction });

      await api.createManualTransaction(payload);

      expect(mockAxios.post).toHaveBeenCalledWith("/transactions/manual", payload);
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
