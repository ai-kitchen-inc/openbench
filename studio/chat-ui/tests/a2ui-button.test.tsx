/**
 * Tests for A2UIButton's validateSurface guard.
 *
 * Historical chat sessions persist a bare {surfaceId} with no components Map.
 * Clicking a button on such a surface must not crash (regression for
 * "can't access property 'values', a.components is undefined").
 */

import { act, render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { A2UIButton } from "../src/a2ui/standard/a2ui-button";
import type { A2UIComponent, A2UISurface } from "../src/types";

const buttonComponent: A2UIComponent = {
  id: "btn",
  component: "Button",
  label: "Go",
  action: { event: { name: "click", context: {} } },
};

function renderButton(surface: A2UISurface, onAction = vi.fn()) {
  render(<A2UIButton component={buttonComponent} surface={surface} onAction={onAction} />);
  return onAction;
}

describe("A2UIButton validateSurface guard", () => {
  it("does not throw and dispatches when components is undefined", async () => {
    const surface = { surfaceId: "s-persisted", dataModel: {} } as unknown as A2UISurface;
    const onAction = renderButton(surface);

    await act(async () => {
      await userEvent.click(screen.getByText("Go"));
    });

    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("does not throw when components is a plain object (JSON round-trip)", async () => {
    const surface = {
      surfaceId: "s-json",
      dataModel: {},
      components: {} as unknown as Map<string, A2UIComponent>,
    } as unknown as A2UISurface;
    const onAction = renderButton(surface);

    await act(async () => {
      await userEvent.click(screen.getByText("Go"));
    });

    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("still validates normally when components is a real Map", async () => {
    const map = new Map<string, A2UIComponent>([[buttonComponent.id, buttonComponent]]);
    const surface: A2UISurface = {
      surfaceId: "s-live",
      catalogId: "openbench",
      components: map,
      dataModel: {},
    };
    const onAction = renderButton(surface);

    await act(async () => {
      await userEvent.click(screen.getByText("Go"));
    });

    expect(onAction).toHaveBeenCalledTimes(1);
  });
});
