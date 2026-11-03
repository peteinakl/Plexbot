import {
  AppStatus,
  MediaItem,
  NetflixImportResult,
  Profile,
  RecommendationResponse,
  Sentiment,
  SyncStatus,
  TasteDNA,
  TastePortrait,
} from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data?.detail) msg = String(data.detail);
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getStatus: () => request<AppStatus>('/api/status'),

  startPlexPin: (forwardUrl?: string) =>
    request<{ pin_id: number; code: string; auth_url: string }>('/api/auth/plex/pin', {
      method: 'POST',
      body: JSON.stringify({ forward_url: forwardUrl }),
    }),

  checkPlexPin: (pinId: number) =>
    request<{ authenticated: boolean; expired?: boolean }>(`/api/auth/plex/pin/${pinId}`),

  loginWithToken: (token: string) =>
    request<{ authenticated: boolean }>('/api/auth/plex/token', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),

  logoutPlex: () => request<{ ok: boolean }>('/api/auth/plex/logout', { method: 'POST' }),

  triggerSync: () => request<SyncStatus>('/api/sync', { method: 'POST' }),

  getSyncStatus: () => request<SyncStatus>('/api/sync/status'),

  toggleServer: (machineId: string, enabled: boolean) =>
    request<{ machine_id: string; enabled: boolean }>(`/api/servers/${machineId}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),

  createProfile: (name: string, description: string, inheritShared: boolean) =>
    request<Profile>('/api/profiles', {
      method: 'POST',
      body: JSON.stringify({
        name,
        description,
        inherit_shared_history: inheritShared,
      }),
    }),

  deleteProfile: (profileId: string) =>
    request<{ deleted: string }>(`/api/profiles/${profileId}`, { method: 'DELETE' }),

  getRecommendations: (params: {
    profile_id: string;
    mood: string;
    media_type: string;
    source_scope: string;
    include_outside: boolean;
    discovery_level: number;
    max_duration?: number | null;
    decade?: string | null;
    prompt?: string;
    exclude_watchlist?: boolean;
    limit?: number;
  }) => {
    const sp = new URLSearchParams();
    sp.set('profile_id', params.profile_id);
    sp.set('mood', params.mood);
    sp.set('media_type', params.media_type);
    sp.set('source_scope', params.source_scope);
    sp.set('include_outside', String(params.include_outside));
    sp.set('discovery_level', String(params.discovery_level));
    if (params.max_duration) sp.set('max_duration', String(params.max_duration));
    if (params.decade) sp.set('decade', params.decade);
    if (params.prompt) sp.set('prompt', params.prompt);
    if (params.exclude_watchlist) sp.set('exclude_watchlist', 'true');
    if (params.limit) sp.set('limit', String(params.limit));
    return request<RecommendationResponse>(`/api/recommendations?${sp.toString()}`);
  },

  aiCurate: (body: {
    profile_id: string;
    mood: string;
    media_type: string;
    source_scope: string;
    include_outside: boolean;
    discovery_level: number;
    max_duration?: number | null;
    decade?: string | null;
    prompt?: string;
    exclude_watchlist?: boolean;
    force_refresh?: boolean;
  }) =>
    request<RecommendationResponse>('/api/recommendations/ai-curate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getTastePortrait: (profileId: string, forceRefresh = false) =>
    request<TastePortrait>('/api/taste-portrait', {
      method: 'POST',
      body: JSON.stringify({ profile_id: profileId, force_refresh: forceRefresh }),
    }),

  getHistory: (params: {
    profile_id: string;
    filter_mode: string;
    media_type: string;
    search: string;
  }) => {
    const sp = new URLSearchParams(params);
    return request<{
      items: MediaItem[];
      total_matching: number;
      counts: Record<string, number>;
      dna: TasteDNA;
    }>(`/api/history?${sp.toString()}`);
  },

  searchCatalog: (q: string, profileId: string) => {
    const sp = new URLSearchParams({ q, profile_id: profileId });
    return request<{ items: MediaItem[] }>(`/api/catalog/search?${sp.toString()}`);
  },

  setFeedback: (profileId: string, mediaId: number, sentiment: Sentiment | 'clear') =>
    request<{ profile_id: string; media_id: number; sentiment: Sentiment | null }>(
      '/api/feedback',
      {
        method: 'POST',
        body: JSON.stringify({ profile_id: profileId, media_id: mediaId, sentiment }),
      }
    ),

  toggleWatchlist: (mediaId: number, onWatchlist: boolean) =>
    request<{ media_id: number; on_watchlist: boolean }>(`/api/watchlist/${mediaId}`, {
      method: 'POST',
      body: JSON.stringify({ on_watchlist: onWatchlist }),
    }),

  saveLLMSettings: (body: {
    llm_provider: string;
    gemini_api_key?: string;
    anthropic_api_key?: string;
    openai_api_key?: string;
    gemini_model?: string;
    anthropic_model?: string;
    openai_model?: string;
  }) =>
    request<{ ok: boolean }>('/api/settings/llm', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  testLLM: (provider: string, apiKey?: string, model?: string) =>
    request<{ ok: boolean; message: string }>('/api/settings/llm/test', {
      method: 'POST',
      body: JSON.stringify({ provider, api_key: apiKey, model }),
    }),

  syncNetflix: () =>
    request<{ enabled: boolean; region: string; movies: number; shows: number; total: number }>(
      '/api/netflix/sync',
      { method: 'POST' }
    ),

  saveNetflixSettings: (body: {
    enabled: boolean;
    watch_region: string;
    tmdb_api_key?: string;
  }) =>
    request<{ ok: boolean }>('/api/netflix/settings', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  importNetflixCSV: (csvText: string, profileFilter?: string) =>
    request<NetflixImportResult>('/api/netflix/import-csv', {
      method: 'POST',
      body: JSON.stringify({
        csv_text: csvText,
        profile_filter: profileFilter || null,
      }),
    }),
};
