import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { CategoriesTab } from "@/components/settings/CategoriesTab";
import { api } from "@/lib/api";
import { getLocale, setLocale } from "@/lib/i18n";

vi.mock("@/lib/api", () => ({
  api: {
    getCategories: vi.fn(),
    createCategory: vi.fn(),
    updateCategory: vi.fn(),
    deleteCategory: vi.fn(),
  },
}));

const mockCategories = [
  { id: 1, name: "Food", is_system: true, parent_id: undefined, color: "#f87171", icon: "utensils" },
  { id: 2, name: "Moja kategoria", is_system: false, parent_id: undefined, color: "#cccccc", icon: "package" },
];

describe("CategoriesTab", () => {
  const originalLocale = getLocale();

  beforeEach(() => {
    vi.clearAllMocks();
    setLocale("pl");
    vi.mocked(api.getCategories).mockResolvedValue(mockCategories);
  });

  afterEach(() => {
    setLocale(originalLocale);
  });

  it("renders translated system categories in PL and EN while preserving user categories", async () => {
    const { rerender } = render(<CategoriesTab />);
    expect(await screen.findByText("Jedzenie")).toBeInTheDocument();
    expect(await screen.findByText("Moja kategoria")).toBeInTheDocument();

    setLocale("en");
    rerender(<CategoriesTab />);
    expect(await screen.findByText("Food")).toBeInTheDocument();
    expect(await screen.findByText("Moja kategoria")).toBeInTheDocument();
  });

  it("does not overwrite canonical system category name when editing color/icon", async () => {
    vi.mocked(api.updateCategory).mockResolvedValue({ ...mockCategories[0], color: "#00ff00" });
    render(<CategoriesTab />);

    const systemLabel = await screen.findByText("Jedzenie");
    fireEvent.click(systemLabel);

    const nameInput = screen.getByDisplayValue("Jedzenie") as HTMLInputElement;
    expect(nameInput).toBeDisabled();

    const colorInput = document.querySelector('input[type="color"]') as HTMLInputElement;
    fireEvent.change(colorInput, { target: { value: "#00ff00" } });

    const saveButtons = document.querySelectorAll("button");
    const saveButton = Array.from(saveButtons).find((btn) => btn.querySelector(".lucide-save"));
    expect(saveButton).toBeTruthy();
    fireEvent.click(saveButton!);

    await waitFor(() => {
      expect(api.updateCategory).toHaveBeenCalledWith(1, {
        color: "#00ff00",
        icon: "utensils",
      });
    });
  });

  it("allows adding a new category", async () => {
    vi.mocked(api.createCategory).mockResolvedValue({ id: 3, name: "Nowa", is_system: false });
    render(<CategoriesTab />);
    
    const addButton = await screen.findByRole("button", { name: /Dodaj kategorię/i });
    fireEvent.click(addButton);
    
    const input = screen.getByPlaceholderText(/Wpisz nazwę/i);
    fireEvent.change(input, { target: { value: "Nowa" } });
    
    const saveButton = screen.getByRole("button", { name: /Zapisz/i });
    fireEvent.click(saveButton);
    
    await waitFor(() => {
      expect(api.createCategory).toHaveBeenCalledWith({ name: "Nowa", parent_id: undefined });
    });
  });
});
