// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AuthPage } from "./auth-page";

afterEach(cleanup);

it("blocks missing or mismatched confirmation and submits matching setup passwords", async () => {
  const onBootstrap = vi.fn().mockResolvedValue(undefined);
  render(<AuthPage hasOwner={false} onLogin={vi.fn()} onBootstrap={onBootstrap} />);
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "owner" } });
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "test-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Create admin account" }));
  expect(onBootstrap).not.toHaveBeenCalled();
  expect(screen.getByRole("alert").textContent).toContain("matching passwords");
  fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "different-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Create admin account" }));
  expect(onBootstrap).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "test-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Create admin account" }));
  await waitFor(() => expect(onBootstrap).toHaveBeenCalledExactlyOnceWith("owner", "test-password"));
  expect(screen.queryByRole("alert")).toBeNull();
});

it("keeps normal login independent of confirmation", async () => {
  const onLogin = vi.fn().mockResolvedValue(undefined);
  render(<AuthPage hasOwner onLogin={onLogin} onBootstrap={vi.fn()} />);
  expect(screen.queryByLabelText("Confirm password")).toBeNull();
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "owner" } });
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "test-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(onLogin).toHaveBeenCalledExactlyOnceWith("owner", "test-password"));
});
