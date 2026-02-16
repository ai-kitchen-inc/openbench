/**
 * OpenBench custom A2UI component catalog.
 */

import type { ComponentCatalog } from "../../types";

import { ObCallout } from "./ob-callout";
import { ObChart } from "./ob-chart";
import { ObCodeBlock } from "./ob-code-block";
import { ObFileCard } from "./ob-file-card";
import { ObMarkdown } from "./ob-markdown";
import { ObTable } from "./ob-table";

export const CUSTOM_CATALOG: ComponentCatalog = {
  ObChart,
  ObFileCard,
  ObCodeBlock,
  ObMarkdown,
  ObTable,
  ObCallout,
};

export { ObChart, ObFileCard, ObCodeBlock, ObMarkdown, ObTable, ObCallout };
