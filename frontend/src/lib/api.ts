// frontend/src/lib/api.ts
import type { Receipt } from "@/types";
import axios from "axios";

// Tworzymy instancję axiosa.
// Dzięki PROXY w vite.config.ts, zapytania do '/api' lecą do localhost:8000
const apiClient = axios.create({
  baseURL: "/api",
  headers: {
    "Content-Type": "application/json",
  },
});

export const api = {
  /**
   * Wysyła zdjęcie paragonu do analizy AI.
   */
  uploadReceipt: async (file: File, force: boolean = false) => {
    const formData = new FormData();
    formData.append("file", file);

    // Ważne: Axios sam ustawi nagłówek 'multipart/form-data' i boundary
    const response = await apiClient.post<Receipt>(`/upload?force=${force}`, formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  /**
   * Pobiera listę wszystkich paragonów z bazy danych.
   */
  getReceipts: async () => {
    const response = await apiClient.get<Receipt[]>("/receipts");
    return response.data;
  },

  /**
   * Ponawia przetwarzanie błędnego paragonu.
   */
  retryReceipt: async (receiptId: number) => {
    const response = await apiClient.post<Receipt>(`/receipts/${receiptId}/retry`);
    return response.data;
  },

  /**
   * Aktualizuje dane paragonu.
   */
  updateReceipt: async (id: number, data: Partial<Receipt>) => {
    const response = await apiClient.patch<Receipt>(`/receipts/${id}`, data);
    return response.data;
  },

  /**
   * Aktualizuje pozycję na paragonie.
   */
  updateItem: async (id: number, data: { name?: string; price?: number; quantity?: number; category?: string }) => {
    // Używamy any dla response type item, lub po prostu zwracamy data.
    // TypeScript w komponencie zadba o typy.
    const response = await apiClient.patch(`/items/${id}`, data);
    return response.data;
  },

  /**
   * Usuwa paragon.
   */
  deleteReceipt: async (id: number) => {
    await apiClient.delete(`/receipts/${id}`);
  },

  /**
   * Pobiera budżet dla danego miesiąca i roku.
   */
  getBudget: async (year: number, month: number) => {
    const response = await apiClient.get(`/budget/${year}/${month}`);
    return response.data;
  },

  /**
   * Ustawia lub aktualizuje budżet.
   */
  setBudget: async (data: { year: number; month: number; amount: number }) => {
    const response = await apiClient.post(`/budget`, data);
    return response.data;
  },
};
