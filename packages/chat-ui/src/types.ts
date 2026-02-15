/**
 * All TypeScript interfaces for @openbench/chat-ui.
 *
 * Aligned with A2UI v0.10 specification (https://github.com/google/A2UI).
 */

// ── Chat Messages ──

export interface StepInfo {
  stepId: string;
  stepName: string;
  status: "active" | "complete";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  surfaces?: A2UISurface[];
  steps?: StepInfo[];
  attachments?: Attachment[];
  timestamp: string; // ISO 8601
  status: "sending" | "streaming" | "complete" | "error";
  metadata?: MessageMetadata;
}

export interface MessageMetadata {
  model?: string;
  tokensUsed?: number;
  cost?: number;
  latencyMs?: number;
  toolCalls?: ToolCallInfo[];
}

export interface ToolCallInfo {
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: "pending" | "running" | "completed" | "error";
}

// ── Attachments ──

export interface Attachment {
  id: string;
  type: "file" | "audio" | "video" | "image";
  name: string;
  url: string;
  mimeType: string;
  sizeBytes?: number;
  file?: File; // Browser File reference (never serialized to server)
  extractedPreview?: string; // Text preview from server extraction
}

// ── Sessions ──

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: string;
  updatedAt: string;
}

// ── A2UI v0.10 Types ──

export interface A2UISurface {
  surfaceId: string;
  catalogId: string;
  components: Map<string, A2UIComponent>; // indexed by component ID
  dataModel: Record<string, unknown>;
  theme?: A2UITheme;
  sendDataModel?: boolean;
}

export interface A2UIComponent {
  id: string;
  component: string; // "Text", "Column", "ObChart", etc.
  [key: string]: unknown; // Flat properties (text, children, variant, etc.)
}

export interface A2UITheme {
  primaryColor?: string; // Hex color, e.g. "#00BFFF"
  iconUrl?: string; // Agent icon URL
  agentDisplayName?: string;
}

// ── A2UI Actions (sent back to server) ──

export interface A2UIAction {
  name: string; // Event name from action.event.name
  surfaceId: string;
  sourceComponentId: string;
  timestamp: string; // ISO 8601
  context: Record<string, unknown>; // Resolved context values
}

// ── Data Binding (A2UI v0.10) ──

export interface DataBinding {
  path: string; // JSON Pointer (RFC 6901)
}

export interface FunctionCall {
  call: string; // Function name (e.g. "formatString")
  args?: Record<string, unknown>;
  returnType?: string;
}

export type DynamicString = string | DataBinding | FunctionCall;
export type DynamicNumber = number | DataBinding | FunctionCall;
export type DynamicBoolean = boolean | DataBinding | FunctionCall;
export type DynamicStringList = string[] | DataBinding | FunctionCall;
export type DynamicValue = string | number | boolean | unknown[] | DataBinding | FunctionCall;

// ── Check Rules (Validation) ──

export interface CheckRule {
  condition: DynamicBoolean;
  message: string;
}

// ── A2UI Server Messages ──

export interface CreateSurfacePayload {
  surfaceId: string;
  catalogId: string;
  theme?: A2UITheme;
  sendDataModel?: boolean;
}

export interface UpdateComponentsPayload {
  surfaceId: string;
  components: A2UIComponent[];
}

export interface UpdateDataModelPayload {
  surfaceId: string;
  path?: string;
  value?: unknown;
}

export interface DeleteSurfacePayload {
  surfaceId: string;
}

export type A2UIServerMessage =
  | { version: "v0.10"; createSurface: CreateSurfacePayload }
  | { version: "v0.10"; updateComponents: UpdateComponentsPayload }
  | { version: "v0.10"; updateDataModel: UpdateDataModelPayload }
  | { version: "v0.10"; deleteSurface: DeleteSurfacePayload };

// ── Configuration ──

export interface ChatConfig {
  streamUrl: string; // POST → SSE AG-UI endpoint (e.g., "/awp")
  actionUrl?: string; // POST → JSON (defaults to "/chat/action")
  uploadUrl?: string; // POST → JSON (defaults to "/chat/upload")
  theme?: "light" | "dark" | "auto";
  maxConcurrentStreams?: number; // Max parallel SSE streams (default: 3)
}

export type TransportStatus = "connected" | "disconnected" | "error";

// ── Component Catalog ──

export type A2UIComponentRenderer = React.ComponentType<{
  component: A2UIComponent;
  surface: A2UISurface;
  children?: React.ReactNode;
  onAction?: (action: A2UIAction) => void;
}>;

export type ComponentCatalog = Record<string, A2UIComponentRenderer>;
