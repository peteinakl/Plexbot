import React, { useCallback, useEffect, useState } from 'react';
import {
  Film,
  Flame,
  Loader2,
  Meh,
  RefreshCw,
  Search,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Tv,
} from 'lucide-react';
import { api } from '../api';
import { MediaItem, Profile, Sentiment, TasteDNA, TastePortrait } from '../types';

interface Props {
  activeProfile: Profile;
  llmEnabled: boolean;
  onOpenSettings: () => void;
  onSelectMedia: (item: MediaItem) => void;
  onTasteChanged: () => void;
}

export const TasteTuner: React.FC<Props> = ({
  activeProfile,
  llmEnabled,
  onOpenSettings,
  onSelectMedia,
  onTasteChanged,
}) => {
  const [mode, setMode] = useState<'history' | 'catalog'>('history');
  const [filterMode, setFilterMode] = useState<string>('all');
  const [mediaType, setMediaType] = useState<string>('all');
  const [search, setSearch] = useState<string>('');
  const [catalogQuery, setCatalogQuery] = useState<string>('');
  const [items, setItems] = useState<MediaItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [dna, setDna] = useState<TasteDNA | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const [portrait, setPortrait] = useState<TastePortrait | null>(null);
  const [portraitLoading, setPortraitLoading] = useState<boolean>(false);
  const [portraitError, setPortraitError] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getHistory({
        profile_id: activeProfile.id,
        filter_mode: filterMode,
        media_type: mediaType,
        search,
      });
      setItems(res.items);
      setCounts(res.counts);
      setDna(res.dna);
    } finally {
      setLoading(false);
    }
  }, [activeProfile.id, filterMode, mediaType, search]);

  useEffect(() => {
    if (mode === 'history') {
      loadHistory();
    }
  }, [mode, loadHistory]);

  useEffect(() => {
    setPortrait(null);
    setPortraitError(null);
  }, [activeProfile.id]);

  const handleCatalogSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!catalogQuery.trim()) return;
    setLoading(true);
    try {
      const res = await api.searchCatalog(catalogQuery.trim(), activeProfile.id);
      setItems(res.items);
    } finally {
      setLoading(false);
    }
  };

  const handleRate = async (item: MediaItem, sentiment: Sentiment) => {
    const next: Sentiment | 'clear' = item.feedback === sentiment ? 'clear' : sentiment;
    await api.setFeedback(activeProfile.id, item.id, next);
    setItems((prev) =>
      prev.map((it) =>
        it.id === item.id ? { ...it, feedback: next === 'clear' ? null : next } : it
      )
    );
    onTasteChanged();
    if (mode === 'history') {
      const refreshed = await api.getHistory({
        profile_id: activeProfile.id,
        filter_mode: filterMode,
        media_type: mediaType,
        search,
      });
      setCounts(refreshed.counts);
      setDna(refreshed.dna);
    }
  };

  const handleLoadPortrait = async (force = false) => {
    if (!llmEnabled) {
      onOpenSettings();
      return;
    }
    setPortraitLoading(true);
    setPortraitError(null);
    try {
      const res = await api.getTastePortrait(activeProfile.id, force);
      setPortrait(res);
    } catch (err: any) {
      setPortraitError(err.message || 'Could not generate portrait.');
    } finally {
      setPortraitLoading(false);
    }
  };

  const filterTabs = [
    { id: 'all', label: `All Watched (${counts.all || 0})` },
    { id: 'unrated', label: `Unrated (${counts.unrated || 0})` },
    { id: 'loved', label: `Loved & Liked (${counts.loved || 0})` },
    { id: 'disliked', label: `Meh & Disliked (${counts.disliked || 0})` },
    { id: 'abandoned', label: `Abandoned (${counts.abandoned || 0})` },
  ];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
      {/* Left 8 cols: Watch History & Quick Thumbs Calibration */}
      <div className="lg:col-span-8 space-y-5">
        <div className="bg-[#121620] border border-slate-800/80 rounded-2xl p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-lg font-bold text-white">
                Calibrate Taste for <span className="text-amber-400">{activeProfile.name}</span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Sharing one Plex account? Thumbs-up your favorites and thumbs-down things someone else watched (or shows you bounced off).
              </p>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={onOpenSettings}
                className="px-3 py-1.5 rounded-xl bg-red-500/15 hover:bg-red-500/25 border border-red-500/35 text-red-200 text-xs font-medium transition cursor-pointer"
              >
                Import Netflix CSV
              </button>
              <div className="inline-flex rounded-xl bg-slate-900 p-1 border border-slate-800">
                <button
                  type="button"
                  onClick={() => setMode('history')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer ${
                    mode === 'history' ? 'bg-amber-500 text-slate-950 font-semibold' : 'text-slate-300'
                  }`}
                >
                  Watched History
                </button>
                <button
                  type="button"
                  onClick={() => setMode('catalog')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer ${
                    mode === 'catalog' ? 'bg-amber-500 text-slate-950 font-semibold' : 'text-slate-300'
                  }`}
                >
                  Search All Libraries
                </button>
              </div>
            </div>
          </div>

          {mode === 'history' ? (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-1.5">
                {filterTabs.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setFilterMode(t.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer ${
                      filterMode === t.id
                        ? 'bg-slate-800 text-amber-300 border border-amber-500/40'
                        : 'bg-slate-900/70 text-slate-400 hover:text-slate-200 border border-slate-800'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                <div className="relative flex-1 min-w-[200px]">
                  <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Filter watched titles..."
                    className="w-full pl-9 pr-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-sm text-white focus:outline-none focus:border-amber-500/60"
                  />
                </div>
                <select
                  value={mediaType}
                  onChange={(e) => setMediaType(e.target.value)}
                  className="px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none"
                >
                  <option value="all">Movies &amp; TV</option>
                  <option value="movie">Movies Only</option>
                  <option value="show">TV Shows Only</option>
                </select>
              </div>
            </div>
          ) : (
            <form onSubmit={handleCatalogSearch} className="flex gap-2">
              <div className="relative flex-1">
                <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={catalogQuery}
                  onChange={(e) => setCatalogQuery(e.target.value)}
                  placeholder="Search any title, director, or actor across local + shared servers..."
                  className="w-full pl-9 pr-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-sm text-white focus:outline-none focus:border-amber-500/60"
                />
              </div>
              <button
                type="submit"
                className="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold text-xs cursor-pointer"
              >
                Search
              </button>
            </form>
          )}
        </div>

        {loading ? (
          <div className="py-16 flex items-center justify-center text-slate-400 gap-2">
            <Loader2 className="w-5 h-5 animate-spin text-amber-400" />
            Loading titles...
          </div>
        ) : items.length === 0 ? (
          <div className="p-10 rounded-2xl bg-[#121620] border border-slate-800/80 text-center text-slate-400 text-sm">
            {mode === 'catalog'
              ? 'Search above to find any movie or TV series across your connected Plex servers.'
              : 'No watched items match this filter yet.'}
          </div>
        ) : (
          <div className="space-y-2.5">
            {items.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-3.5 p-3 rounded-xl bg-[#121620] border border-slate-800/80 hover:border-slate-700 transition"
              >
                <div
                  onClick={() => onSelectMedia(item)}
                  className="w-12 h-18 rounded-lg overflow-hidden bg-slate-900 shrink-0 cursor-pointer border border-slate-800"
                >
                  {item.poster_url ? (
                    <img src={item.poster_url} alt={item.title} className="w-full h-full object-cover" loading="lazy" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-slate-600">
                      {item.media_type === 'movie' ? <Film className="w-5 h-5" /> : <Tv className="w-5 h-5" />}
                    </div>
                  )}
                </div>

                <div
                  onClick={() => onSelectMedia(item)}
                  className="flex-1 min-w-0 cursor-pointer"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-sm text-white hover:text-amber-300 truncate">
                      {item.title}
                    </span>
                    {item.year && <span className="text-xs text-slate-500">({item.year})</span>}
                    {item.implicit_signal && (
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                          item.is_abandoned
                            ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30'
                            : 'bg-slate-800 text-slate-300 border border-slate-700'
                        }`}
                      >
                        {item.implicit_signal}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-400 truncate mt-0.5">
                    {item.genres.slice(0, 3).join(' · ')}
                    {item.directors.length > 0 ? ` · Dir. ${item.directors[0]}` : ''}
                    {item.primary_source ? ` · ${item.primary_source.server_name}` : ''}
                  </div>
                </div>

                {/* 1-Click Thumbs Strip */}
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    title="Loved it (All-time favorite)"
                    onClick={() => handleRate(item, 'love')}
                    className={`px-2.5 py-1.5 rounded-lg border text-xs font-medium inline-flex items-center gap-1 transition cursor-pointer ${
                      item.feedback === 'love'
                        ? 'bg-amber-500/25 border-amber-400 text-amber-200'
                        : 'bg-slate-900 hover:bg-slate-800 border-slate-800 text-slate-400 hover:text-amber-300'
                    }`}
                  >
                    <Flame className="w-3.5 h-3.5" />
                    <span className="hidden sm:inline">Love</span>
                  </button>
                  <button
                    type="button"
                    title="Liked it"
                    onClick={() => handleRate(item, 'like')}
                    className={`px-2.5 py-1.5 rounded-lg border text-xs font-medium inline-flex items-center gap-1 transition cursor-pointer ${
                      item.feedback === 'like'
                        ? 'bg-emerald-500/25 border-emerald-400 text-emerald-200'
                        : 'bg-slate-900 hover:bg-slate-800 border-slate-800 text-slate-400 hover:text-emerald-300'
                    }`}
                  >
                    <ThumbsUp className="w-3.5 h-3.5" />
                    <span className="hidden sm:inline">Like</span>
                  </button>
                  <button
                    type="button"
                    title="Meh / Mixed"
                    onClick={() => handleRate(item, 'meh')}
                    className={`p-1.5 rounded-lg border text-xs transition cursor-pointer ${
                      item.feedback === 'meh'
                        ? 'bg-slate-600/35 border-slate-400 text-slate-100'
                        : 'bg-slate-900 hover:bg-slate-800 border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Meh className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    title="Disliked (Steer away)"
                    onClick={() => handleRate(item, 'dislike')}
                    className={`px-2.5 py-1.5 rounded-lg border text-xs font-medium inline-flex items-center gap-1 transition cursor-pointer ${
                      item.feedback === 'dislike'
                        ? 'bg-rose-500/25 border-rose-400 text-rose-200'
                        : 'bg-slate-900 hover:bg-slate-800 border-slate-800 text-slate-400 hover:text-rose-300'
                    }`}
                  >
                    <ThumbsDown className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Right 4 cols: Live Taste DNA + AI Taste Portrait */}
      <div className="lg:col-span-4 space-y-5">
        <div className="bg-[#121620] border border-slate-800/80 rounded-2xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold uppercase tracking-wider text-amber-400 flex items-center gap-1.5">
              <Sparkles className="w-4 h-4" />
              AI Taste Portrait
            </h3>
            {portrait && (
              <button
                type="button"
                onClick={() => handleLoadPortrait(true)}
                className="text-xs text-slate-400 hover:text-white inline-flex items-center gap-1 cursor-pointer"
              >
                <RefreshCw className="w-3 h-3" />
                Refresh
              </button>
            )}
          </div>

          {portrait ? (
            <div className="space-y-3 text-xs leading-relaxed">
              <div className="text-base font-bold text-white">{portrait.archetype}</div>
              <p className="text-slate-300 whitespace-pre-line">{portrait.summary}</p>
              {portrait.sweet_spots?.length > 0 && (
                <div>
                  <div className="text-[11px] font-semibold text-amber-300 mb-1">Your Sweet Spots</div>
                  <ul className="space-y-1 text-slate-300">
                    {portrait.sweet_spots.map((s, i) => (
                      <li key={i}>• {s}</li>
                    ))}
                  </ul>
                </div>
              )}
              {portrait.stretch_ideas?.length > 0 && (
                <div>
                  <div className="text-[11px] font-semibold text-sky-300 mb-1">Worth Exploring Next</div>
                  <ul className="space-y-1 text-slate-300">
                    {portrait.stretch_ideas.map((s, i) => (
                      <li key={i}>• {s}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <div>
              <p className="text-xs text-slate-400 mb-3 leading-relaxed">
                Synthesize {activeProfile.name}&apos;s watch history, rewatches, and ratings into a custom cinematic profile.
              </p>
              {portraitError && (
                <div className="text-xs text-rose-300 mb-2">{portraitError}</div>
              )}
              <button
                type="button"
                disabled={portraitLoading}
                onClick={() => handleLoadPortrait(false)}
                className="w-full py-2.5 px-4 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/35 text-amber-300 text-xs font-semibold flex items-center justify-center gap-2 transition cursor-pointer"
              >
                {portraitLoading ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Reading your watch history...
                  </>
                ) : llmEnabled ? (
                  <>
                    <Sparkles className="w-3.5 h-3.5" />
                    Generate Taste Portrait
                  </>
                ) : (
                  'Connect Gemini / Claude / OpenAI in Settings'
                )}
              </button>
            </div>
          )}
        </div>

        {dna && (
          <div className="bg-[#121620] border border-slate-800/80 rounded-2xl p-5 space-y-4">
            <div>
              <h3 className="text-sm font-bold text-white">Live Taste Graph Signals</h3>
              <p className="text-xs text-slate-400 mt-0.5">
                {dna.loved_count} positive signals · {dna.disliked_or_abandoned_count} negative/abandoned signals
              </p>
            </div>

            {dna.top_directors.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-1.5">
                  High-Affinity Directors
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {dna.top_directors.slice(0, 6).map((d) => (
                    <span
                      key={d.name}
                      className="px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200"
                    >
                      {d.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {dna.top_writers.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-1.5">
                  Favorite Writers / Creators
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {dna.top_writers.slice(0, 5).map((w) => (
                    <span
                      key={w.name}
                      className="px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-200"
                    >
                      {w.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {dna.top_pairings.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-1.5">
                  Signature Genre Blends
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {dna.top_pairings.slice(0, 5).map((g) => (
                    <span
                      key={g.name}
                      className="px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/25 text-xs text-amber-200"
                    >
                      {g.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {dna.top_themes.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-1.5">
                  Recurring Story Themes
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {dna.top_themes.slice(0, 10).map((t) => (
                    <span
                      key={t.name}
                      className="px-2 py-0.5 rounded bg-slate-900 text-[11px] text-slate-300 border border-slate-800"
                    >
                      {t.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
