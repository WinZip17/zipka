import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
      // Не дублировать: следующий refetchInterval ждёт завершения текущего
      networkMode: "online",
    },
  },
});
