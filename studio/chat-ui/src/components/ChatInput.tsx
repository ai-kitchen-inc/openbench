/**
 * ChatInput — text input with file upload and send button.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { generateId } from "../core/utils";
import type { Attachment } from "../types";
import { AttachmentPreview } from "./AttachmentPreview";
import { VoiceRecorder } from "./VoiceRecorder";

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
  /**
   * Whether users can attach files at all. Defaults to true. When false the
   * attach button, file input, drop zone, and attachment previews are removed
   * — for deployments where chat context is centrally curated.
   */
  allowAttachments?: boolean;
  /** Max size per file in bytes. Files larger than this are rejected. */
  maxUploadSize?: number;
  /**
   * Max files staged on one message. Counts files already attached, so a
   * second pick cannot push the total past the limit. Mirror the server's
   * attachment cap here to reject locally with a readable message instead
   * of a 422 after the upload round-trip.
   */
  maxAttachments?: number;
  /**
   * Overrides for the rejection messages, for hosts whose UI is not in
   * English. Each receives the offending files and returns the string
   * passed to ``onAttachmentError``.
   */
  attachmentMessages?: {
    rejectedType?: (files: File[]) => string;
    oversize?: (files: File[], maxBytes: number) => string;
    tooMany?: (files: File[], max: number) => string;
  };
  /**
   * Optional fallback transcriber for browsers without the Web Speech API.
   * Given a recorded audio blob, returns the transcript text. When omitted
   * and Web Speech is unavailable, the mic button is hidden.
   */
  onTranscribe?: (audio: Blob) => Promise<string>;
}

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = "Type a message...",
  acceptedFileTypes,
  onAttachmentError,
  multiple = true,
  allowAttachments = true,
  maxUploadSize,
  maxAttachments,
  attachmentMessages,
  onTranscribe,
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

  // Voice input: record audio (with a live waveform) and transcribe via the
  // injected onTranscribe backend. No Web Speech API — it's unreliable in
  // Chrome/Edge and gives no audio levels for the waveform.
  const [voiceState, setVoiceState] = useState<"idle" | "recording" | "transcribing">("idle");
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const cancelledRef = useRef(false);

  const micAvailable =
    !!onTranscribe &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia;

  const appendTranscript = useCallback((transcript: string) => {
    const clean = transcript.trim();
    if (!clean) return;
    setText((prev) => (prev ? `${prev} ${clean}` : clean));
    textareaRef.current?.focus();
  }, []);

  const teardownAudio = useCallback(() => {
    const stream = streamRef.current;
    if (stream) for (const track of stream.getTracks()) track.stop();
    streamRef.current = null;
    const ctx = audioCtxRef.current;
    if (ctx && ctx.state !== "closed") void ctx.close();
    audioCtxRef.current = null;
    setAnalyser(null);
  }, []);

  const startRecording = useCallback(async () => {
    if (!onTranscribe || !navigator.mediaDevices?.getUserMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const AudioCtor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AudioCtor) {
        const ctx = new AudioCtor();
        const analyserNode = ctx.createAnalyser();
        analyserNode.fftSize = 1024;
        ctx.createMediaStreamSource(stream).connect(analyserNode);
        audioCtxRef.current = ctx;
        setAnalyser(analyserNode);
      }

      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      cancelledRef.current = false;
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        const blob = new Blob(audioChunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        mediaRecorderRef.current = null;
        teardownAudio();
        if (cancelledRef.current) {
          setVoiceState("idle");
          return;
        }
        setVoiceState("transcribing");
        try {
          appendTranscript(await onTranscribe(blob));
        } catch {
          // Surface nothing in the box on failure; user can retry.
        } finally {
          setVoiceState("idle");
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setVoiceState("recording");
    } catch {
      teardownAudio();
      setVoiceState("idle");
    }
  }, [appendTranscript, onTranscribe, teardownAudio]);

  const confirmRecording = useCallback(() => {
    cancelledRef.current = false;
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }, []);

  const cancelRecording = useCallback(() => {
    cancelledRef.current = true;
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    } else {
      teardownAudio();
      setVoiceState("idle");
    }
  }, [teardownAudio]);

  // Stop any in-flight capture on unmount.
  useEffect(
    () => () => {
      const recorder = mediaRecorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        cancelledRef.current = true;
        recorder.stop();
      }
      teardownAudio();
    },
    [teardownAudio],
  );

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
    if (!allowAttachments) return;
    const asArray = Array.from(files as FileList);
    if (asArray.length === 0) return;
    const selectedFiles = multiple ? asArray : asArray.slice(0, 1);
    const typeRejected = selectedFiles.filter((file) => !isAcceptedFile(file, acceptedFileTypes));
    const typeOk = selectedFiles.filter((file) => isAcceptedFile(file, acceptedFileTypes));
    const oversize = maxUploadSize
      ? typeOk.filter((file) => file.size > maxUploadSize)
      : [];
    const sized = typeOk.filter((file) => !maxUploadSize || file.size <= maxUploadSize);
    // Count what is already staged so two picks cannot exceed the cap.
    const room = maxAttachments
      ? Math.max(0, maxAttachments - attachmentsRef.current.length)
      : sized.length;
    const acceptedFiles = sized.slice(0, room);
    const overflow = sized.slice(room);

    if (typeRejected.length > 0) {
      const format = attachmentMessages?.rejectedType ?? formatRejectedFilesMessage;
      onAttachmentError?.(format(typeRejected), typeRejected);
    }
    if (oversize.length > 0) {
      const format = attachmentMessages?.oversize ?? formatOversizeMessage;
      onAttachmentError?.(format(oversize, maxUploadSize as number), oversize);
    }
    if (overflow.length > 0) {
      const format = attachmentMessages?.tooMany ?? formatTooManyFilesMessage;
      onAttachmentError?.(format(overflow, maxAttachments as number), overflow);
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
  }, [
    acceptedFileTypes,
    allowAttachments,
    attachmentMessages,
    maxAttachments,
    maxUploadSize,
    multiple,
    onAttachmentError,
  ]);

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
      onDragEnter={allowAttachments ? handleDragEnter : undefined}
      onDragLeave={allowAttachments ? handleDragLeave : undefined}
      onDragOver={allowAttachments ? handleDragOver : undefined}
      onDrop={allowAttachments ? handleDrop : undefined}
    >
      {allowAttachments && isDragging && (
        <div className="chat-input__dropzone" aria-hidden="true">
          <span>Drop files to attach</span>
        </div>
      )}
      {allowAttachments && (
        <AttachmentPreview attachments={attachments} onRemove={handleRemoveAttachment} />
      )}
      {voiceState === "idle" ? (
        <div className="chat-input__row">
          {allowAttachments && (
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
          )}
          {micAvailable && (
            <button
              className="chat-input__mic-btn"
              onClick={() => void startRecording()}
              disabled={disabled}
              type="button"
              aria-label="Start voice input"
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
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </button>
          )}
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
      ) : (
        <div className="chat-input__row">
          <VoiceRecorder
            analyser={analyser}
            state={voiceState}
            onCancel={cancelRecording}
            onConfirm={confirmRecording}
          />
        </div>
      )}
      {allowAttachments && (
        <input
          ref={fileInputRef}
          type="file"
          multiple={multiple}
          accept={acceptedFileTypes}
          onChange={handleFileSelect}
          style={{ display: "none" }}
        />
      )}
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

function formatTooManyFilesMessage(files: File[], max: number): string {
  const names = files.map((file) => file.name).join(", ");
  return `Too many files (max ${max} per message), skipped: ${names}`;
}
