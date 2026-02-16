/**
 * ObTable — OpenBench custom structured table component.
 *
 * Renders tabular data with headers and rows. Supports striped
 * rows and compact mode for dense data display.
 */

import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveValue } from "../data-binding";

export const ObTable: A2UIComponentRenderer = ({ component, surface }) => {
  const rawHeaders = resolveValue(component.headers, surface);
  const rawRows = resolveValue(component.rows, surface);
  const headers = Array.isArray(rawHeaders) ? (rawHeaders as string[]) : [];
  const rows = Array.isArray(rawRows) ? (rawRows as string[][]) : [];
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
                    {String(cell ?? "")}
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
