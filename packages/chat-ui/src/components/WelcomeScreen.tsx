/**
 * WelcomeScreen — empty state with suggestion prompts.
 */

export interface WelcomeScreenProps {
  /** Greeting text displayed at top. */
  greeting?: string;
  /** Suggestion prompts the user can click. */
  suggestions?: string[];
  /** Called when a suggestion is clicked. */
  onSuggestionClick?: (suggestion: string) => void;
}

export function WelcomeScreen({
  greeting = "How can I help you today?",
  suggestions = [],
  onSuggestionClick,
}: WelcomeScreenProps) {
  return (
    <div className="chat-welcome">
      <div className="chat-welcome__icon">
        <svg
          width="48"
          height="48"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
        </svg>
      </div>
      <h2 className="chat-welcome__greeting">{greeting}</h2>
      {suggestions.length > 0 && (
        <div className="chat-welcome__suggestions">
          {suggestions.map((suggestion, i) => (
            <button
              key={i}
              className="chat-welcome__suggestion"
              onClick={() => onSuggestionClick?.(suggestion)}
              type="button"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
