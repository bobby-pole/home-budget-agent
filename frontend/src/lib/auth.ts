// frontend/src/lib/auth.ts
import type { UserRead as User } from "@/client";

const TOKEN_KEY = "budget_token";
const USER_KEY = "budget_user";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function setStoredUser(user: User): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

const BUDGET_KEY = "active_budget";

export function getActiveBudget(): number | null {
  const raw = localStorage.getItem(BUDGET_KEY);
  if (!raw) return null;
  return parseInt(raw, 10);
}

export function setActiveBudget(budgetId: number): void {
  localStorage.setItem(BUDGET_KEY, budgetId.toString());
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(BUDGET_KEY);
}
