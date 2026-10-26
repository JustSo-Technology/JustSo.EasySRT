import { useMemo, useState, type ReactNode } from "react";

import { Shield, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiTokensPanel } from "./api-tokens-panel";
import { cn } from "@/lib/utils";
import type { User, UserRole } from "@/lib/api";

const ROLE_OPTIONS: Array<{ value: UserRole; label: string; description: string }> = [
  { value: "owner", label: "Owner", description: "Full access, including user management and system control." },
  { value: "engineer", label: "Engineer", description: "Operational access for diagnostics, config, and service control." },
  { value: "operator", label: "Operator", description: "Day-to-day control surface access without admin rights." },
];

export function AdminModal({
  currentUser,
  users,
  isLoading,
  isSaving,
  error,
  onClose,
  onCreateUser,
  onUpdateUser,
}: {
  currentUser: User;
  users?: User[];
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;
  onClose: () => void;
  onCreateUser: (payload: { username: string; password: string; role: UserRole }) => Promise<void>;
  onUpdateUser: (userId: string, payload: { role?: UserRole; disabled?: boolean }) => Promise<void>;
}) {
  const [showTokens, setShowTokens] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("operator");
  const [formError, setFormError] = useState<string | null>(null);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);

  const sortedUsers = useMemo(
    () =>
      [...(users ?? [])].sort((left, right) => {
        if (left.role !== right.role) {
          return left.role.localeCompare(right.role);
        }
        return left.username.localeCompare(right.username);
      }),
    [users],
  );

  async function handleCreateUser() {
    setFormError(null);
    try {
      await onCreateUser({ username: newUsername, password: newPassword, role: newRole });
      setNewUsername("");
      setNewPassword("");
      setNewRole("operator");
    } catch (createError) {
      setFormError(createError instanceof Error ? createError.message : "Unable to create user");
    }
  }

  async function handleUpdateUser(userId: string, payload: { role?: UserRole; disabled?: boolean }) {
    setBusyUserId(userId);
    try {
      await onUpdateUser(userId, payload);
    } finally {
      setBusyUserId(null);
    }
  }

  if (showTokens) return <ApiTokensPanel users={users ?? []} currentUser={currentUser} onClose={() => setShowTokens(false)} />;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[rgba(2,7,12,0.54)] px-4 py-4 backdrop-blur-[10px] sm:items-center sm:px-7 sm:py-6">
      <div className="absolute inset-0" onClick={onClose} />
      <Card className="float-in relative z-10 w-full max-w-5xl overflow-hidden rounded-[32px] border border-white/15 p-0 shadow-[0_24px_90px_rgba(0,0,0,0.42)]">
        <div className="grid max-h-[88vh] gap-0 overflow-y-auto lg:grid-cols-[0.92fr_1.28fr]">
          <section className="border-b border-white/10 bg-[linear-gradient(160deg,rgba(8,24,31,0.96),rgba(5,12,18,0.92))] p-5 sm:p-7 lg:border-r lg:border-b-0">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="section-label">Admin Access</p>
                <h2 className="mt-3 text-3xl font-semibold tracking-[-0.05em] text-white">User management</h2>
              </div>
              <Button className="px-4 py-2.5" onClick={onClose}>
                Close
              </Button>
            </div>

            <Button className="mt-6" onClick={() => setShowTokens(true)}>API tokens</Button>

            <div className="mt-8 rounded-[28px] border border-white/10 bg-black/20 p-5">
              <div className="flex items-center gap-3">
                <div className="rounded-full border border-cyan-300/20 bg-cyan-300/10 p-3 text-cyan-100">
                  <Shield size={18} />
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Owner Controls</p>
                  <p className="mt-1 text-sm text-slate-300">
                    Create accounts and assign initial passwords. Users should change their password after first login.
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-8 space-y-4">
              <div>
                <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Create User</p>
                <h3 className="mt-2 text-xl font-semibold text-white">Add a new user</h3>
              </div>
              <Field label="Username">
                <Input value={newUsername} onChange={(event) => setNewUsername(event.target.value)} placeholder="alex.engineering" />
              </Field>
              <Field label="Temporary Password">
                <Input
                  type="password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  placeholder="At least 12 characters"
                />
              </Field>
              <Field label="Role">
                <select
                  value={newRole}
                  onChange={(event) => setNewRole(event.target.value as UserRole)}
                  className="w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition focus:border-[var(--accent)]"
                >
                  {ROLE_OPTIONS.map((role) => (
                    <option key={role.value} value={role.value} className="bg-slate-950 text-white">
                      {role.label}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="rounded-[24px] border border-white/10 bg-black/20 p-4 text-sm text-slate-300">
                {ROLE_OPTIONS.find((role) => role.value === newRole)?.description}
              </div>
              {formError || error ? (
                <div className="rounded-[24px] border border-rose-300/20 bg-rose-300/10 px-4 py-3 text-sm whitespace-pre-line text-rose-100">
                  {formError ?? error}
                </div>
              ) : null}
              <Button className="w-full justify-center gap-2" disabled={isSaving} onClick={() => void handleCreateUser()}>
                <UserPlus size={16} />
                {isSaving ? "Creating user..." : "Create user"}
              </Button>
            </div>
          </section>

          <section className="bg-[linear-gradient(180deg,rgba(7,17,26,0.82),rgba(3,8,15,0.92))] p-5 sm:p-7">
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="section-label">Current Access</p>
                <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Roles and account state</h3>
              </div>
              <div className="text-right text-sm text-slate-400">
                <div>{sortedUsers.length} accounts</div>
                <div>{sortedUsers.filter((user) => !user.disabled).length} active</div>
              </div>
            </div>

            <div className="mt-6 space-y-3">
              {isLoading ? (
                <div className="rounded-[28px] border border-white/10 bg-black/20 px-5 py-6 text-sm text-slate-300">
                  Loading user access state.
                </div>
              ) : null}
              {!isLoading && sortedUsers.length === 0 ? (
                <div className="rounded-[28px] border border-white/10 bg-black/20 px-5 py-6 text-sm text-slate-300">
                  No users have been created yet.
                </div>
              ) : null}
              {sortedUsers.map((user) => {
                const isCurrentUser = user.id === currentUser.id;
                const isBusy = isSaving || busyUserId === user.id;
                return (
                  <article
                    key={user.id}
                    className={cn(
                      "rounded-[28px] border p-5 transition",
                      user.disabled ? "border-rose-300/15 bg-rose-300/5" : "border-white/10 bg-black/20",
                    )}
                  >
                    <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-lg font-semibold text-white">{user.username}</h4>
                          {isCurrentUser ? (
                            <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-cyan-100">
                              You
                            </span>
                          ) : null}
                          <span
                            className={cn(
                              "rounded-full border px-2.5 py-1 text-[11px] uppercase tracking-[0.18em]",
                              user.disabled
                                ? "border-rose-300/20 bg-rose-300/10 text-rose-100"
                                : "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
                            )}
                          >
                            {user.disabled ? "Disabled" : "Active"}
                          </span>
                        </div>
                        <p className="mt-2 text-sm text-slate-400">
                          {ROLE_OPTIONS.find((role) => role.value === user.role)?.description}
                        </p>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-[minmax(0,180px)_auto] sm:items-center">
                        <select
                          value={user.role}
                          disabled={isBusy || isCurrentUser}
                          onChange={(event) => void handleUpdateUser(user.id, { role: event.target.value as UserRole })}
                          className="w-full rounded-[16px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition focus:border-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {ROLE_OPTIONS.map((role) => (
                            <option key={role.value} value={role.value} className="bg-slate-950 text-white">
                              {role.label}
                            </option>
                          ))}
                        </select>
                        <Button
                          className={cn(
                            "justify-center",
                            user.disabled
                              ? "bg-[linear-gradient(135deg,#9cd7ff,#6ea2dc)] text-slate-950"
                              : "bg-[linear-gradient(135deg,#f5bd78,#d98b5c)] text-slate-950",
                          )}
                          disabled={isBusy || isCurrentUser}
                          onClick={() => void handleUpdateUser(user.id, { disabled: !user.disabled })}
                        >
                          {user.disabled ? "Enable account" : "Disable account"}
                        </Button>
                      </div>
                    </div>
                    {isCurrentUser ? (
                      <p className="mt-4 text-xs uppercase tracking-[0.18em] text-slate-500">
                        Your own owner access is locked in the UI to avoid accidental lockout.
                      </p>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="space-y-2.5">
      <span className="text-xs uppercase tracking-[0.24em] text-slate-400">{label}</span>
      {children}
    </label>
  );
}
