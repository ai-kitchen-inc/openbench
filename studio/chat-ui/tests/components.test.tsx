import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttachmentPreview } from "../src/components/AttachmentPreview";
import { ChatInput } from "../src/components/ChatInput";
import { ChatPanel } from "../src/components/ChatPanel";
import { MessageBubble } from "../src/components/MessageBubble";
import { MessageList } from "../src/components/MessageList";
import { SessionSidebar } from "../src/components/SessionSidebar";
import { StreamingIndicator } from "../src/components/StreamingIndicator";
import { WelcomeScreen } from "../src/components/WelcomeScreen";
import type { Attachment, ChatMessage } from "../src/types";

// Mock useChatContext for SessionSidebar tests
const mockChatContext = {
  sessions: [
    {
      id: "session-1",
      title: "New Chat",
      messages: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    },
  ],
  activeSessionId: "session-1",
  createSession: vi.fn(() => "session-2"),
  switchSession: vi.fn(),
  deleteSession: vi.fn(),
  renameSession: vi.fn(),
  sidebarOpen: true,
  setSidebarOpen: vi.fn(),
  messages: [],
  sendMessage: vi.fn(),
  isStreaming: false,
  isLoadingSession: false,
  connectionStatus: "disconnected" as const,
  surfaces: [],
  sendAction: vi.fn(),
};

vi.mock("../src/components/ChatProvider", () => ({
  useChatContext: () => mockChatContext,
}));

// ── WelcomeScreen ──

describe("WelcomeScreen", () => {
  it("renders greeting text", () => {
    render(<WelcomeScreen greeting="Hello there!" />);
    expect(screen.getByText("Hello there!")).toBeDefined();
  });

  it("renders default greeting when none provided", () => {
    render(<WelcomeScreen />);
    expect(screen.getByText("How can I help you today?")).toBeDefined();
  });

  it("renders suggestion buttons", () => {
    render(<WelcomeScreen suggestions={["Tell me a joke", "What is AI?"]} />);
    expect(screen.getByText("Tell me a joke")).toBeDefined();
    expect(screen.getByText("What is AI?")).toBeDefined();
  });

  it("calls onSuggestionClick when suggestion clicked", async () => {
    const onClick = vi.fn();
    render(<WelcomeScreen suggestions={["Hello"]} onSuggestionClick={onClick} />);

    await userEvent.click(screen.getByText("Hello"));
    expect(onClick).toHaveBeenCalledWith("Hello");
  });
});

// ── StreamingIndicator ──

describe("StreamingIndicator", () => {
  it("renders three dots", () => {
    const { container } = render(<StreamingIndicator />);
    const dots = container.querySelectorAll(".chat-streaming-indicator__dot");
    expect(dots).toHaveLength(3);
  });

  it("has aria label", () => {
    const { container } = render(<StreamingIndicator />);
    expect(container.querySelector('[aria-label="Assistant is typing"]')).not.toBeNull();
  });
});

// ── AttachmentPreview ──

