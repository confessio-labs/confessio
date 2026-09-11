// Tracks whether a router.push is in flight. Used by the map's setBounds
// shallow-routing call (window.history.replaceState) to avoid clobbering an
// in-flight Next.js navigation transition — a moveend that fires from a
// layout shift right after router.push will otherwise replace the history
// entry the transition is waiting to commit, silently aborting the navigation.
//
// markNavigationPending() is called immediately before router.push.
// The lock is auto-released on the next pathname change (commit) or after a
// timeout safety net in case the navigation aborts for some other reason.

let pendingUntil = 0;

export const markNavigationPending = (durationMs = 3000) => {
  pendingUntil = performance.now() + durationMs;
};

export const clearNavigationPending = () => {
  pendingUntil = 0;
};

export const isNavigationPending = () => performance.now() < pendingUntil;
