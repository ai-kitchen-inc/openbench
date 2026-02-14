/**
 * OpenBench custom A2UI component catalog.
 */

import type { ComponentCatalog } from "../../types";

import { ObChart } from "./ob-chart";
import { ObCodeBlock } from "./ob-code-block";
import { ObFileCard } from "./ob-file-card";
import { ObMarkdown } from "./ob-markdown";

export const CUSTOM_CATALOG: ComponentCatalog = {
  ObChart,
  ObFileCard,
  ObCodeBlock,
  ObMarkdown,
};

export { ObChart, ObFileCard, ObCodeBlock, ObMarkdown };