describe("AttachmentPreview", () => {
  const attachments: Attachment[] = [
    {
      id: "att-1",
      type: "file",
      name: "document.pdf",
      url: "/files/doc.pdf",
      mimeType: "application/pdf",
      sizeBytes: 2048,
    },
    {
      id: "att-2",
      type: "image",
      name: "photo.jpg",
      url: "/files/photo.jpg",
      mimeType: "image/jpeg",
    },
  ];

  it("renders nothing when empty", () => {
    const { container } = render(<AttachmentPreview attachments={[]} onRemove={vi.fn()} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders attachment names", () => {
    render(<AttachmentPreview attachments={attachments} onRemove={vi.fn()} />);
    expect(screen.getByText("document.pdf")).toBeDefined();
    expect(screen.getByText("photo.jpg")).toBeDefined();
  });

  it("renders file size when available", () => {
    render(<AttachmentPreview attachments={attachments} onRemove={vi.fn()} />);
    expect(screen.getByText("2.0 KB")).toBeDefined();
  });

  it("calls onRemove when remove button clicked", async () => {
    const onRemove = vi.fn();
    render(<AttachmentPreview attachments={attachments} onRemove={onRemove} />);

    const removeButtons = screen.getAllByRole("button");
    await userEvent.click(removeButtons[0]!);
    expect(onRemove).toHaveBeenCalledWith("att-1");
  });
});

// ── ChatInput ──

describe("ChatInput", () => {
  it("renders textarea and send button", () => {
    render(<ChatInput onSend={vi.fn()} />);
    expect(screen.getByPlaceholderText("Type a message...")).toBeDefined();
    expect(screen.getByLabelText("Send message")).toBeDefined();
  });

  it("renders custom placeholder", () => {
    render(<ChatInput onSend={vi.fn()} placeholder="Ask me anything..." />);
    expect(screen.getByPlaceholderText("Ask me anything...")).toBeDefined();
  });

  it("send button is disabled when input is empty", () => {
    render(<ChatInput onSend={vi.fn()} />);
    const btn = screen.getByLabelText("Send message");
    expect(btn.hasAttribute("disabled")).toBe(true);
  });

  it("calls onSend when send button clicked with text", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const textarea = screen.getByPlaceholderText("Type a message...");
    await userEvent.type(textarea, "Hello world");
    await userEvent.click(screen.getByLabelText("Send message"));

    expect(onSend).toHaveBeenCalledWith("Hello world", undefined);
  });

  it("calls onSend on Enter key (not Shift+Enter)", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const textarea = screen.getByPlaceholderText("Type a message...");
    await userEvent.type(textarea, "Test message{Enter}");

    expect(onSend).toHaveBeenCalledWith("Test message", undefined);
  });

  it("clears input after sending", async () => {
    render(<ChatInput onSend={vi.fn()} />);

    const textarea = screen.getByPlaceholderText("Type a message...") as HTMLTextAreaElement;
    await userEvent.type(textarea, "Hello{Enter}");

    expect(textarea.value).toBe("");
  });

  it("is disabled when disabled prop is true", () => {
    render(<ChatInput onSend={vi.fn()} disabled />);
    const textarea = screen.getByPlaceholderText("Type a message...");
    expect(textarea.hasAttribute("disabled")).toBe(true);
  });
});

// ── MessageBubble ──

describe("MessageBubble", () => {
  const userMessage: ChatMessage = {
    id: "msg-1",
    role: "user",
    content: "Hello!",
    timestamp: new Date().toISOString(),
    status: "complete",
  };

  const assistantMessage: ChatMessage = {
    id: "msg-2",
    role: "assistant",
    content: "Hi there!",
    timestamp: new Date().toISOString(),
    status: "complete",
    metadata: { model: "gemini-2.5-flash" },
  };

  const streamingMessage: ChatMessage = {
    id: "msg-3",
    role: "assistant",
    content: "",
    timestamp: new Date().toISOString(),
    status: "streaming",
  };

  const errorMessage: ChatMessage = {
    id: "msg-4",
    role: "assistant",
    content: "Something went wrong",
    timestamp: new Date().toISOString(),
    status: "error",
  };

  it("renders user message content", () => {
    render(<MessageBubble message={userMessage} />);
    expect(screen.getByText("Hello!")).toBeDefined();
  });

  it("renders assistant message with model", () => {
    render(<MessageBubble message={assistantMessage} />);
    expect(screen.getByText("Hi there!")).toBeDefined();
    expect(screen.getByText("gemini-2.5-flash")).toBeDefined();
  });

  it("renders streaming indicator for streaming messages", () => {
    const { container } = render(<MessageBubble message={streamingMessage} />);
    expect(container.querySelector(".chat-streaming-indicator")).not.toBeNull();
  });

  it("renders error badge for error messages", () => {
    render(<MessageBubble message={errorMessage} />);
    expect(screen.getByText("Error")).toBeDefined();
  });

  it("applies role-based CSS class", () => {
    const { container } = render(<MessageBubble message={userMessage} />);
    expect(container.querySelector(".chat-message--user")).not.toBeNull();
  });

  it("sets data-message-id", () => {
    const { container } = render(<MessageBubble message={userMessage} />);
    expect(container.querySelector('[data-message-id="msg-1"]')).not.toBeNull();
  });

  // ── Aborted placeholder + retry button ──

  const abortedMessage: ChatMessage = {
    id: "msg-aborted",
    role: "assistant",
    content: "⚠️ Turn interrupted. Please retry.",
    timestamp: new Date().toISOString(),
    status: "error",
    metadata: { aborted: true, error: "Gemini 500" },
  };

  it("renders retry button when metadata.aborted is true and onRetry is provided", () => {
    const onRetry = vi.fn();
    render(<MessageBubble message={abortedMessage} onRetry={onRetry} />);
    const retryBtn = screen.getByRole("button", { name: /retry/i });
    expect(retryBtn).toBeDefined();
    retryBtn.click();
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onRetry).toHaveBeenCalledWith(abortedMessage);
  });

  it("hides retry button when onRetry is not provided", () => {
    render(<MessageBubble message={abortedMessage} />);
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  });

  it("hides retry button when metadata.aborted is not true", () => {
    const onRetry = vi.fn();
    render(<MessageBubble message={assistantMessage} onRetry={onRetry} />);
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  });

  it("applies aborted CSS class when metadata.aborted is true", () => {
    const { container } = render(<MessageBubble message={abortedMessage} />);
    expect(container.querySelector(".chat-message--aborted")).not.toBeNull();
  });

  it("uses the error string as the retry button title for debugging", () => {
    const onRetry = vi.fn();
    render(<MessageBubble message={abortedMessage} onRetry={onRetry} />);
    const retryBtn = screen.getByRole("button", { name: /retry/i });
    expect(retryBtn.getAttribute("title")).toBe("Gemini 500");
  });
});

