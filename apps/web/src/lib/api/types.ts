/**
 * Named aliases over the generated OpenAPI types (`pnpm gen:api`). Nothing here is
 * hand-written: every shape comes from `schema.d.ts`, which is generated from
 * docs/api/openapi.yaml.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type User = S["UserOut"];
export type UserCreate = S["UserCreate"];
export type UserUpdate = S["UserUpdate"];
export type SignIn = S["SignInOut"];
export type ApiKey = S["KeyOut"];
export type ApiKeyCreated = S["KeyCreated"];
export type ApiKeyIn = S["KeyIn"];
export type ApiKeyUpdate = S["KeyUpdate"];
export type Provider = S["ProviderOut"];
export type ProviderIn = S["ProviderIn"];
export type ProviderUpdate = S["ProviderUpdate"];
export type ProviderTest = S["ProviderTest"];
export type Price = S["Price"];
export type Agent = S["AgentOut"];
export type AgentIn = S["AgentIn"];
export type AgentUpdate = S["AgentUpdate"];
export type AgentTemplate = S["TemplateOut"];
export type TurnSettings = S["TurnSettings"];
export type PrivacySettings = S["PrivacySettings"];
export type CacheSettings = S["CacheSettings"];
export type ToolSpec = S["ToolSpec"];
export type VoiceSession = S["SessionOut"];
export type VoiceSessionDetail = S["SessionDetail"];
export type Turn = S["TurnOut"];
export type SessionTicket = S["SessionTicket"];
export type Disclosure = S["Disclosure"];
export type Overview = S["Overview"];
export type Point = S["Point"];
export type AgentBreakdown = S["AgentBreakdown"];
export type StageLatency = S["StageLatency"];
export type Benchmark = S["BenchmarkOut"];
export type AuditEntry = S["AuditOut"];
export type SystemInfo = S["SystemInfo"];

export type Role = NonNullable<UserCreate["role"]>;
export type Stage = ProviderIn["stage"];
export type Adapter = ProviderIn["adapter"];
export type ToolName = ToolSpec["name"];
