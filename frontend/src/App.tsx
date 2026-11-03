import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Compass,
  Globe,
  Loader2,
  RefreshCw,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  ThumbsUp,
  User,
  Users,
} from 'lucide-react';
import { api } from './api';
import { AuthConnect } from './components/AuthConnect';
import { MediaCard } from './components/MediaCard';
import { MediaDetailModal } from './components/MediaDetailModal';
import { SettingsModal } from './components/SettingsModal';
import { TasteTuner } from './components/TasteTuner';
import { AppStatus, MediaItem, Profile, Sentiment } from './types';

export const App: React.FC = () => {
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [bootLoading, setBootLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'discover' | 'taste'>('discover');
  const [activeProfileId, setActiveProfileId] = useState<string>('together');

  // Filter state
  const [mood, setMood] = useState<string>('all');
  const [mediaType, setMediaType] = useState<string>('all');
  const [sourceScope, setSourceScope] = useState<string>('plex_all');
  const [includeOutside, setIncludeOutside] = useState<boolean>(false);
  const [discoveryLevel, setDiscoveryLevel] = useState<number>(0.35);
  const [decade, setDecade] = useState<string>('');
  const [promptInput, setPromptInput] = useState<string>('');
  const [appliedPrompt, setAppliedPrompt] = useState<string>('');

  // Recommendations state
  const [items, setItems] = useState<MediaItem[]>([]);
  const [totalPool, setTotalPool] = useState<number>(0);
  const [curatorHeadline, setCuratorHeadline] = useState<string>('');
  const [recsLoading, setRecsLoading] = useState<boolean>(false);
  const [aiLoading, setAiLoading] = useState<boolean>(false);

  // Modals & Toasts
  const [selectedItem, setSelectedItem] = useState<MediaItem | null>(null);
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => {
      setToast((prev) => (prev === msg ? null : prev));
    }, 3400);
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.getStatus();
      setStatus(s);
    } finally {
      setBootLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  // Poll sync progress automatically while a sync is running
  useEffect(() => {
    if (!status?.sync.running) return;
    const iv = setInterval(async () => {
      try {
        const sync = await api.getSyncStatus();
        setStatus((prev) => (prev ? { ...prev, sync } : prev));
        if (!sync.running) {
          clearInterval(iv);
          await refreshStatus();
        }
      } catch {
        // ignore transient errors
      }
    }, 1500);
    return () => clearInterval(iv);
  }, [status?.sync.running, refreshStatus]);

  const activeProfile: Profile = useMemo(() => {
    const found = status?.profiles.find((p) => p.id === activeProfileId);
    return (
      found ||
      status?.profiles[0] || {
        id: 'together',
        name: 'Us Together',
        icon: 'users',
        description: '',
        inherit_shared_history: 1,
        created_at: 0,
      }
    );
  }, [status?.profiles, activeProfileId]);

  const fetchRecommendations = useCallback(async () => {
    if (!status?.authenticated) return;
    setRecsLoading(true);
    setCuratorHeadline('');
    try {
      const res = await api.getRecommendations({
        profile_id: activeProfile.id,
        mood,
        media_type: mediaType,
        source_scope: sourceScope,
        include_outside: includeOutside,
        discovery_level: discoveryLevel,
        decade: decade || null,
        prompt: appliedPrompt,
        limit: 36,
      });
      setItems(res.items);
      setTotalPool(res.total_pool);
    } catch (err: any) {
      showToast(err.message || 'Could not load recommendations.');
    } finally {
      setRecsLoading(false);
    }
  }, [
    status?.authenticated,
    activeProfile.id,
    mood,
    mediaType,
    sourceScope,
    includeOutside,
    discoveryLevel,
    decade,
    appliedPrompt,
    showToast,
  ]);

  useEffect(() => {
    if (status?.authenticated && activeTab === 'discover' && !status.sync.running) {
      fetchRecommendations();
    }
  }, [
    status?.authenticated,
    status?.last_sync_at,
    activeTab,
    fetchRecommendations,
    status?.sync.running,
  ]);

  const handleRunAICurate = async (forceRefresh = false) => {
    if (!status?.llm.enabled) {
      setSettingsOpen(true);
      showToast('Add a Gemini, Claude, or OpenAI key to enable AI Deep Curate.');
      return;
    }
    const nextPrompt = promptInput.trim();
    setAppliedPrompt(nextPrompt);
    setAiLoading(true);
    try {
      const res = await api.aiCurate({
        profile_id: activeProfile.id,
        mood,
        media_type: mediaType,
        source_scope: sourceScope,
        include_outside: includeOutside,
        discovery_level: discoveryLevel,
        decade: decade || null,
        prompt: nextPrompt,
        force_refresh: forceRefresh,
      });
      setItems(res.items);
      setTotalPool(res.total_pool);
      setCuratorHeadline(res.curator_headline || '');
    } catch (err: any) {
      showToast(err.message || 'AI curation failed.');
    } finally {
      setAiLoading(false);
    }
  };

  const handlePromptSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (status?.llm.enabled && promptInput.trim()) {
      handleRunAICurate(false);
    } else {
      setAppliedPrompt(promptInput.trim());
    }
  };

  const handleToggleWatchlist = async (target: MediaItem) => {
    const nextVal = !target.on_watchlist;
    try {
      await api.toggleWatchlist(target.id, nextVal);
      setItems((prev) =>
        prev.map((it) => (it.id === target.id ? { ...it, on_watchlist: nextVal } : it))
      );
      setSelectedItem((prev) =>
        prev && prev.id === target.id ? { ...prev, on_watchlist: nextVal } : prev
      );
      showToast(
        nextVal
          ? `Added "${target.title}" to your Plex Watchlist`
          : `Removed "${target.title}" from Watchlist`
      );
    } catch (err: any) {
      showToast(err.message || 'Watchlist sync failed.');
    }
  };

  const handleFeedback = async (target: MediaItem, sentiment: Sentiment | 'clear') => {
    try {
      const res = await api.setFeedback(activeProfile.id, target.id, sentiment);
      if (activeTab === 'discover' && sentiment !== 'clear') {
        // Remove rated/dismissed item immediately from recommendations & refresh subtly
        setItems((prev) => prev.filter((it) => it.id !== target.id));
        if (selectedItem?.id === target.id) {
          setSelectedItem(null);
        }
        const labelMap: Record<string, string> = {
          love: 'Marked Loved — boosting similar films & shows!',
          like: 'Marked Liked — updating taste graph',
          meh: 'Noted as Meh',
          dislike: 'Marked Disliked — steering away from similar picks',
          dismiss: 'Hidden from recommendations',
          seen_unrated: 'Marked Seen',
        };
        showToast(labelMap[sentiment] || 'Updated taste');
      } else {
        setSelectedItem((prev) =>
          prev && prev.id === target.id ? { ...prev, feedback: res.sentiment } : prev
        );
      }
    } catch (err: any) {
      showToast(err.message || 'Could not save rating.');
    }
  };

  if (bootLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0b0d12] text-slate-400 gap-2.5">
        <Loader2 className="w-5 h-5 animate-spin text-amber-400" />
        Loading Plexbot...
      </div>
    );
  }

  if (!status?.authenticated) {
    return <AuthConnect onAuthenticated={refreshStatus} />;
  }

  const enabledServers = status.servers.filter((s) => s.enabled);
  const sharedServersCount = enabledServers.filter((s) => !s.owned).length;

  return (
    <div className="min-h-screen bg-[#0b0d12] text-slate-100 flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-30 bg-[#0b0d12]/90 backdrop-blur-md border-b border-slate-800/80">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <div
              onClick={() => setActiveTab('discover')}
              className="flex items-center gap-2.5 cursor-pointer"
            >
              <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center text-slate-950 font-black text-base shadow-md shadow-amber-500/20">
                P
              </div>
              <div>
                <div className="font-bold text-base tracking-tight text-white leading-none">
                  Plexbot
                </div>
                <div className="text-[11px] text-slate-400 mt-0.5 hidden sm:block">
                  {status.stats.total_movies.toLocaleString()} movies ·{' '}
                  {status.stats.total_shows.toLocaleString()} shows
                  {sharedServersCount > 0 ? ` · +${sharedServersCount} shared` : ''}
                </div>
              </div>
            </div>

            {/* Primary Navigation */}
            <nav className="flex items-center gap-1 bg-[#121620] p-1 rounded-xl border border-slate-800/90">
              <button
                type="button"
                onClick={() => setActiveTab('discover')}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 transition cursor-pointer ${
                  activeTab === 'discover'
                    ? 'bg-amber-500 text-slate-950'
                    : 'text-slate-300 hover:text-white'
                }`}
              >
                <Compass className="w-3.5 h-3.5" />
                Tonight&apos;s Picks
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('taste')}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 transition cursor-pointer ${
                  activeTab === 'taste'
                    ? 'bg-amber-500 text-slate-950'
                    : 'text-slate-300 hover:text-white'
                }`}
              >
                <ThumbsUp className="w-3.5 h-3.5" />
                Tune Taste ({status.stats.watched_count})
              </button>
            </nav>
          </div>

          {/* Right Controls: Who's Watching + Sync + Settings */}
          <div className="flex items-center gap-2.5">
            <div className="hidden md:flex items-center gap-1.5 bg-[#121620] px-2.5 py-1.5 rounded-xl border border-slate-800 text-xs">
              {activeProfile.id === 'together' ? (
                <Users className="w-3.5 h-3.5 text-amber-400" />
              ) : (
                <User className="w-3.5 h-3.5 text-amber-400" />
              )}
              <span className="text-slate-400">Watching:</span>
              <select
                value={activeProfile.id}
                onChange={(e) => setActiveProfileId(e.target.value)}
                className="bg-transparent font-semibold text-white focus:outline-none cursor-pointer"
              >
                {status.profiles.map((p) => (
                  <option key={p.id} value={p.id} className="bg-[#121620] text-white">
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="button"
              disabled={status.sync.running}
              onClick={async () => {
                await api.triggerSync();
                await refreshStatus();
              }}
              title="Sync local & shared Plex libraries"
              className="p-2 rounded-xl bg-[#121620] hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-white transition cursor-pointer"
            >
              <RefreshCw className={`w-4 h-4 ${status.sync.running ? 'animate-spin text-amber-400' : ''}`} />
            </button>

            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              className="relative p-2 rounded-xl bg-[#121620] hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-white transition cursor-pointer"
              title="Servers & AI Settings"
            >
              <Settings className="w-4 h-4" />
              {status.llm.enabled && (
                <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-emerald-400" />
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Live Sync Progress Banner */}
      {status.sync.running && (
        <div className="bg-amber-500/10 border-b border-amber-500/25">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2.5 text-amber-200 font-medium">
              <Loader2 className="w-4 h-4 animate-spin text-amber-400 shrink-0" />
              <span>{status.sync.message || 'Syncing your Plex servers...'}</span>
            </div>
            <div className="flex items-center gap-3 text-slate-300">
              <span>
                Servers: {status.sync.completed_servers}/{status.sync.total_servers}
              </span>
              <span>·</span>
              <span>{status.sync.items_indexed.toLocaleString()} items indexed</span>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-6">
        {/* Mobile Who's Watching selector */}
        <div className="md:hidden mb-4 flex items-center justify-between bg-[#121620] p-3 rounded-xl border border-slate-800 text-xs">
          <span className="text-slate-400">Who&apos;s watching tonight?</span>
          <select
            value={activeProfile.id}
            onChange={(e) => setActiveProfileId(e.target.value)}
            className="bg-slate-900 px-2.5 py-1 rounded-lg font-semibold text-amber-300 border border-slate-700"
          >
            {status.profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {activeTab === 'taste' ? (
          <TasteTuner
            activeProfile={activeProfile}
            llmEnabled={status.llm.enabled}
            onOpenSettings={() => setSettingsOpen(true)}
            onSelectMedia={(it) => setSelectedItem(it)}
            onTasteChanged={() => {
              refreshStatus();
            }}
          />
        ) : (
          <div className="space-y-6">
            {/* Mood & AI Steering Panel */}
            <div className="bg-[#121620] border border-slate-800/80 rounded-2xl p-4 sm:p-5 space-y-4 shadow-lg shadow-black/20">
              <form onSubmit={handlePromptSubmit} className="flex flex-col sm:flex-row gap-2.5">
                <div className="relative flex-1">
                  <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={promptInput}
                    onChange={(e) => {
                      setPromptInput(e.target.value);
                      if (!e.target.value.trim() && appliedPrompt) {
                        setAppliedPrompt('');
                      }
                    }}
                    placeholder="Steer tonight's vibe... (e.g. 'smart sci-fi mystery under 2 hours' or 'sharp British dark comedy series')"
                    className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-[#0b0d12] border border-slate-700/80 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-amber-500/70"
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-100 transition cursor-pointer"
                  >
                    Filter
                  </button>
                  <button
                    type="button"
                    disabled={aiLoading}
                    onClick={() => handleRunAICurate(true)}
                    className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-400 hover:from-amber-400 hover:to-amber-300 text-slate-950 font-semibold text-xs inline-flex items-center gap-1.5 shadow-md shadow-amber-500/15 transition cursor-pointer shrink-0"
                  >
                    {aiLoading ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        Curating...
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-3.5 h-3.5" />
                        AI Deep Curate
                      </>
                    )}
                  </button>
                </div>
              </form>

              {/* Mood Chips */}
              <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
                {status.moods.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setMood(m.id)}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition cursor-pointer ${
                      mood === m.id
                        ? 'bg-amber-500/20 border border-amber-400/60 text-amber-200'
                        : 'bg-[#0b0d12] hover:bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>

              {/* Granular Filters Bar */}
              <div className="pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-4 text-xs">
                <div className="flex flex-wrap items-center gap-2.5">
                  <div className="inline-flex rounded-lg bg-[#0b0d12] p-0.5 border border-slate-800">
                    {[
                      { id: 'all', label: 'All' },
                      { id: 'movie', label: 'Movies' },
                      { id: 'show', label: 'TV Shows' },
                    ].map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => setMediaType(t.id)}
                        className={`px-2.5 py-1 rounded-md font-medium transition cursor-pointer ${
                          mediaType === t.id ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>

                  <select
                    value={sourceScope}
                    onChange={(e) => setSourceScope(e.target.value)}
                    className="px-2.5 py-1.5 rounded-lg bg-[#0b0d12] border border-slate-800 text-slate-200 focus:outline-none"
                  >
                    <option value="plex_all">All Plex (Local + Shared)</option>
                    <option value="local_only">My Local Server Only</option>
                    <option value="shared_only">Friends&apos; Shared Servers Only</option>
                  </select>

                  <select
                    value={decade}
                    onChange={(e) => setDecade(e.target.value)}
                    className="px-2.5 py-1.5 rounded-lg bg-[#0b0d12] border border-slate-800 text-slate-200 focus:outline-none"
                  >
                    <option value="">Any Era</option>
                    <option value="2020s">2020s</option>
                    <option value="2010s">2010s</option>
                    <option value="2000s">2000s</option>
                    <option value="1990s">1990s</option>
                    <option value="1980s">1980s</option>
                    <option value="1970s">1970s</option>
                    <option value="1960s">1960s</option>
                  </select>

                  <button
                    type="button"
                    onClick={() => setIncludeOutside((v) => !v)}
                    className={`px-3 py-1.5 rounded-lg border inline-flex items-center gap-1.5 font-medium transition cursor-pointer ${
                      includeOutside
                        ? 'bg-violet-500/20 border-violet-400/50 text-violet-200'
                        : 'bg-[#0b0d12] border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Globe className="w-3.5 h-3.5" />
                    + Outside Plex Discoveries
                  </button>
                </div>

                {/* Discovery Dial */}
                <div className="flex items-center gap-2.5 text-slate-400">
                  <SlidersHorizontal className="w-3.5 h-3.5 text-amber-400" />
                  <span>Familiar</span>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.15}
                    value={discoveryLevel}
                    onChange={(e) => setDiscoveryLevel(parseFloat(e.target.value))}
                    className="w-24 accent-amber-500 cursor-pointer"
                  />
                  <span className={discoveryLevel >= 0.65 ? 'text-amber-300 font-medium' : ''}>
                    Hidden Gems
                  </span>
                </div>
              </div>
            </div>

            {/* AI Curator Headline */}
            {curatorHeadline && (
              <div className="p-4 rounded-2xl bg-gradient-to-r from-amber-500/15 via-amber-500/5 to-transparent border border-amber-500/30 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <Sparkles className="w-5 h-5 text-amber-400 shrink-0" />
                  <div>
                    <div className="text-sm font-semibold text-amber-100">{curatorHeadline}</div>
                    <div className="text-[11px] text-amber-300/75">
                      Curated by {status.llm.provider} ({status.llm.active_model}) + Local Taste Graph
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Results Grid */}
            {recsLoading || aiLoading ? (
              <div className="py-24 flex flex-col items-center justify-center text-slate-400 gap-3">
                <Loader2 className="w-7 h-7 animate-spin text-amber-400" />
                <span className="text-sm">
                  {aiLoading
                    ? 'AI Curator is weighing your taste graph & tonight’s mood...'
                    : 'Scoring your local & shared Plex libraries...'}
                </span>
              </div>
            ) : items.length === 0 ? (
              <div className="p-12 rounded-2xl bg-[#121620] border border-slate-800/80 text-center space-y-3">
                <div className="text-base font-semibold text-white">
                  {status.stats.total_items === 0
                    ? 'Ready to index your Plex libraries'
                    : 'No unwatched titles matched all active filters'}
                </div>
                <p className="text-xs text-slate-400 max-w-md mx-auto">
                  {status.stats.total_items === 0
                    ? 'Click Sync in the top bar to index your local Plex server and shared friend libraries.'
                    : 'Try broadening your era/mood filters or enabling "+ Outside Plex Discoveries".'}
                </p>
              </div>
            ) : (
              <div>
                <div className="flex items-center justify-between mb-3 text-xs text-slate-400">
                  <span>
                    Showing top <strong className="text-slate-200">{items.length}</strong> diverse picks from{' '}
                    <strong className="text-slate-200">{totalPool.toLocaleString()}</strong> unwatched candidates
                    for <strong className="text-amber-300">{activeProfile.name}</strong>
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
                  {items.map((it) => (
                    <MediaCard
                      key={it.id}
                      item={it}
                      onSelect={(m) => setSelectedItem(m)}
                      onToggleWatchlist={handleToggleWatchlist}
                      onFeedback={handleFeedback}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {/* Modals */}
      <MediaDetailModal
        item={selectedItem}
        profileName={activeProfile.name}
        onClose={() => setSelectedItem(null)}
        onToggleWatchlist={handleToggleWatchlist}
        onFeedback={handleFeedback}
      />

      <SettingsModal
        status={status}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onUpdated={refreshStatus}
      />

      {/* Toast Notification */}
      {toast && (
        <div className="fixed bottom-5 right-5 z-50 px-4 py-3 rounded-xl bg-slate-900/95 border border-amber-500/40 text-amber-100 text-xs font-medium shadow-2xl backdrop-blur-md">
          {toast}
        </div>
      )}
    </div>
  );
};
