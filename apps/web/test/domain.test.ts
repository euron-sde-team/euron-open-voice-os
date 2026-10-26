import { describe, expect, it } from "vitest";

import { explain } from "@/features/talk/use-voice-session";
import { ApiError } from "@/lib/api/errors";
import { ADAPTERS_BY_STAGE, adapterLabel, costStatus, endReason, jobChip, languageLabel, stageLabel } from "@/lib/chips";
import { GLOSSARY } from "@/lib/glossary";
import { activeNavItem, isActive, NAV_ITEMS } from "@/lib/nav";
import { canManageUsers, canWrite, isRole, roleLabel } from "@/lib/roles";
import { apiBase, browserSnippet, pythonSnippet, startSessionSnippet, websocketSnippet } from "@/lib/snippets";

describe("chips", () => {
  it("labels how a session ended, with a tone and a reason", () => {
    expect(endReason("agent_ended").label).toBe("Agent ended");
    expect(endReason("error").tone).toBe("danger");
    expect(endReason("idle_timeout").hint).toMatch(/idle timeout/);
    expect(endReason("something_new")).toEqual({ label: "something_new", tone: "neutral", hint: "something_new" });
  });

  it("never presents a missing cost as zero", () => {
    expect(costStatus("not_reported").label).toBe("Not reported");
    expect(costStatus("self_hosted").hint).toMatch(/no per-call price/);
    expect(costStatus("partial").tone).toBe("warning");
  });

  it("labels benchmark states, adapters, stages and languages", () => {
    expect(jobChip("failed").tone).toBe("danger");
    expect(jobChip("succeeded").label).toBe("Done");
    expect(adapterLabel("openai_compatible")).toBe("OpenAI-compatible");
    expect(stageLabel("tts")).toBe("Text to speech");
    expect(languageLabel("hi-IN")).toBe("Hindi");
    expect(languageLabel("xx")).toBe("xx");
  });

  it("offers only adapters that support each stage", () => {
    expect(ADAPTERS_BY_STAGE.llm).not.toContain("deepgram");
    expect(ADAPTERS_BY_STAGE.stt).toContain("sarvam");
    for (const stage of ["stt", "llm", "tts"]) expect(ADAPTERS_BY_STAGE[stage]).toContain("openai_compatible");
  });
});

describe("glossary", () => {
  it("explains every metric in plain words without dashes", () => {
    for (const text of Object.values(GLOSSARY)) {
      expect(text.length).toBeGreaterThan(40);
      expect(text).not.toMatch(/[–—]/);
    }
  });
});

describe("navigation", () => {
  it("matches nested paths to their section and the root exactly", () => {
    expect(activeNavItem("/")?.label).toBe("Overview");
    expect(activeNavItem("/agents/123")?.label).toBe("Agents");
    expect(activeNavItem("/sessions/")?.label).toBe("Sessions");
    const overview = NAV_ITEMS.find((i) => i.href === "/");
    expect(overview && isActive(overview, "/sessions")).toBe(false);
  });
});

describe("roles", () => {
  it("separates reading, writing and managing users", () => {
    expect(isRole("admin")).toBe(true);
    expect(isRole("root")).toBe(false);
    expect(canWrite("viewer")).toBe(false);
    expect(canWrite("admin")).toBe(true);
    expect(canManageUsers("admin")).toBe(false);
    expect(roleLabel("owner")).toBe("Owner");
  });
});

describe("snippets", () => {
  it("start a session with the key and agent on the server", () => {
    expect(apiBase("http://localhost:4510/")).toBe("http://localhost:4510");
    const curl = startSessionSnippet("http://h", "vos_x", "agent-1");
    expect(curl).toContain("http://h/v1/sessions");
    expect(curl).toContain("Bearer vos_x");
    expect(curl).toContain('"agent_id": "agent-1"');
    expect(pythonSnippet("http://h", "vos_x", "agent-1")).toContain('ticket["disclosure"]["message"]');
  });

  it("connect the browser the way the Pipecat client expects", () => {
    expect(browserSnippet()).toContain("webrtcRequestParams: { endpoint: ticket.offer_url }");
    expect(browserSnippet()).toContain("ticket.ice_url");
    expect(websocketSnippet()).toContain("wsUrl: ticket.websocket_url");
  });
});

describe("explain", () => {
  it("turns browser and transport failures into a next step", () => {
    expect(explain({ name: "NotAllowedError", message: "Permission denied" })).toMatch(/Allow the microphone/);
    expect(explain({ name: "NotFoundError", message: "" })).toMatch(/No microphone/);
    expect(explain(new Error("WebRTC timed out"))).toMatch(/timed out/);
    expect(explain(new Error("503 busy"))).toMatch(/busy/);
    expect(explain(new ApiError({ status: 404, code: "not_found", message: "Agent not found" }))).toBe("Agent not found");
    expect(explain(null)).toMatch(/failed/);
  });
});
