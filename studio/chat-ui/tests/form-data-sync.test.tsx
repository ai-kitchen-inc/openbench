/**
 * Integration tests for form data model synchronization.
 *
 * Verifies that input components write their values to surface.dataModel
 * so that Button submit can read them via resolveValue.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { resolvePointer, setAtPath } from "../src/a2ui/data-binding";
import { A2UICheckBox } from "../src/a2ui/standard/a2ui-checkbox";
import { A2UIChoicePicker } from "../src/a2ui/standard/a2ui-choice-picker";
import { A2UISlider } from "../src/a2ui/standard/a2ui-slider";
import { A2UITextField } from "../src/a2ui/standard/a2ui-textfield";
import type { A2UISurface } from "../src/types";

function makeSurface(dataModel: Record<string, unknown> = {}): A2UISurface {
  return {
    surfaceId: "test-surface",
    catalogId: "test",
    components: new Map(),
    dataModel,
  };
}

describe("TextField data model sync", () => {
  it("seeds initial value into dataModel on mount", () => {
    const surface = makeSurface({ form: { name: "Alice" } });
    const component = {
      id: "tf-1",
      component: "TextField",
      label: "Name",
      value: { path: "/form/name" },
    };

    render(<A2UITextField component={component} surface={surface} />);

    // dataModel should have the resolved value
    expect(resolvePointer(surface.dataModel, "/form/name")).toBe("Alice");
  });

  it("updates dataModel on input change", async () => {
    const surface = makeSurface();
    const component = {
      id: "tf-2",
      component: "TextField",
      label: "Email",
      value: { path: "/form/email" },
    };

    render(<A2UITextField component={component} surface={surface} />);
    const input = screen.getByRole("textbox");

    await act(async () => {
      await userEvent.clear(input);
      await userEvent.type(input, "bob@test.com");
    });

    expect(resolvePointer(surface.dataModel, "/form/email")).toBe("bob@test.com");
  });

  it("does not write to dataModel when no binding", () => {
    const surface = makeSurface();
    const component = {
      id: "tf-3",
      component: "TextField",
      label: "Static",
      value: "hello",
    };

    render(<A2UITextField component={component} surface={surface} />);

    // dataModel should be empty (no binding path)
    expect(Object.keys(surface.dataModel)).toHaveLength(0);
  });
});

describe("CheckBox data model sync", () => {
  it("seeds initial checked=false into dataModel", () => {
    const surface = makeSurface();
    const component = {
      id: "cb-1",
      component: "CheckBox",
      label: "Agree",
      checked: { path: "/form/agree" },
    };

    render(<A2UICheckBox component={component} surface={surface} />);
    expect(resolvePointer(surface.dataModel, "/form/agree")).toBe(false);
  });

  it("toggles dataModel on click", async () => {
    const surface = makeSurface();
    const component = {
      id: "cb-2",
      component: "CheckBox",
      label: "Terms",
      checked: { path: "/form/terms" },
    };

    render(<A2UICheckBox component={component} surface={surface} />);
    // Click the label text to toggle (native input + span both have checkbox role)
    const label = screen.getByText("Terms");

    await act(async () => {
      await userEvent.click(label);
    });

    expect(resolvePointer(surface.dataModel, "/form/terms")).toBe(true);
  });
});

describe("ChoicePicker data model sync", () => {
  it("updates dataModel on selection", async () => {
    const surface = makeSurface();
    const component = {
      id: "cp-1",
      component: "ChoicePicker",
      label: "Role",
      value: { path: "/form/role" },
      options: [
        { label: "Admin", value: "admin" },
        { label: "User", value: "user" },
      ],
    };

    render(<A2UIChoicePicker component={component} surface={surface} />);
    const select = screen.getByRole("combobox");

    await act(async () => {
      await userEvent.selectOptions(select, "admin");
    });

    expect(resolvePointer(surface.dataModel, "/form/role")).toBe("admin");
  });
});

describe("Slider data model sync", () => {
  it("seeds initial value into dataModel", () => {
    const surface = makeSurface();
    const component = {
      id: "sl-1",
      component: "Slider",
      label: "Volume",
      value: { path: "/form/volume" },
      min: 0,
      max: 100,
    };

    render(<A2UISlider component={component} surface={surface} />);
    // Initial value resolves to 0 (min) since dataModel has no value yet
    expect(resolvePointer(surface.dataModel, "/form/volume")).toBe(0);
  });
});

describe("cross-component: setAtPath + resolvePointer roundtrip", () => {
  it("simulates form submit reading all field values", () => {
    const dataModel: Record<string, unknown> = {};

    // Simulate what components do on mount/change
    setAtPath(dataModel, "/form/name", "Alice");
    setAtPath(dataModel, "/form/email", "alice@test.com");
    setAtPath(dataModel, "/form/agree", true);
    setAtPath(dataModel, "/form/volume", 75);

    // Simulate what Button does on submit (resolvePointer for each binding)
    expect(resolvePointer(dataModel, "/form/name")).toBe("Alice");
    expect(resolvePointer(dataModel, "/form/email")).toBe("alice@test.com");
    expect(resolvePointer(dataModel, "/form/agree")).toBe(true);
    expect(resolvePointer(dataModel, "/form/volume")).toBe(75);
  });
});
