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
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ skills: [riskSkill] }));
    renderPanel();
    expect(await screen.findByText("Risk Review")).toBeInTheDocument();
    expect(screen.getByText(/Reviews decision risks/)).toBeInTheDocument();
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
