"use client";

import { Chip } from "@/components/ui/chip";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { costStatus, endReason, jobChip, type ChipSpec } from "@/lib/chips";

export function SpecChip({ spec, withHint = true, dot = true }: { spec: ChipSpec; withHint?: boolean; dot?: boolean }) {
  const chip = (
    <Chip tone={spec.tone} dot={dot}>
      {spec.label}
    </Chip>
  );
  if (!withHint || !spec.hint) return chip;
  return (
    <Tooltip>
      <TooltipTrigger render={<span tabIndex={0} className="inline-flex rounded-full focus-visible:outline-2 focus-visible:outline-ring" />}>
        {chip}
      </TooltipTrigger>
      <TooltipContent>{spec.hint}</TooltipContent>
    </Tooltip>
  );
}

export const JobChip = ({ value }: { value: string }) => <SpecChip spec={jobChip(value)} />;
export const EndChip = ({ value }: { value: string }) => <SpecChip spec={endReason(value)} />;
export const CostChip = ({ value }: { value: string }) => <SpecChip spec={costStatus(value)} dot={false} />;
