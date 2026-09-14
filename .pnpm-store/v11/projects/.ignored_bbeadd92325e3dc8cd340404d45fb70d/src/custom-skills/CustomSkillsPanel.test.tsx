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
    await screen.findByText("Belum ada skill. Buat satu di formulir.");

    await userEvent.type(screen.getByLabelText("Skill ID"), "risk-review");
    await userEvent.type(screen.getByLabelText("Nama skill"), "Risk Review");
    await userEvent.click(screen.getByRole("button", { name: "Simpan skill" }));

    expect(await screen.findByText("Risk Review")).toBeInTheDocument();
    const saveCall = fetchMock.mock.calls[1];
    expect(String(saveCall[0])).toContain("/admin/custom-skills");
    expect((saveCall[1] as RequestInit).method).toBe("POST");
  });

  it("shows validation errors from the API", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ skills: [] }))
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid version" }, 400));
    renderPanel();
    await screen.findByText("Belum ada skill. Buat satu di formulir.");

    await userEvent.type(screen.getByLabelText("Skill ID"), "risk-review");
    await userEvent.type(screen.getByLabelText("Nama skill"), "Risk Review");
    await userEvent.clear(screen.getByLabelText("Versi"));
    await userEvent.type(screen.getByLabelText("Versi"), "vNext");
    await userEvent.click(screen.getByRole("button", { name: "Simpan skill" }));

    await waitFor(() => {
      expect(screen.getByText("invalid version")).toBeInTheDocument();
    });
  });
});
