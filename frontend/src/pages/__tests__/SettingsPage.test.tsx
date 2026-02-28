import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { SettingsPage } from "@/pages/SettingsPage";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/components/settings/CategoriesTab", () => ({
  CategoriesTab: () => <div data-testid="mock-categories-tab">Categories Tab Content</div>,
}));

vi.mock("@/components/settings/TagsTab", () => ({
  TagsTab: () => <div data-testid="mock-tags-tab">Tags Tab Content</div>,
}));

describe("SettingsPage", () => {
  it("renders tabs correctly", () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );
    expect(screen.getByText("Ustawienia")).toBeInTheDocument();
    
    // Default tab is categories
    expect(screen.getByTestId("mock-categories-tab")).toBeInTheDocument();
    // Tabs list triggers
    expect(screen.getByRole("tab", { name: /Kategorie/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Tagi/i })).toBeInTheDocument();
  });
});
