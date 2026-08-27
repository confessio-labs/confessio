import { components } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { createPortal } from "react-dom";
import ModalSheetScroller from "./ModalSheet/ModalSheetScroller";
import ModalSheetDragZone from "./ModalSheet/ModalSheetDragZone";
import { useSheetRef } from "./ModalSheet/SheetContext";
import { useKeyboardOverlap } from "@/hooks/useKeyboardOverlap";
import { fetchApi, getFrenchTimeString, getHolidayWarningReason } from "@/utils";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import posthog from "posthog-js";
import {
  ArrowSquareOutIcon,
  CircleNotchIcon,
  NavigationArrowIcon,
  PaperPlaneTiltIcon,
  SealCheckIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";

type EventOut = components["schemas"]["EventOut"];
type FeedbackType = components["schemas"]["FeedbackTypeEnum"];
type ErrorType = components["schemas"]["ErrorTypeEnum"];
type CommentNode = {
  comment: string;
  created_at: string;
  feedback_type: FeedbackType;
  children: CommentNode[];
};

const ERROR_TYPE_LABELS: Record<ErrorType, string> = {
  outdated: "Plus à jour",
  schedules: "Horaires incorrects",
  churches: "Mauvaise église",
  paragraphs: "Texte incorrect",
};

const URL_REGEX = /(https?:\/\/[^\s]+)/g;

const renderCommentBody = (raw: string) => {
  const text = raw.replace(/\\r\\n|\\r|\\n/g, "\n");
  return text.split(URL_REGEX).map((part, i) => {
    if (!/^https?:\/\//.test(part)) return part;
    const trailingMatch = part.match(/[.,;:!?)\]]+$/);
    const trailing = trailingMatch ? trailingMatch[0] : "";
    const url = trailing ? part.slice(0, -trailing.length) : part;
    return (
      <span key={i}>
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-deepblue underline underline-offset-2 hover:text-deepblue/70"
        >
          {url}
        </a>
        {trailing}
      </span>
    );
  });
};

const CommentEntry = ({ node }: { node: CommentNode }) => (
  <div className="flex flex-col gap-0.5">
    <span className="tabular text-deepblue/50 text-[11px] font-medium">
      {new Date(node.created_at).toLocaleDateString("fr-FR", {
        day: "numeric",
        month: "long",
        year: "numeric",
      })}
    </span>
    <p className="text-ink text-[13px] leading-normal whitespace-pre-line [overflow-wrap:anywhere]">
      {renderCommentBody(node.comment)}
    </p>
    {node.children.length > 0 && (
      <div className="mt-3 pl-4 border-l border-ink/15 flex flex-col gap-2">
        {node.children.map((child, i) => (
          <CommentEntry key={i} node={child} />
        ))}
      </div>
    )}
  </div>
);

const formatDayLabel = (dayKey: string) => {
  const date = new Date(dayKey);
  const today = new Date();
  const isToday = date.toDateString() === today.toDateString();
  const dayName = isToday
    ? "Aujourd'hui"
    : date
        .toLocaleDateString("fr-FR", { weekday: "long" })
        .replace(/^./, (c) => c.toUpperCase());
  const dateNum = date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "numeric",
  });
  return { dayName, dateNum };
};

const formatTimeRange = (event: EventOut) => {
  const start = getFrenchTimeString(event.start);
  const end = event.end ? getFrenchTimeString(event.end) : null;
  return end ? `${start} - ${end}` : `${start}`;
};

