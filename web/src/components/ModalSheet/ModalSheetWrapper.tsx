"use client";

import { Suspense } from "react";
import ModalSheet from "../ModalSheet";
import { AggregatedSearchResults } from "@/utils";
import { components } from "@/types";

function ModalSheetWrapper({
  originalSearchResults,
  selectedChurch,
}: {
  originalSearchResults?: AggregatedSearchResults | null | undefined;
  selectedChurch?: components["schemas"]["ChurchDetails"];
}) {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <ModalSheet
        originalSearchResults={originalSearchResults}
        selectedChurch={selectedChurch}
      />
    </Suspense>
  );
}

export default ModalSheetWrapper;
