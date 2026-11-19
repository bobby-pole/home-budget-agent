import { render, fireEvent, waitFor } from "@/__tests__/test-utils";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { UploadBox } from "../UploadBox";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    scanTransaction: vi.fn(),
    scanBatch: vi.fn(),
    getDemoQuota: vi.fn().mockResolvedValue({
      is_demo: false,
      daily_limit: 999,
      used: 0,
      remaining: 999,
      can_scan: true,
    }),
    getAccounts: vi.fn().mockResolvedValue([]),
  },
}));

describe("UploadBox", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uploads multiple dropped valid files via scanBatch and skips invalid files", async () => {
    vi.mocked(api.scanBatch).mockResolvedValue({
      import_batch_id: "batch_drop",
      total_files: 2,
      queued_count: 2,
      duplicate_count: 0,
      failed_count: 0,
      rate_limited_count: 0,
      results: [],
    });

    const { container } = render(<UploadBox totalCount={12} processingCount={1} />);
    const dropZone = container.querySelector(".border-dashed") as HTMLElement;
    expect(dropZone).toBeTruthy();

    const img = new File(["img"], "one.jpg", { type: "image/jpeg" });
    const pdf = new File(["%PDF-1.4"], "two.pdf", { type: "application/pdf" });
    const exe = new File(["bin"], "malware.exe", { type: "application/octet-stream" });

    fireEvent.drop(dropZone, {
      dataTransfer: {
        files: [img, pdf, exe],
      },
    });

    await waitFor(() => {
      expect(api.scanBatch).toHaveBeenCalledTimes(1);
    });
    const uploaded = vi.mocked(api.scanBatch).mock.calls[0][0];
    expect(uploaded.map((f) => f.name)).toEqual(["one.jpg", "two.pdf"]);
  });
});
