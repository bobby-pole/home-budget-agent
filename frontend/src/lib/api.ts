// frontend/src/lib/api.ts
import type { Transaction, AuthResponse, Category, Tag } from "@/types";
import { getToken, clearAuth } from "@/lib/auth";
import axios from "axios";

const apiClient = axios.create({
  baseURL: "/api",
  headers: {
    "Content-Type": "application/json",
  },
});

// Dołącz token do każdego żądania
apiClient.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Obsługa wygasłego/nieprawidłowego tokenu
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const isAuthEndpoint = error.config?.url?.includes("/auth/");
    if (error.response?.status === 401 && !isAuthEndpoint) {
      clearAuth();
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export const api = {
  // --- AUTH ---

  login: async (email: string, password: string): Promise<AuthResponse> => {
    const response = await apiClient.post<AuthResponse>("/auth/login", { email, password });
    return response.data;
  },

  register: async (email: string, password: string): Promise<AuthResponse> => {
    const response = await apiClient.post<AuthResponse>("/auth/register", { email, password });
    return response.data;
  },

  // --- TRANSACTIONS ---

  scanTransaction: async (file: File, force: boolean = false) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiClient.post<Transaction>(`/transactions/scan?force=${force}`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },

  getTransactions: async () => {
    const response = await apiClient.get<Transaction[]>("/transactions");
    return response.data;
  },

  retryTransaction: async (transactionId: number) => {
    const response = await apiClient.post<Transaction>(`/transactions/${transactionId}/retry`);
    return response.data;
  },

  updateTransaction: async (id: number, data: Partial<Transaction> & { tag_ids?: number[] }) => {
    const response = await apiClient.patch<Transaction>(`/transactions/${id}`, data);
    return response.data;
  },

  updateTransactionLine: async (
    transactionId: number,
    lineId: number,
    data: { name?: string; price?: number; quantity?: number; category_id?: number | null }
  ) => {
    const response = await apiClient.patch(`/transactions/${transactionId}/lines/${lineId}`, data);
    return response.data;
  },

  deleteTransaction: async (id: number) => {
    await apiClient.delete(`/transactions/${id}`);
  },

  createManualTransaction: async (data: {
    merchant_name: string;
    total_amount: number;
    currency: string;
    date?: string;
    category_id?: number;
    note?: string;
    tag_ids?: number[];
    type?: string;
    lines?: Array<{ name: string; price: number; quantity: number; category_id?: number | null }>;
  }): Promise<Transaction> => {
    const response = await apiClient.post<Transaction>("/transactions/manual", data);
    return response.data;
  },

  // --- BUDGET ---

  getBudget: async (year: number, month: number) => {
    const response = await apiClient.get(`/budget/${year}/${month}`);
    return response.data;
  },

  setBudget: async (data: { year: number; month: number; amount: number }) => {
    const response = await apiClient.post(`/budget/${data.year}/${data.month}`, { amount: data.amount });
    return response.data;
  },

  // --- CATEGORIES ---

  getCategories: async (): Promise<Category[]> => {
    const response = await apiClient.get<Category[]>("/categories");
    return response.data;
  },

  createCategory: async (data: Partial<Category>): Promise<Category> => {
    const response = await apiClient.post<Category>("/categories", data);
    return response.data;
  },

  updateCategory: async (id: number, data: Partial<Category>): Promise<Category> => {
    const response = await apiClient.patch<Category>(`/categories/${id}`, data);
    return response.data;
  },

  deleteCategory: async (id: number, reassignTo?: number) => {
    const url = reassignTo ? `/categories/${id}?reassign_to=${reassignTo}` : `/categories/${id}`;
    await apiClient.delete(url);
  },

  // --- TAGS ---

  getTags: async (): Promise<Tag[]> => {
    const response = await apiClient.get<Tag[]>("/tags");
    return response.data;
  },

  createTag: async (data: Partial<Tag>): Promise<Tag> => {
    const response = await apiClient.post<Tag>("/tags", data);
    return response.data;
  },

  updateTag: async (id: number, data: Partial<Tag>): Promise<Tag> => {
    const response = await apiClient.patch<Tag>(`/tags/${id}`, data);
    return response.data;
  },

  deleteTag: async (id: number) => {
    await apiClient.delete(`/tags/${id}`);
  },
};