// ── MessageList ──

describe("MessageList", () => {
  const messages: ChatMessage[] = [
    {
      id: "msg-1",
      role: "user",
      content: "First message",
      timestamp: new Date().toISOString(),
      status: "complete",
    },
    {
      id: "msg-2",
      role: "assistant",
      content: "Second message",
      timestamp: new Date().toISOString(),
      status: "complete",
    },
  ];

  it("renders all messages", () => {
    render(<MessageList messages={messages} />);
    expect(screen.getByText("First message")).toBeDefined();
    expect(screen.getByText("Second message")).toBeDefined();
  });

  it("renders empty list", () => {
    const { container } = render(<MessageList messages={[]} />);
    expect(container.querySelector(".chat-message-list")).not.toBeNull();
  });

  it("has scrollable container", () => {
    const { container } = render(<MessageList messages={messages} />);
    expect(container.querySelector(".chat-message-list")).not.toBeNull();
  });

  it("accepts isStreaming prop", () => {
    const { container } = render(<MessageList messages={messages} isStreaming={true} />);
    expect(container.querySelector(".chat-message-list")).not.toBeNull();
  });

  it("does not render sentinel div (uses scrollTop instead)", () => {
    const { container } = render(<MessageList messages={messages} />);
    // No sentinel div — component uses direct scrollTop on scrollable parent
    const listEl = container.querySelector(".chat-message-list");
    expect(listEl).not.toBeNull();
    // Only message bubbles, no extra sentinel div
    const directChildren = listEl?.children ?? [];
    expect(directChildren.length).toBe(messages.length);
  });

  it("re-renders when streaming content grows", () => {
    const streamingMessages: ChatMessage[] = [
      {
        id: "msg-1",
        role: "user",
        content: "Hi",
        timestamp: new Date().toISOString(),
        status: "complete",
      },
      {
        id: "msg-2",
        role: "assistant",
        content: "Hello",
        timestamp: new Date().toISOString(),
        status: "streaming",
      },
    ];

    const { rerender } = render(<MessageList messages={streamingMessages} isStreaming={true} />);
    expect(screen.getByText("Hello")).toBeDefined();

    // Simulate streaming update: content grows
    const updatedMessages = [
      streamingMessages[0],
      { ...streamingMessages[1], content: "Hello World" },
    ];
    rerender(<MessageList messages={updatedMessages} isStreaming={true} />);
    expect(screen.getByText("Hello World")).toBeDefined();
  });
});

