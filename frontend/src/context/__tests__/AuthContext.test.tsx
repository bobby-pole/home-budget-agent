import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { makeAuthResponse, makeUser } from "@/__mocks__/factories";

// Mock api and localStorage helpers
vi.mock("@/lib/api", () => ({
  api: {
    login: vi.fn(),
    register: vi.fn(),
  },
}));

vi.mock("@/lib/auth", () => ({
  getToken: vi.fn().mockReturnValue(null),
  setToken: vi.fn(),
  getStoredUser: vi.fn().mockReturnValue(null),
  setStoredUser: vi.fn(),
  clearAuth: vi.fn(),
}));

// Import after vi.mock (hoisting guarantees correct order)
const { api } = await import("@/lib/api");
const authHelpers = await import("@/lib/auth");

// Helper — test consumer component that exposes context state
// login/register catch errors to prevent unhandled rejections in event handlers
function TestConsumer() {
  const { user, login, register, logout } = useAuth();
  return (
    <div>
      <span data-testid="user-email">{user?.email ?? "brak"}</span>
      <button onClick={() => { login("a@b.com", "pass").catch(() => {}); }}>Login</button>
      <button onClick={() => { register("new@b.com", "pass").catch(() => {}); }}>Register</button>
      <button onClick={logout}>Logout</button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <AuthProvider>
      <TestConsumer />
    </AuthProvider>
  );
}

describe("AuthContext", () => {
  beforeEach(() => {
    vi.mocked(authHelpers.getStoredUser).mockReturnValue(null);
    vi.mocked(authHelpers.getToken).mockReturnValue(null);
  });

  describe("initial state", () => {
    it("user is null when no data in localStorage", () => {
      renderWithProvider();
      expect(screen.getByTestId("user-email").textContent).toBe("brak");
    });

    it("restores user from localStorage on initialization", () => {
      const user = makeUser({ email: "stored@example.com" });
      vi.mocked(authHelpers.getStoredUser).mockReturnValue(user);

      renderWithProvider();

      expect(screen.getByTestId("user-email").textContent).toBe(
        "stored@example.com"
      );
    });
  });

  describe("login", () => {
    it("updates user in context after successful login", async () => {
      const userEvent_ = userEvent.setup();
      const authResponse = makeAuthResponse({
        user: makeUser({ email: "a@b.com" }),
      });
      vi.mocked(api.login).mockResolvedValueOnce(authResponse);

      renderWithProvider();
      await userEvent_.click(screen.getByRole("button", { name: "Login" }));

      await waitFor(() => {
        expect(screen.getByTestId("user-email").textContent).toBe("a@b.com");
      });
    });

    it("calls setToken and setStoredUser after login", async () => {
      const userEvent_ = userEvent.setup();
      const authResponse = makeAuthResponse();
      vi.mocked(api.login).mockResolvedValueOnce(authResponse);

      renderWithProvider();
      await userEvent_.click(screen.getByRole("button", { name: "Login" }));

      await waitFor(() => {
        expect(authHelpers.setToken).toHaveBeenCalledWith("mock-jwt-token");
        expect(authHelpers.setStoredUser).toHaveBeenCalledWith(authResponse.user);
      });
    });

    it("user remains null when api.login fails", async () => {
      const userEvent_ = userEvent.setup();
      vi.mocked(api.login).mockRejectedValueOnce(new Error("Unauthorized"));

      renderWithProvider();
      await userEvent_.click(screen.getByRole("button", { name: "Login" }));

      // user should remain null after a failed login
      expect(screen.getByTestId("user-email").textContent).toBe("brak");
    });
  });

  describe("register", () => {
    it("updates user after registration", async () => {
      const userEvent_ = userEvent.setup();
      const authResponse = makeAuthResponse({
        user: makeUser({ email: "new@b.com" }),
      });
      vi.mocked(api.register).mockResolvedValueOnce(authResponse);

      renderWithProvider();
      await userEvent_.click(
        screen.getByRole("button", { name: "Register" })
      );

      await waitFor(() => {
        expect(screen.getByTestId("user-email").textContent).toBe("new@b.com");
      });
    });
  });

  describe("logout", () => {
    it("clears user from context", async () => {
      const userEvent_ = userEvent.setup();
      // Set a logged-in user
      vi.mocked(authHelpers.getStoredUser).mockReturnValue(makeUser());

      renderWithProvider();
      await userEvent_.click(screen.getByRole("button", { name: "Logout" }));

      expect(screen.getByTestId("user-email").textContent).toBe("brak");
    });

    it("calls clearAuth after logout", async () => {
      const userEvent_ = userEvent.setup();
      renderWithProvider();
      await userEvent_.click(screen.getByRole("button", { name: "Logout" }));

      expect(authHelpers.clearAuth).toHaveBeenCalledOnce();
    });
  });

  describe("useAuth hook", () => {
    it("throws error when used outside AuthProvider", () => {
      // Suppress console.error for this test
      const consoleSpy = vi
        .spyOn(console, "error")
        .mockImplementation(() => {});

      expect(() => render(<TestConsumer />)).toThrow(
        "useAuth must be used within AuthProvider"
      );

      consoleSpy.mockRestore();
    });
  });
});
