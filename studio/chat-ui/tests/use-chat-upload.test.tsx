import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useChat } from "../src/hooks/use-chat";
import type { Attachment } from "../src/types";

vi.mock("../src/core/transport", () => ({
  AGUITransport: class {
    onStatusChange() {
      return () => {};
    }
    async listSessions() {
      return [];
    }
    async loadSession() {
      return null;
    }
    async upload() {
      throw new Error("unexpected: tests inject config.uploadFile");
    }
    dispose() {}
  },
}));

vi.mock("../src/core/stream-manager", () => ({
  StreamManager: class {
    startStream = vi.fn(async () => {});
    dispose() {}
  },
}));

beforeEach(() => {
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn((file: File) => `blob:${file.name}`),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
});

function localAttachment(id: string): Attachment {
  return {
    id,
    type: "file",
    name: `${id}.txt`,
    url: `blob:${id}`,
    file: new File(["data"], `${id}.txt`, { type: "text/plain" }),
  };
}

describe("useChat upload blob lifecycle", () => {
  it("revokes the local blob URL when the upload succeeds", async () => {
    const uploadFile = vi.fn(async () => ({
      id: "server-1",
      type: "file" as const,
      name: "a.txt",
      url: "/files/a.txt",
    }));
    const { result } = renderHook(() => useChat({ streamUrl: "/awp", uploadFile }));
    await waitFor(() => expect(result.current.activeSessionId).not.toBeNull());

    act(() => {
      result.current.sendMessage("hello", [localAttachment("att-ok")]);
    });

    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:att-ok"));
  });

  it("revokes the local blob URL when the upload fails", async () => {
    const uploadFile = vi.fn(async () => {
      throw new Error("boom");
    });
    const onUploadError = vi.fn();
    const { result } = renderHook(() =>
      useChat({ streamUrl: "/awp", uploadFile, onUploadError }),
    );
    await waitFor(() => expect(result.current.activeSessionId).not.toBeNull());

    act(() => {
      result.current.sendMessage("hello", [localAttachment("att-fail")]);
    });

    await waitFor(() => expect(onUploadError).toHaveBeenCalledTimes(1));
    // The failed file is dropped from the turn, so its preview URL is
    // dead — not revoking it leaked one blob per failed upload.
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:att-fail"));
  });
});