// ── SessionSidebar ──

describe("SessionSidebar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockChatContext.sidebarOpen = true;
    mockChatContext.sessions = [
      {
        id: "session-1",
        title: "New Chat",
        messages: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    ];
  });

  it("renders session title", () => {
    render(<SessionSidebar />);
    expect(screen.getByText("New Chat")).toBeDefined();
  });

  it("returns null when sidebar is closed", () => {
    mockChatContext.sidebarOpen = false;
    const { container } = render(<SessionSidebar />);
    expect(container.innerHTML).toBe("");
  });

  it("double-click shows input with current title", async () => {
    render(<SessionSidebar />);

    const title = screen.getByText("New Chat");
    await userEvent.dblClick(title);

    const input = screen.getByLabelText("Rename session") as HTMLInputElement;
    expect(input).toBeDefined();
    expect(input.value).toBe("New Chat");
  });

  it("Enter commits rename", async () => {
    render(<SessionSidebar />);

    const title = screen.getByText("New Chat");
    await userEvent.dblClick(title);

    const input = screen.getByLabelText("Rename session") as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "My Research{Enter}");

    expect(mockChatContext.renameSession).toHaveBeenCalledWith("session-1", "My Research");
  });

  it("blur commits rename", async () => {
    render(<SessionSidebar />);

    const title = screen.getByText("New Chat");
    await userEvent.dblClick(title);

    const input = screen.getByLabelText("Rename session") as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "Blurred Title");
    await userEvent.tab(); // triggers blur

    expect(mockChatContext.renameSession).toHaveBeenCalledWith("session-1", "Blurred Title");
  });

  it("Escape cancels without renaming", async () => {
    render(<SessionSidebar />);

    const title = screen.getByText("New Chat");
    await userEvent.dblClick(title);

    const input = screen.getByLabelText("Rename session") as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "Something{Escape}");

    expect(mockChatContext.renameSession).not.toHaveBeenCalled();
    // Input should be gone, title should be back
    expect(screen.getByText("New Chat")).toBeDefined();
  });
});

// ── ChatPanel: loading skeleton ──

describe("ChatPanel — session loading state", () => {
  beforeEach(() => {
    mockChatContext.messages = [];
    mockChatContext.isLoadingSession = false;
  });

  it("renders WelcomeScreen when empty and not loading", () => {
    render(<ChatPanel greeting="Hi" />);
    expect(screen.getByText("Hi")).toBeDefined();
    expect(document.querySelector(".chat-loading")).toBeNull();
  });

  it("renders loading skeleton when empty + isLoadingSession=true", () => {
    mockChatContext.isLoadingSession = true;
    render(<ChatPanel greeting="Hi" />);
    expect(document.querySelector(".chat-loading")).toBeDefined();
    // Skeleton replaces the welcome greeting to avoid double-render.
    expect(screen.queryByText("Hi")).toBeNull();
    // A screen-reader-only status announces the load.
    expect(screen.getByRole("status")).toBeDefined();
  });

  it("skeleton exposes aria-busy=true for a11y", () => {
    mockChatContext.isLoadingSession = true;
    render(<ChatPanel />);
    const region = document.querySelector(".chat-loading") as HTMLElement | null;
    expect(region?.getAttribute("aria-busy")).toBe("true");
  });

  it("shows existing messages even while isLoadingSession=true (subsequent refresh)", () => {
    // Once a session has messages, a background refresh shouldn't
    // blank the conversation; skeleton is only for empty sessions.
    mockChatContext.messages = [
      {
        id: "m1",
        role: "user",
        content: "hello",
        timestamp: new Date().toISOString(),
        status: "complete",
      },
    ];
    mockChatContext.isLoadingSession = true;
    render(<ChatPanel />);
    expect(screen.getByText("hello")).toBeDefined();
    expect(document.querySelector(".chat-loading")).toBeNull();
  });
});
