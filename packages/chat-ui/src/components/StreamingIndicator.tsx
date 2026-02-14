/**
 * StreamingIndicator — animated typing/streaming dots.
 */

export function StreamingIndicator() {
  return (
    <div className="chat-streaming-indicator" aria-label="Assistant is typing">
      <span className="chat-streaming-indicator__dot" />
      <span className="chat-streaming-indicator__dot" />
      <span className="chat-streaming-indicator__dot" />
    </div>
  );
}
