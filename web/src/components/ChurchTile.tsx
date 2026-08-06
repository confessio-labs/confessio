"use client";
import { AggregatedSearchResults } from "@/utils";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

const formatDayLabel = (dateString: string) => {
  const date = new Date(dateString);
  const parts = date
    .toLocaleDateString("fr-FR", { weekday: "short", day: "numeric" })
    .replace(".", "")
    .split(" ");
  const weekday = parts[0] ?? "";
  const day = parts.slice(1).join(" ");
  return {
    weekday: weekday.charAt(0).toUpperCase() + weekday.slice(1),
    day,
  };
};

const formatTime = (dateString: string) => {
  const date = new Date(dateString);
  const hours = date.getHours();
  const minutes = date.getMinutes();
  if (minutes === 0) return `${hours}h`;
  return `${hours}h${minutes.toString().padStart(2, "0")}`;
};

const ChurchTile = ({
  church,
}: {
  church: AggregatedSearchResults["churches"][number];
}) => {
  const searchParams = useSearchParams();
  const query = searchParams.toString();
  const events = church.eventsByDay;
  if (events === undefined || Object.keys(events).length === 0) return null;
  const entries = Object.entries(events);
  const totalEvents = entries.reduce((sum, [, e]) => sum + e.length, 0);
  const soleEvent =
    totalEvents === 1 ? entries[0]?.[1][0] ?? null : null;

  return (
    <Link
      href={query ? `/church/${church.uuid}?${query}` : `/church/${church.uuid}`}
      key={church.uuid}
      className="w-full bg-paper border border-hairline rounded-2xl px-4 py-3 block transition-shadow hover:shadow-[0_4px_14px_-6px_rgba(36,46,76,0.18)] active:scale-[0.995]"
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-deepblue text-[17px] leading-tight tracking-[-0.01em]">
            {church.name}
          </h3>
          <p className="text-[12.5px] text-deepblue/55 mt-0.5">
            {church.address}
          </p>
        </div>
        {soleEvent && (
          <div className="shrink-0 flex flex-col items-center gap-1.5">
            <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-deepblue/55">
              {formatDayLabel(soleEvent.start).weekday}{" "}
              {formatDayLabel(soleEvent.start).day}
            </span>
            <span className="tabular inline-flex items-center justify-center rounded-full bg-deepblue text-white px-3 py-1 text-[13px] font-semibold min-w-[54px]">
              {formatTime(soleEvent.start)}
            </span>
          </div>
        )}
      </div>
      {!soleEvent && (
        <div className="mt-3 -mx-1 flex gap-3 overflow-x-auto scrollbar-hide px-1">
          {entries.flatMap(([day, dayEvents]) =>
            dayEvents.map((event, eventIdx) => ({
              key: `${day}-${eventIdx}`,
              event,
            })),
          ).map(({ key, event }, flatIdx) => (
            <div
              key={key}
              className="flex flex-col items-center gap-1.5 shrink-0"
            >
              <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-deepblue/55">
                {formatDayLabel(event.start).weekday}{" "}
                {formatDayLabel(event.start).day}
              </span>
              <span
                className={
                  flatIdx === 0
                    ? "tabular inline-flex items-center justify-center rounded-full bg-deepblue text-white px-3 py-1 text-[13px] font-semibold min-w-[54px]"
                    : "tabular inline-flex items-center justify-center rounded-full border border-hairline bg-white text-deepblue px-3 py-1 text-[13px] font-semibold min-w-[54px]"
                }
              >
                {formatTime(event.start)}
              </span>
            </div>
          ))}
        </div>
      )}
    </Link>
  );
};
export default ChurchTile;
