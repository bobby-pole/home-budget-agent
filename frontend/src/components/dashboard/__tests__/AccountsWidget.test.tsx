import { render, screen, fireEvent } from "../../../__tests__/test-utils";
import { describe, it, expect, vi } from "vitest";
import { AccountsWidget } from "../AccountsWidget";
import { MemoryRouter } from "react-router-dom";
import type { AccountRead } from "@/client";

describe("AccountsWidget", () => {
  const mockAccounts: AccountRead[] = [
    {
      id: 1,
      name: "Main Checking",
      type: "checking",
      currency: "PLN",
      initial_balance: 1000,
      current_balance: 2500,
      is_on_budget: true,
      is_active: true,
    },
    {
      id: 2,
      name: "Emergency Savings",
      type: "savings",
      currency: "PLN",
      initial_balance: 5000,
      current_balance: 10000,
      is_on_budget: true,
      is_active: true,
    },
    {
      id: 3,
      name: "Credit Card",
      type: "credit",
      currency: "PLN",
      initial_balance: 0,
      current_balance: -1500,
      is_on_budget: true,
      is_active: true,
    },
    {
      id: 4,
      name: "Stock Portfolio",
      type: "tracking_asset",
      currency: "PLN",
      initial_balance: 0,
      current_balance: 4000,
      is_on_budget: false,
      is_active: true,
    },
  ];

  it("calculates Net Worth correctly (assets - liabilities)", () => {
    // Assets: Checking (2500) + Savings (10000) + Stock (4000) = 16500
    // Liabilities: Credit Card (1500) = 1500
    // Net Worth: 16500 - 1500 = 15000
    render(
      <MemoryRouter>
        <AccountsWidget accounts={mockAccounts} />
      </MemoryRouter>
    );

    expect(screen.getByText(/Wartość netto/i)).toBeInTheDocument();
    expect(screen.getByText(/15.*000,00/i)).toBeInTheDocument();
    expect(screen.getByText(/\+16.*500,00/i)).toBeInTheDocument();
    expect(screen.getAllByText(/-1.*500,00/i).length).toBeGreaterThan(0);
  });

  it("renders all account names and balances", () => {
    render(
      <MemoryRouter>
        <AccountsWidget accounts={mockAccounts} />
      </MemoryRouter>
    );

    expect(screen.getByText("Main Checking")).toBeInTheDocument();
    expect(screen.getByText("Emergency Savings")).toBeInTheDocument();
    expect(screen.getByText("Credit Card")).toBeInTheDocument();
    expect(screen.getByText("Stock Portfolio")).toBeInTheDocument();
  });

  it("calls onSelectAccount when clicking an account card", () => {
    const handleSelect = vi.fn();
    render(
      <MemoryRouter>
        <AccountsWidget accounts={mockAccounts} onSelectAccount={handleSelect} />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByText("Main Checking"));
    expect(handleSelect).toHaveBeenCalledWith(1);
  });

  it("shows filter indicator and clear filter button when selectedAccountId is set", () => {
    const handleClear = vi.fn();
    render(
      <MemoryRouter>
        <AccountsWidget
          accounts={mockAccounts}
          selectedAccountId={1}
          onClearFilter={handleClear}
        />
      </MemoryRouter>
    );

    expect(screen.getByText(/Filtr konta:/i)).toBeInTheDocument();
    const clearBtns = screen.getAllByRole("button", { name: /Wyczyść/i });
    expect(clearBtns.length).toBeGreaterThan(0);
    fireEvent.click(clearBtns[0]);
    expect(handleClear).toHaveBeenCalled();
  });

  it("renders empty state when no accounts exist", () => {
    render(
      <MemoryRouter>
        <AccountsWidget accounts={[]} />
      </MemoryRouter>
    );

    expect(screen.getByText(/Brak dodanych kont/i)).toBeInTheDocument();
  });
});
