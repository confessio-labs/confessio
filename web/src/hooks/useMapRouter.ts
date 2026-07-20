import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { markNavigationPending } from "@/lib/navigationLock";

// Drop-in replacement for next/navigation's useRouter when the navigation
// happens from a component mounted alongside the map. Engages the navigation
// lock before each transition so a concurrent map moveend → setBounds →
// replaceState can't clobber the in-flight router transition. See
// src/lib/navigationLock.ts and src/hooks/useMapBounds.ts.
//
// Only push/replace are wrapped — the other router methods (back, forward,
// refresh, prefetch) aren't currently used from map-mounted components; if
// you need one and it triggers a transition, extend this hook rather than
// reaching for useRouter directly.
export const useMapRouter = () => {
  const router = useRouter();
  return useMemo(() => {
    const push: typeof router.push = (...args) => {
      markNavigationPending();
      return router.push(...args);
    };
    const replace: typeof router.replace = (...args) => {
      markNavigationPending();
      return router.replace(...args);
    };
    return { push, replace };
  }, [router]);
};
