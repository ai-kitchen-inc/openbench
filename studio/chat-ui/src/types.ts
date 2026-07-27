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
  /**
   * True when the assistant turn never completed — the backend caught a
   * mid-turn exception (Gemini 500, tool crash, process signal) and
   * wrote a placeholder so the session doesn't dead-end on a bare user
   * message. Paired with {@link error} for a short-form reason. The UI
   * uses this flag to render a retry affordance on the message.
   */
  aborted?: boolean;
  /** Short-form reason string written alongside {@link aborted}. */
  error?: string;
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
  path?: string; // Server-side path for tools, when available
  extractedText?: string; // Full server-side extracted context
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

/**
 * Lightweight session metadata returned by GET /sessions.
 *
 * Uses wire-format field names (sessionId, createdAt) to match the
 * Python SessionSummary.to_dict() payload exactly.
 */
export interface SessionSummary {
  sessionId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
  preview: string;
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

export interface TableExportOption {
  /** Stable key — also used as the React key. */
  id: string;
  /** Button label. */
  label: string;
  /** User message sent when the button is clicked. */
  prompt: string;
}

export interface TableExportConfig {
  /** Defaults to true when ``tableExport`` is supplied at all. */
  enabled?: boolean;
  /** Row label shown before the buttons. Defaults to "Export:". */
  label?: string;
  /** Defaults to Excel / PDF / Markdown with English prompts. */
  formats?: TableExportOption[];
}

export interface ChatConfig {
  streamUrl: string; // POST → SSE AG-UI endpoint (e.g., "/awp")
  actionUrl?: string; // POST → JSON (defaults to "/chat/action")
  uploadUrl?: string; // POST → JSON (defaults to "/chat/upload")
  uploadFile?: (file: File, options: AttachmentUploadOptions) => Promise<Attachment>;
  sessionsUrl?: string; // REST CRUD endpoint (defaults to "/sessions")
  theme?: "light" | "dark" | "auto";
  maxConcurrentStreams?: number; // Max parallel SSE streams (default: 3)
  /**
   * Max attachment uploads in flight at once when a message carries
   * several files (default: 3). Uploads settle independently — a failed
   * file is reported via ``onUploadError`` and dropped from the turn
   * rather than aborting the whole send.
   */
  uploadConcurrency?: number;
  /**
   * Export shortcuts rendered under every ObTable. Clicking one sends a
   * normal user turn asking for that file, so the agent's export tools
   * do the work. Set ``enabled: false`` to hide the row; override
   * ``formats`` to localize the labels and prompts (the defaults are
   * English).
   */
  tableExport?: TableExportConfig;
  /**
   * Optional hook called before every authenticated request. Wire it
   * to Firebase Auth's getIdToken() (or any equivalent) to have the
   * transport attach ``Authorization: Bearer <token>`` headers.
   *
   * Returning ``null`` or leaving this unset omits the header — the
   * backend's auth dependency then decides whether to reject (401)
   * or allow anonymous access.
   */
  getAuthToken?: () => Promise<string | null>;
  /**
   * Fires when an uploaded attachment successfully round-trips to the
   * server. ``localId`` is the pre-upload id the user's ChatInput
   * assigned; ``attachment`` is the server-shaped response. Use to
   * surface a success toast or analytics event.
   */
  onUploadSuccess?: (localId: string, attachment: Attachment) => void;
  /**
   * Fires when an upload fails. ``file`` is the original ``File`` the
   * user picked (filename, size, etc. still readable); ``error`` is
   * whatever the transport threw. Use to surface a failure toast.
   */
  onUploadError?: (file: File, error: unknown) => void;
  /**
   * Optional host-provided actions for dashboard artifacts. When supplied,
   * the dashboard renderer shows Publish / Export buttons that call these.
   * The host wires them to its own authenticated API client, keeping the
   * SDK decoupled from any specific backend.
   */
  dashboardActions?: DashboardActions;
}

export interface DashboardActions {
  /** Persist the ViewModel and return a public, shareable URL. */
  publish?: (viewModel: unknown) => Promise<{ url: string }>;
  /** Convert the ViewModel to a Grafana dashboard JSON model. */
  exportGrafana?: (viewModel: unknown) => Promise<unknown>;
  /** Push the ViewModel to a hosted Grafana; resolves to the dashboard URL. */
  deployGrafana?: (viewModel: unknown) => Promise<{ url: string }>;
  /** Render the ViewModel to a PDF document (charts included) for download. */
  exportPdf?: (viewModel: unknown) => Promise<Blob>;
  /**
   * Fetch a dashboard's standalone HTML through the host's authenticated
   * client. Lets the renderer preview an auth-protected artifact URL via a
   * sandboxed ``srcDoc`` iframe instead of a bare ``src`` the browser can't
   * authenticate. Returns the raw HTML text.
   */
  loadHtml?: (url: string) => Promise<string>;
}

export interface AttachmentUploadOptions {
  sessionId?: string | null;
  onProgress?: (fraction: number) => void;
}

export type TransportStatus = "connected" | "disconnected" | "error";

// ── Component Catalog ──

export type A2UIComponentRenderer = React.ComponentType<{
  component: A2UIComponent;
  surface: A2UISurface;
  children?: React.ReactNode;
  onAction?: (action: A2UIAction) => void | Promise<void>;
}>;

export type ComponentCatalog = Record<string, A2UIComponentRenderer>;
