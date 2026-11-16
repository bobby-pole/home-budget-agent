import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { render } from "@/__tests__/test-utils";
import { ConnectionsTab } from "@/components/settings/ConnectionsTab";
import { api } from "@/lib/api";
import type { ExternalReceiptConnectionRead } from "@/client";

vi.mock("@/lib/api", () => ({
  api: {
    getAppConfig: vi.fn(),
    getConnections: vi.fn(),
    createConnection: vi.fn(),
    startConnectionOAuth: vi.fn(),
    completeConnectionOAuth: vi.fn(),
    desktopLoginConnectionOAuth: vi.fn(),
    syncNowConnection: vi.fn(),
    reconnectConnection: vi.fn(),
    disconnectConnection: vi.fn(),
  },
}));

const mockActiveConnection: ExternalReceiptConnectionRead = {
  id: 1,
  budget_id: 10,
  owner_user_id: 5,
  provider: "lidl",
  consented_scopes: "openid,tickets,profile",
  consented_at: "2026-09-20T12:00:00Z",
  status: "active",
  has_token: true,
  last_success_at: "2026-09-21T08:00:00Z",
  last_error_code: null,
  next_sync_at: "2026-09-22T08:00:00Z",
  sync_requested_at: null,
  created_at: "2026-09-20T12:00:00Z",
  updated_at: "2026-09-21T08:00:00Z",
};

const mockReauthConnection: ExternalReceiptConnectionRead = {
  id: 2,
  budget_id: 10,
  owner_user_id: 5,
  provider: "biedronka",
  consented_scopes: "receipts",
  consented_at: "2026-09-18T10:00:00Z",
  status: "reauth_required",
  has_token: false,
  last_success_at: null,
  last_error_code: "REAUTH_REQUIRED",
  next_sync_at: null,
  sync_requested_at: null,
  created_at: "2026-09-18T10:00:00Z",
  updated_at: "2026-09-21T09:00:00Z",
};

describe("ConnectionsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAppConfig).mockResolvedValue({
      demo_mode: false,
      environment: "development",
      import_worker_role: "trusted_local",
      trusted_local: true,
      desktop_oauth_available: false,
    });
  });

  it("renders empty state when no connections configured", async () => {
    vi.mocked(api.getConnections).mockResolvedValue([]);
    render(<ConnectionsTab />);

    expect(await screen.findByText(/Brak skonfigurowanych połączeń/i)).toBeInTheDocument();
  });

  it("renders active connection with health status and data scope info", async () => {
    vi.mocked(api.getConnections).mockResolvedValue([mockActiveConnection]);
    render(<ConnectionsTab />);

    // Provider; account identifier is intentionally not exposed in the UI.
    expect(await screen.findByText("Lidl Plus")).toBeInTheDocument();

    // Health badge
    expect(screen.getByText("Aktywne")).toBeInTheDocument();

    // Data scope section
    expect(screen.getByText(/Zakres danych/i)).toBeInTheDocument();

    // Disclaimer
    expect(screen.getAllByText(/Konektory sklepowe są funkcją eksperymentalną/i).length).toBeGreaterThan(0);
  });

  it("triggers sync now and shows pending state", async () => {
    vi.mocked(api.getConnections).mockResolvedValue([mockActiveConnection]);
    vi.mocked(api.syncNowConnection).mockResolvedValue({
      connection_id: 1,
      status: "active",
      sync_requested_at: "2026-09-21T10:00:00Z",
      message: "Sync request queued",
    });

    render(<ConnectionsTab />);

    const syncButton = await screen.findByRole("button", { name: /Synchronizuj teraz/i });
    fireEvent.click(syncButton);

    await waitFor(() => {
      expect(api.syncNowConnection).toHaveBeenCalledWith(1);
    });
  });

  it("requires explicit confirmation before disconnect", async () => {
    vi.mocked(api.getConnections).mockResolvedValue([mockActiveConnection]);
    vi.mocked(api.disconnectConnection).mockResolvedValue({
      connection_id: 1,
      status: "disconnected",
      revocation_status: "provider_revocation_unavailable",
      message: "Disconnected",
    });

    render(<ConnectionsTab />);

    const disconnectBtn = await screen.findByRole("button", { name: /Odłącz konto/i });
    fireEvent.click(disconnectBtn);

    // Verify confirmation dialog title is displayed
    expect(await screen.findByText(/Odłączyć konto sklepu\?/i)).toBeInTheDocument();

    // Click confirm in dialog
    const confirmBtn = screen.getByRole("button", { name: /^Odłącz konto$/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(api.disconnectConnection).toHaveBeenCalledWith(1);
    });
  });

  it("renders reauth_required status and triggers reconnect", async () => {
    vi.mocked(api.getConnections).mockResolvedValue([mockReauthConnection]);
    vi.mocked(api.reconnectConnection).mockResolvedValue({
      ...mockReauthConnection,
      status: "reauth_required",
    });

    render(<ConnectionsTab />);

    expect(await screen.findByText("Wymagana reautoryzacja")).toBeInTheDocument();
    expect(screen.getByText("REAUTH_REQUIRED")).toBeInTheDocument();

    const reconnectBtn = screen.getByRole("button", { name: /Połącz ponownie/i });
    fireEvent.click(reconnectBtn);

    await waitFor(() => {
      expect(api.reconnectConnection).toHaveBeenCalledWith(2);
    });
  });

