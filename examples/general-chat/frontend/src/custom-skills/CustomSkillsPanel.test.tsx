import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../Toast";
import { CustomSkillsPanel } from "./CustomSkillsPanel";
import type { CustomSkill } from "./types";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const riskSkill: CustomSkill = {
  id: "risk-review",
  name: "Risk Review",
  description: "Reviews decision risks.",
  triggers: ["risk", "mitigation"],
  instructions: "Return risks, impact, and mitigation.",
  version: "0.1.0",
  created_at: "2026-08-05T00:00:00+00:00",
  updated_at: "2026-08-05T00:00:00+00:00",
  source: "/tmp/risk-review",
  context_chars: 200,
  skill_md: "# Risk Review",
};

const budgetSkill: CustomSkill = {
  ...riskSkill,
  id: "budget-estimation",
  name: "Budget Estimation",
  tooling: {
    required: [
      {
        capability: "budget_estimation",
        label: "Budget estimation",
        status: "available",
        type: "custom_function",
        name: "custom_skill_estimate_budget",
      },
    ],
    created_functions: [
      {
        capability: "budget_estimation",
        name: "custom_skill_estimate_budget",
        type: "custom_function",
      },
    ],
    reused_tools: [],
  },
};

function renderPanel() {
  return render(
    <ToastProvider>
      <CustomSkillsPanel />
    </ToastProvider>,
  );
}

describe("CustomSkillsPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists saved skills", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ skills: [budgetSkill] }));
    renderPanel();
    expect(await screen.findByText("Budget Estimation")).toBeInTheDocument();
    expect(screen.getByText(/Reviews decision risks/)).toBeInTheDocument();
    expect(screen.getByText(/1\/1 tool tersedia/)).toBeInTheDocument();
    expect(screen.getByText(/1 fungsi dibuat/)).toBeInTheDocument();
    expect(screen.getByText("Fungsi: custom_skill_estimate_budget")).toBeInTheDocument();
  });

  it("saves a skill and reloads the list", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ skills: [] }))
      .mockResolvedValueOnce(jsonResponse(riskSkill))
      .mockResolvedValueOnce(jsonResponse({ skills: [riskSkill] }));
    renderPanel();
    await screen.findByText("Belum ada skill. Tulis kebutuhan skill di prompt.");

    await userEvent.type(
      screen.getByLabelText("Prompt kebutuhan skill"),
      "Buat skill untuk review risiko keputusan dan mitigasinya.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Buat dan simpan skill" }));

    expect(await screen.findByText("Risk Review")).toBeInTheDocument();
    const saveCall = fetchMock.mock.calls[1];
    expect(String(saveCall[0])).toContain("/admin/custom-skills");
    expect((saveCall[1] as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((saveCall[1] as RequestInit).body))).toEqual({
      prompt: "Buat skill untuk review risiko keputusan dan mitigasinya.",
    });
  });

  it("opens generated markdown for manual editing", async () => {
    const updatedSkill = { ...riskSkill, skill_md: "# Risk Review\n\nUpdated." };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ skills: [riskSkill] }))
      .mockResolvedValueOnce(jsonResponse(updatedSkill))
      .mockResolvedValueOnce(jsonResponse({ skills: [updatedSkill] }));
    renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Edit MD" }));
    const editor = screen.getByLabelText("Markdown skill");
    expect(editor).toHaveValue("# Risk Review");
    await userEvent.clear(editor);
    await userEvent.type(editor, "# Risk Review\n\nUpdated.");
    await userEvent.click(screen.getByRole("button", { name: "Simpan perubahan MD" }));

    const saveCall = fetchMock.mock.calls[1];
    expect(JSON.parse(String((saveCall[1] as RequestInit).body))).toEqual({
      id: "risk-review",
      skill_md: "# Risk Review\n\nUpdated.",
    });
  });

  it("removes a deleted skill from the visible list immediately", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ skills: [riskSkill] }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    renderPanel();

    expect(await screen.findByText("Risk Review")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hapus" }));

    await waitFor(() => {
      expect(screen.queryByText("Risk Review")).not.toBeInTheDocument();
    });
    const deleteCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes("/admin/custom-skills/risk-review") &&
        (init as RequestInit | undefined)?.method === "DELETE",
    );
    expect(deleteCall).toBeTruthy();
  });

  it("shows validation errors from the API", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ skills: [] }))
      .mockResolvedValueOnce(jsonResponse({ detail: "prompt is required" }, 400));
    renderPanel();
    await screen.findByText("Belum ada skill. Tulis kebutuhan skill di prompt.");

    await userEvent.type(screen.getByLabelText("Prompt kebutuhan skill"), "Buat skill uji");
    await userEvent.click(screen.getByRole("button", { name: "Buat dan simpan skill" }));

    await waitFor(() => {
      expect(screen.getByText("prompt is required")).toBeInTheDocument();
    });
  });
});
