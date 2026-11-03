import React, { useState } from 'react';
import {
  Bookmark,
  BookmarkCheck,
  ExternalLink,
  Film,
  Flame,
  HardDrive,
  Loader2,
  Meh,
  Sparkles,
  Star,
  ThumbsDown,
  ThumbsUp,
  Tv,
  Users,
  X,
} from 'lucide-react';
import { MediaItem, Sentiment } from '../types';

interface Props {
  item: MediaItem | null;
  profileName: string;
  onClose: () => void;
  onToggleWatchlist: (item: MediaItem) => Promise<void>;
  onFeedback: (item: MediaItem, sentiment: Sentiment | 'clear') => Promise<void>;
}

export const MediaDetailModal: React.FC<Props> = ({
  item,
  profileName,
  onClose,
  onToggleWatchlist,
  onFeedback,
}) => {
  const [wlBusy, setWlBusy] = useState(false);

  if (!item) return null;

  const handleWl = async () => {
    setWlBusy(true);
    try {
      await onToggleWatchlist(item);
    } finally {
      setWlBusy(false);
    }
  };

  const sentiments: { id: Sentiment; label: string; icon: React.ReactNode; activeCls: string }[] = [
    {
      id: 'love',
      label: 'Loved It',
      icon: <Flame className="w-4 h-4" />,
      activeCls: 'bg-amber-500/25 border-amber-400 text-amber-200',
    },
    {
      id: 'like',
      label: 'Liked',
      icon: <ThumbsUp className="w-4 h-4" />,
      activeCls: 'bg-emerald-500/25 border-emerald-400 text-emerald-200',
    },
    {
      id: 'meh',
      label: 'Meh',
      icon: <Meh className="w-4 h-4" />,
      activeCls: 'bg-slate-600/30 border-slate-400 text-slate-200',
    },
    {
      id: 'dislike',
      label: 'Disliked',
      icon: <ThumbsDown className="w-4 h-4" />,
      activeCls: 'bg-rose-500/25 border-rose-400 text-rose-200',
    },
  ];

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm overflow-y-auto"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative max-w-3xl w-full bg-[#131824] border border-slate-700/80 rounded-2xl shadow-2xl overflow-hidden my-8"
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 z-10 p-2 rounded-full bg-black/60 hover:bg-black/85 text-slate-300 hover:text-white transition cursor-pointer"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex flex-col md:flex-row gap-6 p-6 md:p-8">
          {/* Poster */}
          <div className="w-44 md:w-56 shrink-0 mx-auto md:mx-0">
            <div className="aspect-[2/3] rounded-xl overflow-hidden bg-slate-900 border border-slate-800 shadow-lg">
              {item.poster_url ? (
                <img src={item.poster_url} alt={item.title} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-slate-600">
                  {item.media_type === 'movie' ? (
                    <Film className="w-12 h-12" />
                  ) : (
                    <Tv className="w-12 h-12" />
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Details */}
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-2">
              {item.match_score && (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-400/40 text-amber-300 text-xs font-bold">
                  {item.ai_curated && <Sparkles className="w-3.5 h-3.5" />}
                  {item.match_score}% Match
                </span>
              )}
              {item.vibe_tag && (
                <span className="px-2.5 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-200 text-xs">
                  {item.vibe_tag}
                </span>
              )}
              {item.content_rating && (
                <span className="px-2 py-0.5 rounded border border-slate-700 text-slate-400 text-[11px]">
                  {item.content_rating}
                </span>
              )}
            </div>

            <h2 className="text-2xl md:text-3xl font-bold text-white leading-tight mb-1">
              {item.title}{' '}
              {item.year && <span className="text-slate-400 font-normal text-xl">({item.year})</span>}
            </h2>

            {item.tagline && (
              <p className="text-sm italic text-amber-200/80 mb-3">&ldquo;{item.tagline}&rdquo;</p>
            )}

            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-300 mb-4">
              <span className="uppercase tracking-wider font-semibold text-slate-400">
                {item.media_type === 'movie' ? 'Movie' : 'TV Series'}
              </span>
              {item.duration_min && (
                <span>
                  {item.media_type === 'movie'
                    ? `${item.duration_min} mins`
                    : `${item.duration_min} mins / ep`}
                </span>
              )}
              {item.leaf_count > 0 && item.media_type === 'show' && (
                <span>{item.leaf_count} episodes</span>
              )}
              {item.audience_rating && (
                <span className="inline-flex items-center gap-1 text-amber-300 font-medium">
                  <Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
                  Audience {item.audience_rating.toFixed(1)}/10
                </span>
              )}
              {item.critic_rating && (
                <span className="text-slate-300">Critic {item.critic_rating.toFixed(1)}/10</span>
              )}
            </div>

            {item.explanation && (
              <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/25 text-amber-100 text-sm leading-relaxed mb-4">
                <div className="text-[11px] uppercase tracking-wider font-semibold text-amber-400 mb-1">
                  Why Plexbot Picked This For {profileName}
                </div>
                {item.explanation}
              </div>
            )}

            <p className="text-sm text-slate-300 leading-relaxed mb-5">{item.summary}</p>

            {/* Genres & Credits */}
            <div className="space-y-2 text-xs text-slate-300 mb-6">
              {item.genres.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {item.genres.map((g) => (
                    <span
                      key={g}
                      className="px-2.5 py-0.5 rounded-full bg-slate-800/90 border border-slate-700/80 text-slate-200"
                    >
                      {g}
                    </span>
                  ))}
                </div>
              )}
              {item.directors.length > 0 && (
                <div>
                  <span className="text-slate-500">Directed by: </span>
                  <span className="text-slate-200 font-medium">{item.directors.join(', ')}</span>
                </div>
              )}
              {item.writers.length > 0 && (
                <div>
                  <span className="text-slate-500">Written by: </span>
                  <span className="text-slate-200">{item.writers.join(', ')}</span>
                </div>
              )}
              {item.cast.length > 0 && (
                <div>
                  <span className="text-slate-500">Cast: </span>
                  <span className="text-slate-200">{item.cast.slice(0, 6).join(', ')}</span>
                </div>
              )}
              {item.studios.length > 0 && (
                <div>
                  <span className="text-slate-500">Studio / Network: </span>
                  <span className="text-slate-200">{item.studios.join(', ')}</span>
                </div>
              )}
            </div>

            {/* Primary Actions */}
            <div className="flex flex-wrap items-center gap-3 mb-6">
              <button
                type="button"
                disabled={wlBusy}
                onClick={handleWl}
                className={`py-2.5 px-4 rounded-xl text-sm font-semibold inline-flex items-center gap-2 transition cursor-pointer ${
                  item.on_watchlist
                    ? 'bg-amber-500 text-slate-950'
                    : 'bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/40 text-amber-300'
                }`}
              >
                {wlBusy ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : item.on_watchlist ? (
                  <>
                    <BookmarkCheck className="w-4 h-4" />
                    In Your Plex Watchlist
                  </>
                ) : (
                  <>
                    <Bookmark className="w-4 h-4" />
                    Add to Plex Watchlist
                  </>
                )}
              </button>

              {item.primary_source && (
                <a
                  href={item.primary_source.deep_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`py-2.5 px-4 rounded-xl font-semibold text-sm inline-flex items-center gap-2 transition ${
                    item.primary_source.source_type === 'streaming'
                      ? 'bg-red-600 hover:bg-red-500 text-white'
                      : 'bg-emerald-500 hover:bg-emerald-400 text-slate-950'
                  }`}
                >
                  {item.primary_source.source_type === 'streaming'
                    ? `Watch on ${item.primary_source.server_name}`
                    : `Open in Plex (${item.primary_source.server_name})`}
                  <ExternalLink className="w-4 h-4" />
                </a>
              )}
            </div>

            {/* Available Sources List */}
            {item.sources.length > 0 && (
              <div className="mb-6">
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
                  Available Across {item.sources.length} Source{item.sources.length > 1 ? 's' : ''}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {item.sources.map((src) => (
                    <a
                      key={`${src.machine_id}-${src.rating_key}`}
                      href={src.deep_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/90 hover:bg-slate-800 border border-slate-800 transition text-xs"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        {src.source_type === 'streaming' ? (
                          <span className="w-3.5 h-3.5 rounded-full bg-red-500 shrink-0" />
                        ) : src.owned ? (
                          <HardDrive className="w-4 h-4 text-emerald-400 shrink-0" />
                        ) : (
                          <Users className="w-4 h-4 text-sky-400 shrink-0" />
                        )}
                        <div className="truncate">
                          <div className="font-medium text-slate-100 truncate">{src.server_name}</div>
                          <div className="text-[11px] text-slate-400 truncate">
                            {src.source_type === 'streaming'
                              ? `${src.section_title} · Direct Stream`
                              : `${src.section_title} · ${src.owned ? 'Your Local Server' : `Shared by ${src.owner_name}`}`}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0 ml-2">
                        {src.resolution && (
                          <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-200 font-medium">
                            {src.resolution}
                            {src.hdr ? ' HDR' : ''}
                          </span>
                        )}
                        <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
                      </div>
                    </a>
                  ))}
                </div>
              </div>
            )}

            {/* Taste Calibration Strip */}
            <div className="pt-4 border-t border-slate-800">
              <div className="text-xs text-slate-400 mb-2">
                Tune taste for <span className="text-slate-200 font-medium">{profileName}</span>:
              </div>
              <div className="flex flex-wrap gap-2">
                {sentiments.map((s) => {
                  const active = item.feedback === s.id;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => onFeedback(item, active ? 'clear' : s.id)}
                      className={`px-3 py-1.5 rounded-lg border text-xs font-medium inline-flex items-center gap-1.5 transition cursor-pointer ${
                        active
                          ? s.activeCls
                          : 'bg-slate-900 hover:bg-slate-800 border-slate-700/80 text-slate-300'
                      }`}
                    >
                      {s.icon}
                      {s.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
