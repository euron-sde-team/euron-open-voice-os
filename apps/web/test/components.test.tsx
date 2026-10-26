// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { GaugeIcon } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";

import { EmptyState } from "@/components/empty-state";
import { KpiTile } from "@/components/kpi-tile";
import { TurnWaterfall } from "@/features/sessions/components/turn-waterfall";
import type { Turn } from "@/lib/api/types";

afterEach(cleanup);

describe("KpiTile", () => {
  it("shows the value and marks a slower response as bad", () => {
    render(<KpiTile label="Response" icon={GaugeIcon} value="135" current={135} previous={100} goodWhen="down" comparison="vs prior 30d" />);
    expect(screen.getByText("135")).toBeInTheDocument();
    const chip = screen.getByText("+35%");
    expect(chip.className).toMatch(/warning/);
  });

  it("marks rising cache savings as good", () => {
    render(<KpiTile label="Saved by caches" icon={GaugeIcon} value="27.1%" current={27.1} previous={24.2} goodWhen="up" comparison="vs prior 30d" />);
    expect(screen.getByText("+12%").className).toMatch(/savings/);
  });

  it("says New when there is no previous period", () => {
    render(<KpiTile label="Sessions" icon={GaugeIcon} value="12" current={12} previous={0} comparison="vs prior 30d" />);
    expect(screen.getByText("New")).toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    const { container } = render(<KpiTile label="Cost" icon={GaugeIcon} value="$1" current={1} previous={1} comparison="x" loading />);
    expect(screen.queryByText("$1")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[data-slot='skeleton'], .animate-pulse").length).toBeGreaterThan(0);
  });
});

describe("EmptyState", () => {
  it("always explains itself and offers an action", () => {
    render(
      <EmptyState
        icon={GaugeIcon}
        title="No sessions yet"
        description="Each conversation appears here as soon as it ends."
        action={<button type="button">Talk to an agent</button>}
      />,
    );
    expect(screen.getByText("No sessions yet")).toBeInTheDocument();
    expect(screen.getByText(/as soon as it ends/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Talk to an agent" })).toBeInTheDocument();
  });
});

describe("TurnWaterfall", () => {
  const turn = (extra: Partial<Turn>): Turn =>
    ({
      index: 0,
      started_at: "2026-10-26T10:00:00Z",
      user_text: "hello",
      agent_text: "hi",
      response_ms: 1000,
      endpoint_ms: 200,
      stt_ms: 300,
      llm_first_token_ms: 400,
      tts_first_audio_ms: 250,
      interrupted: false,
      ...extra,
    }) as Turn;

  it("draws each stage in sequence with what is left as transport", () => {
    render(<TurnWaterfall turn={turn({})} scaleMs={2000} />);
    const bar = screen.getByRole("img", { name: /Response/ });
    expect(bar.querySelector('[title^="End of turn"]')).toHaveStyle({ width: "10%" });
    expect(bar.querySelector('[title^="LLM first token"]')).toHaveStyle({ width: "20%" });
    expect(bar.querySelector('[title^="Transport and playout"]')).toHaveStyle({ width: "7.5%" });
    expect(screen.getByTitle(/Speech to text \(in parallel\)/)).toHaveStyle({ width: "15%" });
  });

  it("draws nothing for a turn that was never answered", () => {
    const { container } = render(<TurnWaterfall turn={turn({ response_ms: null })} scaleMs={1000} />);
    expect(container).toBeEmptyDOMElement();
  });
});
