// frontend/src/lib/api.ts
import type { 
  TransactionRead as Transaction, 
  Token as AuthResponse, 
  CategoryRead as Category, 
  TagRead as Tag, 
  MonthlyBudgetSummary, 
  BudgetMemberRead as BudgetMember, 
  BudgetMemberCreate,
  TransactionUpdate,
  TransactionLineUpdate,
  AppStatusRead,
  UserBudgetRead,
  ChangePasswordRequest,
  UserRead,
  AccountRead,
  AccountCreate,
  AccountUpdate
} from "@/client";
import { getToken, clearAuth, getActiveBudget } from "@/lib/auth";
import axios from "axios";

export const apiClient = axios.create({
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
  const budgetId = getActiveBudget();
  if (budgetId) {
    config.headers["X-Budget-Id"] = budgetId.toString();
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

  scanTransaction: async (file: File, force: boolean = false, note?: string) => {
    const formData = new FormData();
    formData.append("file", file);
    if (note) formData.append("note", note);
    const response = await apiClient.post<Transaction>(`/transactions/scan?force=${force}`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },

  getTransactions: async () => {
    const response = await apiClient.get<Transaction[]>("/transactions");
    return response.data;
  },

  getInbox: async () => {
    const response = await apiClient.get<Transaction[]>("/transactions/inbox");
    return response.data;
  },

  getAppStatus: async () => {
    const response = await apiClient.get<AppStatusRead>("/status");
    return response.data;
  },

  markAlertRead: async (id: number) => {
    const response = await apiClient.post(`/alerts/${id}/read`);
    return response.data;
  },

  verifyTransaction: async (
    id: number,
    transaction_update: TransactionUpdate,
    lines_update?: TransactionLineUpdate[],
    keep_image: boolean = false
  ) => {
    const response = await apiClient.post<Transaction>(`/transactions/${id}/verify`, {
      transaction_update,
      lines_update,
      keep_image,
    });
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

  importTransactions: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiClient.post<{
      created: number;
      skipped: number;
      failed: number;
      summary: string | { code: string; imported: number; skipped: number; filename: string };
    }>("/transactions/import", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },

  createManualTransaction: async (data: {
    merchant_name: string;
    total_amount: number;
    currency: string;
    date?: string;
    category_id?: number;
    account_id?: number;
    transfer_id?: number;
    note?: string;
    tag_ids?: number[];
    type?: string;
    lines?: Array<{ name: string; price: number; quantity: number; category_id?: number | null }>;
  }): Promise<Transaction> => {
    const response = await apiClient.post<Transaction>("/transactions/manual", data);
    return response.data;
  },

  // --- BUDGET ---

  getBudgetSummary: async (year: number, month: number): Promise<MonthlyBudgetSummary> => {
    const response = await apiClient.get(`/budget/${year}/${month}/summary`);
    return response.data;
  },

  getBudgetLimits: async (year: number, month: number) => {
    const response = await apiClient.get(`/budget/${year}/${month}/limits`);
    return response.data;
  },

  setBudgetLimit: async (year: number, month: number, category_id: number, amount: number) => {
    const response = await apiClient.put(`/budget/${year}/${month}/limits/${category_id}`, { amount });
    return response.data;
  },

  deleteBudgetLimit: async (year: number, month: number, category_id: number) => {
    await apiClient.delete(`/budget/${year}/${month}/limits/${category_id}`);
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

  // --- MEMBERS ---

  inviteMember: async (data: BudgetMemberCreate): Promise<BudgetMember> => {
    const res = await apiClient.post<BudgetMember>("/budget/members", data);
    return res.data;
  },
  
  getMyBudgets: async (): Promise<UserBudgetRead[]> => {
    const res = await apiClient.get<UserBudgetRead[]>("/users/me/budgets");
    return res.data;
  },

  deleteBudget: async (id: number): Promise<void> => {
    await apiClient.delete(`/budgets/${id}`);
  },

  changePassword: async (data: ChangePasswordRequest): Promise<void> => {
    await apiClient.post("/auth/change-password", data);
  },

  updateMe: async (data: { default_budget_id: number | null }): Promise<UserRead> => {
    const res = await apiClient.patch<UserRead>("/users/me", data);
    return res.data;
  },
  createBudget: async (data: { name: string }): Promise<UserBudgetRead> => {
    const res = await apiClient.post("/budgets", data);
    return res.data;
  },
  updateBudget: async (id: number, data: { name: string }): Promise<UserBudgetRead> => {
    const res = await apiClient.patch(`/budgets/${id}`, data);
    return res.data;
  },

  // --- ACCOUNTS ---

  getAccounts: async () => {
    const response = await apiClient.get<AccountRead[]>("/accounts");
    return response.data;
  },

  createAccount: async (data: AccountCreate) => {
    const response = await apiClient.post<AccountRead>("/accounts", data);
    return response.data;
  },

  updateAccount: async (id: number, data: AccountUpdate) => {
    const response = await apiClient.patch<AccountRead>(`/accounts/${id}`, data);
    return response.data;
  },

  deleteAccount: async (id: number) => {
    const response = await apiClient.delete(`/accounts/${id}`);
    return response.data;
  },

  reconcileAccount: async (id: number, real_balance: number) => {
    const response = await apiClient.post<AccountRead>(`/accounts/${id}/reconcile`, { real_balance });
    return response.data;
  },
};
