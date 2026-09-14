import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../Toast";
import { FunctionsPanel } from "./FunctionsPanel";
import type { CustomFunction } from "./types";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const addFunction: CustomFunction = {
  name: "add",
  description: "adds two numbers",
  created_at: "2026-07-02T00:00:00+00:00",
  code: "def add(a, b):\n    return a + b\n",
};

function renderPanel(onClose = () => {}) {
  return render(
    <ToastProvider>
      <FunctionsPanel open onClose={onClose} />
    </ToastProvider>,
  );
}

describe("FunctionsPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders nothing when closed", () => {
    const { container } = render(
      <ToastProvider>
        <FunctionsPanel open={false} onClose={() => {}} />
      </ToastProvider>,
    );
    expect(container.querySelector(".mcp-dialog")).toBeNull();
  });

  it("lists saved functions on open", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ functions: [addFunction] }),
    );
    renderPanel();
    expect(await screen.findByText("add")).toBeInTheDocument();
    expect(screen.getByText("adds two numbers")).toBeInTheDocument();
  });

  it("saves a function and reloads the list", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ functions: [] })) // initial load
      .mockResolvedValueOnce(jsonResponse({ name: "add" })) // save
      .mockResolvedValueOnce(jsonResponse({ functions: [addFunction] })); // reload
    renderPanel();
    await screen.findByText("No functions yet — define one above.");

    await userEvent.type(screen.getByPlaceholderText("add_numbers"), "add");
    await userEvent.click(screen.getByRole("button", { name: "Save function" }));

    expect(await screen.findByText("add")).toBeInTheDocument();
    const saveCall = fetchMock.mock.calls[1];
    expect(String(saveCall[0])).toContain("/functions");
    expect((saveCall[1] as RequestInit).method).toBe("POST");
  });

  it("shows a validation error from the API", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ functions: [] }))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "code must define exactly one top-level function" }, 400),
      );
    renderPanel();
    await screen.findByText("No functions yet — define one above.");

    await userEvent.type(screen.getByPlaceholderText("add_numbers"), "add");
    await userEvent.click(screen.getByRole("button", { name: "Save function" }));

    expect(
      await screen.findByText("code must define exactly one top-level function"),
    ).toBeInTheDocument();
  });

  it("test-runs a function and shows the result", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ functions: [addFunction] }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, result: 5, stdout: "" }));
    renderPanel();
    await screen.findByText("add");

    const argsInput = screen.getByPlaceholderText('{"a": 2, "b": 3}');
    await userEvent.clear(argsInput);
    await userEvent.type(argsInput, '{{"a": 2, "b": 3}');
    await userEvent.click(screen.getByRole("button", { name: "Test run" }));

    await waitFor(() => {
      expect(screen.getByText(/add → 5/)).toBeInTheDocument();
    });
  });
});
