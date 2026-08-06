"use client";
import { createContext, createElement, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { MOBILE_BREAKPOINT } from "@/utils";

const IsMobileContext = createContext(false);

// Single source of truth so all consumers flip the breakpoint atomically.
export const IsMobileProvider = ({ children }: { children: ReactNode }) => {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    const update = () => setIsMobile(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);
  return createElement(IsMobileContext.Provider, { value: isMobile }, children);
};

export const useIsMobile = () => useContext(IsMobileContext);
