import { describe, expect, it } from "vitest";
import type { TransactionRead } from "@/client";
import { translateValidationMessage } from "@/lib/errorCodes";
import {
  getCategorySourceMeta,
  getEffectiveReviewReasons,
  getLiveSumComparison,
  getTransactionProvenance,
  normalizeCategorySource,
} from "@/lib/provenance";

const baseTx: TransactionRead = {
  id: 1,
  merchant_name: "Lidl Polska",
  total_amount: "45.00",
  currency: "PLN",
  date: "2026-06-01T12:00:00Z",
  is_manual: false,
  type: "expense",
  review_status: "pending",
  canonical_total_valid: true,
  review_reasons: [],
  lines: [],
  source_records: [],
};

describe("provenance helper", () => {
  it("does not synthesize OCR quality percentage for structured providers", () => {
    const lidlTx: TransactionRead = {
      ...baseTx,
      source_records: [
        {
          id: 10,
          budget_id: 1,
          source_type: "MERCHANT_API",
          provider: "lidl",
          external_id: "ticket-1",
          adapter_version: "lidl_plus_v3",
          acquired_at: "2026-06-01T12:05:00Z",
          quality: "1.0000",
          raw_payload_policy: "canonical_only",
        },
      ],
    };

    const summary = getTransactionProvenance(lidlTx);
    expect(summary.dataMode).toBe("structured");
    expect(summary.sourceLabel).toBe("Lidl Plus");
    expect(summary.adapterVersion).toBe("lidl_plus_v3");
    expect(summary.qualityPercent).toBeNull();
    expect(summary.isExternalImport).toBe(true);
  });

  it("extracts OCR quality percentage only for OCR_PHOTO", () => {
    const ocrTx: TransactionRead = {
      ...baseTx,
      source_records: [
        {
          id: 11,
          budget_id: 1,
          source_type: "OCR_PHOTO",
          provider: "google_vision",
          adapter_version: "ocr_pipeline_v1",
          acquired_at: "2026-06-01T12:05:00Z",
          quality: "0.8750",
          raw_payload_policy: "ephemeral_image",
        },
      ],
    };

    const summary = getTransactionProvenance(ocrTx);
    expect(summary.dataMode).toBe("ocr");
    expect(summary.qualityPercent).toBe(88);
    expect(summary.isExternalImport).toBe(false);
  });

  it("normalizes category_source including legacy manual alias", () => {
    expect(normalizeCategorySource("cache")).toBe("cache");
    expect(normalizeCategorySource("ai")).toBe("ai");
    expect(normalizeCategorySource("user")).toBe("user");
    expect(normalizeCategorySource("manual")).toBe("user");
    expect(normalizeCategorySource("auto_categorizer")).toBe("auto");

    expect(getCategorySourceMeta("cache")?.label).toBe("Cache");
    expect(getCategorySourceMeta("ai")?.label).toBe("AI");
    expect(getCategorySourceMeta("manual")?.label).toBe("Użytkownik");
    expect(getCategorySourceMeta("user")?.label).toBe("Użytkownik");
  });

  it("computes total check using exact integer cents and guards unsaved edits", () => {
    const exact = getLiveSumComparison(baseTx, "45.00", "45.00");
    expect(exact.showVerifiedTotalBadge).toBe(true);
    expect(exact.isExactMatch).toBe(true);

    const withinPenny = getLiveSumComparison(baseTx, "45.01", "45.00");
    expect(withinPenny.showVerifiedTotalBadge).toBe(true);

    const editedMismatch = getLiveSumComparison(baseTx, "46.20", "45.00");
    expect(editedMismatch.showVerifiedTotalBadge).toBe(false);
    expect(editedMismatch.isExactMatch).toBe(false);
    expect(editedMismatch.formattedAbsDiff).toBe("1.20");

    const failedBackend = getLiveSumComparison(
      { ...baseTx, canonical_total_valid: false },
      "45.00",
      "45.00",
    );
    expect(failedBackend.showVerifiedTotalBadge).toBe(false);
  });

  it("falls back cleanly for review reasons and translates known codes", () => {
    const reasons = getEffectiveReviewReasons({
      ...baseTx,
      account_id: null,
      review_reasons: [],
      receipt_scan: {
        id: 2,
        status: "NEEDS_REVIEW",
        created_at: "2026-06-01T12:00:00Z",
        validation_message: "LOW_CONFIDENCE",
      },
    });
    expect(reasons).toEqual(["LOW_CONFIDENCE", "MISSING_ACCOUNT"]);
    expect(translateValidationMessage("LOW_CONFIDENCE")).not.toBe("LOW_CONFIDENCE");
    expect(translateValidationMessage("VALIDATION_FAILED")).not.toBe("VALIDATION_FAILED");
    expect(translateValidationMessage("MISSING_ACCOUNT")).not.toBe("MISSING_ACCOUNT");
    expect(translateValidationMessage("RECEIPT_SUM_MISMATCH:1.25")).toContain("1.25");
  });
});
