/**
 * Smoke test for the package entrypoint.
 *
 * Consumers import everything through src/index.ts; a re-export that
 * drifts (renamed source symbol, deleted file) should fail here rather
 * than in a downstream build.
 */

import { describe, expect, it } from "vitest";
import * as publicApi from "../src/index";

const EXPECTED_VALUE_EXPORTS = [
  // Components
  "AttachmentPreview",
  "ChatInput",
  "ChatPanel",
  "ChatProvider",
  "MessageBubble",
  "MessageList",
  "SessionSidebar",
  "StepIndicator",
  "StreamingIndicator",
  "VoiceRecorder",
  "WelcomeScreen",
  // A2UI rendering + catalogs
  "SurfaceRenderer",
  "STANDARD_CATALOG",
  "CUSTOM_CATALOG",
  "ObCallout",
  "ObChart",
  "ObCodeBlock",
  "ObDashboardFrame",
  "ObFileCard",
  "ObMarkdown",
  "ObTable",
  "getComponentCatalog",
  "registerCustomComponent",
  // Core
  "A2UIMessageProcessor",
  "AGUITransport",
  "StreamManager",
  "createChatStore",
  "runWithConcurrency",
  // Hooks
  "useChat",
  "useA2UIProcessor",
] as const;

describe("public entrypoint", () => {
  it.each(EXPECTED_VALUE_EXPORTS)("exports %s", (name) => {
    expect(publicApi[name as keyof typeof publicApi]).toBeDefined();
  });

  it("exposes the 18 standard components through STANDARD_CATALOG", () => {
    expect(Object.keys(publicApi.STANDARD_CATALOG)).toHaveLength(18);
  });

  it("exposes the 7 custom components through CUSTOM_CATALOG", () => {
    expect(Object.keys(publicApi.CUSTOM_CATALOG).sort()).toEqual([
      "ObCallout",
      "ObChart",
      "ObCodeBlock",
      "ObDashboardFrame",
      "ObFileCard",
      "ObMarkdown",
      "ObTable",
    ]);
  });
});
