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
  resources: {
    references: [],
    assets: [],
    examples: [],
    scripts: [],
  },
  skill_md: "# Risk Review",
  markdown_files: [
    {
      path: "SKILL.md",
      label: "SKILL.md",
      description: "Instruksi utama skill.",
      bucket: "root",
      primary: true,
      content: "# Risk Review",
      size_bytes: 13,
    },
  ],
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
  resources: {
    references: [
      {
        filename: "accounting-rules.md",
        path: "references/accounting-rules.md",
        description: "Accounting rules.",
        generated: true,
      },
    ],
    assets: [
      {
        filename: "invoice-template.xlsx",
        path: "assets/invoice-template.xlsx",
        description: "Invoice report template.",
      },
    ],
    examples: [],
    scripts: [],
  },
  markdown_files: [
    {
      path: "SKILL.md",
      label: "SKILL.md",
      description: "Instruksi utama skill.",
      bucket: "root",
      primary: true,
      content: "# Budget Estimation",
      size_bytes: 19,
    },
    {
      path: "references/accounting-rules.md",
      label: "accounting-rules.md",
      description: "Accounting rules.",
      bucket: "references",
      content: "# Accounting Rules\n\nUse invoice totals.",
      size_bytes: 38,
    },
  ],
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
    expect(screen.getByText(/1 reference/)).toBeInTheDocument();
    expect(screen.getByText(/1 asset/)).toBeInTheDocument();
    expect(screen.getByText("Fungsi: custom_skill_estimate_budget")).toBeInTheDocument();
    expect(screen.getByText("references: references/accounting-rules.md")).toBeInTheDocument();
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

  it("sends prompt uploads as a skill package", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ skills: [] }))
      .mockResolvedValueOnce(jsonResponse(riskSkill))
      .mockResolvedValueOnce(jsonResponse({ skills: [riskSkill] }));
    renderPanel();
    await screen.findByText("Belum ada skill. Tulis kebutuhan skill di prompt.");

    await userEvent.type(
      screen.getByLabelText("Prompt kebutuhan skill"),
      "Buat skill invoice analyzer. File SOP yang saya upload adalah reference.",
    );
    const file = new File(["aturan invoice"], "invoice-sop.md", { type: "text/markdown" });
    await userEvent.upload(screen.getByLabelText("Upload SOP, knowledge, contoh, atau template"), file);
    await userEvent.click(screen.getByRole("button", { name: "Buat dan simpan skill" }));

    const saveCall = fetchMock.mock.calls[1];
    expect((saveCall[1] as RequestInit).body).toBeInstanceOf(FormData);
    const form = (saveCall[1] as RequestInit).body as FormData;
    expect(form.get("prompt")).toBe(
      "Buat skill invoice analyzer. File SOP yang saya upload adalah reference.",
    );
    expect(form.get("resource_hint")).toBeNull();
    expect(form.getAll("files")).toHaveLength(1);
  });

  it("opens generated markdown for manual editing", async () => {
    const updatedSkill = {
      ...riskSkill,
      skill_md: "# Risk Review\n\nUpdated.",
      markdown_files: [
        {
          path: "SKILL.md",
          label: "SKILL.md",
          description: "Instruksi utama skill.",
          bucket: "root" as const,
          primary: true,
          content: "# Risk Review\n\nUpdated.",
          size_bytes: 24,
        },
      ],
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ skills: [riskSkill] }))
      .mockResolvedValueOnce(jsonResponse(updatedSkill))
      .mockResolvedValueOnce(jsonResponse({ skills: [updatedSkill] }));
    renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Edit MD" }));
    const editor = screen.getByLabelText("SKILL.md");
    expect(editor).toHaveValue("# Risk Review");
    await userEvent.clear(editor);
    await userEvent.type(editor, "# Risk Review\n\nUpdated.");
    await userEvent.click(screen.getByRole("button", { name: "Simpan perubahan MD" }));

    const saveCall = fetchMock.mock.calls[1];
    expect(JSON.parse(String((saveCall[1] as RequestInit).body))).toEqual({
      id: "risk-review",
      path: "SKILL.md",
      skill_md: "# Risk Review\n\nUpdated.",
    });
  });

  it("lets admins choose another generated markdown file to edit", async () => {
    const updatedSkill = {
      ...budgetSkill,
      markdown_files: budgetSkill.markdown_files?.map((file) =>
        file.path === "references/accounting-rules.md"
          ? { ...file, content: "# Accounting Rules\n\nUpdated reference." }
          : file,
      ),
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ skills: [budgetSkill] }))
      .mockResolvedValueOnce(jsonResponse(updatedSkill))
      .mockResolvedValueOnce(jsonResponse({ skills: [updatedSkill] }));
    renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Edit MD" }));
    expect(screen.getByText("references/accounting-rules.md")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /accounting-rules\.md/ }));

    const editor = screen.getByLabelText("references/accounting-rules.md");
    expect(editor).toHaveValue("# Accounting Rules\n\nUse invoice totals.");
    await userEvent.clear(editor);
    await userEvent.type(editor, "# Accounting Rules\n\nUpdated reference.");
    await userEvent.click(screen.getByRole("button", { name: "Simpan perubahan MD" }));

    const saveCall = fetchMock.mock.calls[1];
    expect(JSON.parse(String((saveCall[1] as RequestInit).body))).toEqual({
      id: "budget-estimation",
      path: "references/accounting-rules.md",
      skill_md: "# Accounting Rules\n\nUpdated reference.",
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
