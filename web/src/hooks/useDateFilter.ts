import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useCallback } from "react";

type DateFilterContext = {
  date: Date | null;
  setDate: (date: Date | null) => void;
};

const getDateFromParams = (searchParams: URLSearchParams): Date | null => {
  const dateParam = searchParams.get("date");
  if (!dateParam) return null;

  const parsed = new Date(dateParam);
  if (isNaN(parsed.getTime())) return null;

  return parsed;
};

const setDateToParams = (
  date: Date | null,
  searchParams: URLSearchParams,
): URLSearchParams => {
  const params = new URLSearchParams(searchParams);
  const parsedDate = date?.toISOString().split("T")[0];
  if (parsedDate) {
    params.set("date", parsedDate);
  } else {
    params.delete("date");
  }
  return params;
};

export const useDateFilter = (): DateFilterContext => {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const date = getDateFromParams(searchParams);

  const setDate = useCallback(
    (newDate: Date | null) => {
      const newParams = setDateToParams(newDate, searchParams);
      router.replace(`${pathname}?${newParams.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  return { date, setDate };
};
