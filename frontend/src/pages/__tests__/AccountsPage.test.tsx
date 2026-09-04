import { render, screen, fireEvent, waitFor } from "../../__tests__/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AccountsPage } from "../AccountsPage";
import { MemoryRouter } from "react-router-dom";
import { api } from "@/lib/api";
import type { AccountRead } from "@/client";

const mockAccounts: AccountRead[] = [
  {
    id: 1,
    name: "Checking Account",
    type: "checking",
    currency: "PLN",
    initial_balance: 1000,
    current_balance: 3200,
    is_on_budget: true,
    is_active: true,
  },
  {
    id: 2,
    name: "Savings Account",
    type: "savings",
    currency: "PLN",
    initial_balance: 5000,
    current_balance: 12000,
    is_on_budget: true,
    is_active: true,
  },
];

vi.mock("@/lib/api", () => ({
  api: {
    getAccounts: vi.fn(),
    getCategories: vi.fn().mockResolvedValue([]),
    createAccount: vi.fn(),
    updateAccount: vi.fn(),
    deleteAccount: vi.fn(),
    reconcileAccount: vi.fn(),
  },
}));

describe("AccountsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAccounts).mockResolvedValue(mockAccounts);
  });

  it("renders accounts title and list of accounts", async () => {
    render(
      <MemoryRouter>
        <AccountsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Checking Account")).toBeInTheDocument();
      expect(screen.getByText("Savings Account")).toBeInTheDocument();
      expect(screen.getByText(/3.*200,00/i)).toBeInTheDocument();
    });
  });

  it("opens Add Account dialog when clicking add button", async () => {
    render(
      <MemoryRouter>
        <AccountsPage />
      </MemoryRouter>
    );

    const addBtn = screen.getByRole("button", { name: /Dodaj konto/i });
    fireEvent.click(addBtn);

    expect(screen.getByText(/Nowe konto/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Nazwa konta/i)).toBeInTheDocument();
  });

  it("opens Edit Account dialog when clicking pencil button", async () => {
    render(
      <MemoryRouter>
        <AccountsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Checking Account")).toBeInTheDocument();
    });

    const editBtns = screen.getAllByTitle(/Edytuj konto/i);
    fireEvent.click(editBtns[0]);

    expect(screen.getByText(/Edytuj konto/i)).toBeInTheDocument();
    const nameInput = screen.getByLabelText(/Nazwa konta/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Checking Account");
  });

  it("opens Reconcile dialog when clicking reconcile button", async () => {
    render(
      <MemoryRouter>
        <AccountsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Checking Account")).toBeInTheDocument();
    });

    const reconcileBtns = screen.getAllByTitle(/Wyrównaj saldo/i);
    fireEvent.click(reconcileBtns[0]);

    expect(screen.getByText(/Wyrównaj saldo konta/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Rzeczywiste saldo/i)).toBeInTheDocument();
  });
});
