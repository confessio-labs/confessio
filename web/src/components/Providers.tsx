"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { IsMobileProvider } from "@/hooks/useIsMobile";

const queryClient = new QueryClient();

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <IsMobileProvider>{children}</IsMobileProvider>
    </QueryClientProvider>
  );
}
