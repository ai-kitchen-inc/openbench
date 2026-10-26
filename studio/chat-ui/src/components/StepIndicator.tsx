/**
 * StepIndicator — shows processing step with spinner (active) or checkmark (complete).
 */

import type { StepInfo } from "../types";

export interface StepIndicatorProps {
  step: StepInfo;
}

function SpinnerIcon() {
  return (
    <svg
      className="chat-step-indicator__spinner"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M12 2a10 10 0 0 1 10 10" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      className="chat-step-indicator__check"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

export function StepIndicator({ step }: StepIndicatorProps) {
  const isActive = step.status === "active";

  return (
    <div
      className={`chat-step-indicator chat-step-indicator--${step.status}`}
      data-step-id={step.stepId}
    >
      {isActive ? <SpinnerIcon /> : <CheckIcon />}
      <span className="chat-step-indicator__label">{step.stepName}</span>
    </div>
  );
}
