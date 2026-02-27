// frontend/src/lib/api.ts
import type { Receipt, AuthResponse } from "@/types";
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

  // --- RECEIPTS ---

  uploadReceipt: async (file: File, force: boolean = false) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiClient.post<Receipt>(`/upload?force=${force}`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },

  getReceipts: async () => {
    const response = await apiClient.get<Receipt[]>("/receipts");
    return response.data;
  },

  retryReceipt: async (receiptId: number) => {
    const response = await apiClient.post<Receipt>(`/receipts/${receiptId}/retry`);
    return response.data;
  },

  updateReceipt: async (id: number, data: Partial<Receipt>) => {
    const response = await apiClient.patch<Receipt>(`/receipts/${id}`, data);
    return response.data;
  },

  updateItem: async (id: number, data: { name?: string; price?: number; quantity?: number; category?: string }) => {
    const response = await apiClient.patch(`/items/${id}`, data);
    return response.data;
  },

  deleteReceipt: async (id: number) => {
    await apiClient.delete(`/receipts/${id}`);
  },

  // --- BUDGET ---

  getBudget: async (year: number, month: number) => {
    const response = await apiClient.get(`/budget/${year}/${month}`);
    return response.data;
  },

  setBudget: async (data: { year: number; month: number; amount: number }) => {
    const response = await apiClient.post(`/budget`, data);
    return response.data;
  },
};
