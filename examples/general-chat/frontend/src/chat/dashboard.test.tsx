import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DashboardArtifactPanel, findDashboardArtifacts, findLatestDashboard } from "./dashboard";

describe("findLatestDashboard", () => {
  const baseMessage = {
    role: "assistant" as const,
    content: "reply",
    timestamp: "2026-07-08T10:00:00Z",
    status: "complete" as const,
  };

  it("does not throw on persisted stub surfaces without components", () => {
    // Regression: opening a past chat crashed with
    // `can't access property "values", a.components is undefined`.
    const messages = [
      {
        ...baseMessage,
        id: "m-1",
        surfaces: [{ surfaceId: "s-stub" } as never],
      },
    ];

    expect(() => findLatestDashboard(messages)).not.toThrow();
    expect(findLatestDashboard(messages)).toBeNull();
  });

  it("finds the dashboard in a Map-based surface", () => {
    const messages = [
      {
        ...baseMessage,
        id: "m-1",
        surfaces: [
          {
            surfaceId: "s-1",
            catalogId: "openbench",
            components: new Map([
              [
                "root",
                {
                  id: "root",
                  component: "ObDashboardFrame",
                  title: "Sales Dashboard",
                  dashboardUrl: "/downloads/sales.html",
                },
              ],
            ]),
            dataModel: {},
          },
        ],
      },
    ];

    const artifact = findLatestDashboard(messages);
    expect(artifact).not.toBeNull();
    expect(artifact?.title).toBe("Sales Dashboard");
    expect(artifact?.url).toBe("/downloads/sales.html");
    expect(artifact?.surface.components.get("root")).toBeDefined();
  });

  it("keeps every dashboard artifact addressable by a stable key", () => {
    const messages = [
      {
        ...baseMessage,
        id: "m-1",
        surfaces: [
          {
            surfaceId: "s-1",
            catalogId: "openbench",
            components: new Map([
              [
                "root",
                {
                  id: "root",
                  component: "ObDashboardFrame",
                  title: "First Dashboard",
                  dashboardUrl: "/downloads/first.html",
                },
              ],
            ]),
            dataModel: {},
          },
        ],
      },
      {
        ...baseMessage,
        id: "m-2",
        surfaces: [
          {
            surfaceId: "s-2",
            catalogId: "openbench",
            components: new Map([
              [
                "root",
                {
                  id: "root",
                  component: "ObDashboardFrame",
                  title: "Second Dashboard",
                  dashboardUrl: "/downloads/second.html",
                },
              ],
            ]),
            dataModel: {},
          },
        ],
      },
    ];

    const artifacts = findDashboardArtifacts(messages);
    expect(artifacts.map((artifact) => artifact.title)).toEqual([
      "First Dashboard",
      "Second Dashboard",
    ]);
    expect(artifacts[0]?.key).toBe("m-1:s-1:root");
    expect(findLatestDashboard(messages)?.title).toBe("Second Dashboard");
  });

  it("returns null when no dashboard components exist", () => {
    const messages = [
      {
        ...baseMessage,
        id: "m-1",
        surfaces: [
          {
            surfaceId: "s-1",
            catalogId: "openbench",
            components: new Map([
              ["root", { id: "root", component: "Text", text: "plain" }],
            ]),
            dataModel: {},
          },
        ],
      },
    ];

    expect(findLatestDashboard(messages)).toBeNull();
  });
});

describe("DashboardArtifactPanel", () => {
  it("renders the exported HTML dashboard preview when ViewModel and dashboardUrl both exist", () => {
    const viewModel = {
      title: "Sales Dashboard",
      description: "Native dashboard data.",
      kpis: [{ label: "Revenue", value: 1200 }],
      sections: [],
      datasets: {},
    };
    const artifact = {
      key: "msg-1:surface-1:root",
      messageId: "msg-1",
      surfaceId: "surface-1",
      componentId: "root",
      title: "Sales Dashboard",
      url: "/downloads/sales.html",
      fileName: "sales.html",
      summary: "Native dashboard data.",
      surface: {
        surfaceId: "msg-1-dashboard-artifact",
        catalogId: "openbench",
        components: new Map([
          [
            "root",
            {
              id: "root",
              component: "ObDashboardFrame",
              title: "Sales Dashboard",
              dashboardUrl: "/downloads/sales.html",
              viewModel,
            },
          ],
        ]),
        dataModel: {},
      },
    };

    const { container } = render(
      <DashboardArtifactPanel artifact={artifact} onClose={vi.fn()} />,
    );

    expect(screen.getAllByText("Sales Dashboard").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-dashboard-renderer="html-export"]')).not.toBeNull();
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toBe("/downloads/sales.html");
  });

  it("renders maximize and minimize controls without replacing the open-in-new-tab link", async () => {
    const onToggleMaximized = vi.fn();
    const artifact = {
      key: "msg-1:surface-1:root",
      messageId: "msg-1",
      surfaceId: "surface-1",
      componentId: "root",
      title: "Sales Dashboard",
      url: "/downloads/sales.html",
      fileName: "sales.html",
      summary: "",
      surface: {
        surfaceId: "msg-1-dashboard-artifact",
        catalogId: "openbench",
        components: new Map([
          [
            "root",
            {
              id: "root",
              component: "ObDashboardFrame",
              title: "Sales Dashboard",
              dashboardUrl: "/downloads/sales.html",
            },
          ],
        ]),
        dataModel: {},
      },
    };

    const { rerender } = render(
      <DashboardArtifactPanel
        artifact={artifact}
        onClose={vi.fn()}
        onToggleMaximized={onToggleMaximized}
      />,
    );

    expect(screen.getByLabelText("Buka ekspor dashboard di tab baru")).toHaveAttribute(
      "href",
      "/downloads/sales.html",
    );
    await userEvent.click(screen.getByRole("button", { name: "Perbesar panel dashboard" }));
    expect(onToggleMaximized).toHaveBeenCalledTimes(1);

    rerender(
      <DashboardArtifactPanel
        artifact={artifact}
        isMaximized
        onClose={vi.fn()}
        onToggleMaximized={onToggleMaximized}
      />,
    );
    expect(screen.getByRole("button", { name: "Perkecil panel dashboard" })).toBeInTheDocument();
  });

  it("renders the exported HTML dashboard preview when ViewModel is inside legacy properties", () => {
    const viewModel = {
      title: "Dashboard Penjualan Kopi",
      description: "Native dashboard data.",
      kpis: [{ label: "Revenue", value: 1200 }],
      sections: [],
      datasets: {},
    };
    const artifact = {
      key: "msg-1:surface-1:root",
      messageId: "msg-1",
      surfaceId: "surface-1",
      componentId: "root",
      title: "Dashboard Penjualan Kopi",
      url: "/downloads/kopi.html",
      fileName: "kopi.html",
      summary: "Native dashboard data.",
      surface: {
        surfaceId: "msg-1-dashboard-artifact",
        catalogId: "openbench",
        components: new Map([
          [
            "root",
            {
              id: "root",
              component: "ObDashboardFrame",
              title: "Dashboard Penjualan Kopi",
              dashboardUrl: "/downloads/kopi.html",
              properties: { viewModel },
            },
          ],
        ]),
        dataModel: {},
      },
    };

    const { container } = render(
      <DashboardArtifactPanel artifact={artifact} onClose={vi.fn()} />,
    );

    expect(screen.getAllByText("Dashboard Penjualan Kopi").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-dashboard-renderer="html-export"]')).not.toBeNull();
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toBe("/downloads/kopi.html");
  });
});
