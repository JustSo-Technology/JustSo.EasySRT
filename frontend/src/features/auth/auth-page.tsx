import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export function AuthPage({
  hasOwner,
  onLogin,
  onBootstrap,
}: {
  hasOwner: boolean;
  onLogin: (username: string, password: string) => Promise<void>;
  onBootstrap: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(mode: "login" | "bootstrap") {
    try {
      setError(null);
      if (mode === "login") {
        await onLogin(username, password);
      } else {
        await onBootstrap(username, password);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    }
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1280px] items-center px-5 sm:px-7">
      <div className="mx-auto flex w-full max-w-[980px] flex-col justify-center gap-6 py-0">
        <section className="float-in flex w-full items-center justify-center px-6 py-0">
          <img
            src="/easysrt-logo.png"
            alt="JustSo EasySRT"
            className="h-auto w-full max-w-[420px] drop-shadow-[0_18px_52px_rgba(111,186,168,0.24)] sm:max-w-[500px]"
          />
        </section>
        <Card
          className="float-in w-full max-w-xl self-center space-y-6 px-7 pt-[33px] pb-[33px] sm:px-8"
          style={{
            border: "1px solid rgba(255, 255, 255, 0.23)",
            background: "linear-gradient(90deg, rgba(24, 52, 49, 0.23) 0%, rgba(0, 0, 0, 0.04) 100%)",
          }}
        >
          <div>
            <p className="section-label">{hasOwner ? "Session Login" : "Admin Setup"}</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">
              {hasOwner ? "Sign in to the controller" : "Create the initial admin account"}
            </h2>
          </div>
          <div className="space-y-4">
            <Field label="Username">
              <Input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="owner" />
            </Field>
            <Field label="Password">
              <Input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter a strong password"
              />
            </Field>
          </div>
          <div className="rounded-[22px] border border-white/10 bg-black/20 p-4 text-sm text-slate-300">
            This control plane should only be accessible from trusted networks.
          </div>
          {error ? <p className="rounded-2xl border border-rose-300/20 bg-rose-300/10 px-4 py-3 text-sm text-rose-200">{error}</p> : null}
          <Button className="w-full justify-center" onClick={() => handleSubmit(hasOwner ? "login" : "bootstrap")}>
            {hasOwner ? "Sign in" : "Create admin account"}
          </Button>
        </Card>
      </div>
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
