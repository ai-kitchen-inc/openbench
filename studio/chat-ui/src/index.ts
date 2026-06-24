/**
 * @openbench/chat-ui — Public API exports.
 *
 * Complete SDK: Components + Hooks + A2UI rendering + Core + Types.
 */

export {
  getComponentCatalog,
  isKnownComponent,
  registerCustomComponent,
  resolveComponent,
} from "./a2ui/catalog";
export {
  evaluateChecks,
  resolveBoolean,
  resolveNumber,
  resolvePointer,
  resolveString,
  resolveValue,
  setAtPath,
} from "./a2ui/data-binding";
export type { SurfaceRendererProps } from "./a2ui/surface-renderer";
// ── A2UI (rendering layer) ──
export { SurfaceRenderer } from "./a2ui/surface-renderer";
export type { AttachmentPreviewProps } from "./components/AttachmentPreview";
export { AttachmentPreview } from "./components/AttachmentPreview";
export type { ChatInputProps } from "./components/ChatInput";
export { ChatInput } from "./components/ChatInput";
export type { ChatPanelProps } from "./components/ChatPanel";
export { ChatPanel } from "./components/ChatPanel";
export type { ChatProviderProps } from "./components/ChatProvider";
// ── Components (drop-in ready) ──
export { ChatProvider, useChatContext, useChatContextOptional } from "./components/ChatProvider";
export type { MessageBubbleProps } from "./components/MessageBubble";
export { MessageBubble } from "./components/MessageBubble";
export type { MessageListProps } from "./components/MessageList";
export { MessageList } from "./components/MessageList";
export type { SessionSidebarProps } from "./components/SessionSidebar";
export { SessionSidebar } from "./components/SessionSidebar";
export type { StepIndicatorProps } from "./components/StepIndicator";
export { StepIndicator } from "./components/StepIndicator";
export { StreamingIndicator } from "./components/StreamingIndicator";
export type { WelcomeScreenProps } from "./components/WelcomeScreen";
export { WelcomeScreen } from "./components/WelcomeScreen";
export type { ChatActions, ChatState, ChatStore } from "./core/chat-store";
export { createChatStore } from "./core/chat-store";
export type { SurfaceChangeListener } from "./core/message-processor";
export { A2UIMessageProcessor } from "./core/message-processor";
export { StreamContext } from "./core/stream-context";
export type { StreamManagerConfig } from "./core/stream-manager";
export { StreamManager } from "./core/stream-manager";
export type { AGUIEventListener, StatusListener } from "./core/transport";
// ── Core (headless / framework-agnostic) ──
export { AGUITransport } from "./core/transport";
export {
  formatFileSize,
  formatRelativeTime,
  formatTime,
  generateId,
  isDataBinding,
  isFunctionCall,
  nowISO,
} from "./core/utils";
export type { UseA2UIProcessorReturn } from "./hooks/use-a2ui-processor";
export { useA2UIProcessor } from "./hooks/use-a2ui-processor";
export type { UseChatReturn } from "./hooks/use-chat";
// ── Hooks (for building custom UIs) ──
export { useChat } from "./hooks/use-chat";

// ── Types ──
export type {
  A2UIAction,
  A2UIComponent,
  // Component Catalog
  A2UIComponentRenderer,
  A2UIServerMessage,
  // A2UI
  A2UISurface,
  A2UITheme,
  Attachment,
  AttachmentUploadOptions,
  // Config
  ChatConfig,
  // Chat
  ChatMessage,
  ChatSession,
  CheckRule,
  ComponentCatalog,
  // A2UI Server Messages
  CreateSurfacePayload,
  DashboardActions,
  DataBinding,
  DeleteSurfacePayload,
  DynamicBoolean,
  DynamicNumber,
  DynamicString,
  DynamicStringList,
  DynamicValue,
  FunctionCall,
  MessageMetadata,
  // Step Info
  SessionSummary,
  StepInfo,
  ToolCallInfo,
  TransportStatus,
  UpdateComponentsPayload,
  UpdateDataModelPayload,
} from "./types";
