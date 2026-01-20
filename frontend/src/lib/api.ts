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
  uploadReceipt: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);

    // Ważne: Axios sam ustawi nagłówek 'multipart/form-data' i boundary
    const response = await apiClient.post<Receipt>("/upload", formData, {
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
};
