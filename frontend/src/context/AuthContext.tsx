// frontend/src/context/AuthContext.tsx
import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import type { UserRead as User, Token as AuthResponse } from "@/client";
import { getToken, setToken, getStoredUser, setStoredUser, clearAuth } from "@/lib/auth";
import { api } from "@/lib/api";

import { getActiveBudget, setActiveBudget as setLocalActiveBudget } from "@/lib/auth";
import { useQueryClient } from "@tanstack/react-query";

interface AuthContextType {
  user: User | null;
  token: string | null;
  activeBudgetId: number | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  switchBudget: (id: number) => void;
  updateUser: (u: User) => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

function handleAuthResponse(data: AuthResponse, setUser: (u: User) => void, setTokenState: (t: string) => void) {
  setToken(data.access_token);
  setStoredUser(data.user);
  setTokenState(data.access_token);
  setUser(data.user);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(getStoredUser);
  const [token, setTokenState] = useState<string | null>(getToken);
  const [activeBudgetId, setActiveBudgetId] = useState<number | null>(getActiveBudget);
  const queryClient = useQueryClient();

  const login = async (email: string, password: string) => {
    const data = await api.login(email, password);
    handleAuthResponse(data, setUser, setTokenState);
    if (data.user.default_budget_id) {
      setActiveBudgetId(data.user.default_budget_id);
      setLocalActiveBudget(data.user.default_budget_id);
    } else {
      setActiveBudgetId(null); // Reset on login so backend uses default first budget if not set
    }
  };

  const register = async (email: string, password: string) => {
    const data = await api.register(email, password);
    handleAuthResponse(data, setUser, setTokenState);
    setActiveBudgetId(null);
  };

  const logout = () => {
    clearAuth();
    setTokenState(null);
    setUser(null);
    setActiveBudgetId(null);
    queryClient.clear();
  };

  const switchBudget = (id: number) => {
    setLocalActiveBudget(id);
    setActiveBudgetId(id);
    queryClient.invalidateQueries();
  };

  const updateUser = (u: User) => {
    setUser(u);
    setStoredUser(u);
  };

  return (
    <AuthContext.Provider value={{ user, token, activeBudgetId, login, register, logout, switchBudget, updateUser }}>
      {children}
    </AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
