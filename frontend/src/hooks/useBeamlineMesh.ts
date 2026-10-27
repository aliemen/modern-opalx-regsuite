import { useQuery } from "@tanstack/react-query";
import { parseBeamlineMesh } from "../lib/beamlineMesh";

/** Fetch and validate a 3D beamline mesh; `data` is null when it has nothing to draw. */
export function useBeamlineMesh(url: string | null) {
  return useQuery({
    queryKey: ["beamline-mesh", url],
    queryFn: async () => {
      const res = await fetch(url!);
      if (!res.ok) throw new Error(`mesh fetch failed (${res.status})`);
      return parseBeamlineMesh(await res.text());
    },
    enabled: !!url,
    staleTime: Infinity,
    retry: false,
  });
}
