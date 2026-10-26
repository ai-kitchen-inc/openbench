import { Database, Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { connectDb } from "../api";

const URL_EXAMPLES = [
  { label: "SQLite (bundled sample)", value: "sqlite:///sample.db" },
  { label: "PostgreSQL", value: "postgresql://user:password@localhost:5432/mydb" },
  { label: "MySQL", value: "mysql+pymysql://user:password@localhost:3306/mydb" },
];

export function ConnectCard({ onConnected }: { onConnected: () => void }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (isSubmitting) return;
    setError(null);
    setIsSubmitting(true);
    try {
      await connectDb(url.trim());
      onConnected();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="connect-card" onSubmit={handleSubmit}>
      <div className="connect-card__icon">
        <Database size={24} strokeWidth={1.5} />
      </div>
      <h2 className="connect-card__title">Connect your database</h2>
      <p className="connect-card__subtitle">
        Paste a SQLAlchemy URL. The assistant reads only the schema — table names, columns,
        and types. Your rows never leave this app.
      </p>
      <label className="connect-card__field">
        <span>Database URL</span>
        <input
          type="text"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="sqlite:///sample.db"
          spellCheck={false}
          autoFocus
          required
        />
      </label>
      <div className="connect-card__examples">
        {URL_EXAMPLES.map((example) => (
          <button
            key={example.label}
            type="button"
            className="connect-card__example"
            onClick={() => setUrl(example.value)}
          >
            <span className="connect-card__example-label">{example.label}</span>
            <code>{example.value}</code>
          </button>
        ))}
      </div>
      {error && (
        <div className="connect-card__error" role="alert">
          {error}
        </div>
      )}
      <button className="connect-card__submit" type="submit" disabled={isSubmitting || !url.trim()}>
        {isSubmitting ? (
          <>
            <Loader2 size={16} strokeWidth={1.5} className="spin" /> Connecting…
          </>
        ) : (
          "Connect"
        )}
      </button>
    </form>
  );
}
