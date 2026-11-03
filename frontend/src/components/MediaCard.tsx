import React, { useState } from 'react';
import {
  Bookmark,
  BookmarkCheck,
  ExternalLink,
  EyeOff,
  Film,
  Flame,
  Globe,
  HardDrive,
  Loader2,
  Sparkles,
  Star,
  ThumbsDown,
  ThumbsUp,
  Tv,
  Users,
} from 'lucide-react';
import { MediaItem, Sentiment } from '../types';

interface Props {
  item: MediaItem;
  onSelect: (item: MediaItem) => void;
  onToggleWatchlist: (item: MediaItem) => Promise<void>;
  onFeedback: (item: MediaItem, sentiment: Sentiment) => Promise<void>;
}

export const MediaCard: React.FC<Props> = ({
  item,
  onSelect,
  onToggleWatchlist,
  onFeedback,
}) => {
  const [imgErr, setImgErr] = useState(false);
  const [wlBusy, setWlBusy] = useState(false);

  const primary = item.primary_source;
  const rating = item.audience_rating || item.critic_rating;

  const handleWl = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setWlBusy(true);
    try {
      await onToggleWatchlist(item);
    } finally {
      setWlBusy(false);
    }
  };

  const handleQuickFeedback = async (e: React.MouseEvent, s: Sentiment) => {
    e.stopPropagation();
    await onFeedback(item, s);
  };

  return (
    <div
      onClick={() => onSelect(item)}
      className="group relative flex flex-col bg-[#121620] border border-slate-800/80 hover:border-amber-500/45 rounded-2xl overflow-hidden transition-all duration-200 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-black/40 cursor-pointer"
    >
      {/* Poster region */}
      <div className="relative aspect-[2/3] w-full bg-slate-900 overflow-hidden">
        {item.poster_url && !imgErr ? (
          <img
            src={item.poster_url}
            alt={item.title}
            loading="lazy"
            onError={() => setImgErr(true)}
            className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center p-6 text-center bg-gradient-to-br from-slate-800 via-slate-900 to-[#0b0d12]">
            {item.media_type === 'movie' ? (
              <Film className="w-10 h-10 text-slate-600 mb-3" />
            ) : (
              <Tv className="w-10 h-10 text-slate-600 mb-3" />
            )}
            <span className="text-sm font-semibold text-slate-300 line-clamp-3">{item.title}</span>
            {item.year && <span className="text-xs text-slate-500 mt-1">{item.year}</span>}
          </div>
        )}

        <div className="absolute inset-0 bg-gradient-to-t from-[#121620] via-transparent to-black/55 pointer-events-none" />

        {/* Availability badge (top-left) */}
        <div className="absolute top-2.5 left-2.5 right-16 flex flex-wrap gap-1">
          {primary ? (
            primary.source_type === 'streaming' ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-red-950/90 border border-red-500/45 text-red-200 text-[11px] font-semibold backdrop-blur-sm truncate max-w-full">
                <span className="w-2 h-2 rounded-full bg-red-500 shrink-0" />
                <span className="truncate">{primary.server_name}</span>
              </span>
            ) : primary.owned ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-950/90 border border-emerald-500/40 text-emerald-300 text-[11px] font-medium backdrop-blur-sm truncate max-w-full">
                <HardDrive className="w-3 h-3 shrink-0" />
                <span className="truncate">Local{primary.resolution ? ` · ${primary.resolution}` : ''}</span>
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-sky-950/90 border border-sky-500/40 text-sky-200 text-[11px] font-medium backdrop-blur-sm truncate max-w-full">
                <Users className="w-3 h-3 shrink-0" />
                <span className="truncate">
                  {primary.server_name}
                  {primary.resolution ? ` · ${primary.resolution}` : ''}
                </span>
              </span>
            )
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-violet-950/90 border border-violet-500/40 text-violet-200 text-[11px] font-medium backdrop-blur-sm">
              <Globe className="w-3 h-3 shrink-0" />
              Outside
            </span>
          )}
          {item.sources.length > 1 && (
            <span className="px-1.5 py-0.5 rounded-md bg-black/75 text-slate-300 text-[10px] font-medium backdrop-blur-sm">
              +{item.sources.length - 1}
            </span>
          )}
        </div>

        {/* Match % badge (top-right) */}
        {item.match_score && (
          <div className="absolute top-2.5 right-2.5 px-2 py-0.5 rounded-md bg-black/80 border border-amber-400/40 text-amber-300 text-xs font-bold backdrop-blur-sm flex items-center gap-1">
            {item.ai_curated && <Sparkles className="w-3 h-3 text-amber-400" />}
            {item.match_score}%
          </div>
        )}

        {/* Quick hover feedback bar */}
        <div className="absolute bottom-2.5 left-2.5 right-2.5 flex items-center justify-between opacity-0 group-hover:opacity-100 transition-opacity duration-150">
          <div className="flex items-center gap-1 bg-black/85 border border-slate-700/80 rounded-lg p-1 backdrop-blur-md">
            <button
              type="button"
              title="Seen & Loved it!"
              onClick={(e) => handleQuickFeedback(e, 'love')}
              className="p-1.5 rounded-md hover:bg-amber-500/25 text-slate-300 hover:text-amber-300 transition cursor-pointer"
            >
              <Flame className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              title="Seen & Liked it"
              onClick={(e) => handleQuickFeedback(e, 'like')}
              className="p-1.5 rounded-md hover:bg-emerald-500/25 text-slate-300 hover:text-emerald-300 transition cursor-pointer"
            >
              <ThumbsUp className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              title="Disliked / Not my taste"
              onClick={(e) => handleQuickFeedback(e, 'dislike')}
              className="p-1.5 rounded-md hover:bg-rose-500/25 text-slate-300 hover:text-rose-300 transition cursor-pointer"
            >
              <ThumbsDown className="w-3.5 h-3.5" />
            </button>
          </div>

          <button
            type="button"
            title="Hide from recommendations"
            onClick={(e) => handleQuickFeedback(e, 'dismiss')}
            className="p-2 rounded-lg bg-black/85 border border-slate-700/80 text-slate-400 hover:text-slate-100 backdrop-blur-md transition cursor-pointer"
          >
            <EyeOff className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Info & Taste Pitch */}
      <div className="flex-1 flex flex-col p-3.5">
        <div className="flex items-start justify-between gap-2 mb-1">
          <h3 className="font-semibold text-sm text-white leading-snug line-clamp-2 group-hover:text-amber-300 transition">
            {item.title}
          </h3>
        </div>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-400 mb-2.5">
          {item.year && <span>{item.year}</span>}
          <span>·</span>
          <span className="uppercase tracking-wider text-[10px] font-medium text-slate-300">
            {item.media_type === 'movie' ? 'Movie' : 'Series'}
          </span>
          {item.duration_min && (
            <>
              <span>·</span>
              <span>
                {item.media_type === 'movie'
                  ? `${item.duration_min}m`
                  : `${item.duration_min}m/ep`}
              </span>
            </>
          )}
          {rating && (
            <>
              <span>·</span>
              <span className="inline-flex items-center gap-0.5 text-amber-300 font-medium">
                <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
                {rating.toFixed(1)}
              </span>
            </>
          )}
        </div>

        {item.vibe_tag && (
          <div className="mb-1.5">
            <span className="inline-block px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/25 text-amber-300 text-[10px] font-medium">
              {item.vibe_tag}
            </span>
          </div>
        )}

        {item.explanation && (
          <p className="text-xs text-slate-300/95 leading-relaxed line-clamp-3 mb-3 flex-1">
            {item.explanation}
          </p>
        )}

        {/* Action buttons */}
        <div className="mt-auto pt-2.5 border-t border-slate-800/80 flex items-center gap-2">
          <button
            type="button"
            disabled={wlBusy}
            onClick={handleWl}
            className={`flex-1 py-1.5 px-2.5 rounded-lg text-xs font-medium flex items-center justify-center gap-1.5 transition cursor-pointer ${
              item.on_watchlist
                ? 'bg-amber-500/20 border border-amber-500/45 text-amber-300'
                : 'bg-slate-800/90 hover:bg-slate-700/90 text-slate-200 border border-slate-700/70'
            }`}
          >
            {wlBusy ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : item.on_watchlist ? (
              <>
                <BookmarkCheck className="w-3.5 h-3.5" />
                Watchlisted
              </>
            ) : (
              <>
                <Bookmark className="w-3.5 h-3.5" />
                Watchlist
              </>
            )}
          </button>

          {primary && (
            <a
              href={primary.deep_link}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              title={
                primary.source_type === 'streaming'
                  ? `Open "${item.title}" on ${primary.server_name}`
                  : `Open on ${primary.server_name} in Plex`
              }
              className={`py-1.5 px-2.5 rounded-lg text-xs font-medium inline-flex items-center gap-1 transition ${
                primary.source_type === 'streaming'
                  ? 'bg-red-500/15 hover:bg-red-500/25 border border-red-500/40 text-red-200'
                  : 'bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/35 text-emerald-300'
              }`}
            >
              {primary.source_type === 'streaming' ? primary.server_name : 'Plex'}
              <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      </div>
    </div>
  );
};