const ChurchCard = ({
  church,
}: {
  church: components["schemas"]["ChurchDetails"];
}) => {
  const { data: churchDetails, isLoading } = useQuery<
    components["schemas"]["ChurchDetails"]
  >({
    queryKey: ["churchDetails", church.uuid],
    queryFn: () => fetchApi(`/church/${church.uuid}`),
    initialData: "schedules" in church ? church : undefined,
  });

  const eventsByDay = useMemo(() => {
    const events =
      churchDetails?.events.sort(
        (a, b) => new Date(a.start).getTime() - new Date(b.start).getTime(),
      ) ?? [];
    const byDay: Record<string, EventOut[]> = {};
    for (const event of events) {
      const key = new Date(event.start).toDateString();
      if (!byDay[key]) byDay[key] = [];
      byDay[key].push(event);
    }
    return byDay;
  }, [churchDetails?.events]);

  const dayKeys = useMemo(() => Object.keys(eventsByDay), [eventsByDay]);

  const [selectedDayIndex, setSelectedDayIndex] = useState(0);

  const selectedDay = dayKeys[selectedDayIndex];
  const eventsForDay = selectedDay ? (eventsByDay?.[selectedDay] ?? []) : [];

  const holidayWarningReason = getHolidayWarningReason(
    eventsForDay.flatMap((event) => event.periods ?? []),
  );

  const getSchedulesForEvent = (event: EventOut) => {
    if (!churchDetails) return [];
    const indices = new Set(event.schedules_indices);
    return churchDetails.schedules.filter((_, i) => indices.has(i));
  };

  const { upvotes, downvotes, comments } = useMemo(() => {
    const reports = churchDetails?.website?.reports ?? [];
    let up = 0;
    let down = 0;
    const countVotes = (list: typeof reports) => {
      for (const r of list) {
        if (r.feedback_type === "good") up++;
        if (r.feedback_type === "error") down++;
        countVotes(r.sub_reports);
      }
    };
    countVotes(reports);

    const buildComments = (list: typeof reports): CommentNode[] => {
      const result: CommentNode[] = [];
      for (const r of list) {
        const children = buildComments(r.sub_reports);
        if (r.comment) {
          result.push({
            comment: r.comment,
            created_at: r.created_at,
            feedback_type: r.feedback_type,
            children,
          });
        } else {
          result.push(...children);
        }
      }
      return result;
    };
    return {
      upvotes: up,
      downvotes: down,
      comments: buildComments(reports),
    };
  }, [churchDetails?.website?.reports]);

  const queryClient = useQueryClient();
  const [feedbackOpen, setFeedbackOpen] = useState<"good" | "error" | null>(
    null,
  );
  const [feedbackText, setFeedbackText] = useState("");
  const [errorType, setErrorType] = useState<ErrorType | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [portalReady, setPortalReady] = useState(false);
  const lightboxClosedByBackRef = useRef(false);
  useEffect(() => setPortalReady(true), []);

  useEffect(() => {
    if (!lightboxUrl) return;
    lightboxClosedByBackRef.current = false;
    // Push a no-URL history entry so the OS/browser back button closes the
    // lightbox first instead of leaving the church card.
    window.history.pushState({ confessioLightbox: true }, "");
    const onPopState = () => {
      lightboxClosedByBackRef.current = true;
      setLightboxUrl(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLightboxUrl(null);
    };
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("popstate", onPopState);
      document.body.style.overflow = prevOverflow;
      // If closed via UI (X / backdrop / Escape), consume the history entry
      // we pushed — but only if it's still on top. If a route navigation
      // (e.g. closing the church card) happened first, our entry is buried
      // and calling back() would surface it again.
      if (
        !lightboxClosedByBackRef.current &&
        window.history.state?.confessioLightbox
      ) {
        window.history.back();
      }
    };
  }, [lightboxUrl]);

  const postReport = useMutation({
    mutationFn: async (payload: components["schemas"]["ReportIn"]) =>
      fetchApi("/reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["churchDetails", church.uuid],
      });
      setFeedbackOpen(null);
      setFeedbackText("");
      setErrorType(null);
    },
  });

  useEffect(() => {
    if (feedbackOpen) textareaRef.current?.focus();
  }, [feedbackOpen]);

  // iOS keyboard vs the bottom sheet: the card lives in a fixed, transformed
  // sheet sized off window.innerHeight, and on iOS the keyboard overlays the
  // page instead of resizing it — so the feedback box (near the bottom of the
  // card) ends up entirely behind the keyboard, and iOS's automatic
  // scroll-into-view fails inside the fixed sheet. When the keyboard opens:
  // 1. expand the sheet to its top snap point (at the half snap point the
  //    keyboard covers nearly all of the visible sheet),
  // 2. pad the box by the keyboard height (keyboardOverlap, also applied
  //    below as paddingBottom) so the scroller has room to place it higher,
  // 3. scroll the box into view with block "end": aligning its padded bottom
  //    with the scroller bottom puts the box itself right above the keyboard.
  const sheetRef = useSheetRef();
  const feedbackBoxRef = useRef<HTMLDivElement>(null);
  const keyboardOverlap = useKeyboardOverlap(feedbackOpen !== null);
  useEffect(() => {
    if (keyboardOverlap === 0) return;
    sheetRef?.current?.snapTo(0);
    feedbackBoxRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [keyboardOverlap, sheetRef]);

  const handleFeedbackClick = (type: "good" | "error") => {
    posthog.capture(
      type === "good" ? "church_upvoted" : "church_downvoted",
      { church_uuid: church.uuid, church_name: church.name },
    );
    setFeedbackOpen((current) => (current === type ? null : type));
    setFeedbackText("");
    setErrorType(null);
  };

  const handleSubmitFeedback = () => {
    if (!churchDetails?.website?.uuid || !feedbackOpen) return;
    postReport.mutate({
      website_uuid: churchDetails.website.uuid,
      church_uuid: church.uuid,
      feedback_type: feedbackOpen,
      error_type: feedbackOpen === "error" ? errorType : null,
      comment: feedbackText.trim() || null,
    });
  };

  const canReport = Boolean(churchDetails?.website?.uuid);

  const searchParams = useSearchParams();
  const query = searchParams.toString();

  useEffect(() => {
    const prev = document.title;
    document.title = `${church.name} — Confessio`;
    posthog.capture("church_viewed", {
      church_uuid: church.uuid,
      church_name: church.name,
      church_city: church.city,
    });
    return () => {
      document.title = prev;
    };
  }, [church.name, church.uuid, church.city]);

  return (
    <>
      <ModalSheetDragZone>
        <div className="px-5 pt-4 pb-3 flex flex-col gap-1.5">
          <span className="flex justify-between gap-2 items-start">
            <h3 className="text-white leading-[1.15] text-[22px] font-semibold tracking-[-0.01em]">
              {church.name}
            </h3>
            <Link
              href={`/?${query}`}
              aria-label="Fermer"
              className="shrink-0 w-8 h-8 rounded-full bg-white/10 flex items-center justify-center hover:bg-white/20 transition-colors z-10"
            >
              <XIcon size={16} weight="bold" color="white" />
            </Link>
          </span>
          <Link
            href={`https://www.google.com/maps/dir/?api=1&destination=${church.latitude},${church.longitude}`}
            target="_blank"
            className="group inline-flex items-start gap-1.5 self-start text-[13px] leading-snug text-white/70 hover:text-white transition-colors"
            onClick={() =>
              posthog.capture("directions_opened", {
                church_uuid: church.uuid,
                church_name: church.name,
              })
            }
          >
            <NavigationArrowIcon
              size={14}
              weight="fill"
              className="mt-[3px] shrink-0 text-white/55 group-hover:text-white transition-colors"
            />
            <span className="whitespace-pre-line">
              {[church.address, church.city].filter(Boolean).join("\n")}
            </span>
          </Link>
        </div>

        <hr className="mx-0 border-0 h-px bg-white/12" />
      </ModalSheetDragZone>

      <ModalSheetScroller draggableAt="top">
        {churchDetails?.website?.home_url && (
          <div className="px-5 pt-3 pb-1 flex">
            <Link
              href={churchDetails.website.home_url}
              target="_blank"
              className="inline-flex items-center gap-1.5 text-[12px] font-medium text-white/75 hover:text-white transition-colors"
              onClick={() =>
                posthog.capture("parish_website_clicked", {
                  church_uuid: church.uuid,
                  church_name: church.name,
                  parish_url: churchDetails.website?.home_url,
                })
              }
            >
              <span>Paroisse de {church.name}</span>
              <ArrowSquareOutIcon
                size={13}
                weight="bold"
                className="shrink-0"
              />
            </Link>
          </div>
        )}
        <div className="pb-6 pt-2">
          {isLoading && (
            <div className="flex items-center justify-center py-8">
              <CircleNotchIcon
                size={24}
                color="white"
                className="animate-spin"
              />
            </div>
          )}

          {churchDetails && dayKeys.length > 0 && (
            <div className="mx-3">
              <div className="flex gap-0 overflow-x-auto snap-x snap-mandatory px-[calc(50%-40px)] scrollbar-hide">
                {dayKeys.map((dayKey, i) => {
                  const { dayName, dateNum } = formatDayLabel(dayKey);
                  const isSelected = i === selectedDayIndex;
                  return (
                    <button
                      key={dayKey}
                      onClick={(e) => {
                        setSelectedDayIndex(i);
                        e.currentTarget.scrollIntoView({
                          behavior: "smooth",
                          inline: "center",
                          block: "nearest",
                        });
                      }}
                      className={[
                        "day-tab relative flex flex-col items-center shrink-0 snap-center px-3 pt-1 pb-2 text-[14px] font-semibold leading-tight rounded-t-xl transition-colors",
                        isSelected
                          ? "day-tab-selected bg-paper text-deepblue"
                          : "bg-transparent text-white/65 hover:text-white/90",
                      ].join(" ")}
                    >
                      <span className="text-[11px] font-medium uppercase tracking-[0.08em] opacity-80">
                        {dayName}
                      </span>
                      <span className="tabular text-[15px] font-semibold leading-tight">
                        {dateNum}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="rounded-xl bg-paper overflow-hidden divide-y divide-hairline shadow-[0_4px_16px_-6px_rgba(0,0,0,0.25)]">
                {holidayWarningReason && (
                  <div className="flex items-center gap-2 px-4 py-2.5 text-[12.5px] font-medium text-warn-amber bg-warn-amber-bg">
                    <WarningCircleIcon
                      size={15}
                      weight="fill"
                      className="shrink-0"
                      style={{ color: "#b4690e" }}
                    />
                    <span>
                      Horaires susceptibles de changer {holidayWarningReason}.
                    </span>
                  </div>
                )}
                {eventsForDay.map((event, i) => {
                  const schedules = getSchedulesForEvent(event);
                  return (
                    <div
                      key={`${event.start}-${i}`}
                      className="px-4 py-3.5 flex flex-col gap-2"
                    >
                      <div className="flex justify-center">
                        <span className="tabular inline-flex items-center rounded-full px-4 py-1.5 text-[15px] font-semibold bg-deepblue text-white">
                          {formatTimeRange(event)}
                        </span>
                      </div>
                      {schedules.length > 0 && (
                        <div className="flex flex-col gap-1.5 text-[13px] leading-relaxed text-ink/70">
                          {schedules.map((s, j) => {
                            const sourceParsing = s.sources
                              .filter(
                                (src) =>
                                  src.source_type === "parsing" &&
                                  src.parsing_uuid,
                              )
                              .map((src) =>
                                churchDetails.parsings.find(
                                  (p) => p.uuid === src.parsing_uuid,
                                ),
                              )
                              .find((p) => p?.scraping_url || p?.image_url);
                            const pageUrl = sourceParsing?.scraping_url ?? null;
                            const imageUrl = !pageUrl
                              ? (sourceParsing?.image_url ?? null)
                              : null;
                            const hasOclocher = s.sources.some(
                              (src) => src.source_type === "oclocher",
                            );
                            return (
                              <div
                                key={j}
                                className="whitespace-pre-line flex flex-col gap-1"
                              >
                                <p>{s.explanation}</p>
                                {hasOclocher && (
                                  <div className="flex justify-end">
                                    <span
                                      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 border select-none"
                                      style={{
                                        borderColor: "#609E2E",
                                        color: "#609E2E",
                                      }}
                                      title="Source vérifiée par OClocher"
                                    >
                                      <SealCheckIcon size={12} weight="fill" />
                                      <span className="text-[11px] font-medium tracking-tight">
                                        OClocher
                                      </span>
                                    </span>
                                  </div>
                                )}
                                {imageUrl && (
                                  <div className="flex justify-end">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setLightboxUrl(imageUrl);
                                        posthog.capture(
                                          "source_image_opened",
                                          {
                                            church_uuid: church.uuid,
                                            url: imageUrl,
                                          },
                                        );
                                      }}
                                      aria-label="Voir la source"
                                      className="block w-12 h-12 rounded-lg overflow-hidden border border-ink/10 hover:border-deepblue/40 transition-colors bg-paper"
                                    >
                                      {/* eslint-disable-next-line @next/next/no-img-element */}
                                      <img
                                        src={imageUrl}
                                        alt="Aperçu de la source"
                                        loading="lazy"
                                        className="w-full h-full object-cover"
                                      />
                                    </button>
                                  </div>
                                )}
                                {pageUrl && (
                                  <Link
                                    href={pageUrl}
                                    target="_blank"
                                    className="text-deepblue/50 hover:text-deepblue block text-right text-[12px]"
                                  >
                                    Source ↗
                                  </Link>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {!isLoading && churchDetails && dayKeys.length === 0 && (
            <p className="text-center text-white/55 py-6 text-sm">
              Aucun horaire trouvé,{" "}
              {churchDetails.website?.home_url ? (
                <Link
                  href={churchDetails.website.home_url}
                  target="_blank"
                  className="underline underline-offset-4 decoration-white/30 hover:decoration-white/70 text-white/75 hover:text-white transition-colors"
                  onClick={() =>
                    posthog.capture("parish_website_clicked", {
                      church_uuid: church.uuid,
                      church_name: church.name,
                      parish_url: churchDetails.website?.home_url,
                    })
                  }
                >
                  visitez le site de la paroisse
                </Link>
              ) : (
                "visitez le site de la paroisse"
              )}
            </p>
          )}

          <div className="flex flex-col items-center py-5 gap-3">
            <div className="w-full max-w-[300px] flex flex-col items-center gap-2.5">
              <p className="text-white/70 text-[13px] font-medium text-center">
                Ces informations sont-elles à jour&nbsp;?
              </p>
              <div className="flex gap-2 w-full">
                <button
                  aria-label="Confirmer que ces informations sont à jour"
                  disabled={!canReport}
                  className={[
                    "flex-1 inline-flex items-center justify-center gap-1.5 min-h-[44px] rounded-full border text-[13px] font-semibold transition-colors",
                    feedbackOpen === "good"
                      ? "bg-emerald-300/12 border-emerald-300/50 text-white"
                      : "bg-white/7 border-white/14 text-white/90 hover:bg-white/12",
                    !canReport && "opacity-40 cursor-not-allowed",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => handleFeedbackClick("good")}
                >
                  <ThumbsUpIcon
                    size={16}
                    weight={feedbackOpen === "good" ? "fill" : "regular"}
                    className="text-emerald-300 shrink-0"
                  />
                  <span>Oui</span>
                  <span className="tabular text-white/55">{upvotes}</span>
                </button>
                <button
                  aria-label="Signaler une erreur"
                  disabled={!canReport}
                  className={[
                    "flex-1 inline-flex items-center justify-center gap-1.5 min-h-[44px] rounded-full border text-[13px] font-semibold transition-colors",
                    feedbackOpen === "error"
                      ? "bg-rose-300/12 border-rose-300/50 text-white"
                      : "bg-white/7 border-white/14 text-white/90 hover:bg-white/12",
                    !canReport && "opacity-40 cursor-not-allowed",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => handleFeedbackClick("error")}
                >
                  <ThumbsDownIcon
                    size={16}
                    weight={feedbackOpen === "error" ? "fill" : "regular"}
                    className="text-rose-300 shrink-0"
                  />
                  <span>Erreur</span>
                  <span className="tabular text-white/55">{downvotes}</span>
                </button>
              </div>
            </div>

            {feedbackOpen && (
              <div
                ref={feedbackBoxRef}
                className="w-full px-4"
                // Keyboard-height padding so the box can sit fully above the
                // iOS keyboard when scrolled into view (see keyboardOverlap
                // effect above).
                style={{ paddingBottom: keyboardOverlap }}
              >
                <div className="bg-paper rounded-xl p-3 flex flex-col gap-2 shadow-[0_2px_8px_-4px_rgba(0,0,0,0.2)]">
                  {feedbackOpen === "error" && (
                    <div className="grid grid-cols-2 gap-1.5">
                      {(Object.keys(ERROR_TYPE_LABELS) as ErrorType[]).map(
                        (key) => {
                          const selected = errorType === key;
                          return (
                            <button
                              key={key}
                              type="button"
                              disabled={postReport.isPending}
                              onClick={() =>
                                setErrorType((curr) =>
                                  curr === key ? null : key,
                                )
                              }
                              className={[
                                "text-[12px] font-medium rounded-full px-2.5 py-1 transition-colors border",
                                selected
                                  ? "bg-deepblue text-white border-deepblue"
                                  : "bg-transparent text-deepblue/70 border-hairline hover:border-deepblue/40 hover:text-deepblue",
                              ].join(" ")}
                            >
                              {ERROR_TYPE_LABELS[key]}
                            </button>
                          );
                        },
                      )}
                    </div>
                  )}
                  <textarea
                    ref={textareaRef}
                    value={feedbackText}
                    onChange={(e) => setFeedbackText(e.target.value)}
                    placeholder="Un commentaire ? (optionnel)"
                    rows={3}
                    disabled={postReport.isPending}
                    // Keep mobile font-size >= 16px: iOS Safari force-zooms into inputs below 16px. Do not lower.
                    className="w-full resize-none text-ink text-[16px] md:text-[13px] leading-normal placeholder:text-ink/40 bg-transparent focus:outline-none disabled:opacity-60"
                  />
                  {postReport.isError && (
                    <p className="text-rose-600 text-[12px]">
                      Erreur lors de l&apos;envoi. Réessayez.
                    </p>
                  )}
                  <div className="flex justify-end gap-2 items-center">
                    <button
                      type="button"
                      onClick={() => {
                        setFeedbackOpen(null);
                        setFeedbackText("");
                        setErrorType(null);
                      }}
                      disabled={postReport.isPending}
                      className="text-deepblue/60 hover:text-deepblue text-[13px] px-2 py-1 transition-colors disabled:opacity-50"
                    >
                      Annuler
                    </button>
                    <button
                      type="button"
                      onClick={handleSubmitFeedback}
                      disabled={postReport.isPending}
                      className="inline-flex items-center gap-1.5 bg-deepblue text-white text-[13px] font-semibold rounded-full px-3.5 py-1.5 hover:bg-deepblue/90 transition-colors disabled:opacity-60"
                    >
                      {postReport.isPending ? (
                        <CircleNotchIcon
                          size={14}
                          weight="bold"
                          className="animate-spin"
                        />
                      ) : (
                        <PaperPlaneTiltIcon size={14} weight="fill" />
                      )}
                      Envoyer
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {comments.length > 0 && (
            <div className="px-4 pb-4 flex flex-col gap-2">
              {comments.map((c, i) => (
                <div
                  key={i}
                  className="relative bg-paper rounded-xl px-3.5 py-2.5 shadow-[0_2px_8px_-4px_rgba(0,0,0,0.2)]"
                >
                  {c.feedback_type === "good" && (
                    <ThumbsUpIcon
                      size={14}
                      weight="fill"
                      aria-label="Avis positif"
                      className="absolute top-2.5 right-3 text-emerald-700/60"
                    />
                  )}
                  {c.feedback_type === "error" && (
                    <ThumbsDownIcon
                      size={14}
                      weight="fill"
                      aria-label="Avis négatif"
                      className="absolute top-2.5 right-3 text-rose-700/60"
                    />
                  )}
                  <CommentEntry node={c} />
                </div>
              ))}
            </div>
          )}

          <div className="text-center px-4">
            <Link
              href={`https://confessio.fr/paroisse/${churchDetails?.website?.uuid}#feedbackForm`}
              target="_blank"
              className="inline-block underline underline-offset-4 decoration-white/30 hover:decoration-white/70 text-white/75 hover:text-white text-[13px] transition-colors"
              onClick={() =>
                posthog.capture("contribution_link_clicked", {
                  church_uuid: church.uuid,
                  church_name: church.name,
                })
              }
            >
              Ajouter une image des horaires de confession
            </Link>
          </div>
        </div>
      </ModalSheetScroller>
      {portalReady &&
        lightboxUrl &&
        createPortal(
          <div
            className="fixed inset-0 bg-deepblue/90 z-[1000] flex items-center justify-center p-4"
            onClick={() => setLightboxUrl(null)}
            role="dialog"
            aria-modal="true"
          >
            <button
              type="button"
              onClick={() => setLightboxUrl(null)}
              aria-label="Fermer"
              className="absolute top-4 right-4 w-9 h-9 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors"
            >
              <XIcon size={18} weight="bold" color="white" />
            </button>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={lightboxUrl}
              alt="Source"
              className="max-w-full max-h-full object-contain rounded-xl"
              onClick={(e) => e.stopPropagation()}
            />
            <Link
              href={lightboxUrl}
              target="_blank"
              onClick={(e) => e.stopPropagation()}
              className="absolute bottom-4 inline-flex items-center gap-1.5 text-white/75 hover:text-white text-[13px] underline underline-offset-4 decoration-white/30 hover:decoration-white/70 transition-colors"
            >
              Ouvrir dans un nouvel onglet
              <ArrowSquareOutIcon size={14} weight="bold" />
            </Link>
          </div>,
          document.body,
        )}
    </>
  );
};

export { ChurchCard };
