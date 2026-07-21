import { LayoutDashboard, Moon, Sun } from "lucide-react";
import { useState, type FormEvent } from "react";
import { login, type AuthUser } from "./api";
import { useDarkMode } from "./theme";

const VALUE_POINTS = [
  "Connect any SQL database with a single URL",
  "The AI reads only your schema — never your rows",
  "Refine every panel by chatting with the assistant",
];

export function LoginGate({ onLogin }: { onLogin: (user: AuthUser) => void }) {
  const [dark, toggleDark] = useDarkMode();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (isSubmitting) return;
    setError(null);
    setIsSubmitting(true);
    try {
      onLogin(await login(username.trim(), password));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="login-screen">
      <aside className="login-hero">
        <div className="login-hero__brand">
          <LayoutDashboard size={28} strokeWidth={1.5} />
          <span>Dashboard Chat</span>
        </div>
        <div className="login-hero__body">
          <h1 className="login-hero__title">
            Your database, <em>seen clearly</em>.
          </h1>
          <p className="login-hero__subtitle">
            Sign in, connect a database, and get a live dashboard designed by an AI that
            understands your schema — then shape it in conversation.
          </p>
          <ul className="login-hero__points">
            {VALUE_POINTS.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </div>
        <div className="login-hero__footer">OpenBench example — local demo</div>
      </aside>
      <div className="login-form-side">
        <button
          type="button"
          className="topbar__icon-button login-theme-toggle"
          onClick={toggleDark}
          title={dark ? "Switch to light mode" : "Switch to dark mode"}
          aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {dark ? <Sun size={16} strokeWidth={1.5} /> : <Moon size={16} strokeWidth={1.5} />}
        </button>
        <form className="login-card" onSubmit={handleSubmit}>
          <h2 className="login-card__title">Sign in</h2>
          <p className="login-card__subtitle">
            Local demo accounts: <code>admin/admin123</code> or <code>guest/guest123</code>.
          </p>
          <label className="login-card__field">
            <span>Username</span>
            <input
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </label>
          <label className="login-card__field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error && (
            <div className="login-card__error" role="alert">
              {error}
            </div>
          )}
          <button className="login-card__submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
