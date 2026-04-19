import { render, screen } from "../../../__tests__/test-utils";
import { describe, it, expect } from "vitest";
import { RecentTransactionsList } from "../RecentTransactionsList";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../../../context/AuthContext";
import type { TransactionRead as Transaction } from "@/client";

describe("RecentTransactionsList", () => {
  const mockTransactions: Transaction[] = [
    {
      id: 1,
      merchant_name: "Biedronka",
      total_amount: 42.5,
      currency: "PLN",
      date: "2026-02-28",
      type: "expense",
      lines: [],
    },
    {
      id: 2,
      merchant_name: "Wypłata",
      total_amount: 5000,
      currency: "PLN",
      date: "2026-02-27",
      type: "income",
      lines: [],
    },
  ];

  it("renders transaction list with amounts", () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <RecentTransactionsList transactions={mockTransactions} isLoading={false} />
        </AuthProvider>
      </MemoryRouter>
    );
    
    expect(screen.getByText("Biedronka")).toBeInTheDocument();
    expect(screen.getByText(/-42,50/i)).toBeInTheDocument();
    
    expect(screen.getByText("Wypłata")).toBeInTheDocument();
    expect(screen.getByText(/\+5.*000,00/i)).toBeInTheDocument();
  });

  it("renders 'All' link to transactions page", () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <RecentTransactionsList transactions={mockTransactions} isLoading={false} />
        </AuthProvider>
      </MemoryRouter>
    );
    
    const link = screen.getByRole("link", { name: /Wszystkie/i });
    expect(link).toHaveAttribute("href", "/transactions");
  });

  it("shows empty state when no transactions", () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <RecentTransactionsList transactions={[]} isLoading={false} />
        </AuthProvider>
      </MemoryRouter>
    );
    expect(screen.getByText(/Brak niedawnych transakcji/i)).toBeInTheDocument();
  });
});
