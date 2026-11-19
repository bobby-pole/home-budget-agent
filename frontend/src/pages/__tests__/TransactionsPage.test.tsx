import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { render } from "@/__tests__/test-utils";
import { TransactionsPage } from "@/pages/TransactionsPage";
import { api } from "@/lib/api";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("@/hooks/use-transaction-actions", () => ({
  useTransactionActions: () => ({
    setQuickEntryOpen: vi.fn(),
    renderModals: () => null,
  }),
}));

vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    isDemo: false,
    user: { id: 1, email: "owner@example.com" },
  }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    getTransactions: vi.fn(),
    getAccounts: vi.fn(),
    getCategories: vi.fn(),
    previewImportTransactions: vi.fn(),
    importTransactions: vi.fn(),
    deleteTransaction: vi.fn(),
    retryTransaction: vi.fn(),
  },
}));

describe("TransactionsPage pre-import modal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getTransactions).mockResolvedValue([]);
    vi.mocked(api.getCategories).mockResolvedValue([]);
    vi.mocked(api.getAccounts).mockResolvedValue([
      {
        id: 12,
        name: "PKO ROR",
        type: "checking",
        currency: "PLN",
        initial_balance: "1000.00",
        current_balance: "1000.00",
        is_on_budget: true,
        is_active: true,
        budget_id: 1,
        category_id: null,
      },
    ]);
    vi.mocked(api.previewImportTransactions).mockResolvedValue({
      filename: "ing.csv",
      total_rows: 2,
      new_count: 1,
      duplicate_count: 1,
      suggested_account_id: 12,
      warnings: [],
      rows: [
        {
          date: "2026-05-10T00:00:00Z",
          merchant_name: "Lidl",
          title: "Zakup",
          amount: "42.50",
          currency: "PLN",
          detected_type: "expense",
          is_duplicate: false,
        },
        {
          date: "2026-05-09T00:00:00Z",
          merchant_name: "Biedronka",
          title: "Zakup",
          amount: "20.00",
          currency: "PLN",
          detected_type: "expense",
          is_duplicate: true,
        },
      ],
    });
    vi.mocked(api.importTransactions).mockResolvedValue({
      created: 1,
      skipped: 1,
      failed: 0,
      summary: { code: "CSV_IMPORT_COMPLETE", imported: 1, skipped: 1, filename: "ing.csv" },
    });
  });

  it("opens preview modal with suggested account and submits chosen merge policy", async () => {
    const { container } = render(
      <MemoryRouter>
        <TransactionsPage />
      </MemoryRouter>
    );

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();

    const csvFile = new File(["date,amount\n2026-05-10,-42.50"], "ing.csv", { type: "text/csv" });
    fireEvent.change(fileInput, { target: { files: [csvFile] } });

    expect(await screen.findByText(/Potwierdź import wyciągu bankowego/i)).toBeInTheDocument();
    expect(await screen.findByText(/Nowych: 1/i)).toBeInTheDocument();
    expect(screen.getByText(/Duplikatów pominiętych: 1/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Ręcznie w Inboxie/i }));
    fireEvent.click(screen.getByRole("button", { name: /Importuj \(1\)/i }));

    await waitFor(() => {
      expect(api.importTransactions).toHaveBeenCalledWith(csvFile, {
        account_id: 12,
        auto_merge_policy: "manual",
        require_account: true,
      });
    });
  });
});
