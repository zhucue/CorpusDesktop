import { useQuery } from "@tanstack/react-query";
import { api, type SystemInfo } from "../../api";

/** GET /system/info: version, model host and embedding mode. Changes only on redeploy. */
export function useSystemInfo() {
  return useQuery({
    queryKey: ["system-info"],
    queryFn: () => api.get<SystemInfo>("/system/info"),
    staleTime: 5 * 60_000,
  });
}
