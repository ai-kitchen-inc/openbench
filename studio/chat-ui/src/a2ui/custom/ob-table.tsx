/**
 * ObTable — OpenBench custom structured table component.
 *
 * Renders tabular data with headers and rows. Supports striped
 * rows and compact mode for dense data display.
 */

import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveValue } from "../data-binding";

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
    </div>
  );
};
