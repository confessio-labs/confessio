import { components } from "@/types";
import clsx from "clsx";
import { Map } from "leaflet";
import Image from "next/image";
import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { NavigationModal } from "./NavigationModal";
import { usePathname } from "next/navigation";
import { useAtom } from "jotai";
import { isSearchFocusedAtom } from "@/atoms";
import { useMapRouter } from "@/hooks/useMapRouter";
import { useKeyboardOverlap } from "@/hooks/useKeyboardOverlap";
import {
  ArrowLeftIcon,
  BuildingsIcon,
  ChurchIcon,
  CircleNotchIcon,
  ListIcon,
  UsersIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Icon } from "@phosphor-icons/react/dist/lib/types";
import posthog from "posthog-js";

const mapItemTypeToIcon: Record<string, Icon> = {
  church: ChurchIcon,
  parish: UsersIcon,
  municipality: BuildingsIcon,
};

export const SearchInput = ({
  map,
  data,
  isLoading,
  searchQuery,
  setSearchQuery,
}: {
  map: Map | null;
  data: components["schemas"]["AutocompleteItem"][];
  isLoading: boolean;
  searchQuery: string;
  setSearchQuery: (query: string) => void;
}) => {
  const [isFocused, setIsFocused] = useAtom(isSearchFocusedAtom);
  const router = useMapRouter();
  const pathname = usePathname();
  const [isNavigationModalOpen, setIsNavigationModalOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // iOS keyboard overlays the h-dvh overlay instead of shrinking it; pad the
  // results list by the covered height so the last results stay reachable
  // (see useKeyboardOverlap for details).
  const keyboardOverlap = useKeyboardOverlap(isFocused);

  const closeSearch = useCallback(() => {
    setIsFocused(false);
    inputRef.current?.blur();
  }, [setIsFocused]);

  // Android back button closes search instead of navigating away
  useEffect(() => {
    const handlePopState = (e: PopStateEvent) => {
      if (isFocused) {
        e.preventDefault();
        closeSearch();
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [isFocused, closeSearch]);

  const onClick = useCallback(
    (item: components["schemas"]["AutocompleteItem"]) => () => {
      if (map && item.latitude && item.longitude) {
        const zoomLevel = item.type === "municipality" ? 13 : 15;
        map.setView([item.latitude, item.longitude], zoomLevel);
        inputRef.current?.blur();
      }
    },
    [map],
  );
  const onInputChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value;
      setSearchQuery(value);
      if (value.length > 0) {
        posthog.capture("search_performed", { query: value });
      }
      // When user types, navigate back to home if on a church detail page
      if (pathname?.startsWith("/church/")) {
        const currentParams = new URLSearchParams(window.location.search);
        router.push(`/?${currentParams.toString()}`);
      }
    },
    [setSearchQuery, pathname, router],
  );

  const selectFirstResult = useCallback(() => {
    const first = data[0];
    if (!first) return;
    if (first.type === "church" && first.uuid) {
      inputRef.current?.blur();
      const params = new URLSearchParams(window.location.search);
      if (first.latitude && first.longitude) {
        params.set("center", `${first.latitude},${first.longitude}`);
      }
      router.push(`/church/${first.uuid}?${params.toString()}`);
    } else {
      onClick(first)();
    }
  }, [data, router, onClick]);

  const hasResults = searchQuery.length > 0 && (data.length > 0 || isLoading);

  return (
    <>
      <div
        className={clsx([
          "absolute flex flex-col items-stretch justify-start z-40 md:w-[468px] md:rounded-2xl md:inset-x-4 md:top-4",
          isFocused
            ? "inset-0 h-dvh bg-white pt-4 px-4 md:bg-transparent md:p-0 md:h-auto md:bottom-auto md:right-auto"
            : "inset-x-4 top-4 rounded-2xl",
        ])}
      >
        <div
          className={clsx([
            "h-11 px-2 bg-white gap-2 rounded-full text-deepblue flex items-center relative z-10 border border-hairline transition-shadow",
            !isFocused && "shadow-[0_4px_14px_-4px_rgba(36,46,76,0.14)]",
            isFocused && "shadow-none md:shadow-[0_0_0_3px_rgba(0,92,223,0.18),0_8px_24px_-8px_rgba(36,46,76,0.18)]",
          ])}
        >
          {isFocused ? (
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={closeSearch}
              className="cursor-pointer self-center shrink-0 flex items-center justify-center size-8"
            >
              <ArrowLeftIcon size={24} />
            </button>
          ) : (
            <div className="self-center shrink-0 flex items-center justify-center size-8">
              <Image
                src="/confessioLogoBlue.svg"
                alt="Logo de Confessio"
                width={24}
                height={24}
              />
            </div>
          )}
          <input
            ref={inputRef}
            type="text"
            placeholder="Chercher une église ou une ville"
            value={searchQuery}
            onChange={onInputChange}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                selectFirstResult();
              }
            }}
            onFocus={() => {
              setIsFocused(true);
              history.pushState({ search: true }, "");
            }}
            onBlur={() => setIsFocused(false)}
            // Keep mobile font-size >= 16px: iOS Safari force-zooms into inputs below 16px. Do not lower.
            className="outline-none flex-1 self-stretch bg-transparent text-deepblue placeholder:text-deepblue/45 text-[16px] md:text-[15px]"
          />
          {isLoading && (
            <div className="self-center shrink-0 flex items-center justify-center size-8">
              <CircleNotchIcon size={18} className="animate-spin" />
            </div>
          )}
          {isFocused && searchQuery.length > 0 && !isLoading && (
            <button
              onClick={() => {
                setSearchQuery("");
                setIsFocused(false);
                inputRef.current?.blur();
              }}
              className="cursor-pointer self-center shrink-0 flex items-center justify-center size-8"
              aria-label="Clear search"
              title="Clear search"
              onMouseDown={(e) => e.preventDefault()}
              onMouseUp={(e) => e.preventDefault()}
            >
              <XIcon size={18} />
            </button>
          )}
          {!isFocused && (
            <button
              onClick={() => {
                setIsNavigationModalOpen(true);
                posthog.capture("navigation_modal_opened");
              }}
              className="cursor-pointer self-center shrink-0 flex items-center justify-center size-8 rounded-full border border-hairline bg-paper text-deepblue transition-colors hover:bg-hairline active:bg-hairline"
              aria-label="Ouvrir le menu"
              title="Menu"
            >
              <ListIcon size={18} />
            </button>
          )}
        </div>
        <ul
          className={clsx(
            "min-h-0 overflow-y-auto bg-white rounded-b-2xl -mt-5 pt-5",
            { hidden: !isFocused, "flex-1": !hasResults },
          )}
          // Keyboard-height padding so the end of the list is scrollable
          // above the iOS keyboard (see keyboardOverlap effect above).
          style={{ paddingBottom: keyboardOverlap }}
        >
          {isFocused && data.length === 0 && !isLoading && (
            <li className="flex items-center justify-center h-full p-4">
              <p className="font-medium text-deepblue/50 text-center">
                {searchQuery.length > 0
                  ? "Pas de résultat trouvé pour cette recherche"
                  : "Tapez le nom d'une ville, d'une église"}
              </p>
            </li>
          )}
          {isFocused &&
            data.map((item, index) => {
              const ItemIcon = mapItemTypeToIcon[item.type] ?? BuildingsIcon;
              const inner = (
                <>
                  <ItemIcon size={22} className="text-deepblue/75 shrink-0" />
                  <div className="flex flex-col min-w-0">
                    <div className="text-deepblue font-medium truncate">
                      {item.name}
                    </div>
                    <div className="text-[12px] text-deepblue/55 truncate">
                      {item.context}
                    </div>
                  </div>
                </>
              );
              const className =
                "w-full text-left px-2 py-1.5 rounded-lg transition-colors cursor-pointer flex items-center hover:bg-paper gap-2.5";
              return (
                <li key={index} className="p-2">
                  {item.type === "church" && item.uuid ? (
                    <button
                      onPointerDown={(e) => e.preventDefault()}
                      onClick={() => {
                        posthog.capture("search_result_selected", {
                          result_type: item.type,
                          result_name: item.name,
                          result_uuid: item.uuid,
                          query: searchQuery,
                        });
                        inputRef.current?.blur();
                        const params = new URLSearchParams(
                          window.location.search,
                        );
                        if (item.latitude && item.longitude) {
                          params.set(
                            "center",
                            `${item.latitude},${item.longitude}`,
                          );
                        }
                        router.push(
                          `/church/${item.uuid}?${params.toString()}`,
                        );
                      }}
                      className={className}
                    >
                      {inner}
                    </button>
                  ) : (
                    <button
                      onPointerDown={(e) => e.preventDefault()}
                      onClick={() => {
                        posthog.capture("search_result_selected", {
                          result_type: item.type,
                          result_name: item.name,
                          query: searchQuery,
                        });
                        onClick(item)();
                      }}
                      className={className}
                    >
                      {inner}
                    </button>
                  )}
                </li>
              );
            })}
        </ul>
      </div>
      <NavigationModal
        isOpen={isNavigationModalOpen}
        onClose={() => setIsNavigationModalOpen(false)}
      />
    </>
  );
};
