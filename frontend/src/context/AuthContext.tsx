// frontend/src/context/AuthContext.tsx
import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import type { User, AuthResponse } from "@/types";
import { getToken, setToken, getStoredUser, setStoredUser, clearAuth } from "@/lib/auth";
import { api } from "@/lib/api";

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
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

  const login = async (email: string, password: string) => {
    const data = await api.login(email, password);
    handleAuthResponse(data, setUser, setTokenState);
  };

  const register = async (email: string, password: string) => {
    const data = await api.register(email, password);
    handleAuthResponse(data, setUser, setTokenState);
  };

  const logout = () => {
    clearAuth();
    setTokenState(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout }}>
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
