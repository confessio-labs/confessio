import ModalSheetContainer from "@/components/ModalSheet/ModalSheetContainer";

// The sheet container lives in the slot layout so it stays mounted across
// navigations; pages only swap the sheet's content.
export default function ModalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ModalSheetContainer>{children}</ModalSheetContainer>;
}
