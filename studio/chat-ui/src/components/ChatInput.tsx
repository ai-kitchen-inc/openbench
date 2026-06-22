/**
 * ChatInput — text input with file upload and send button.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { generateId } from "../core/utils";
import type { Attachment } from "../types";
import { AttachmentPreview } from "./AttachmentPreview";

export interface ChatInputProps {
  onSend: (content: string, attachments?: Attachment[]) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Comma-separated accept policy, matching the native file input accept attribute. */
  acceptedFileTypes?: string;
  /** Called when one or more selected/dropped files do not match acceptedFileTypes. */
  onAttachmentError?: (message: string, files: File[]) => void;
  /** Whether users can attach more than one file. Defaults to true. */
  multiple?: boolean;
  /** Max size per file in bytes. Files larger than this are rejected. */
  maxUploadSize?: number;
}

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = "Type a message...",
  acceptedFileTypes,
  onAttachmentError,
  multiple = true,
  maxUploadSize,
}: ChatInputProps) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  // Drag events fire rapidly across child elements — track depth so we
  // only flip the drag state on the outermost enter/leave pair.
  const dragDepth = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const attachmentsRef = useRef(attachments);
  attachmentsRef.current = attachments;

  // Revoke blob URLs on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      for (const att of attachmentsRef.current) {
        if (att.url.startsWith("blob:")) {
          URL.revokeObjectURL(att.url);
        }
      }
    };
  }, []);

  const handleSend = useCallback(() => {
    const content = text.trim();
    if (!content && attachments.length === 0) return;

    onSend(content, attachments.length > 0 ? attachments : undefined);
    setText("");
    setAttachments([]);

    // Refocus textarea
    textareaRef.current?.focus();
  }, [text, attachments, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const addFiles = useCallback((files: FileList | File[]) => {
    const asArray = Array.from(files as FileList);
    if (asArray.length === 0) return;
    const selectedFiles = multiple ? asArray : asArray.slice(0, 1);
    const typeRejected = selectedFiles.filter((file) => !isAcceptedFile(file, acceptedFileTypes));
    const typeOk = selectedFiles.filter((file) => isAcceptedFile(file, acceptedFileTypes));
    const oversize = maxUploadSize
      ? typeOk.filter((file) => file.size > maxUploadSize)
      : [];
    const acceptedFiles = typeOk.filter((file) => !maxUploadSize || file.size <= maxUploadSize);

    if (typeRejected.length > 0) {
      onAttachmentError?.(formatRejectedFilesMessage(typeRejected), typeRejected);
    }
    if (oversize.length > 0) {
      onAttachmentError?.(formatOversizeMessage(oversize, maxUploadSize as number), oversize);
    }

    if (acceptedFiles.length === 0) return;

    const newAttachments: Attachment[] = acceptedFiles.map((file) => ({
      id: generateId("att"),
      type: getFileType(file.type),
      name: file.name,
      url: URL.createObjectURL(file),
      mimeType: file.type,
      sizeBytes: file.size,
      file: file,
    }));
    setAttachments((prev) => [...prev, ...newAttachments]);
  }, [acceptedFileTypes, maxUploadSize, multiple, onAttachmentError]);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files) addFiles(files);
      // Reset file input so re-picking the same file still fires change.
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    },
    [addFiles],
  );

  const handleDragEnter = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer?.types?.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current += 1;
    if (dragDepth.current === 1) setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer?.types?.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    // Required to allow drop — without preventDefault the drop event
    // never fires.
    if (!e.dataTransfer?.types?.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      if (!e.dataTransfer?.types?.includes("Files")) return;
      e.preventDefault();
      e.stopPropagation();
      dragDepth.current = 0;
      setIsDragging(false);
      if (e.dataTransfer?.files?.length) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles],
  );

  const handleRemoveAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const att = prev.find((a) => a.id === id);
      if (att) URL.revokeObjectURL(att.url);
      return prev.filter((a) => a.id !== id);
    });
  }, []);

  // Auto-resize textarea
  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  return (
    <div
      className={`chat-input ${isDragging ? "chat-input--dragging" : ""}`}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {isDragging && (
        <div className="chat-input__dropzone" aria-hidden="true">
          <span>Drop files to attach</span>
        </div>
      )}
      <AttachmentPreview attachments={attachments} onRemove={handleRemoveAttachment} />
      <div className="chat-input__row">
        <button
          className="chat-input__attach-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          type="button"
          aria-label="Attach file"
        >
          <svg
            aria-hidden="true"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
          </svg>
        </button>
        <textarea
          ref={textareaRef}
          className="chat-input__textarea"
          value={text}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
        />
        <button
          className="chat-input__send-btn"
          onClick={handleSend}
          disabled={disabled || (!text.trim() && attachments.length === 0)}
          type="button"
          aria-label="Send message"
        >
          <svg
            aria-hidden="true"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="12" y1="19" x2="12" y2="5" />
            <polyline points="5 12 12 5 19 12" />
          </svg>
        </button>
      </div>
      <input
        ref={fileInputRef}
        type="file"
        multiple={multiple}
        accept={acceptedFileTypes}
        onChange={handleFileSelect}
        style={{ display: "none" }}
      />
    </div>
  );
}

function getFileType(mimeType: string): Attachment["type"] {
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType.startsWith("audio/")) return "audio";
  if (mimeType.startsWith("video/")) return "video";
  return "file";
}

function isAcceptedFile(file: File, acceptedFileTypes?: string): boolean {
  const tokens = acceptedFileTypes
    ?.split(",")
    .map((token) => token.trim().toLowerCase())
    .filter(Boolean);

  if (!tokens || tokens.length === 0) return true;

  const fileName = file.name.toLowerCase();
  const mimeType = file.type.toLowerCase();

  return tokens.some((token) => {
    if (token.startsWith(".")) return fileName.endsWith(token);
    if (token.endsWith("/*")) return mimeType.startsWith(token.slice(0, -1));
    return mimeType === token;
  });
}

function formatRejectedFilesMessage(files: File[]): string {
  if (files.length === 1) {
    return `Unsupported file type: ${files[0]?.name ?? "file"}`;
  }
  return `Unsupported file types: ${files.map((file) => file.name).join(", ")}`;
}

function formatOversizeMessage(files: File[], maxBytes: number): string {
  const mb = Math.round(maxBytes / (1024 * 1024));
  const names = files.map((file) => file.name).join(", ");
  return `File too large (max ${mb} MB): ${names}`;
}
