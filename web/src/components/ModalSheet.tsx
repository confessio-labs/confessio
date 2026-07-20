"use client";
import Image from "next/image";
import { ChurchCard } from "./ChurchCard";
import ModalSheetScroller from "./ModalSheet/ModalSheetScroller";
import ModalSheetDragZone from "./ModalSheet/ModalSheetDragZone";
import { AggregatedSearchResults } from "@/utils";
import ChurchTile from "./ChurchTile";
import DateFilterRail from "./DateFilterRail";
import { components } from "@/types";
import { useSearchResults } from "@/hooks/useSearchResults";
import { useDateFilter } from "@/hooks/useDateFilter";

const WEEKDAYS = [
  "dimanche",
  "lundi",
  "mardi",
  "mercredi",
  "jeudi",
  "vendredi",
  "samedi",
];
const MONTHS = [
  "janvier",
  "février",
  "mars",
  "avril",
  "mai",
  "juin",
  "juillet",
  "août",
  "septembre",
  "octobre",
  "novembre",
  "décembre",
];

const dateHeadingSuffix = (date: Date | null) => {
  if (!date) return "";
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.round(
    (target.getTime() - today.getTime()) / 86400000,
  );
  if (diffDays === 0) return "aujourd'hui";
  if (diffDays === 1) return "demain";
  return `${WEEKDAYS[target.getDay()]} ${target.getDate()} ${MONTHS[target.getMonth()]}`;
};

function ModalSheet({
  originalSearchResults,
  selectedChurch,
}: {
  originalSearchResults?: AggregatedSearchResults | null | undefined;
  selectedChurch?: components["schemas"]["ChurchDetails"];
}) {
  // URL is the single source of truth - use the church from server if present
  const { data: searchResults } = useSearchResults();
  const { date } = useDateFilter();

  const displayedSearchResults = searchResults
    ? searchResults
    : originalSearchResults;

  if (selectedChurch) return <ChurchCard church={selectedChurch} />;

  return (
    <>
      <ModalSheetDragZone>
        <div className="flex flex-col gap-2 py-2">
          <h4 className="text-base md:text-lg font-semibold text-white px-4">
            {`Horaires de confession ${dateHeadingSuffix(date)}`.trim()}
          </h4>
        </div>
      </ModalSheetDragZone>
      <DateFilterRail />
      <hr className="text-gray-500 mt-2" />
      <ModalSheetScroller draggableAt="top">
        <div className="p-4 space-y-4">
          {displayedSearchResults?.churches?.map((church) => (
            <ChurchTile key={church.uuid} church={church} />
          ))}
          <div className="flex items-center justify-center gap-2 py-4">
            <span className="text-white text-xs">Un projet généreusement encouragé par</span>
            <a href="https://hozana.org" target="_blank" rel="noopener noreferrer">
              <Image src="/hozana-logo-white.png" alt="Hozana" height={16} width={64} />
            </a>
          </div>
        </div>
      </ModalSheetScroller>
    </>
  );
}

export default ModalSheet;
