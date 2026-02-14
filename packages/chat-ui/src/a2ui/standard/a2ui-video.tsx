/**
 * A2UI Video component (standard A2UI v0.10).
 */

import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString } from "../data-binding";

export const A2UIVideo: A2UIComponentRenderer = ({ component, surface }) => {
  const src = resolveString(component.src ?? component.url, surface);
  const title = resolveString(component.title ?? "", surface);
  const poster = component.poster ? resolveString(component.poster, surface) : undefined;
  const autoplay = component.autoplay ? resolveBoolean(component.autoplay, surface) : false;
  const width = (component.width as string) ?? "100%";
  const height = (component.height as string) ?? undefined;

  return (
    <div className="a2ui-video" data-component-id={component.id}>
      {title && <p className="a2ui-video__title">{title}</p>}
      <video
        className="a2ui-video__player"
        src={src}
        poster={poster}
        autoPlay={autoplay}
        controls
        style={{ width, height, borderRadius: "8px" }}
      >
        <track kind="captions" />
      </video>
    </div>
  );
};
