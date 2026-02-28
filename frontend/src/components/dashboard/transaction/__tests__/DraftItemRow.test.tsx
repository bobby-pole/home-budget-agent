import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { DraftItemRow } from "@/components/dashboard/transaction/DraftItemRow";
import type { NewItemDraft } from "@/components/dashboard/transaction/DraftItemRow";

// Mock Radix UI Select — SelectTrigger/SelectValue must return null
// to avoid invalid HTML (<span> inside <select>) in jsdom
vi.mock("@/components/ui/select", () => ({
  Select: ({ children, onValueChange, value }: { children: React.ReactNode; onValueChange?: (v: string) => void; value?: string }) => (
    <select
      data-testid="category-select"
      value={value ?? ""}
      onChange={(e) => onValueChange?.(e.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  ),
}));

const defaultDraft: NewItemDraft = {
  name: "",
  price: "",
  quantity: "1",
  category: "Other",
};

function renderDraftRow(
  draft: NewItemDraft = defaultDraft,
  overrides: Partial<{
    draftValid: boolean;
    onChange: (d: NewItemDraft) => void;
    onConfirm: () => void;
    onCancel: () => void;
    onKeyDown: (e: React.KeyboardEvent) => void;
  }> = {}
) {
  const ref = createRef<HTMLInputElement>();
  return render(
    <DraftItemRow
      draft={draft}
      draftNameRef={ref}
      draftValid={overrides.draftValid ?? false}
      onChange={overrides.onChange ?? vi.fn()}
      onConfirm={overrides.onConfirm ?? vi.fn()}
      onCancel={overrides.onCancel ?? vi.fn()}
      onKeyDown={overrides.onKeyDown ?? vi.fn()}
    />
  );
}

describe("DraftItemRow", () => {
  it("renders item name input", () => {
    renderDraftRow();
    expect(screen.getByPlaceholderText("Nazwa pozycji")).toBeInTheDocument();
  });

  it("renders price input", () => {
    renderDraftRow();
    expect(screen.getByPlaceholderText("Cena")).toBeInTheDocument();
  });

  it("renders quantity input", () => {
    renderDraftRow();
    expect(screen.getByPlaceholderText("Ilość")).toBeInTheDocument();
  });

  it("renders category select", () => {
    renderDraftRow();
    expect(screen.getByTestId("category-select")).toBeInTheDocument();
  });

  it("confirm button is disabled when draftValid=false", () => {
    renderDraftRow(defaultDraft, { draftValid: false });
    const buttons = screen.getAllByRole("button");
    // first button is Confirm (Check icon)
    expect(buttons[0]).toBeDisabled();
  });

  it("confirm button is enabled when draftValid=true", () => {
    renderDraftRow(defaultDraft, { draftValid: true });
    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).not.toBeDisabled();
  });

  it("calls onChange when name is changed", () => {
    const onChange = vi.fn();
    renderDraftRow(defaultDraft, { onChange });

    // fireEvent.change sends a single event with the full value
    // (userEvent.type does not work correctly with controlled inputs
    // whose value is not updated by the mock)
    fireEvent.change(screen.getByPlaceholderText("Nazwa pozycji"), {
      target: { value: "Chleb" },
    });

    expect(onChange).toHaveBeenCalledOnce();
    const lastCall = onChange.mock.calls.at(-1)?.[0] as NewItemDraft;
    expect(lastCall.name).toBe("Chleb");
  });

  it("calls onConfirm when confirm button is clicked", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    renderDraftRow(defaultDraft, { draftValid: true, onConfirm });

    const buttons = screen.getAllByRole("button");
    await user.click(buttons[0]);

    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("calls onCancel when cancel button is clicked", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    renderDraftRow(defaultDraft, { onCancel });

    const buttons = screen.getAllByRole("button");
    await user.click(buttons[1]); // second button = X (Cancel)

    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("displays draft values in input fields", () => {
    const draft: NewItemDraft = {
      name: "Masło",
      price: "5.99",
      quantity: "3",
      category: "Food",
    };
    renderDraftRow(draft);

    expect(screen.getByDisplayValue("Masło")).toBeInTheDocument();
    expect(screen.getByDisplayValue("5.99")).toBeInTheDocument();
    expect(screen.getByDisplayValue("3")).toBeInTheDocument();
  });

  describe("snapshots", () => {
    it("matches snapshot — empty draft (confirm disabled)", () => {
      const { asFragment } = renderDraftRow(defaultDraft, { draftValid: false });
      expect(asFragment()).toMatchSnapshot();
    });

    it("matches snapshot — filled draft (confirm enabled)", () => {
      const draft: NewItemDraft = {
        name: "Chleb",
        price: "3.50",
        quantity: "2",
        category: "Food",
      };
      const { asFragment } = renderDraftRow(draft, { draftValid: true });
      expect(asFragment()).toMatchSnapshot();
    });
  });
});
