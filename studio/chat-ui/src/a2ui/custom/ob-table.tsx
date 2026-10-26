/**
 * ObTable — OpenBench custom structured table component.
 *
 * Renders tabular data with headers and rows. Supports striped
 * rows and compact mode for dense data display.
 */

import { useChatContextOptional } from "../../components/ChatProvider";
import type { A2UIComponentRenderer, TableExportOption } from "../../types";
import { resolveBoolean, resolveValue } from "../data-binding";

/** English defaults; hosts localize via ChatConfig.tableExport.formats. */
const DEFAULT_EXPORT_FORMATS: TableExportOption[] = [
  {
    id: "xlsx",
    label: "Excel",
    prompt: "Export the table above to an Excel (.xlsx) file I can download.",
  },
  {
    id: "pdf",
    label: "PDF",
    prompt: "Export the table above to a PDF file I can download.",
  },
  {
    id: "md",
    label: "Markdown",
    prompt: "Export the table above to a Markdown (.md) file I can download.",
  },
];

function formatCell(value: unknown): string {
  if (value == null) return "";
  if (Array.isArray(value)) {
    return value.map(formatCell).filter(Boolean).join(", ");
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const preferred = record.value ?? record.label ?? record.name ?? record.title;
    if (preferred !== undefined) return formatCell(preferred);
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value);
}

/** Export shortcuts under a table.
 *
 * Clicking one sends an ordinary user turn rather than calling an export
 * endpoint directly: the agent already owns the export tools, and routing
 * through a normal message keeps the request, the file card, and the
 * agent's confirmation in one conversation. Renders nothing outside a
 * ChatProvider (e.g. in isolated component tests). */
function TableExportBar() {
  const chat = useChatContextOptional();
  if (!chat) return null;
  const config = chat.tableExport;
  if (config?.enabled === false) return null;
  const formats = config?.formats ?? DEFAULT_EXPORT_FORMATS;
  if (formats.length === 0) return null;

  return (
    <div className="ob-table__export">
      <span className="ob-table__export-label">{config?.label ?? "Export:"}</span>
      {formats.map((format) => (
        <button
          key={format.id}
          type="button"
          className="ob-table__export-button"
          disabled={chat.isStreaming}
          onClick={() => chat.sendMessage(format.prompt)}
        >
          {format.label}
        </button>
      ))}
    </div>
  );
}

export const ObTable: A2UIComponentRenderer = ({ component, surface }) => {
  const rawHeaders = resolveValue(component.headers, surface);
  const rawRows = resolveValue(component.rows, surface);
  const headers = Array.isArray(rawHeaders) ? rawHeaders.map(formatCell) : [];
  const rows = Array.isArray(rawRows) ? rawRows : [];
  const striped = component.striped != null ? resolveBoolean(component.striped, surface) : true;
  const compact = component.compact != null ? resolveBoolean(component.compact, surface) : false;

  const tableClasses = [
    "ob-table__table",
    striped && "ob-table__table--striped",
    compact && "ob-table__table--compact",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="ob-table" data-component-id={component.id}>
      <div className="ob-table__scroll">
        <table className={tableClasses}>
          <thead>
            <tr>
              {headers.map((header, i) => (
                <th key={i} className="ob-table__th">
                  {String(header)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIdx) => (
              <tr key={rowIdx} className="ob-table__row">
                {(Array.isArray(row) ? row : []).map((cell, cellIdx) => (
                  <td key={cellIdx} className="ob-table__td">
                    {formatCell(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <TableExportBar />
    </div>
  );
};
