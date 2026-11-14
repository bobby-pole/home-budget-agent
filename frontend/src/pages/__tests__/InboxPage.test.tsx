import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { render } from "@/__tests__/test-utils";
import { InboxPage } from "@/pages/InboxPage";
import { api } from "@/lib/api";
import type { ReconciliationLinkRead, ReconciliationListResponse, TransactionRead } from "@/client";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("@/lib/api", () => ({
  apiClient: {
    get: vi.fn().mockRejectedValue(new Error("no image")),
  },
  api: {
    getInbox: vi.fn(),
    getCategories: vi.fn().mockResolvedValue([]),
    getEnvelopes: vi.fn().mockResolvedValue([]),
    getAccounts: vi.fn().mockResolvedValue([]),
    getReconciliationCandidates: vi.fn(),
    refreshReconciliationCandidates: vi.fn(),
    acceptReconciliation: vi.fn(),
    rejectReconciliation: vi.fn(),
    unlinkReconciliation: vi.fn(),
    approveTransaction: vi.fn(),
    updateTransaction: vi.fn(),
    deleteTransaction: vi.fn(),
  },
}));

const mockInboxScans: TransactionRead[] = [
  {
    id: 1,
    merchant_name: "Lidl Warszawa",
    total_amount: "54.20",
    currency: "PLN",
    date: "2026-05-10T10:00:00Z",
    type: "expense",
    status: "uncleared",
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
    vi.mocked(api.getInbox).mockResolvedValue(mockInboxScans);
    vi.mocked(api.getReconciliationCandidates).mockResolvedValue(mockReconciliationResponse);
  });

  it("displays receipt and pending reconciliation badge counters and switches tabs cleanly", async () => {
    render(
      <MemoryRouter>
        <InboxPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Skany paragonów/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Uzgadnianie z bankiem/i })).toBeInTheDocument();
    });

    const receiptsTab = screen.getByRole("button", { name: /Skany paragonów/i });
    const reconciliationTab = screen.getByRole("button", { name: /Uzgadnianie z bankiem/i });

    await waitFor(() => {
      expect(receiptsTab).toHaveTextContent("2");
      expect(reconciliationTab).toHaveTextContent("3");
    });

    // Receipts tab is active initially
    expect(screen.getByText(/Lidl Warszawa/i)).toBeInTheDocument();
    expect(screen.queryByText(/CARREFOUR POLSKA/i)).not.toBeInTheDocument();

    // Switch to Bank reconciliation tab
    fireEvent.click(reconciliationTab);
    await waitFor(() => {
      expect(screen.getByText(/CARREFOUR POLSKA/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Lidl Warszawa/i)).not.toBeInTheDocument();

    // Switch back to Receipt scans tab
    fireEvent.click(receiptsTab);
    await waitFor(() => {
      expect(screen.getByText(/Lidl Warszawa/i)).toBeInTheDocument();
    });
  });
});
