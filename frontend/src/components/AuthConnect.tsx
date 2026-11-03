import React, { useEffect, useState } from 'react';
import { Film, KeyRound, Loader2, Server, ShieldCheck, Sparkles, Tv } from 'lucide-react';
import { api } from '../api';

interface Props {
  onAuthenticated: () => void;
}

export const AuthConnect: React.FC<Props> = ({ onAuthenticated }) => {
  const [pinId, setPinId] = useState<number | null>(null);
  const [authUrl, setAuthUrl] = useState<string>('');
  const [waiting, setWaiting] = useState(false);
  const [showManual, setShowManual] = useState(false);
  const [manualToken, setManualToken] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleStartOAuth = async () => {
    setError(null);
    setWaiting(true);
    try {
      const res = await api.startPlexPin();
      setPinId(res.pin_id);
      setAuthUrl(res.auth_url);
      window.open(res.auth_url, '_blank', 'noopener,noreferrer');
    } catch (err: any) {
      setError(err.message || 'Could not start Plex sign-in.');
      setWaiting(false);
    }
  };

  useEffect(() => {
    if (!pinId || !waiting) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const res = await api.checkPlexPin(pinId);
        if (cancelled) return;
        if (res.authenticated) {
          clearInterval(timer);
          setWaiting(false);
          onAuthenticated();
        } else if (res.expired) {
          clearInterval(timer);
          setWaiting(false);
          setError('Sign-in link expired. Click Sign in with Plex to try again.');
        }
      } catch {
        // Ignore transient network hiccups while polling
      }
    }, 1800);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [pinId, waiting, onAuthenticated]);

  const handleManualSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualToken.trim()) return;
    setError(null);
    setWaiting(true);
    try {
      await api.loginWithToken(manualToken.trim());
      setWaiting(false);
      onAuthenticated();
    } catch (err: any) {
      setWaiting(false);
      setError(err.message || 'Invalid Plex token.');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-amber-950/25 via-[#0b0d12] to-[#0b0d12]">
      <div className="max-w-xl w-full bg-[#121620] border border-slate-800/80 rounded-2xl p-8 md:p-10 shadow-2xl">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/25 text-amber-300 text-xs font-medium mb-6">
          <Sparkles className="w-3.5 h-3.5" />
          Zero Commercial Bias · Local + Shared Plex Libraries
        </div>

        <h1 className="text-3xl md:text-4xl font-bold tracking-tight text-white mb-3">
          Meet <span className="text-amber-400">Plexbot</span>
        </h1>
        <p className="text-slate-300 text-sm md:text-base leading-relaxed mb-8">
          Recommendations built around what you actually loved, finished, rewatched, or turned off —
          searching across both your local Plex server and every friend&apos;s shared library.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-8 text-xs text-slate-300">
          <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800/70">
            <Server className="w-4 h-4 text-emerald-400 mb-2" />
            <div className="font-semibold text-slate-100 mb-0.5">All Your Servers</div>
            Unifies your local Mac downloads and friends&apos; shared Plex libraries.
          </div>
          <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800/70">
            <Film className="w-4 h-4 text-amber-400 mb-2" />
            <div className="font-semibold text-slate-100 mb-0.5">Real Taste DNA</div>
            Weighs directors, writers, themes, rewatches &amp; abandoned shows.
          </div>
          <div className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800/70">
            <Tv className="w-4 h-4 text-sky-400 mb-2" />
            <div className="font-semibold text-slate-100 mb-0.5">1-Click Watchlist</div>
            Send picks straight to your Plex Watchlist so they appear on your TV.
          </div>
        </div>

        {error && (
          <div className="mb-5 p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-200 text-sm">
            {error}
          </div>
        )}

        {!waiting ? (
          <button
            onClick={handleStartOAuth}
            className="w-full py-3.5 px-6 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold text-base transition flex items-center justify-center gap-2.5 shadow-lg shadow-amber-500/15 cursor-pointer"
          >
            Sign in with Plex
          </button>
        ) : (
          <div className="space-y-3">
            <div className="w-full py-3.5 px-6 rounded-xl bg-amber-500/15 border border-amber-500/35 text-amber-200 font-medium text-sm flex items-center justify-center gap-2.5">
              <Loader2 className="w-4 h-4 animate-spin" />
              Waiting for Plex authorization in your browser...
            </div>
            {authUrl && (
              <p className="text-center text-xs text-slate-400">
                Browser tab didn&apos;t open?{' '}
                <a
                  href={authUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-amber-400 hover:underline font-medium"
                >
                  Click here to authorize Plexbot
                </a>
                {' · '}
                <button
                  type="button"
                  onClick={() => setWaiting(false)}
                  className="text-slate-400 hover:text-slate-200 underline cursor-pointer"
                >
                  Cancel
                </button>
              </p>
            )}
          </div>
        )}

        <div className="mt-6 pt-5 border-t border-slate-800/80 flex flex-col gap-3">
          <button
            type="button"
            onClick={() => setShowManual((v) => !v)}
            className="text-xs text-slate-400 hover:text-slate-200 inline-flex items-center gap-1.5 self-start cursor-pointer"
          >
            <KeyRound className="w-3.5 h-3.5" />
            {showManual ? 'Hide manual X-Plex-Token input' : 'Or sign in with an X-Plex-Token manually'}
          </button>

          {showManual && (
            <form onSubmit={handleManualSubmit} className="flex gap-2">
              <input
                type="password"
                value={manualToken}
                onChange={(e) => setManualToken(e.target.value)}
                placeholder="Paste X-Plex-Token..."
                className="flex-1 px-3.5 py-2 rounded-lg bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none focus:border-amber-500"
              />
              <button
                type="submit"
                className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-sm font-medium text-white cursor-pointer"
              >
                Connect
              </button>
            </form>
          )}

          <div className="flex items-center gap-1.5 text-[11px] text-slate-500 mt-1">
            <ShieldCheck className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            Runs 100% locally on your Mac. Your Plex token stays in your local SQLite database.
          </div>
        </div>
      </div>
    </div>
  );
};
