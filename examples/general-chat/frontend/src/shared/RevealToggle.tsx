/** Icon-only eye button that shows/hides a secret, like a password field. */
import { EyeIcon, EyeOffIcon } from "../brand/icons";

export function RevealToggle({
  revealed,
  onToggle,
  showLabel,
  hideLabel,
  className = "panel-button",
}: {
  revealed: boolean;
  onToggle: () => void;
  showLabel: string;
  hideLabel: string;
  className?: string;
}) {
  const label = revealed ? hideLabel : showLabel;
  return (
    <button
      type="button"
      className={`${className} panel-button--icon`}
      aria-label={label}
      aria-pressed={revealed}
      title={label}
      onClick={onToggle}
    >
      {revealed ? <EyeOffIcon /> : <EyeIcon />}
    </button>
  );
}
