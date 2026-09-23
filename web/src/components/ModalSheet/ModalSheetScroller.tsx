import { ReactNode } from "react";
import ModalSheetScrollerServer from "./ModalSheetScrollerServer";
import ModalSheetScrollerClient from "./ModalSheetScrollerClient";
import { SheetScrollerProps } from "react-modal-sheet";
import { useIsMobile } from "@/hooks/useIsMobile";

const ModalSheetScroller = ({
  children,
  ...props
}: { children: ReactNode } & SheetScrollerProps) => {
  const isMobile = useIsMobile();
  if (isMobile)
    return (
      <ModalSheetScrollerClient {...props}>{children}</ModalSheetScrollerClient>
    );
  return (
    <ModalSheetScrollerServer {...props}>{children}</ModalSheetScrollerServer>
  );
};

export default ModalSheetScroller;
