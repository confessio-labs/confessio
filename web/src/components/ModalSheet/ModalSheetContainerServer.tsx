import { useAtomValue } from "jotai";
import { isSearchFocusedAtom } from "@/atoms";

function ModalSheetContainerServer({
  children,
}: {
  children: React.ReactNode;
}) {
  const isSearchFocused = useAtomValue(isSearchFocusedAtom);

  if (isSearchFocused) return null;

  return (
    <div className="absolute z-30 w-full max-w-[500px] px-0 md:px-4 pb-4 flex flex-col bottom-0 md:bottom-auto md:top-[74px] max-h-[140px] md:max-h-[calc(100vh-74px)] overflow-hidden">
      <div className="react-modal-sheet-container flex flex-col min-h-0">
        {children}
      </div>
    </div>
  );
}

export default ModalSheetContainerServer;
