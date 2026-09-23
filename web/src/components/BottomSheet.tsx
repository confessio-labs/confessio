import { components } from "@/types";
import React, { useState, useRef, useEffect, useCallback } from "react";

const BottomSheet = ({
  searchResults,
}: {
  searchResults: components["schemas"]["SearchResultOut"] | undefined;
}) => {
  const [position, setPosition] = useState<"bottom" | "top">("bottom");
  const [isDragging, setIsDragging] = useState(false);
  const [dragY, setDragY] = useState(0);
  const [startY, setStartY] = useState(0);
  const [velocity, setVelocity] = useState(0);
  const [lastMoveTime, setLastMoveTime] = useState(0);
  const [lastMoveY, setLastMoveY] = useState(0);
  const [initialViewportHeight, setInitialViewportHeight] = useState(0);

  const sheetRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);

  // Store initial viewport height to avoid browser UI interference
  useEffect(() => {
    const setVH = () => {
      const vh = window.innerHeight * 0.01;
      document.documentElement.style.setProperty("--vh", `${vh}px`);
      setInitialViewportHeight(window.innerHeight);
    };

    setVH();

    // Update on resize, but debounce to avoid too many updates
    let resizeTimer: NodeJS.Timeout;
    const handleResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(setVH, 150);
    };

    window.addEventListener("resize", handleResize);
    window.addEventListener("orientationchange", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("orientationchange", handleResize);
      clearTimeout(resizeTimer);
    };
  }, []);

  // Calculate sheet transform based on position and drag
  const getTransform = useCallback(() => {
    const viewportHeight = initialViewportHeight || window.innerHeight;

    if (isDragging) {
      const dragOffset = Math.max(0, dragY);
      if (position === "top") {
        return `translateY(${Math.min(dragOffset, viewportHeight * 0.9)}px)`;
      } else {
        return `translateY(${Math.min(
          dragOffset + viewportHeight * 0.8,
          viewportHeight,
        )}px)`;
      }
    }

    return position === "top" ? "translateY(74px)" : "translateY(80vh)";
  }, [isDragging, dragY, position, initialViewportHeight]);

  // Handle drag start
  const handleDragStart = useCallback((clientY: number) => {
    setIsDragging(true);
    setStartY(clientY);
    setDragY(0);
    setVelocity(0);
    setLastMoveTime(Date.now());
    setLastMoveY(clientY);

    // Prevent content scrolling during drag
    if (contentRef.current) {
      contentRef.current.style.overflowY = "hidden";
    }
  }, []);

  // Handle drag move
  const handleDragMove = useCallback(
    (clientY: number) => {
      if (!isDragging) return;

      const now = Date.now();
      const deltaY = clientY - startY;
      setDragY(deltaY);

      // Calculate velocity for momentum
      if (now - lastMoveTime > 0) {
        const newVelocity = (clientY - lastMoveY) / (now - lastMoveTime);
        setVelocity(newVelocity);
      }

      setLastMoveTime(now);
      setLastMoveY(clientY);
    },
    [isDragging, startY, lastMoveTime, lastMoveY],
  );

  // Handle drag end with momentum
  const handleDragEnd = useCallback(() => {
    if (!isDragging) return;

    setIsDragging(false);

    // Re-enable content scrolling
    if (contentRef.current) {
      contentRef.current.style.overflowY = "auto";
    }

    const viewportHeight = initialViewportHeight || window.innerHeight;
    const threshold = viewportHeight * 0.2;
    const momentumThreshold = 0.5;

    // Determine next position based on drag distance and velocity
    if (position === "top") {
      if (dragY > threshold || velocity > momentumThreshold) {
        setPosition("bottom");
      }
    } else {
      if (dragY < -threshold || velocity < -momentumThreshold) {
        setPosition("top");
      } else if (dragY > threshold || velocity > momentumThreshold) {
        // setIsOpen(false);
      }
    }

    setDragY(0);
    setVelocity(0);
  }, [isDragging, dragY, velocity, position, initialViewportHeight]);

  // Handle scroll beyond top to dismiss
  const [isScrollDragging, setIsScrollDragging] = useState(false);
  const [scrollStartY, setScrollStartY] = useState(0);

  const handleTouchStartOnContent = useCallback(
    (e: React.TouchEvent) => {
      const scrollTop = contentRef.current?.scrollTop || 0;
      if (scrollTop <= 0 && position === "top") {
        const touch = e.touches[0];
        if (touch) {
          setScrollStartY(touch.clientY);
          setIsScrollDragging(true);
        }
      }
    },
    [position],
  );

  const handleTouchMoveOnContent = useCallback(
    (e: React.TouchEvent) => {
      if (!isScrollDragging) return;

      const touch = e.touches[0];
      if (!touch) return;

      const deltaY = touch.clientY - scrollStartY;
      const scrollTop = contentRef.current?.scrollTop || 0;

      // If we're at the top and trying to scroll up (pull down)
      if (scrollTop <= 0 && deltaY > 0) {
        e.preventDefault(); // Prevent rubber band effect and browser UI

        // Convert to drag gesture
        if (!isDragging) {
          handleDragStart(scrollStartY);
        }
        handleDragMove(touch.clientY);
      }
    },
    [
      isScrollDragging,
      scrollStartY,
      isDragging,
      handleDragStart,
      handleDragMove,
    ],
  );

  const handleTouchEndOnContent = useCallback(() => {
    if (isScrollDragging) {
      setIsScrollDragging(false);
      if (isDragging) {
        handleDragEnd();
      }
    }
  }, [isScrollDragging, isDragging, handleDragEnd]);

  // Touch event handlers
  const handleTouchStart = (e: React.TouchEvent) => {
    e.preventDefault(); // Prevent browser UI from showing
    const touch = e.touches[0];
    if (touch) {
      handleDragStart(touch.clientY);
    }
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    e.preventDefault(); // Prevent page scroll and browser UI
    const touch = e.touches[0];
    if (touch) {
      handleDragMove(touch.clientY);
    }
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    e.preventDefault(); // Prevent browser UI from showing
    handleDragEnd();
  };

  // Mouse event handlers for desktop testing
  const handleMouseDown = (e: React.MouseEvent) => {
    handleDragStart(e.clientY);
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      handleDragMove(e.clientY);
    };

    const handleMouseUp = () => {
      handleDragEnd();
    };

    // Add/remove mouse event listeners
    if (isDragging) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      return () => {
        document.removeEventListener("mousemove", handleMouseMove);
        document.removeEventListener("mouseup", handleMouseUp);
      };
    }
  }, [isDragging, handleDragMove, handleDragEnd]);

  // Keyboard accessibility
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
    } else if (e.key === "Enter" || e.key === " ") {
      if ((e.target as HTMLElement).dataset.action === "toggle-position") {
        e.preventDefault();
        setPosition(position === "top" ? "bottom" : "top");
      }
    }
  };

  // Focus management
  useEffect(() => {
    if (sheetRef.current) {
      sheetRef.current.focus();
    }
  }, []);

  return (
    <div
      ref={sheetRef}
      className={`fixed inset-x-0 bottom-0 bg-deepblue rounded-t-3xl shadow-2xl transition-transform duration-300 ease-out ${
        isDragging ? "transition-none" : "transition-transform"
      }`}
      style={{
        transform: getTransform(),
        zIndex: 80,
        height: "calc(var(--vh, 1vh) * 100)",
        maxHeight: "calc(var(--vh, 1vh) * 100)",
        touchAction: "none", // Prevent browser touch gestures
        WebkitTouchCallout: "none", // Prevent callout on iOS
        WebkitUserSelect: "none", // Prevent text selection
        userSelect: "none",
        WebkitOverflowScrolling: "touch", // Smooth scrolling on iOS
      }}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      onKeyDown={handleKeyDown}
    >
      {/* Drag handle */}
      <div
        className="flex justify-center pt-4 pb-2 cursor-grab active:cursor-grabbing"
        style={{
          touchAction: "none", // Prevent browser touch gestures
          WebkitTouchCallout: "none", // Prevent callout on iOS
          WebkitUserSelect: "none", // Prevent text selection
          userSelect: "none",
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onMouseDown={handleMouseDown}
        data-action="toggle-position"
        tabIndex={0}
        role="button"
        aria-label={`Drag to ${
          position === "top" ? "minimize" : "expand"
        } sheet`}
      >
        <div className="w-12 h-1.5 bg-gray-300 rounded-full" />
      </div>
      {/* Scrollable content */}
      <div
        ref={contentRef}
        className="flex-1 overflow-y-auto"
        style={{ height: "calc(var(--vh, 1vh) * 100 - 120px)" }}
        onTouchStart={handleTouchStartOnContent}
        onTouchMove={handleTouchMoveOnContent}
        onTouchEnd={handleTouchEndOnContent}
      >
        <div className="p-4 space-y-4">
          {searchResults?.churches?.map((item) => (
            <div
              key={item.uuid}
              className="p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
            >
              <h3 className="font-medium text-gray-900 mb-2">{item.name}</h3>
              <p className="text-sm text-gray-600">{item.address}</p>
            </div>
          ))}
        </div>

        {/* Extra padding at bottom */}
        <div className="h-20" />
      </div>
    </div>
  );
};

export default BottomSheet;
