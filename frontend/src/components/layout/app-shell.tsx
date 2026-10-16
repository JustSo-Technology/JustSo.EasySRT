import type { PropsWithChildren } from "react";

import { LogOut, Shield } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { User } from "@/lib/api";

export type AppTab = "control" | "config" | "diagnostics";

const TABS: { id: AppTab; label: string }[] = [
  { id: "control", label: "Control" },
  { id: "config", label: "Configuration" },
  { id: "diagnostics", label: "Diagnostics" },
];

export function AppShell({
  user,
  hostname,
  onLogout,
  onOpenAdmin,
  updateNotice,
  onOpenUpdates,
  activeTab,
  onTabChange,
  children,
}: PropsWithChildren<{
  user: User;
  hostname?: string;
  onLogout: () => void;
  onOpenAdmin?: () => void;
  updateNotice?: { label: string; tone: "available" | "running" | "failed" };
  onOpenUpdates?: () => void;
  activeTab: AppTab;
  onTabChange: (tab: AppTab) => void;
}>) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1280px] flex-col px-5 py-5 sm:px-7 sm:py-7">
      <header className="glass-panel float-in mb-5 rounded-[28px] p-5 sm:p-6">
        <div className="flex flex-col gap-8">
          <div className="flex items-start justify-between gap-6">
            <div className="min-w-0">
              <div className="inline-flex items-center gap-2.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-slate-100">
                <span className="h-2 w-2 shrink-0 rounded-full bg-[var(--accent-strong)] shadow-[0_0_14px_rgba(133,221,198,0.65)]" />
                EasySRT Control Plane{hostname ? ` - ${hostname}` : ""}
              </div>
              <p className="mt-1 ml-[5px] text-base font-semibold text-white">{user.username}</p>
            </div>
            <div className="flex shrink-0 items-center gap-5">
              {user.role === "owner" && updateNotice && onOpenUpdates ? (
                <Button
                  className={
                    updateNotice.tone === "available"
                      ? "gap-2 bg-[linear-gradient(135deg,#f5bd78,#d98b5c)] text-slate-950"
                      : updateNotice.tone === "failed"
                        ? "gap-2 bg-[linear-gradient(135deg,#fca5a5,#fb7185)] text-slate-950"
                        : "gap-2 bg-[linear-gradient(135deg,#9cd7ff,#6ea2dc)] text-slate-950"
                  }
                  onClick={onOpenUpdates}
                >
                  {updateNotice.label}
                </Button>
              ) : null}
              {user.role === "owner" && onOpenAdmin ? (
                <Button className="gap-2 bg-[linear-gradient(135deg,#9cd7ff,#6ea2dc)] text-slate-950" onClick={onOpenAdmin}>
                  <Shield size={15} />
                  Admin
                </Button>
              ) : null}
              <Button className="gap-2" onClick={onLogout}>
                <LogOut size={15} />
                Logout
              </Button>
            </div>
          </div>
          <div className="flex min-h-[170px] items-center justify-center sm:min-h-[210px]">
            <img
              src="/easysrt-logo-cropped.png"
              alt="JustSo EasySRT"
              className="max-h-[150px] w-auto object-contain sm:max-h-[190px]"
            />
          </div>
        </div>
      </header>

      <nav className="float-in mb-6 flex gap-1.5 rounded-[20px] border border-[rgba(133,221,198,0.21)] bg-[linear-gradient(126deg,rgba(15,41,34,0.13),rgba(225,249,243,0.06))] p-1.5">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={cn(
              "flex-1 rounded-[14px] px-4 py-2.5 text-sm font-medium transition-all duration-150",
              activeTab === tab.id
                ? "bg-[linear-gradient(90deg,#85ddc6,#6fbaa8)] text-slate-950 shadow-[0_0_30px_20px_rgba(111,186,168,0.18)]"
                : "text-slate-400 hover:text-white",
            )}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main className="flex-1">{children}</main>
      <footer className="mt-6 flex flex-wrap justify-center gap-3 text-xs text-slate-500">
        <span>Copyright © 2026 JUST SO GROUP PTY LTD</span>
        <a
          className="text-slate-400 underline decoration-white/20 underline-offset-4 hover:text-white"
          href="https://github.com/JustSo-Technology/JustSo.EasySRT"
          rel="noreferrer"
          target="_blank"
        >
          Source and AGPL licence
        </a>
      </footer>
    </div>
  );
}
