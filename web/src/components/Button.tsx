/**
 * Button or link with the design's variants. Renders a Next <Link> when
 * `href` is given, otherwise a <button type="button"> (pass type="submit" for forms).
 *
 *   primary       white pill (landing CTAs)            sizes sm 44 · md 56 · lg 58
 *   amber         filled amber, 10px radius ("Open chart", "Ask")
 *   outline       1px line-3 border ("Ask about MU", "Regenerate")
 *   outlineAmber  amber border + text ("Arm alert on zones")
 *   text          amber text link ("Open portfolio →")
 *
 * Icon-only buttons must pass aria-label.
 */
import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cx } from "@/lib/cx";

export type ButtonVariant = "primary" | "amber" | "outline" | "outlineAmber" | "text";
export type ButtonSize = "sm" | "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-2.5 whitespace-nowrap font-sans transition-colors disabled:cursor-not-allowed disabled:opacity-50";

const variants: Record<ButtonVariant, string> = {
  primary: "rounded-full bg-white font-semibold text-ground hover:bg-[#E6E9ED]",
  amber: "rounded-control bg-amber font-semibold text-on-amber hover:bg-amber-hover",
  outline: "rounded-control border border-line-3 bg-transparent font-medium text-text-2 hover:bg-raised",
  outlineAmber: "rounded-control border border-amber bg-transparent font-medium text-amber hover:bg-amber/10",
  text: "font-medium text-amber hover:text-amber-hover",
};

const sizes: Record<ButtonVariant, Record<ButtonSize, string>> = {
  primary: { sm: "h-11 px-[22px] text-[15px]", md: "h-14 px-[30px] text-[17px]", lg: "h-[58px] px-8 text-lg" },
  amber: { sm: "h-8 px-3 text-xs", md: "h-11 px-[18px] text-sm", lg: "h-12 px-6 text-[15px]" },
  outline: { sm: "h-8 px-3 text-xs", md: "h-11 px-[18px] text-sm", lg: "h-12 px-6 text-[15px]" },
  outlineAmber: { sm: "h-[38px] rounded-[9px] px-3.5 text-[13px]", md: "h-11 px-[18px] text-sm", lg: "h-12 px-6 text-[15px]" },
  text: { sm: "text-xs", md: "text-[13px]", lg: "text-sm" },
};

type Common = { variant?: ButtonVariant; size?: ButtonSize; className?: string; children: ReactNode };
type LinkRest = { href: string } & Omit<ComponentPropsWithoutRef<typeof Link>, "href" | "className" | "children">;
type ButtonRest = { href?: undefined } & Omit<ComponentPropsWithoutRef<"button">, "className" | "children">;

export function Button({ variant = "outline", size = "md", className, children, ...rest }: Common & (LinkRest | ButtonRest)) {
  const cls = cx(base, variants[variant], sizes[variant][size], className);
  if (rest.href !== undefined) {
    return (
      <Link {...(rest as LinkRest)} className={cls}>
        {children}
      </Link>
    );
  }
  const { type = "button", ...buttonProps } = rest as ButtonRest;
  return (
    <button type={type} {...buttonProps} className={cls}>
      {children}
    </button>
  );
}
