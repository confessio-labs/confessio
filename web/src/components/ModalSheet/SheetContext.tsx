import { createContext, useContext } from "react";
import { SheetRef } from "react-modal-sheet";

export const SheetRefContext = createContext<React.RefObject<SheetRef | null> | null>(null);
export const useSheetRef = () => useContext(SheetRefContext);
