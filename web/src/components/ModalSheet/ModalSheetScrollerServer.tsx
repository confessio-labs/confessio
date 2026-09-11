import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

function ModalSheetScrollerServer({ children }: { children: React.ReactNode }) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  // Same-segment navigations (church A → church B) keep this scroller
  // instance mounted, so the previous scroll offset would carry over.
  useEffect(() => {
    if (scrollerRef.current) scrollerRef.current.scrollTop = 0;
  }, [pathname]);

  return (
    <div ref={scrollerRef} className="min-h-0 overflow-auto">
      {children}
    </div>
  );
}

export default ModalSheetScrollerServer;
