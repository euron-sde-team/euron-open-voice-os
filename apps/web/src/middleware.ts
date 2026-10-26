import { NextResponse, type NextRequest } from "next/server";

const prod = process.env.NODE_ENV === "production";

/** The voice runtime's origin as http(s) and ws(s), from RUNTIME_PUBLIC_URL; none if unset. */
function runtimeOrigins(): string[] {
  const raw = process.env.RUNTIME_PUBLIC_URL;
  if (!raw) return [];
  try {
    const url = new URL(raw);
    const ws = url.protocol === "https:" ? "wss:" : "ws:";
    return [url.origin, `${ws}//${url.host}`];
  } catch {
    return [];
  }
}

/**
 * Next inlines its bootstrap scripts and styles, so those need 'unsafe-inline'; the dev
 * server also needs 'unsafe-eval' for fast refresh. The voice client records and plays
 * audio in AudioWorklets it creates from blob: URLs, which only this origin's code can
 * mint. Everything loads from this origin; the only other place the browser may connect
 * to is the voice runtime (WebRTC offer, ICE servers and the WebSocket fallback).
 */
function contentSecurityPolicy(): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline' blob:${prod ? "" : " 'unsafe-eval'"}`,
    "worker-src 'self' blob:",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    ["connect-src 'self'", ...runtimeOrigins(), ...(prod ? [] : ["ws:"])].join(" "),
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");
}

/**
 * Sets the Content-Security-Policy on every page, and sends signed-out visitors straight
 * to /login instead of flashing the dashboard shell. The cookie is only checked for
 * presence here; the API validates it on every call and the client redirects on any 401.
 */
export function middleware(req: NextRequest) {
  const hasSession = req.cookies.has("vos_session");
  const { pathname, search } = req.nextUrl;
  let res: NextResponse;
  if (!hasSession && pathname !== "/login") {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    if (pathname !== "/") url.searchParams.set("next", `${pathname}${search}`);
    res = NextResponse.redirect(url);
  } else {
    res = NextResponse.next();
  }
  res.headers.set("Content-Security-Policy", contentSecurityPolicy());
  return res;
}

export const config = {
  // Everything except the proxied API surfaces, Next internals and static files.
  matcher: ["/((?!api/|v1/|health|readyz|docs|openapi\\.json|_next/|favicon|icon|.*\\.(?:svg|png|jpg|ico|webp|txt)$).*)"],
};
