// ── Agent identity badge on assistant messages ──

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "../src/components/MessageBubble";
import type { ChatMessage } from "../src/types";

function assistantMessage(metadata: ChatMessage["metadata"]): ChatMessage {
  return {
    id: "msg-1",
    role: "assistant",
    content: "Jawaban.",
    timestamp: new Date().toISOString(),
    status: "complete",
    metadata,
  };
}

describe("MessageBubble agent badge", () => {
  it("renders the answering agent's name", () => {
    render(
      <MessageBubble
        message={assistantMessage({ agentId: "analis", agentName: "Analis Keuangan" })}
      />,
    );
    expect(screen.getByText("Analis Keuangan")).toBeDefined();
  });

  it("marks escalated answers", () => {
    render(
      <MessageBubble
        message={assistantMessage({
          agentId: "senior",
          agentName: "Konsultan Senior",
          escalated: true,
        })}
      />,
    );
    expect(screen.getByText(/Konsultan Senior · eskalasi/)).toBeDefined();
  });

  it("renders no badge without agent metadata", () => {
    const { container } = render(
      <MessageBubble message={assistantMessage({ model: "gemini-2.5-flash" })} />,
    );
    expect(container.querySelector(".chat-message__agent")).toBeNull();
    expect(screen.getByText("gemini-2.5-flash")).toBeDefined();
  });

  it("keeps the model span alongside the agent badge", () => {
    render(
      <MessageBubble
        message={assistantMessage({
          model: "gemini-2.5-pro",
          agentId: "analis",
          agentName: "Analis Keuangan",
        })}
      />,
    );
    expect(screen.getByText("Analis Keuangan")).toBeDefined();
    expect(screen.getByText("gemini-2.5-pro")).toBeDefined();
  });
});
