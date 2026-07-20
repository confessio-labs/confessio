"use client";
import { ReactNode } from "react";
import ModalSheetDragZoneClient from "./ModalSheetDragZoneClient";
import { useIsMobile } from "@/hooks/useIsMobile";

const ModalSheetDragZone = ({ children }: { children: ReactNode }) => {
  const isMobile = useIsMobile();
  if (isMobile)
    return <ModalSheetDragZoneClient>{children}</ModalSheetDragZoneClient>;
  return <>{children}</>;
};

export default ModalSheetDragZone;
