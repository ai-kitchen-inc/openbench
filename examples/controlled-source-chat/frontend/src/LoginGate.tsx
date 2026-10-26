import { useState, type FormEvent } from "react";
import { login, type AuthUser } from "./api";
import { BrandMark } from "./brand/BrandMark";
import { CheckIcon } from "./brand/icons";
import { APP_NAME, APP_TAGLINE, FOOTER_ATTRIBUTION } from "./i18n/id";
import { ThemeIcon, useDarkMode } from "./theme";

const VALUE_POINTS = [
  "Jawaban hanya bersumber dari basis pengetahuan resmi yang dikurasi",
  "Setiap jawaban disertai kutipan sumber yang dapat diverifikasi",
  "Kontrol penuh administrator atas sumber, pengguna, dan perangkat",
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
      setError(err instanceof Error ? err.message : "Gagal masuk.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="login-screen">
      <aside className="login-hero">
        <div className="login-hero__brand">
          <BrandMark size={44} />
          <div>
            <div className="login-hero__brand-name">{APP_NAME}</div>
            <div className="login-hero__brand-tagline">{APP_TAGLINE}</div>
          </div>
        </div>
        <div className="login-hero__body">
          <h1 className="login-hero__title">
            Layanan informasi resmi yang <em>akurat</em>, <em>terkurasi</em>, dan{" "}
            <em>tepercaya</em>.
          </h1>
          <ul className="login-hero__points">
            {VALUE_POINTS.map((point) => (
              <li key={point}>
                <CheckIcon size={18} />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="login-hero__footer">{FOOTER_ATTRIBUTION}</div>
      </aside>
      <div className="login-form-side">
        <button
          type="button"
          className="theme-toggle login-theme-toggle"
          onClick={toggleDark}
          title={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
          aria-label={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
        >
          <ThemeIcon dark={dark} />
        </button>
        <form className="login-card" onSubmit={handleSubmit}>
          <div className="login-card__brand">
            <BrandMark size={40} />
            <div>
              <div className="login-card__brand-name">{APP_NAME}</div>
              <div className="login-card__brand-tagline">{APP_TAGLINE}</div>
            </div>
          </div>
          <h2 className="login-card__title">Masuk</h2>
          <p className="login-card__subtitle">
            Gunakan akun yang diberikan oleh administrator untuk mengakses layanan.
          </p>
          <label className="login-card__field">
            <span>Nama Pengguna</span>
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
            <span>Kata Sandi</span>
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
            {isSubmitting ? "Sedang masuk..." : "Masuk"}
          </button>
          <div className="login-card__footer">{FOOTER_ATTRIBUTION}</div>
        </form>
      </div>
    </div>
  );
}
