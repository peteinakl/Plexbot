export interface PlexUser {
  username: string;
  email: string;
  thumb: string;
}

export interface Profile {
  id: string;
  name: string;
  icon: string;
  description: string;
  inherit_shared_history: number;
  created_at: number;
}

export interface PlexServerInfo {
  machine_id: string;
  name: string;
  owned: boolean;
  owner_name: string;
  is_local_conn: boolean;
  is_relay: boolean;
  latency_ms: number;
  online: boolean;
  enabled: boolean;
  movie_count: number;
  show_count: number;
  last_synced_at: number | null;
}

export interface SyncServerDetail {
  machine_id: string;
  name: string;
  owned: boolean;
  owner_name: string;
  online: boolean;
  enabled: boolean;
  status: string;
  items: number;
}

export interface SyncStatus {
  running: boolean;
  phase: string;
  message: string;
  total_servers: number;
  completed_servers: number;
  items_indexed: number;
  servers_detail: SyncServerDetail[];
  error: string | null;
  started_at: number | null;
  finished_at: number | null;
}

export interface LLMConfigStatus {
  enabled: boolean;
  provider: 'none' | 'gemini' | 'anthropic' | 'openai';
  active_model: string;
  has_gemini_key: boolean;
  has_anthropic_key: boolean;
  has_openai_key: boolean;
  gemini_key_masked: string;
  anthropic_key_masked: string;
  openai_key_masked: string;
  gemini_model: string;
  anthropic_model: string;
  openai_model: string;
}

export interface AppStatus {
  authenticated: boolean;
  user: PlexUser | null;
  last_sync_at: number | null;
  sync: SyncStatus;
  profiles: Profile[];
  servers: PlexServerInfo[];
  stats: {
    total_items: number;
    total_movies: number;
    total_shows: number;
    watched_count: number;
    watchlist_count: number;
    feedback_count: number;
  };
  llm: LLMConfigStatus;
  moods: { id: string; label: string }[];
}

export interface MediaSource {
  id: number;
  media_id: number;
  machine_id: string;
  rating_key: string;
  section_title: string;
  resolution: string;
  video_codec: string;
  hdr: number;
  server_name: string;
  owned: number;
  owner_name: string;
  online: number;
  latency_ms: number;
  deep_link: string;
}

export type Sentiment = 'love' | 'like' | 'meh' | 'dislike' | 'dismiss' | 'seen_unrated';

export interface MediaItem {
  id: number;
  canonical_key: string;
  media_type: 'movie' | 'show';
  plex_guid?: string | null;
  discover_rating_key?: string | null;
  imdb_id?: string | null;
  tmdb_id?: string | null;
  title: string;
  original_title?: string | null;
  year?: number | null;
  tagline: string;
  summary: string;
  content_rating: string;
  duration_min?: number | null;
  critic_rating?: number | null;
  audience_rating?: number | null;
  genres: string[];
  directors: string[];
  writers: string[];
  cast: string[];
  countries: string[];
  studios: string[];
  collections: string[];
  poster_url?: string | null;
  is_watched: boolean;
  max_view_count: number;
  max_user_rating?: number | null;
  leaf_count: number;
  viewed_leaf_count: number;
  max_progress_ratio: number;
  is_abandoned: boolean;
  last_viewed_at?: number | null;
  on_watchlist: boolean;
  is_external_only: boolean;
  sources: MediaSource[];
  primary_source?: MediaSource | null;
  feedback?: Sentiment | null;
  // Recommendation-specific fields
  match_score?: number;
  because_you_liked?: string[];
  match_reasons?: string[];
  explanation?: string;
  vibe_tag?: string;
  ai_curated?: boolean;
  // History-specific fields
  implicit_signal?: string;
  signal_weight?: number;
}

export interface TasteDNA {
  signal_count: number;
  loved_count: number;
  disliked_or_abandoned_count: number;
  top_directors: { name: string; weight: number }[];
  top_writers: { name: string; weight: number }[];
  top_genres: { name: string; weight: number }[];
  top_pairings: { name: string; weight: number }[];
  top_studios: { name: string; weight: number }[];
  top_actors: { name: string; weight: number }[];
  top_countries: { name: string; weight: number }[];
  top_decades: { name: string; weight: number }[];
  top_themes: { name: string; weight: number }[];
  anchor_favorites: {
    id: number;
    title: string;
    year?: number;
    media_type: string;
    reason: string;
    weight: number;
  }[];
  avoid_examples: {
    id: number;
    title: string;
    year?: number;
    reason: string;
  }[];
}

export interface RecommendationResponse {
  items: MediaItem[];
  dna: TasteDNA;
  total_pool: number;
  curator_headline?: string;
  provider?: string;
  model?: string;
}

export interface TastePortrait {
  archetype: string;
  summary: string;
  sweet_spots: string[];
  stretch_ideas: string[];
  provider: string;
  model: string;
}
