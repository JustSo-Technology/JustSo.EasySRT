import type { CSSProperties, PropsWithChildren } from "react";

import { cn } from "@/lib/utils";

export function Card({ className, children, style }: PropsWithChildren<{ className?: string; style?: CSSProperties }>) {
  return <section className={cn("glass-panel rounded-[30px] p-6 shadow-xl sm:p-7", className)} style={style}>{children}</section>;
}
