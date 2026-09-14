/** Dashboard artifact discovery + side panel, extracted from the legacy
 * general-chat UI. */
import {
  SurfaceRenderer,
  type A2UIComponent,
  type A2UISurface,
  type ChatMessage,
} from "@openbench/chat-ui";

export type DashboardArtifact = {
  key: string;
  messageId: string;
  surfaceId: string;
  componentId: string;
  title: string;
  url?: string;
  fileName: string;
  summary: string;
  fileSize?: number;
  surface: A2UISurface;
};

function componentString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function componentNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function componentValue(component: A2UIComponent, key: string): unknown {
  if (component[key] !== undefined) return component[key];
  const nestedProperties = component.properties;
  if (isRecord(nestedProperties)) return nestedProperties[key];
  return undefined;
}

function hasDashboardData(component: A2UIComponent): boolean {
  return Boolean(
    componentValue(component, "viewModel") ??
      componentValue(component, "view_model") ??
      componentValue(component, "datasets") ??
      componentValue(component, "kpis") ??
      componentValue(component, "sections"),
  );
}

function dashboardArtifactSurface(
  messageId: string,
  sourceSurface: A2UISurface,
  component: A2UIComponent,
): A2UISurface {
  const rootComponent = { ...component, id: "root" };
  return {
    surfaceId: `${messageId}-${sourceSurface.surfaceId}-${component.id}-dashboard-artifact`,
    catalogId: sourceSurface.catalogId,
    components: new Map([["root", rootComponent]]),
    dataModel: sourceSurface.dataModel ?? {},
    theme: sourceSurface.theme,
    sendDataModel: sourceSurface.sendDataModel,
  };
}

export function findLatestDashboard(messages: ChatMessage[]): DashboardArtifact | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    const surfaces = message.surfaces ?? [];
    for (let surfaceIndex = surfaces.length - 1; surfaceIndex >= 0; surfaceIndex -= 1) {
      const surface = surfaces[surfaceIndex];
      // Persisted legacy sessions can carry surface stubs without a
      // components Map — skip them instead of crashing the chat layout.
      const surfaceComponents = surface?.components;
      if (!surfaceComponents || typeof surfaceComponents.values !== "function") continue;
      const components = Array.from(surfaceComponents.values()).reverse();
      for (const component of components) {
        if (component.component !== "ObDashboardFrame") continue;
        const url = componentString(
          componentValue(component, "dashboardUrl") ?? componentValue(component, "url"),
        );
        if (!url && !hasDashboardData(component)) continue;
        return {
          key: `${message.id}:${surface.surfaceId}:${component.id}`,
          messageId: message.id,
          surfaceId: surface.surfaceId,
          componentId: component.id,
          title: componentString(componentValue(component, "title")) || "Dashboard",
          url: url || undefined,
          fileName: componentString(componentValue(component, "fileName")) || "dashboard.html",
          summary: componentString(
            componentValue(component, "summary") ?? componentValue(component, "description"),
          ),
          fileSize: componentNumber(componentValue(component, "fileSize")),
          surface: dashboardArtifactSurface(message.id, surface, component),
        };
      }
    }
  }
  return null;
}

export function dashboardArtifactsForSurface(
  message: ChatMessage,
  surface: A2UISurface,
): DashboardArtifact[] {
  const surfaceComponents = surface?.components;
  if (!surfaceComponents || typeof surfaceComponents.values !== "function") return [];
  const artifacts: DashboardArtifact[] = [];
  for (const component of surfaceComponents.values()) {
    if (component.component !== "ObDashboardFrame") continue;
    const url = componentString(
      componentValue(component, "dashboardUrl") ?? componentValue(component, "url"),
    );
    if (!url && !hasDashboardData(component)) continue;
    artifacts.push({
      key: `${message.id}:${surface.surfaceId}:${component.id}`,
      messageId: message.id,
      surfaceId: surface.surfaceId,
      componentId: component.id,
      title: componentString(componentValue(component, "title")) || "Dashboard",
      url: url || undefined,
      fileName: componentString(componentValue(component, "fileName")) || "dashboard.html",
      summary: componentString(
        componentValue(component, "summary") ?? componentValue(component, "description"),
      ),
      fileSize: componentNumber(componentValue(component, "fileSize")),
      surface: dashboardArtifactSurface(message.id, surface, component),
    });
  }
  return artifacts;
}

export function findDashboardArtifacts(messages: ChatMessage[]): DashboardArtifact[] {
  const artifacts: DashboardArtifact[] = [];
  for (const message of messages) {
    const surfaces = message.surfaces ?? [];
    for (const surface of surfaces) {
      artifacts.push(...dashboardArtifactsForSurface(message, surface));
    }
  }
  return artifacts;
}

function formatArtifactSize(value: number | undefined): string {
  if (value == null) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function DashboardArtifactPanel({
  artifact,
  isMaximized = false,
  onToggleMaximized,
  onClose,
}: {
  artifact: DashboardArtifact;
  isMaximized?: boolean;
  onToggleMaximized?: () => void;
  onClose: () => void;
}) {
  const sizeText = formatArtifactSize(artifact.fileSize);
  return (
    <aside
      className={`dashboard-artifact${isMaximized ? " dashboard-artifact--maximized" : ""}`}
      aria-label="Artefak dashboard"
    >
      <div className="dashboard-artifact__header">
        <div className="dashboard-artifact__title-wrap">
          <div className="dashboard-artifact__eyebrow">Dashboard</div>
          <h2 className="dashboard-artifact__title">{artifact.title}</h2>
          <div className="dashboard-artifact__meta">
            {artifact.fileName}
            {sizeText ? ` - ${sizeText}` : ""}
          </div>
        </div>
        {artifact.url && (
          <a
            className="dashboard-artifact__icon-btn"
            href={artifact.url}
            target="_blank"
            rel="noreferrer"
            aria-label="Buka ekspor dashboard di tab baru"
            title="Buka ekspor dashboard"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M15 3h6v6" />
              <path d="M10 14 21 3" />
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            </svg>
          </a>
        )}
        <button
          type="button"
          className="dashboard-artifact__icon-btn"
          onClick={onToggleMaximized}
          aria-label={isMaximized ? "Perkecil panel dashboard" : "Perbesar panel dashboard"}
          title={isMaximized ? "Perkecil dashboard" : "Perbesar dashboard"}
        >
          {isMaximized ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M8 3v5H3" />
              <path d="M21 8h-5V3" />
              <path d="M16 21v-5h5" />
              <path d="M3 16h5v5" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M15 3h6v6" />
              <path d="M9 21H3v-6" />
              <path d="M21 3 14 10" />
              <path d="M3 21l7-7" />
            </svg>
          )}
        </button>
        <button
          type="button"
          className="dashboard-artifact__icon-btn"
          onClick={onClose}
          aria-label="Tutup panel dashboard"
          title="Tutup dashboard"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>
      </div>
      {artifact.summary && <div className="dashboard-artifact__summary">{artifact.summary}</div>}
      <div className="dashboard-artifact__surface">
        <SurfaceRenderer surface={artifact.surface} />
      </div>
    </aside>
  );
}
