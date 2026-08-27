import { Sheet } from "react-modal-sheet";

function ModalSheetDragZoneClient({
  children,
}: {
  children: React.ReactNode;
}) {
  return <Sheet.Header>{children}</Sheet.Header>;
}

export default ModalSheetDragZoneClient;
