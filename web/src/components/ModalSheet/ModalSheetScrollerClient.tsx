import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { Sheet, SheetScrollerProps } from "react-modal-sheet";

function ModalSheetScrollerClient({
  children,
  draggableAt = "top",
  ...props
}: { children: React.ReactNode } & SheetScrollerProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  // Same-segment navigations (church A → church B) keep this scroller
  // instance mounted, so the previous scroll offset would carry over.
  useEffect(() => {
    if (scrollerRef.current) scrollerRef.current.scrollTop = 0;
  }, [pathname]);

  // The library's scroll-boundary → drag handoff (preventScrollMobileSafari)
  // only runs on iOS. We replicate it here for all platforms: when the scroller
  // is at a boundary and the user drags past it, preventDefault() stops the
  // browser from capturing the touch for scrolling and lets the gesture
  // propagate to Sheet.Content's motion drag handler.
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;

    let startY = 0;

    const onTouchStart = (e: TouchEvent) => {
      startY = e.touches[0]?.pageY ?? 0;
    };

    const onTouchMove = (e: TouchEvent) => {
      const currentY = e.touches[0]?.pageY ?? 0;
      const deltaY = currentY - startY;
      const { scrollTop, scrollHeight, clientHeight } = el;
      const isAtTop = scrollTop <= 0;
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 1;

      // deltaY > 0 → finger moved down → user pulling sheet down (at top)
      if ((draggableAt === "top" || draggableAt === "both") && isAtTop && deltaY > 0) {
        e.preventDefault();
      }
      // deltaY < 0 → finger moved up → user pulling sheet up (at bottom)
      if ((draggableAt === "bottom" || draggableAt === "both") && isAtBottom && deltaY < 0) {
        e.preventDefault();
      }
    };

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: false });

    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
    };
  }, [draggableAt]);

  return (
    <Sheet.Content>
      <Sheet.Scroller ref={scrollerRef} {...props} draggableAt={draggableAt}>
        {children}
      </Sheet.Scroller>
    </Sheet.Content>
  );
}

export default ModalSheetScrollerClient;
