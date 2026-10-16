import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Button({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-full border border-[rgba(111,186,168,0.22)] bg-[linear-gradient(135deg,#85ddc6,#6fbaa8)] px-5 py-2.5 text-sm font-semibold text-slate-950 shadow-[0_10px_35px_rgba(133,221,198,0.22)] transition duration-200 hover:translate-y-[-1px] hover:shadow-[0_12px_40px_rgba(133,221,198,0.3)] disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
