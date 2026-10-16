import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none ring-0 placeholder:text-slate-500 transition focus:border-[var(--accent)] focus:bg-black/30",
        className,
      )}
      {...props}
    />
  );
}
