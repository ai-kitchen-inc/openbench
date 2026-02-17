/**
 * A2UI Modal component.
 *
 * Overlay dialog that renders children in a centered panel.
 * Supports close button (X), backdrop click dismiss, and Escape key.
 */

import { useEffect, useRef, useState } from "react";
import { isDataBinding, nowISO } from "../../core/utils";
import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString, setAtPath } from "../data-binding";

export const A2UIModal: A2UIComponentRenderer = ({ component, surface, onAction, children }) => {
  const title = resolveString(component.title ?? "", surface);
  const open = component.open != null ? resolveBoolean(component.open, surface) : true;
  const backdropRef = useRef<HTMLDivElement>(null);

  const [forceClosed, setForceClosed] = useState(false);

  const openBindingPath = isDataBinding(component.open)
    ? (component.open as { path: string }).path
    : null;

  const handleClose = () => {
    setForceClosed(true);
    if (openBindingPath) setAtPath(surface.dataModel, openBindingPath, false);
    if (onAction) {
      onAction({
        name: "close",
        surfaceId: surface.surfaceId,
        sourceComponentId: component.id,
        timestamp: nowISO(),
        context: {},
      });
    }
  };

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === backdropRef.current) {
      handleClose();
    }
  };

  useEffect(() => {
    if (!open || forceClosed) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [open, forceClosed, handleClose]);

  if (!open || forceClosed) return null;

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: Modal backdrop dismiss is intentional
    <div
      className="a2ui-modal"
      data-component-id={component.id}
      ref={backdropRef}
      onClick={handleBackdropClick}
      onKeyDown={(e) => {
        if (e.key === "Escape") handleClose();
      }}
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
          backgroundColor: "var(--ob-card-bg, #ffffff)",
          borderRadius: "12px",
          maxWidth: "600px",
          width: "90%",
          maxHeight: "80vh",
          overflowY: "auto",
        }}
      >
        <div className="a2ui-modal__header">
          <h2 className="a2ui-modal__title">{title}</h2>
          <button
            className="a2ui-modal__close"
            onClick={handleClose}
            aria-label="Close"
            type="button"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M18 6L6 18M6 6l12 12"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
        <div className="a2ui-modal__body">{children}</div>
      </div>
    </div>
  );
};