it("selects a store without accepting a free-text provider", async () => {
  vi.mocked(api.getConnections).mockResolvedValue([]);
  vi.mocked(api.createConnection).mockResolvedValue(mockReauthConnection);
  render(<ConnectionsTab />);
  fireEvent.click(await screen.findByRole("button", { name: /Dodaj połączenie sklepu/i }));
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.getByRole("radio", { name: "Lidl Plus" })).toBeChecked();
  fireEvent.click(screen.getByRole("radio", { name: "Biedronka" }));
  expect(screen.getByText(/Zapisanie wyboru doda oczekujące połączenie/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Zapisz wybór" }));
  await waitFor(() => expect(api.createConnection).toHaveBeenCalledWith({ provider: "biedronka" }));
});

it("prevents adding an existing provider and selects the remaining store", async () => {
  vi.mocked(api.getConnections).mockResolvedValue([mockActiveConnection]);
  render(<ConnectionsTab />);
  await screen.findByText("Lidl Plus");
  fireEvent.click(screen.getByRole("button", { name: /Dodaj połączenie sklepu/i }));
  expect(screen.getByRole("radio", { name: /Lidl Plus/ })).toBeDisabled();
  expect(screen.getByRole("radio", { name: "Biedronka" })).toBeChecked();
});

it("offers 1-click desktop OAuth login without manual callback copying when available", async () => {
  vi.mocked(api.getAppConfig).mockResolvedValue({
    demo_mode: false,
    environment: "development",
    import_worker_role: "trusted_local",
    trusted_local: true,
    desktop_oauth_available: true,
  });
  vi.mocked(api.getConnections).mockResolvedValue([
    { ...mockReauthConnection, id: 7, provider: "lidl" },
  ]);
  vi.mocked(api.desktopLoginConnectionOAuth).mockResolvedValue({
    ...mockActiveConnection,
    id: 7,
  });

  render(<ConnectionsTab />);
  const authorizeBtn = await screen.findByRole("button", { name: /Zaloguj z Lidl Plus/i });
  fireEvent.click(authorizeBtn);

  const desktopBtn = await screen.findByRole("button", { name: /Zaloguj w oknie desktopowym/i });
  fireEvent.click(desktopBtn);

  await waitFor(() => {
    expect(api.desktopLoginConnectionOAuth).toHaveBeenCalledWith(7);
  });
});

it("shows privacy boundary notice and disables authorization/sync on central VPS", async () => {
  vi.mocked(api.getAppConfig).mockResolvedValue({
    demo_mode: false,
    environment: "production",
    import_worker_role: "central_vps",
    trusted_local: false,
    desktop_oauth_available: false,
  });
  vi.mocked(api.getConnections).mockResolvedValue([
    mockActiveConnection,
    { ...mockReauthConnection, id: 9, provider: "lidl" },
  ]);

  render(<ConnectionsTab />);
  expect(await screen.findByText(/Ograniczenie prywatności/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Zaloguj z Lidl Plus/i })).toBeDisabled();
  for (const syncBtn of screen.getAllByRole("button", { name: /Synchronizuj teraz/i })) {
    expect(syncBtn).toBeDisabled();
  }
});

it("fails closed (buttons disabled, no false central-VPS banner) while appConfig is loading", async () => {
  vi.mocked(api.getAppConfig).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.getConnections).mockResolvedValue([
    mockActiveConnection,
    { ...mockReauthConnection, id: 11, provider: "lidl" },
  ]);

  render(<ConnectionsTab />);
  expect((await screen.findAllByText("Lidl Plus")).length).toBeGreaterThan(0);
  expect(screen.queryByText(/Ograniczenie prywatności/i)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Zaloguj z Lidl Plus/i })).toBeDisabled();
  for (const syncBtn of screen.getAllByRole("button", { name: /Synchronizuj teraz/i })) {
    expect(syncBtn).toBeDisabled();
  }
});
});
