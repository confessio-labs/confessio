"use client";

import { useEffect } from "react";

export default function DioceseRedirect({
  boundsStr,
}: {
  boundsStr: string;
}) {
  useEffect(() => {
    window.history.replaceState(null, "", `/?bounds=${boundsStr}`);
  }, [boundsStr]);

  return null;
}
