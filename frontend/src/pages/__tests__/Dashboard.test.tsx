import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { Dashboard } from "@/pages/Dashboard";

vi.mock("@/components/dashboard/KpiCard", () => ({
  KPICard: () => <div data-testid="mock-kpi-card">KpiCard</div>,
}));

vi.mock("@/components/dashboard/TransactionsTable", () => ({
  TransactionsTable: () => <div data-testid="mock-transactions-table">TransactionsTable</div>,
}));

vi.mock("@/components/dashboard/SpendingChart", () => ({
  SpendingChart: () => <div data-testid="mock-spending-chart">SpendingChart</div>,
}));

vi.mock("@/components/dashboard/UploadBox", () => ({
  UploadBox: () => <div data-testid="mock-upload-box">UploadBox</div>,
}));

vi.mock("@/components/dashboard/MonthlySummaryModal", () => ({
  MonthlySummaryModal: () => <div data-testid="mock-monthly-summary-modal" />,
}));

vi.mock("@/components/dashboard/BudgetModal", () => ({
  BudgetModal: () => <div data-testid="mock-budget-modal" />,
}));

vi.mock("@/components/dashboard/AddTransactionModal", () => ({
  AddTransactionModal: ({ open }: { open: boolean }) =>
    open ? <div data-testid="mock-add-transaction-modal">AddTransactionModal</div> : null,
}));

const mockGetTransactions = vi.fn();
const mockGetBudget = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    getTransactions: () => mockGetTransactions(),
    getBudget: () => mockGetBudget(),
    getCategories: vi.fn().mockResolvedValue([]),
  },
}));

describe("Dashboard", () => {
  beforeEach(() => {
    mockGetTransactions.mockResolvedValue([]);
    mockGetBudget.mockResolvedValue({ amount: 0, year: 2026, month: 2 });
  });

  it("shows loading state before data resolves", () => {
    // Make queries hang indefinitely to keep the loading state
    mockGetTransactions.mockReturnValue(new Promise(() => {}));
    mockGetBudget.mockReturnValue(new Promise(() => {}));

    render(<Dashboard />);

    expect(screen.getByText(/ładowanie twoich finansów/i)).toBeInTheDocument();
  });

  it("renders KPI Cards and UploadBox after data loads", async () => {
    render(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("mock-upload-box")).toBeInTheDocument();
      expect(screen.getAllByTestId("mock-kpi-card")).toHaveLength(3);
    });
  });

  it("renders UploadBox after data loads", async () => {
    render(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("mock-upload-box")).toBeInTheDocument();
    });
  });

  it("pressing N key opens AddTransactionModal", async () => {
    render(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("mock-upload-box")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("mock-add-transaction-modal")).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "n" });

    expect(screen.getByTestId("mock-add-transaction-modal")).toBeInTheDocument();
  });

  it("snapshot — loaded state", async () => {
    const { container } = render(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("mock-upload-box")).toBeInTheDocument();
    });

    expect(container).toMatchSnapshot();
  });
});
