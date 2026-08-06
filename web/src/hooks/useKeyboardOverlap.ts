import { useEffect, useState } from "react";

// iOS Safari: the on-screen keyboard overlays the page instead of resizing
// it, so fixed/fullscreen layouts keep their full height and content near
// the bottom ends up hidden behind the keyboard (no CSS unit accounts for
// the keyboard on iOS). The VisualViewport API is the only reliable signal:
// its height shrinks when the keyboard opens. This hook returns how many
// pixels of the layout viewport the keyboard covers, so callers can add
// bottom padding and/or scroll the focused element above the keyboard.
// On Android the keyboard resizes window.innerHeight as well, so the
// overlap computes to ~0 and this is a no-op there.
export const useKeyboardOverlap = (enabled: boolean) => {
  const [overlap, setOverlap] = useState(0);

  useEffect(() => {
    const visualViewport = window.visualViewport;
    if (!visualViewport || !enabled) {
      setOverlap(0);
      return;
    }
    const updateOverlap = () => {
      // Portion of the layout viewport hidden below the visual viewport
      // (i.e. covered by the keyboard). offsetTop matters when iOS scrolls
      // the visual viewport to keep the focused input visible.
      setOverlap(
        Math.max(
          0,
          window.innerHeight - visualViewport.height - visualViewport.offsetTop,
        ),
      );
    };
    updateOverlap();
    visualViewport.addEventListener("resize", updateOverlap);
    visualViewport.addEventListener("scroll", updateOverlap);
    return () => {
      visualViewport.removeEventListener("resize", updateOverlap);
      visualViewport.removeEventListener("scroll", updateOverlap);
    };
  }, [enabled]);

  return overlap;
};
