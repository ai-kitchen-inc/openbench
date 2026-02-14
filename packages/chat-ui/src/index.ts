/**
 * @openbench/chat-ui — Public API exports.
 *
 * Complete SDK: Components + Hooks + A2UI rendering + Core + Types.
 */

// ── Components (drop-in ready) ──
export { ChatProvider, useChatContext } from "./components/ChatProvider";
export type { ChatProviderProps } from "./components/ChatProvider";

export { ChatPanel } from "./components/ChatPanel";
export type { ChatPanelProps } from "./components/ChatPanel";

export { MessageList } from "./components/MessageList";
export type { MessageListProps } from "./components/MessageList";

export { MessageBubble } from "./components/MessageBubble";
export type { MessageBubbleProps } from "./components/MessageBubble";

export { ChatInput } from "./components/ChatInput";
export type { ChatInputProps } from "./components/ChatInput";

export { SessionSidebar } from "./components/SessionSidebar";
export type { SessionSidebarProps } from "./components/SessionSidebar";

export { WelcomeScreen } from "./components/WelcomeScreen";
export type { WelcomeScreenProps } from "./components/WelcomeScreen";

export { StreamingIndicator } from "./components/StreamingIndicator";

export { StepIndicator } from "./components/StepIndicator";
export type { StepIndicatorProps } from "./components/StepIndicator";

export { AttachmentPreview } from "./components/AttachmentPreview";
export type { AttachmentPreviewProps } from "./components/AttachmentPreview";

// ── Hooks (for building custom UIs) ──
export { useChat } from "./hooks/use-chat";
export type { UseChatReturn } from "./hooks/use-chat";

export { useChatTransport } from "./hooks/use-chat-transport";
export type { UseChatTransportReturn } from "./hooks/use-chat-transport";

export { useA2UIProcessor } from "./hooks/use-a2ui-processor";
export type { UseA2UIProcessorReturn } from "./hooks/use-a2ui-processor";

// ── A2UI (rendering layer) ──
export { SurfaceRenderer } from "./a2ui/surface-renderer";
export type { SurfaceRendererProps } from "./a2ui/surface-renderer";

export {
  registerCustomComponent,
  resolveComponent,
  getComponentCatalog,
  isKnownComponent,
} from "./a2ui/catalog";

export {
  resolveValue,
  resolveString,
  resolveNumber,
  resolveBoolean,
  resolvePointer,
} from "./a2ui/data-binding";

// ── Core (headless / framework-agnostic) ──
export { ChatTransport } from "./core/transport";
export type { TransportListener, StatusListener } from "./core/transport";

export { A2UIMessageProcessor } from "./core/message-processor";
export type { SurfaceChangeListener } from "./core/message-processor";

export { createChatStore } from "./core/chat-store";
export type { ChatState, ChatActions, ChatStore } from "./core/chat-store";

export {
  generateId,
  formatFileSize,
  formatTime,
  formatRelativeTime,
  isDataBinding,
  isFunctionCall,
  nowISO,
} from "./core/utils";

// ── Types ──
export type {
  // Chat
  ChatMessage,
  MessageMetadata,
  ToolCallInfo,
  Attachment,
  ChatSession,
  // A2UI
  A2UISurface,
  A2UIComponent,
  A2UITheme,
  A2UIAction,
  DataBinding,
  FunctionCall,
  DynamicString,
  DynamicNumber,
  DynamicBoolean,
  DynamicStringList,
  DynamicValue,
  CheckRule,
  // A2UI Server Messages
  CreateSurfacePayload,
  UpdateComponentsPayload,
  UpdateDataModelPayload,
  DeleteSurfacePayload,
  A2UIServerMessage,
  // Stream Envelope
  StreamStartMessage,
  StreamEndMessage,
  StreamErrorMessage,
  StepStartMessage,
  StepCompleteMessage,
  StreamEnvelopeMessage,
  // Step Info
  StepInfo,
  // Client Messages
  ClientMessage,
  ClientAction,
  ClientPayload,
  // Config
  ChatConfig,
  TransportStatus,
  // Component Catalog
  A2UIComponentRenderer,
  ComponentCatalog,
} from "./types";
