/**
 * Tests for StepIndicator component.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StepIndicator } from "../src/components/StepIndicator";
import type { StepInfo } from "../src/types";

describe("StepIndicator", () => {
  it("renders active step with spinner", () => {
    const step: StepInfo = { stepId: "s1", stepName: "Thinking", status: "active" };
    const { container } = render(<StepIndicator step={step} />);

    expect(screen.getByText("Thinking")).toBeDefined();

    const wrapper = container.querySelector(".chat-step-indicator");
    expect(wrapper?.classList.contains("chat-step-indicator--active")).toBe(true);

    const spinner = container.querySelector(".chat-step-indicator__spinner");
    expect(spinner).not.toBeNull();
  });

  it("renders complete step with checkmark", () => {
    const step: StepInfo = { stepId: "s2", stepName: "Processing input", status: "complete" };
    const { container } = render(<StepIndicator step={step} />);

    expect(screen.getByText("Processing input")).toBeDefined();

    const wrapper = container.querySelector(".chat-step-indicator");
    expect(wrapper?.classList.contains("chat-step-indicator--complete")).toBe(true);

    const check = container.querySelector(".chat-step-indicator__check");
    expect(check).not.toBeNull();
  });

  it("sets data-step-id attribute", () => {
    const step: StepInfo = { stepId: "step-abc123", stepName: "Rendering", status: "active" };
    const { container } = render(<StepIndicator step={step} />);

    const wrapper = container.querySelector("[data-step-id='step-abc123']");
    expect(wrapper).not.toBeNull();
  });
});
