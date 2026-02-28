import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { CategoriesTab } from "@/components/settings/CategoriesTab";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    getCategories: vi.fn(),
    createCategory: vi.fn(),
    updateCategory: vi.fn(),
    deleteCategory: vi.fn(),
  },
}));

const mockCategories = [
  { id: 1, name: "Jedzenie", is_system: true, parent_id: undefined },
  { id: 2, name: "Moja kategoria", is_system: false, parent_id: undefined },
];

describe("CategoriesTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getCategories).mockResolvedValue(mockCategories);
  });

  it("renders categories correctly", async () => {
    render(<CategoriesTab />);
    expect(await screen.findByText("Jedzenie")).toBeInTheDocument();
    expect(await screen.findByText("Moja kategoria")).toBeInTheDocument();
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
