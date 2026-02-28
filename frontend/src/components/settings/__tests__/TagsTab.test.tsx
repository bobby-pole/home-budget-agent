import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { TagsTab } from "@/components/settings/TagsTab";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    getTags: vi.fn(),
    createTag: vi.fn(),
    deleteTag: vi.fn(),
  },
}));

const mockTags = [
  { id: 1, name: "wakacje", owner_id: 1 },
  { id: 2, name: "remont", owner_id: 1 },
];

describe("TagsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getTags).mockResolvedValue(mockTags);
  });

  it("renders tags correctly", async () => {
    render(<TagsTab />);
    expect(await screen.findByText("#wakacje")).toBeInTheDocument();
    expect(await screen.findByText("#remont")).toBeInTheDocument();
  });

  it("allows adding a new tag", async () => {
    vi.mocked(api.createTag).mockResolvedValue({ id: 3, name: "nowytag", owner_id: 1 });
    render(<TagsTab />);
    
    const input = await screen.findByPlaceholderText(/Dodaj nowy tag/i);
    const button = screen.getByRole("button", { name: /Dodaj/i });
    
    fireEvent.change(input, { target: { value: "nowytag" } });
    fireEvent.click(button);
    
    await waitFor(() => {
      expect(api.createTag).toHaveBeenCalledWith({ name: "nowytag" });
    });
  });
});
