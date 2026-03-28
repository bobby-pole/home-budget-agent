import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { Dashboard } from "@/pages/Dashboard";

vi.mock("@/components/dashboard/BudgetSummaryCard", () => ({
  BudgetSummaryCard: () => <div data-testid="mock-budget-summary">BudgetSummaryCard</div>,
}));

vi.mock("@/components/dashboard/SpendingPieChart", () => ({
  SpendingPieChart: () => <div data-testid="mock-pie-chart">SpendingPieChart</div>,
}));

vi.mock("@/components/dashboard/TopEnvelopesCard", () => ({
  TopEnvelopesCard: () => <div data-testid="mock-top-envelopes">TopEnvelopesCard</div>,
}));

vi.mock("@/components/dashboard/RecentTransactionsList", () => ({
  RecentTransactionsList: () => <div data-testid="mock-recent-transactions">RecentTransactionsList</div>,
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
    scanTransaction: vi.fn(),
  },
}));

describe("Dashboard", () => {
  beforeEach(() => {
    mockGetTransactions.mockResolvedValue([]);
    mockGetBudget.mockResolvedValue({ amount: 0, year: 2026, month: 2, category_limits: [] });
  });

  it("shows loading state before data resolves", () => {
    mockGetTransactions.mockReturnValue(new Promise(() => {}));
    render(<Dashboard />);
    expect(screen.getByText(/Przygotowujemy Twój pulpit/i)).toBeInTheDocument();
  });

  it("renders summary and charts after data loads", async () => {
    render(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("mock-budget-summary")).toBeInTheDocument();
      expect(screen.getByTestId("mock-pie-chart")).toBeInTheDocument();
      expect(screen.getByTestId("mock-top-envelopes")).toBeInTheDocument();
      expect(screen.getByTestId("mock-recent-transactions")).toBeInTheDocument();
    });
  });

  it("pressing N key opens AddTransactionModal", async () => {
    render(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByTestId("mock-budget-summary")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("mock-add-transaction-modal")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "n" });
    expect(screen.getByTestId("mock-add-transaction-modal")).toBeInTheDocument();
  });

  it("snapshot — loaded state", async () => {
    const { container } = render(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByTestId("mock-budget-summary")).toBeInTheDocument();
    });
    expect(container).toMatchSnapshot();
  });
});
