"use client";

import { useId } from "react";

import { cn } from "@/lib/cn";

/** The VoiceOS mark: a short waveform, louder in the middle, inside the brand tile. */
export function VoiceMark({ className }: { className?: string }) {
  // A unique gradient id per instance: when the first SVG defining a shared id sits in a
  // hidden subtree (the collapsed sidebar on phones), browsers resolve the fill to nothing.
  const gradient = `vos-mark-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-7 shrink-0", className)}>
      <defs>
        <linearGradient id={gradient} x1="4" y1="3" x2="28" y2="29" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--stage-stt)" />
          <stop offset="1" stopColor="var(--primary)" />
        </linearGradient>
      </defs>
      <rect x="2.5" y="2.5" width="27" height="27" rx="8" fill={`url(#${gradient})`} />
      <rect x="7.5" y="13.5" width="2.6" height="5" rx="1.3" fill="white" fillOpacity="0.65" />
      <rect x="11.8" y="10" width="2.6" height="12" rx="1.3" fill="white" fillOpacity="0.85" />
      <rect x="16.1" y="7.5" width="2.6" height="17" rx="1.3" fill="white" />
      <rect x="20.4" y="11" width="2.6" height="10" rx="1.3" fill="white" fillOpacity="0.85" />
      <rect x="24.7" y="14" width="2.6" height="4" rx="1.3" fill="white" fillOpacity="0.65" />
    </svg>
  );
}

export function VoiceLogo({ className, collapsed = false }: { className?: string; collapsed?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <VoiceMark />
      {!collapsed && <span className="text-[15px] font-semibold tracking-[-0.02em] text-foreground">VoiceOS</span>}
    </span>
  );
}
