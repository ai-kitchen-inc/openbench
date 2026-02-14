import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AttachmentPreview } from "../src/components/AttachmentPreview";
import { ChatInput } from "../src/components/ChatInput";
import { MessageBubble } from "../src/components/MessageBubble";
import { MessageList } from "../src/components/MessageList";
import { StreamingIndicator } from "../src/components/StreamingIndicator";
import { WelcomeScreen } from "../src/components/WelcomeScreen";
import type { Attachment, ChatMessage } from "../src/types";

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
});
