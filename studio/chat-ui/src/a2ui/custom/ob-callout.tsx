/**
 * ObCallout — OpenBench custom callout box component.
 *
 * Variant-driven styling (Notion callouts / GitHub alerts pattern).
 * Renders markdown content with a colored left border and icon.
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { A2UIComponentRenderer } from "../../types";
import { resolveString } from "../data-binding";

/** Lucide-style inline SVG icons per variant. */
function LightbulbIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="9" y1="18" x2="15" y2="18" />
      <line x1="10" y1="22" x2="14" y2="22" />
      <path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14" />
    </svg>
  );
}

function InfoIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  );
}

function CheckCircleIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  );
}

function AlertTriangleIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

const VARIANT_ICONS: Record<string, () => React.JSX.Element> = {
  default: LightbulbIcon,
  info: InfoIcon,
  success: CheckCircleIcon,
  warning: AlertTriangleIcon,
};

export const ObCallout: A2UIComponentRenderer = ({ component, surface }) => {
  const content = resolveString(component.content, surface);
  const variant = resolveString(component.variant ?? "default", surface);
  const title = component.title ? resolveString(component.title, surface) : "";

  const validVariant = ["default", "info", "success", "warning"].includes(variant)
    ? variant
    : "default";

  const IconComponent = VARIANT_ICONS[validVariant] ?? LightbulbIcon;

  const className = ["ob-callout", `ob-callout--${validVariant}`].join(" ");

  return (
    <div className={className} data-component-id={component.id}>
      <span className="ob-callout__icon">
        <IconComponent />
      </span>
      <div className="ob-callout__body">
        {title && <div className="ob-callout__title">{title}</div>}
        <div className="ob-callout__content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
};
