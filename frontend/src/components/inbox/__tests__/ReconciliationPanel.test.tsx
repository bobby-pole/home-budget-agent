import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { ReconciliationPanel } from "@/components/inbox/ReconciliationPanel";
import { api } from "@/lib/api";
import type { ReconciliationLinkRead, ReconciliationListResponse } from "@/client";

vi.mock("@/lib/api", () => ({
  api: {
    getReconciliationCandidates: vi.fn(),
    refreshReconciliationCandidates: vi.fn(),
    acceptReconciliation: vi.fn(),
    rejectReconciliation: vi.fn(),
    unlinkReconciliation: vi.fn(),
  },
}));

const pendingCandidate: ReconciliationLinkRead = {
  id: 101,
  budget_id: 1,
  bank_source_record_id: 11,
  target_source_record_id: 22,
  bank_transaction_id: 201,
  target_transaction_id: 202,
  match_kind: "exact",
  status: "pending",
  score: "0.95",
  confidence_tier: "high",
  same_day_conflict_count: 2,
  signals: [
    { code: "amount_exact", matched: true, weight: "0.45", detail: {} },
    { code: "date_same_day", matched: true, weight: "0.25", detail: {} },
    { code: "merchant_strong_match", matched: true, weight: "0.20", detail: {} },
    { code: "same_day_equal_amount_ambiguity", matched: false, weight: "0.00", detail: { conflict_count: 2 } },
  ],
  bank_transaction: {
    id: 201,
    merchant_name: "Biedronka 1234",
    total_amount: "42.50",
    currency: "PLN",
    date: "2026-05-10T00:00:00Z",
    type: "expense",
    status: "cleared",
    account_id: 3,
    account_name: "ING Główne",
    note: "Płatność kartą",
    source_type: "BANK_CSV",
    provider: "ing_csv",
  },
  target_transaction: {
    id: 202,
    merchant_name: "Biedronka",
    total_amount: "42.50",
    currency: "PLN",
    date: "2026-05-10T10:15:00Z",
    type: "expense",
    status: "uncleared",
    account_id: null,
    account_name: null,
    note: "Paragon",
    source_type: "OCR_PHOTO",
    provider: "receipt_ocr",
  },
  decided_at: null,
  created_at: "2026-05-10T11:00:00Z",
  updated_at: "2026-05-10T11:00:00Z",
};

const acceptedLink: ReconciliationLinkRead = {
  ...pendingCandidate,
  id: 102,
  status: "accepted",
  same_day_conflict_count: 0,
  decided_at: "2026-05-10T12:00:00Z",
};

const emptyListResponse: ReconciliationListResponse = {
  candidates: [],
  pending_count: 0,
  accepted_count: 0,
  rejected_count: 0,
  unlinked_count: 0,
};

describe("ReconciliationPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders explainable signals, ambiguity warning, and supports accept and reject", async () => {
    vi.mocked(api.getReconciliationCandidates).mockResolvedValue({
      candidates: [pendingCandidate],
      pending_count: 1,
      accepted_count: 0,
      rejected_count: 0,
      unlinked_count: 0,
    });
    vi.mocked(api.acceptReconciliation).mockResolvedValue({
      link: acceptedLink,
      message: "Reconciliation link accepted",
    });
    vi.mocked(api.rejectReconciliation).mockResolvedValue({
      link: { ...pendingCandidate, status: "rejected" },
      message: "Reconciliation candidate rejected",
    });

    render(<ReconciliationPanel />);

    expect(await screen.findByText("Biedronka 1234")).toBeInTheDocument();
    expect(screen.getByText("Biedronka")).toBeInTheDocument();
    expect(screen.getByText(/Dokładna zgodność kwoty/i)).toBeInTheDocument();
    expect(screen.getByText(/Ta sama data transakcji/i)).toBeInTheDocument();
    expect(screen.getByText(/Wykryto wiele transakcji \(2\)/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Połącz$/i }));
    await waitFor(() => {
      expect(api.acceptReconciliation).toHaveBeenCalledWith(101, expect.anything());
    });

    fireEvent.click(screen.getByRole("button", { name: /^Odrzuć$/i }));
    await waitFor(() => {
      expect(api.rejectReconciliation).toHaveBeenCalledWith(101, expect.anything());
    });
  });

  it("supports unlinking an accepted reconciliation link and refreshing matches", async () => {
    vi.mocked(api.getReconciliationCandidates).mockImplementation(async (status) => {
      if (status === "accepted") {
        return {
          candidates: [acceptedLink],
          pending_count: 0,
          accepted_count: 1,
          rejected_count: 0,
          unlinked_count: 0,
        };
      }
      return emptyListResponse;
    });
    vi.mocked(api.unlinkReconciliation).mockResolvedValue({
      link: { ...acceptedLink, status: "unlinked" },
      message: "Reconciliation link unlinked",
    });
    vi.mocked(api.refreshReconciliationCandidates).mockResolvedValue(emptyListResponse);

    render(<ReconciliationPanel />);

    expect(await screen.findByText(/Brak dopasowań w tym widoku/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Odśwież dopasowania/i }));
    await waitFor(() => {
      expect(api.refreshReconciliationCandidates).toHaveBeenCalledWith("pending");
    });

    fireEvent.click(screen.getByRole("button", { name: /^Połączone/i }));
    const unlinkBtn = await screen.findByRole("button", { name: /^Rozłącz$/i });
    fireEvent.click(unlinkBtn);

    await waitFor(() => {
      expect(api.unlinkReconciliation).toHaveBeenCalledWith(102, expect.anything());
    });
  });
});
