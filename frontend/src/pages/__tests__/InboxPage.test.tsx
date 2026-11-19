import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { render } from "@/__tests__/test-utils";
import { InboxPage } from "@/pages/InboxPage";
import { api } from "@/lib/api";
import type {
  AccountRead,
  ReconciliationLinkRead,
  ReconciliationListResponse,
  TransactionRead,
} from "@/client";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("@/lib/api", () => ({
  apiClient: {
    get: vi.fn().mockRejectedValue(new Error("no image")),
  },
  api: {
    getInbox: vi.fn(),
    bulkApproveInbox: vi.fn(),
    rejectInboxItem: vi.fn(),
    restoreInboxItem: vi.fn(),
    getCategories: vi.fn().mockResolvedValue([]),
    getEnvelopes: vi.fn().mockResolvedValue([]),
    getAccounts: vi.fn(),
    getReconciliationCandidates: vi.fn(),
    refreshReconciliationCandidates: vi.fn(),
    acceptReconciliation: vi.fn(),
    rejectReconciliation: vi.fn(),
    unlinkReconciliation: vi.fn(),
    mergeDuplicateReconciliation: vi.fn(),
    approveTransaction: vi.fn(),
    updateTransaction: vi.fn(),
    deleteTransaction: vi.fn(),
  },
}));

const mockAccounts: AccountRead[] = [
  {
    id: 5,
    name: "ING Wspólne",
    type: "checking",
    currency: "PLN",
    initial_balance: "1000.00",
    current_balance: "1000.00",
    is_on_budget: true,
    is_active: true,
    budget_id: 1,
    category_id: null,
  },
];

const mockInboxScans: TransactionRead[] = [
  {
    id: 1,
    merchant_name: "Lidl Warszawa",
    total_amount: "54.20",
    currency: "PLN",
    date: "2026-05-10T10:00:00Z",
    type: "expense",
    status: "uncleared",
    review_status: "pending",
    suggested_account_id: 5,
    is_manual: false,
    lines: [],
  },
  {
    id: 2,
    merchant_name: "Rossmann",
    total_amount: "32.00",
    currency: "PLN",
    date: "2026-05-11T12:00:00Z",
    type: "expense",
    status: "uncleared",
    review_status: "pending",
    suggested_account_id: 5,
    is_manual: false,
    lines: [],
  },
];

const mockRejectedScans: TransactionRead[] = [
  {
    id: 99,
    merchant_name: "Lidl Stary Paragon",
    total_amount: "19.99",
    currency: "PLN",
    date: "2026-05-09T12:00:00Z",
    type: "expense",
    status: "uncleared",
    review_status: "rejected",
    rejection_reason: "deleted_by_user",
    is_manual: false,
    lines: [],
  },
];

const mockCandidate: ReconciliationLinkRead = {
  id: 901,
  budget_id: 1,
  bank_source_record_id: 11,
  target_source_record_id: 22,
  bank_transaction_id: 301,
  target_transaction_id: 302,
  match_kind: "exact",
  status: "pending",
  score: "0.95",
  confidence_tier: "high",
  same_day_conflict_count: 1,
  signals: [
    { code: "amount_exact", matched: true, weight: "0.45", detail: {} },
    { code: "date_same_day", matched: true, weight: "0.25", detail: {} },
  ],
  bank_transaction: {
    id: 301,
    merchant_name: "CARREFOUR POLSKA",
    total_amount: "88.00",
    currency: "PLN",
    date: "2026-05-10T00:00:00Z",
    type: "expense",
    status: "cleared",
    account_id: 5,
    account_name: "ING Główne",
    note: "Płatność kartą",
    source_type: "BANK_CSV",
    provider: "ing_csv",
  },
  target_transaction: {
    id: 302,
    merchant_name: "Carrefour",
    total_amount: "88.00",
    currency: "PLN",
    date: "2026-05-10T12:00:00Z",
    type: "expense",
    status: "uncleared",
    account_id: null,
    account_name: null,
    note: null,
    source_type: "OCR_PHOTO",
    provider: "receipt_ocr",
  },
  decided_at: null,
  created_at: "2026-05-10T12:30:00Z",
  updated_at: "2026-05-10T12:30:00Z",
};

const mockReconciliationResponse: ReconciliationListResponse = {
  candidates: [mockCandidate],
  pending_count: 3,
  accepted_count: 1,
  rejected_count: 0,
  unlinked_count: 0,
};

describe("InboxPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAccounts).mockResolvedValue(mockAccounts);
    vi.mocked(api.getInbox).mockImplementation(async (params) => {
      if (params?.tab === "rejected") return mockRejectedScans;
      return mockInboxScans;
    });
    vi.mocked(api.getReconciliationCandidates).mockResolvedValue(mockReconciliationResponse);
  });

  it("displays hybrid Inbox tab counters and switches across all 3 tabs cleanly", async () => {
    render(
      <MemoryRouter>
        <InboxPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Wyjątki i do przeglądu/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Uzgodnienia i duplikaty/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Odrzucone \/ Usunięte/i })).toBeInTheDocument();
    });

    const exceptionsTab = screen.getByRole("button", { name: /Wyjątki i do przeglądu/i });
    const reconciliationTab = screen.getByRole("button", { name: /Uzgodnienia i duplikaty/i });
    const rejectedTab = screen.getByRole("button", { name: /Odrzucone \/ Usunięte/i });

    await waitFor(() => {
      expect(exceptionsTab).toHaveTextContent("2");
      expect(reconciliationTab).toHaveTextContent("3");
      expect(rejectedTab).toHaveTextContent("1");
    });

    expect(screen.getByText(/Lidl Warszawa/i)).toBeInTheDocument();

    fireEvent.click(reconciliationTab);
    await waitFor(() => {
      expect(screen.getByText(/CARREFOUR POLSKA/i)).toBeInTheDocument();
    });

    fireEvent.click(rejectedTab);
    await waitFor(() => {
      expect(screen.getByText(/Lidl Stary Paragon/i)).toBeInTheDocument();
    });

    fireEvent.click(exceptionsTab);
    await waitFor(() => {
      expect(screen.getByText(/Lidl Warszawa/i)).toBeInTheDocument();
    });
  });

  it("supports bulk selection and approval onto suggested account plus restoring rejected items", async () => {
    vi.mocked(api.bulkApproveInbox).mockResolvedValue({
      approved_count: 2,
      skipped_ids: [],
      errors: [],
    });
    vi.mocked(api.restoreInboxItem).mockResolvedValue({
      ...mockRejectedScans[0],
      review_status: "pending",
      rejection_reason: null,
    });

    render(
      <MemoryRouter>
        <InboxPage />
      </MemoryRouter>
    );

    await screen.findByText(/Lidl Warszawa/i);

    const selectAllCheckbox = screen.getByRole("checkbox", { name: /Zaznacz wszystkie/i });
    fireEvent.click(selectAllCheckbox);

    const bulkBtn = await screen.findByRole("button", { name: /Zatwierdź wybrane/i });
    fireEvent.click(bulkBtn);

    await waitFor(() => {
      expect(api.bulkApproveInbox).toHaveBeenCalledWith({
        transaction_ids: [1, 2],
        account_id: 5,
      });
    });

    fireEvent.click(screen.getByRole("button", { name: /Odrzucone \/ Usunięte/i }));
    const restoreBtn = await screen.findByRole("button", { name: /Przywróć/i });
    fireEvent.click(restoreBtn);

    await waitFor(() => {
      expect(api.restoreInboxItem).toHaveBeenCalledWith(99);
    });
  });
});
