import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { ThemeProvider } from "@/lib/ThemeProvider";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { BottomNav } from "@/components/BottomNav";
import { DashboardHeader } from "@/components/DashboardHeader";
import { Dashboard } from "@/pages/Dashboard";
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { BudgetPage } from "@/pages/BudgetPage";
import { TransactionsPage } from "@/pages/TransactionsPage";
import { InboxPage } from "@/pages/InboxPage";
import type { ReactNode } from "react";

function ProtectedLayout({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <SidebarInset>
          <div className="flex flex-col flex-1 h-full relative">
            <DashboardHeader />
            <main className="flex-1 pb-20 md:pb-6 overflow-y-auto">
              {children}
            </main>
            <BottomNav />
          </div>
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      
      <Route
        path="/dashboard"
        element={
          <ProtectedLayout>
            <Dashboard />
          </ProtectedLayout>
        }
      />
      <Route
        path="/budget"
        element={
          <ProtectedLayout>
            <BudgetPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/transactions"
        element={
          <ProtectedLayout>
            <TransactionsPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/inbox"
        element={
          <ProtectedLayout>
            <InboxPage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/settings"
        element={
          <ProtectedLayout>
            <SettingsPage />
          </ProtectedLayout>
        }
      />
      
      {/* Backward compatibility and redirects */}
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/settings/categories" element={<Navigate to="/settings" replace />} />
      
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <ThemeProvider defaultTheme="system" storageKey="budget-ai-theme">
        <AuthProvider>
          <div className="min-h-screen bg-background font-sans antialiased">
            <AppRoutes />
            <Toaster position="top-right" richColors />
          </div>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}

export default App;
