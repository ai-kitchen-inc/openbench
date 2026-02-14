/**
 * A2UI Modal component.
 *
 * Overlay dialog that renders children in a centered panel.
 */

import { useEffect, useRef } from "react";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString } from "../data-binding";

export const A2UIModal: A2UIComponentRenderer = ({ component, surface, children }) => {
  const title = resolveString(component.title ?? "", surface);
  const open = component.open != null ? resolveBoolean(component.open, surface) : true;
  const backdropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="a2ui-modal"
      data-component-id={component.id}
      ref={backdropRef}
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "rgba(0,0,0,0.5)",
        zIndex: 1000,
      }}
    >
      <div
        className="a2ui-modal__panel"
        role="dialog"
        aria-label={title}
        style={{
          backgroundColor: "var(--a2ui-card-bg, #ffffff)",
          borderRadius: "12px",
          padding: "24px",
          maxWidth: "600px",
          width: "90%",
          maxHeight: "80vh",
          overflowY: "auto",
        }}
      >
        {title && <h2 className="a2ui-modal__title">{title}</h2>}
        {children}
      </div>
    </div>
  );
};
