import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, qs } from "./client";
import type {
  BuildResponse,
  CopilotStatus,
  DataStatus,
  DraftRequest,
  DraftResponse,
  GsiStatus,
  HeroDetail,
  HeroListRow,
  Hud,
  ItemDetail,
  ItemRow,
  LiveSnapshot,
  MatchReview,
  MetaResponse,
  Peer,
  PostGameJob,
  ProfileResponse,
  RankBucket,
  Recommendation,
  Recording,
  Settings,
  VersionInfo,
} from "./types";

const forever = { staleTime: Infinity, gcTime: Infinity } as const;

export const useHeroes = () => useQuery({ queryKey: ["heroes"], queryFn: () => api.get<HeroListRow[]>("/api/heroes"), ...forever });
export const useItems = () => useQuery({ queryKey: ["items"], queryFn: () => api.get<ItemRow[]>("/api/items"), ...forever });
export const useVersion = () => useQuery({ queryKey: ["version"], queryFn: () => api.get<VersionInfo>("/api/version"), ...forever });

export const useHero = (ref: string, bucket?: RankBucket) =>
  useQuery({ queryKey: ["hero", ref, bucket], queryFn: () => api.get<HeroDetail>(`/api/heroes/${encodeURIComponent(ref)}${qs({ bucket })}`) });

export const useBuild = (ref: string) =>
  useQuery({ queryKey: ["build", ref], queryFn: () => api.get<BuildResponse>(`/api/heroes/${encodeURIComponent(ref)}/build`) });

export const useItem = (key: string) =>
  useQuery({ queryKey: ["item", key], queryFn: () => api.get<ItemDetail>(`/api/items/${encodeURIComponent(key)}`) });

export const useMeta = (source: string, bracket: number | null, position: number | null) =>
  useQuery({
    queryKey: ["meta", source, bracket, position],
    queryFn: () => api.get<MetaResponse>(`/api/meta${qs({ source, bracket, position })}`),
    placeholderData: keepPreviousData,
  });

export const useDraft = (req: DraftRequest, enabled: boolean) =>
  useQuery({
    queryKey: ["draft", req],
    queryFn: () => api.post<DraftResponse>("/api/draft", req),
    placeholderData: keepPreviousData,
    enabled,
  });

export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings") });

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (changes: Partial<Settings>) => api.put<Settings>("/api/settings", changes),
    onSuccess: (s) => qc.setQueryData(["settings"], s),
  });
}

export const useGsiStatus = (path?: string) =>
  useQuery({ queryKey: ["gsi", path], queryFn: () => api.get<GsiStatus>(`/api/gsi/status${qs({ path })}`), refetchInterval: 3000 });

export const useDataStatus = (poll: boolean) =>
  useQuery({ queryKey: ["data-status"], queryFn: () => api.get<DataStatus>("/api/data/status"), refetchInterval: poll ? 1500 : false });

export const useRecordings = () => useQuery({ queryKey: ["recordings"], queryFn: () => api.get<Recording[]>("/api/recordings") });

export const useProfile = (accountId: number | null) =>
  useQuery({
    queryKey: ["profile", accountId],
    queryFn: () => api.get<ProfileResponse>(`/api/profile${qs({ account_id: accountId })}`),
    enabled: accountId !== null,
    retry: false,
  });

export const usePeers = (accountId: number | null) =>
  useQuery({
    queryKey: ["peers", accountId],
    queryFn: () => api.get<Peer[]>(`/api/profile/peers${qs({ account_id: accountId })}`),
    enabled: accountId !== null,
    retry: false,
  });

export const useMatch = (id: number | null) =>
  useQuery({
    queryKey: ["match", id],
    queryFn: () => api.get<MatchReview>(`/api/matches/${id}`),
    enabled: id !== null,
    retry: false,
  });

export const usePostGame = () =>
  useQuery({ queryKey: ["postgame"], queryFn: () => api.get<PostGameJob[]>("/api/postgame"), refetchInterval: 10000 });

/** The live snapshot over Server-Sent Events, with a reconnect after errors. */
export function useLive(): { snap: LiveSnapshot | null; online: boolean } {
  const [snap, setSnap] = useState<LiveSnapshot | null>(null);
  const [online, setOnline] = useState(false);
  const retry = useRef<number | undefined>(undefined);
  useEffect(() => {
    let source: EventSource | null = null;
    let closed = false;
    const open = () => {
      source = new EventSource("/api/live/stream");
      source.onopen = () => setOnline(true);
      source.onmessage = (e: MessageEvent<string>) => setSnap(JSON.parse(e.data) as LiveSnapshot);
      source.onerror = () => {
        setOnline(false);
        source?.close();
        if (!closed) retry.current = window.setTimeout(open, 2000);
      };
    };
    open();
    return () => {
      closed = true;
      window.clearTimeout(retry.current);
      source?.close();
    };
  }, []);
  return { snap, online };
}

export const useCopilotStatus = () =>
  useQuery({ queryKey: ["copilot-status"], queryFn: () => api.get<CopilotStatus>("/api/copilot/status"), refetchInterval: 2000 });

/** What the Copilot advises right now. Polled twice a second on this machine, so new advice shows within 0.5 s of the event. */
export const useCopilotAdvice = () =>
  useQuery({
    queryKey: ["copilot-advice"],
    queryFn: () => api.get<Recommendation[]>("/api/copilot/recommendations?status=suggested"),
    refetchInterval: 500,
  });

/** The overlay widgets' hints, polled once a second. */
export const useHud = () => useQuery({ queryKey: ["hud"], queryFn: () => api.get<Hud>("/api/copilot/hud"), refetchInterval: 1000 });

export function useDismissAdvice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<{ ok: boolean }>(`/api/copilot/recommendations/${encodeURIComponent(id)}/dismiss`),
    onSettled: () => qc.invalidateQueries({ queryKey: ["copilot-advice"] }),
  });
}
