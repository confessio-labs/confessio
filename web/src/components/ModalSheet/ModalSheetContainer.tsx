"use client";
import { ReactNode } from "react";
import ModalSheetContainerClient from "./ModalSheetContainerClient";
import ModalSheetContainerServer from "./ModalSheetContainerServer";
import { useIsMobile } from "@/hooks/useIsMobile";

import "./ModalSheet.css";
const ModalSheetContainer = ({ children }: { children: ReactNode }) => {
  const isMobile = useIsMobile();
  if (isMobile)
    return <ModalSheetContainerClient>{children}</ModalSheetContainerClient>;
  return <ModalSheetContainerServer>{children}</ModalSheetContainerServer>;
};

export default ModalSheetContainer;
