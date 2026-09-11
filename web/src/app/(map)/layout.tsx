import ModalSheetContainer from "@/components/ModalSheet/ModalSheetContainer";

// The sheet container lives in this route-group layout so it stays mounted
// across all map-route navigations (list ↔ church ↔ diocese); the @modal slot
// pages only swap the sheet's content. It must not live in a parallel-route
// slot layout: slot subtrees are keyed in the router cache and remount on
// navigation (verified empirically). Routes outside (map) — e.g. a future
// home page — render no sheet at all.
export default function MapLayout({
  children,
  modal,
  map,
}: {
  children: React.ReactNode;
  modal: React.ReactNode;
  map: React.ReactNode;
}) {
  return (
    <>
      {children}
      <ModalSheetContainer>{modal}</ModalSheetContainer>
      {map}
    </>
  );
}
