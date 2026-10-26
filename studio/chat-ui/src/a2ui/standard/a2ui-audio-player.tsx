/**
 * A2UI AudioPlayer component (standard A2UI v0.10).
 */

import type { A2UIComponentRenderer } from "../../types";
import { resolveBoolean, resolveString } from "../data-binding";

export const A2UIAudioPlayer: A2UIComponentRenderer = ({ component, surface }) => {
  const src = resolveString(component.src ?? component.url, surface);
  const title = resolveString(component.title ?? "", surface);
  const autoplay = component.autoplay ? resolveBoolean(component.autoplay, surface) : false;

  return (
    <div className="a2ui-audio-player" data-component-id={component.id}>
      {title && <p className="a2ui-audio-player__title">{title}</p>}
      <audio
        className="a2ui-audio-player__player"
        src={src}
        autoPlay={autoplay}
        controls
        style={{ width: "100%" }}
      >
        Your browser does not support the audio element.
      </audio>
    </div>
  );
};
