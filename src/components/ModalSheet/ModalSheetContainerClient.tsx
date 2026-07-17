import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { Sheet, SheetRef } from "react-modal-sheet";
import { SheetRefContext } from "./SheetContext";

const SNAP_POINTS: number[] = [0.9, 0.5, 140];
const BOTTOM_SNAP_PX = 140;

function ModalSheetContainerClient({
  children,
}: {
  children: React.ReactNode;
}) {
  const sheetRef = useRef<SheetRef>(null);
  const pathname = usePathname();
  const prevPathnameRef = useRef<string | null>(null);

  // The sheet persists across navigations (mounted in the @modal layout), so
  // snap points no longer reset via remount — set them per transition instead.
  // On first mount a list route keeps the initialSnap entrance animation; a
  // church deep link snaps up like any church navigation.
  useEffect(() => {
    const prev = prevPathnameRef.current;
    prevPathnameRef.current = pathname;
    if (prev === pathname) return;
    if (pathname.startsWith("/church/")) sheetRef.current?.snapTo(1);
    else if (prev !== null) sheetRef.current?.snapTo(2);
  }, [pathname]);

  // Hard-stop at the bottom snap point during drag.
  // The library only constrains the TOP snap in onDrag; the bottom is
  // unconstrained (it snaps back on release but overshoots visually).
  // We subscribe to the y MotionValue and clamp — but only when crossing
  // the boundary from at-or-below (drag down), not from above (animations
  // like the initial open that start from windowHeight).
  useEffect(() => {
    const ref = sheetRef.current;
    if (!ref) return;

    let bottomSnapY: number | null = null;
    let prevY = ref.y.get();

    return ref.y.on("change", (latest: number) => {
      if (bottomSnapY === null) {
        const sheetEl = document.querySelector(".react-modal-sheet-container");
        if (!sheetEl) return;
        bottomSnapY =
          Math.round(sheetEl.getBoundingClientRect().height) - BOTTOM_SNAP_PX;
      }

      if (prevY <= bottomSnapY && latest > bottomSnapY) {
        ref.y.jump(bottomSnapY);
        prevY = bottomSnapY;
      } else {
        prevY = latest;
      }
    });
  }, []);

  return (
    <Sheet
      isOpen
      ref={sheetRef}
      snapPoints={SNAP_POINTS}
      initialSnap={2}
      tweenConfig={{ ease: "easeOut", duration: 0.3 }}
      dragCloseThreshold={1}
      onClose={() => sheetRef.current?.snapTo(2)}
      style={{ zIndex: 30 }}
    >
      <Sheet.Container>
        <Sheet.Header />
        <SheetRefContext.Provider value={sheetRef}>
          {children}
        </SheetRefContext.Provider>
      </Sheet.Container>
    </Sheet>
  );
}

export default ModalSheetContainerClient;
