import { describe, expect, it } from "vitest";

import { expiryFromDate, parseOrigins } from "@/features/keys/components/create-key-dialog";
import { loginUrl, safeNext } from "@/lib/auth-redirect";

describe("safeNext", () => {
  it("keeps same-origin paths with their query and hash", () => {
    expect(safeNext("/sessions?session=12#turns")).toBe("/sessions?session=12#turns");
    expect(safeNext("/keys")).toBe("/keys");
  });

  it("refuses anything that would leave the origin", () => {
    for (const evil of ["//evil.example", "/\\evil.example", "/\t/evil.example", "https://evil.example", "javascript:alert(1)", "/%5Cevil.example"]) {
      const out = safeNext(evil);
      expect(new URL(out, "http://dashboard.local").origin).toBe("http://dashboard.local");
    }
  });

  it("never loops back to the login page", () => {
    expect(safeNext("/login?next=/x")).toBe("/");
    expect(safeNext(null)).toBe("/");
    expect(safeNext("")).toBe("/");
  });

  it("builds a login URL that returns to where the person was", () => {
    expect(loginUrl("/sessions", "?session=3")).toBe("/login?next=%2Fsessions%3Fsession%3D3");
    expect(loginUrl("/", "", "expired")).toBe("/login?reason=expired");
  });
});

describe("expiryFromDate", () => {
  it("keeps a key valid through the whole chosen day (UTC)", () => {
    expect(expiryFromDate("2026-12-31")).toBe("2026-12-31T23:59:59.000Z");
  });

  it("treats empty or invalid input as no expiry", () => {
    expect(expiryFromDate("")).toBeNull();
    expect(expiryFromDate("not-a-date")).toBeNull();
  });
});

describe("parseOrigins", () => {
  it("accepts one origin per line or comma, without trailing slashes or repeats", () => {
    expect(parseOrigins("https://app.example.com/\nhttp://localhost:4510, https://app.example.com")).toEqual({
      origins: ["https://app.example.com", "http://localhost:4510"],
      invalid: [],
    });
    expect(parseOrigins("   ")).toEqual({ origins: [], invalid: [] });
  });

  it("flags anything that is not scheme and host", () => {
    expect(parseOrigins("https://app.example.com/path ftp://x.example").invalid).toEqual(["https://app.example.com/path", "ftp://x.example"]);
  });
});
