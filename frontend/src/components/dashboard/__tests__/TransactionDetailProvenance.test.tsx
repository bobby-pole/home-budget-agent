import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { TransactionDetailModal } from "@/components/dashboard/TransactionDetailModal";
import type { TransactionRead } from "@/client";

vi.mock("@/lib/api", () => ({
  api: {
    getCategories: vi.fn().mockResolvedValue([
      { id: 1, name: "Food", is_system: true, color: "#10b981", icon: "utensils" },
    ]),
    getAccounts: vi.fn().mockResolvedValue([
      {
        id: 2,
        name: "Konto",
        type: "checking",
        currency: "PLN",
        initial_balance: "500.00",
        current_balance: "500.00",
        is_on_budget: true,
        is_active: true,
      },
    ]),
    getTags: vi.fn().mockResolvedValue([]),
    updateTransaction: vi.fn().mockResolvedValue({}),
    updateTransactionLine: vi.fn().mockResolvedValue({}),
  },
}));

const approvedTx: TransactionRead = {
  id: 88,
  merchant_name: "Biedronka",
  date: "2026-06-12T08:30:00Z",
  total_amount: "19.99",
  currency: "PLN",
  type: "expense",
  account_id: 2,
  review_status: "approved",
  canonical_total_valid: true,
  review_reasons: [],
  source_records: [
    {
      id: 31,
      budget_id: 1,
      source_type: "E_RECEIPT",
      provider: "eparagon_json",
      external_id: "ep-88",
      adapter_version: "eparagon_v1",
      acquired_at: "2026-06-12T08:31:00Z",
      quality: "1.0000",
      raw_payload_policy: "canonical_only",
    },
  ],
  receipt_scan: {
    id: 12,
    status: "DONE",
    processed_via: "eparagon_v1",
    needs_review: false,
    created_at: "2026-06-12T08:31:00Z",
  },
  lines: [
    {
      id: 401,
      name: "Jabłka 1kg",
      price: "19.99",
      quantity: "1",
      category_id: 1,
      category_source: "user",
      is_adjustment: false,
    },
  ],
};

describe("TransactionDetailModal provenance visibility", () => {
  it("displays document provenance, canonical sum check, and user category badge per line", () => {
    render(<TransactionDetailModal transaction={approvedTx} isOpen onClose={vi.fn()} />);

    expect(screen.getByText("e-Paragon")).toBeInTheDocument();
    expect(screen.getByText("eparagon_v1")).toBeInTheDocument();
    expect(screen.getByText("Suma zgodna")).toBeInTheDocument();
    expect(screen.getByText("Użytkownik")).toBeInTheDocument();
  });
});
