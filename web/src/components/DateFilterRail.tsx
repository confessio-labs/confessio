"use client";
import { useEffect, useRef } from "react";
import { useDateFilter } from "@/hooks/useDateFilter";

const WEEKDAYS = ["Dim.", "Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam."];
const MONTHS = [
  "janv.",
  "févr.",
  "mars",
  "avr.",
  "mai",
  "juin",
  "juil.",
  "août",
  "sept.",
  "oct.",
  "nov.",
  "déc.",
];
const DAYS = 30;

const toKey = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;

const chipClass = (active: boolean) =>
  active
    ? "shrink-0 rounded-full bg-paper text-deepblue border border-paper px-4 py-2 text-[13px] font-semibold shadow-[0_3px_10px_-3px_rgba(0,0,0,0.45)] transition active:scale-95"
    : "shrink-0 rounded-full bg-white/10 text-white/80 border border-white/20 px-4 py-2 text-[13px] font-semibold transition hover:bg-white/15 active:scale-95";

const DateFilterRail = () => {
  const { date, setDate } = useDateFilter();
  const selectedKey = date ? date.toISOString().split("T")[0] : null;
  const activeRef = useRef<HTMLButtonElement | null>(null);

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const days = Array.from({ length: DAYS }, (_, i) => {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    return d;
  });

  useEffect(() => {
    if (selectedKey)
      activeRef.current?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [selectedKey]);

  return (
    <div className="relative">
      <div
        role="group"
        aria-label="Filtrer par jour"
        className="flex gap-2 overflow-x-auto scrollbar-hide px-4 py-1.5"
      >
        <button
          type="button"
          aria-pressed={selectedKey === null}
          onClick={() => setDate(null)}
          className={chipClass(selectedKey === null)}
        >
          Tous les jours
        </button>
        {days.map((d, i) => {
          const key = toKey(d);
          const active = selectedKey === key;
          const crossesMonth = d.getMonth() !== today.getMonth();
          return (
            <button
              key={key}
              ref={active ? activeRef : undefined}
              type="button"
              aria-pressed={active}
              onClick={() => setDate(active ? null : new Date(key))}
              className={chipClass(active)}
            >
              {i === 0 ? (
                "Aujourd'hui"
              ) : i === 1 ? (
                "Demain"
              ) : (
                <>
                  {WEEKDAYS[d.getDay()]}{" "}
                  <span className="tabular">
                    {d.getDate()}
                    {crossesMonth ? ` ${MONTHS[d.getMonth()]}` : ""}
                  </span>
                </>
              )}
            </button>
          );
        })}
      </div>
      <div className="pointer-events-none absolute inset-y-0 left-0 w-4 bg-gradient-to-r from-deepblue to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-4 bg-gradient-to-l from-deepblue to-transparent" />
    </div>
  );
};

export default DateFilterRail;
