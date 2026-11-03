import React, { useRef, useState } from 'react';
import {
  CheckCircle2,
  ExternalLink,
  FileSpreadsheet,
  HardDrive,
  Loader2,
  LogOut,
  Plus,
  RefreshCw,
  Server,
  Sparkles,
  Trash2,
  Upload,
  Users,
  X,
} from 'lucide-react';
import { api } from '../api';
import { AppStatus, NetflixImportResult } from '../types';

interface Props {
  status: AppStatus;
  open: boolean;
  onClose: () => void;
  onUpdated: () => Promise<void>;
}

export const SettingsModal: React.FC<Props> = ({ status, open, onClose, onUpdated }) => {
  const [provider, setProvider] = useState<string>(status.llm.provider || 'none');
  const [geminiKey, setGeminiKey] = useState<string>(status.llm.gemini_key_masked || '');
  const [anthropicKey, setAnthropicKey] = useState<string>(status.llm.anthropic_key_masked || '');
  const [openaiKey, setOpenaiKey] = useState<string>(status.llm.openai_key_masked || '');
  const [geminiModel, setGeminiModel] = useState<string>(status.llm.gemini_model);
  const [anthropicModel, setAnthropicModel] = useState<string>(status.llm.anthropic_model);
  const [openaiModel, setOpenaiModel] = useState<string>(status.llm.openai_model);

  const [savingLLM, setSavingLLM] = useState(false);
  const [testingLLM, setTestingLLM] = useState(false);
  const [llmFeedback, setLlmFeedback] = useState<{ ok: boolean; msg: string } | null>(null);

  // Netflix state
  const [nfEnabled, setNfEnabled] = useState<boolean>(status.netflix?.enabled ?? true);
  const [nfRegion, setNfRegion] = useState<string>(status.netflix?.watch_region || 'NZ');
  const [tmdbKey, setTmdbKey] = useState<string>(status.netflix?.tmdb_key_masked || '');
  const [showTmdbInput, setShowTmdbInput] = useState<boolean>(Boolean(status.netflix?.has_tmdb_key));
  const [syncingNf, setSyncingNf] = useState<boolean>(false);
  const [nfMsg, setNfMsg] = useState<{ ok: boolean; msg: string } | null>(null);

  // CSV Import state
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [csvProfileFilter, setCsvProfileFilter] = useState<string>('');
  const [importingCsv, setImportingCsv] = useState<boolean>(false);
  const [csvResult, setCsvResult] = useState<NetflixImportResult | null>(null);
  const [csvError, setCsvError] = useState<string | null>(null);

  const [newProfName, setNewProfName] = useState('');
  const [newProfInherit, setNewProfInherit] = useState(true);

  if (!open) return null;

  const plexServers = status.servers.filter((s) => (s.source_type || 'plex') === 'plex');

  const handleSaveLLM = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingLLM(true);
    setLlmFeedback(null);
    try {
      await api.saveLLMSettings({
        llm_provider: provider,
        gemini_api_key: geminiKey,
        anthropic_api_key: anthropicKey,
        openai_api_key: openaiKey,
        gemini_model: geminiModel,
        anthropic_model: anthropicModel,
        openai_model: openaiModel,
      });
      await onUpdated();
      setLlmFeedback({ ok: true, msg: 'AI Curator settings saved!' });
    } catch (err: any) {
      setLlmFeedback({ ok: false, msg: err.message || 'Failed saving settings.' });
    } finally {
      setSavingLLM(false);
    }
  };

  const handleTestLLM = async () => {
    if (provider === 'none') return;
    setTestingLLM(true);
    setLlmFeedback(null);
    const activeKey =
      provider === 'gemini' ? geminiKey : provider === 'anthropic' ? anthropicKey : openaiKey;
    const activeModel =
      provider === 'gemini' ? geminiModel : provider === 'anthropic' ? anthropicModel : openaiModel;
    try {
      const res = await api.testLLM(provider, activeKey, activeModel);
      setLlmFeedback({ ok: true, msg: `Connected (${provider}): "${res.message}"` });
    } catch (err: any) {
      setLlmFeedback({ ok: false, msg: err.message || 'Connection test failed.' });
    } finally {
      setTestingLLM(false);
    }
  };

  const handleSaveAndSyncNetflix = async (nextEnabled = nfEnabled, nextRegion = nfRegion) => {
    setSyncingNf(true);
    setNfMsg(null);
    try {
      await api.saveNetflixSettings({
        enabled: nextEnabled,
        watch_region: nextRegion,
        tmdb_api_key: tmdbKey,
      });
      await onUpdated();
      setNfMsg({
        ok: true,
        msg: nextEnabled
          ? `Synced Netflix (${nextRegion}) catalog!`
          : 'Netflix catalog disabled.',
      });
    } catch (err: any) {
      setNfMsg({ ok: false, msg: err.message || 'Netflix sync failed.' });
    } finally {
      setSyncingNf(false);
    }
  };

  const handleCsvFileSelected = async (file: File | null) => {
    if (!file) return;
    setImportingCsv(true);
    setCsvError(null);
    setCsvResult(null);
    try {
      const text = await file.text();
      const res = await api.importNetflixCSV(text, csvProfileFilter.trim() || undefined);
      setCsvResult(res);
      await onUpdated();
    } catch (err: any) {
      setCsvError(err.message || 'Failed importing Netflix CSV.');
    } finally {
      setImportingCsv(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleToggleServer = async (machineId: string, enabled: boolean) => {
    await api.toggleServer(machineId, enabled);
    await onUpdated();
  };

  const handleAddProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProfName.trim()) return;
    await api.createProfile(newProfName.trim(), '', newProfInherit);
    setNewProfName('');
    await onUpdated();
  };

  const handleDeleteProfile = async (id: string) => {
    await api.deleteProfile(id);
    await onUpdated();
  };

  const handleLogout = async () => {
    await api.logoutPlex();
    await onUpdated();
    onClose();
  };

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm overflow-y-auto"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative max-w-2xl w-full bg-[#131824] border border-slate-700/80 rounded-2xl shadow-2xl p-6 md:p-8 my-8 max-h-[90vh] overflow-y-auto space-y-8"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-white">Sources, Netflix, AI Brain &amp; Profiles</h2>
          <button
            onClick={onClose}
            className="p-2 rounded-full hover:bg-slate-800 text-slate-400 hover:text-white cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 1. Netflix Catalog & Viewing History CSV */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-bold text-red-400 uppercase tracking-wider">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
              Netflix Source &amp; Watch History
            </div>
            <span className="text-xs text-slate-400">
              {status.netflix.movie_count.toLocaleString()} movies ·{' '}
              {status.netflix.show_count.toLocaleString()} shows indexed
            </span>
          </div>

          <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="inline-flex items-center gap-2.5 cursor-pointer text-xs font-medium text-slate-200">
                <input
                  type="checkbox"
                  checked={nfEnabled}
                  onChange={(e) => {
                    const v = e.target.checked;
                    setNfEnabled(v);
                    handleSaveAndSyncNetflix(v, nfRegion);
                  }}
                  className="accent-red-500 w-4 h-4"
                />
                Include Netflix catalog in recommendations
              </label>

              <div className="flex items-center gap-2">
                <select
                  value={nfRegion}
                  onChange={(e) => setNfRegion(e.target.value)}
                  className="px-2.5 py-1.5 rounded-lg bg-[#0e121b] border border-slate-700 text-xs text-white"
                >
                  <option value="NZ">New Zealand (NZ)</option>
                  <option value="AU">Australia (AU)</option>
                  <option value="US">United States (US)</option>
                  <option value="GB">United Kingdom (GB)</option>
                  <option value="CA">Canada (CA)</option>
                  <option value="IE">Ireland (IE)</option>
                </select>

                <button
                  type="button"
                  disabled={syncingNf}
                  onClick={() => handleSaveAndSyncNetflix(nfEnabled, nfRegion)}
                  className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-semibold inline-flex items-center gap-1.5 cursor-pointer"
                >
                  {syncingNf ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3.5 h-3.5" />
                  )}
                  Sync Netflix
                </button>
              </div>
            </div>

            <div>
              <button
                type="button"
                onClick={() => setShowTmdbInput((v) => !v)}
                className="text-[11px] text-slate-400 hover:text-slate-200 underline cursor-pointer"
              >
                {showTmdbInput
                  ? 'Hide optional TMDB API key'
                  : 'Optional: Add free TMDB API key to expand deep-catalog Netflix indexing'}
              </button>
              {showTmdbInput && (
                <div className="mt-2 flex gap-2">
                  <input
                    type="password"
                    value={tmdbKey}
                    onChange={(e) => setTmdbKey(e.target.value)}
                    placeholder="TMDB API Key or Read Access Token..."
                    className="flex-1 px-3 py-1.5 rounded-lg bg-[#0e121b] border border-slate-700 text-xs text-white"
                  />
                  <button
                    type="button"
                    disabled={syncingNf}
                    onClick={() => handleSaveAndSyncNetflix(nfEnabled, nfRegion)}
                    className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-white font-medium cursor-pointer"
                  >
                    Save &amp; Sync
                  </button>
                </div>
              )}
            </div>

            {nfMsg && (
              <div
                className={`p-2.5 rounded-lg text-xs ${
                  nfMsg.ok
                    ? 'bg-emerald-500/15 text-emerald-200 border border-emerald-500/30'
                    : 'bg-rose-500/15 text-rose-200 border border-rose-500/30'
                }`}
              >
                {nfMsg.msg}
              </div>
            )}

            {/* CSV Drop / Upload */}
            <div className="pt-3 border-t border-slate-800/90 space-y-2.5">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                  <FileSpreadsheet className="w-4 h-4 text-red-400" />
                  Import Netflix Watch History (CSV)
                  {status.netflix.history_imported_count > 0 && (
                    <span className="px-2 py-0.5 rounded-full bg-red-500/15 text-red-200 text-[10px]">
                      {status.netflix.history_imported_count} imported
                    </span>
                  )}
                </div>
                <a
                  href="https://www.netflix.com/viewingactivity"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] text-amber-400 hover:underline inline-flex items-center gap-1"
                >
                  Open netflix.com/viewingactivity
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>

              <p className="text-[11px] text-slate-400 leading-relaxed">
                Scroll to the bottom of your Netflix Viewing Activity page, click{' '}
                <strong className="text-slate-300">Download all</strong>, and upload{' '}
                <code className="text-slate-300">NetflixViewingActivity.csv</code>. Plexbot rolls episodes up into shows, avoids recommending things you already saw on Netflix, and feeds your completions into your taste DNA.
              </p>

              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => handleCsvFileSelected(e.target.files?.[0] || null)}
                  className="hidden"
                />
                <button
                  type="button"
                  disabled={importingCsv}
                  onClick={() => fileInputRef.current?.click()}
                  className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-white inline-flex items-center gap-2 cursor-pointer"
                >
                  {importingCsv ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-red-400" />
                      Matching &amp; enriching history...
                    </>
                  ) : (
                    <>
                      <Upload className="w-3.5 h-3.5 text-red-400" />
                      Choose NetflixViewingActivity.csv
                    </>
                  )}
                </button>

                <input
                  type="text"
                  value={csvProfileFilter}
                  onChange={(e) => setCsvProfileFilter(e.target.value)}
                  placeholder="Optional: Netflix profile name filter"
                  className="px-3 py-2 rounded-lg bg-[#0e121b] border border-slate-800 text-xs text-slate-200 w-56"
                />
              </div>

              {csvResult && (
                <div className="p-3 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-200 text-xs leading-relaxed">
                  Parsed <strong>{csvResult.rows_parsed.toLocaleString()}</strong> viewing rows → marked{' '}
                  <strong>{csvResult.movies_marked}</strong> movies &amp;{' '}
                  <strong>{csvResult.shows_marked}</strong> series as watched (
                  {csvResult.newly_enriched} newly enriched from cloud metadata
                  {csvResult.abandoned_detected > 0
                    ? `, ${csvResult.abandoned_detected} dropped 1-episode shows detected`
                    : ''}
                  ).
                </div>
              )}

              {csvError && (
                <div className="p-2.5 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-200 text-xs">
                  {csvError}
                </div>
              )}
            </div>
          </div>
        </section>

        {/* 2. Connected Local & Shared Plex Servers */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-bold text-emerald-400 uppercase tracking-wider">
              <Server className="w-4 h-4" />
              Connected Plex Servers ({plexServers.length})
            </div>
            <button
              type="button"
              onClick={async () => {
                await api.triggerSync();
                await onUpdated();
              }}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 inline-flex items-center gap-1.5 cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Re-Sync All
            </button>
          </div>

          <div className="space-y-2">
            {plexServers.map((srv) => (
              <div
                key={srv.machine_id}
                className="flex items-center justify-between p-3 rounded-xl bg-slate-900/70 border border-slate-800 text-xs"
              >
                <div className="flex items-center gap-3 min-w-0">
                  {srv.owned ? (
                    <HardDrive className="w-4 h-4 text-emerald-400 shrink-0" />
                  ) : (
                    <Users className="w-4 h-4 text-sky-400 shrink-0" />
                  )}
                  <div className="truncate">
                    <div className="font-semibold text-slate-100 flex items-center gap-2">
                      {srv.name}
                      <span
                        className={`w-2 h-2 rounded-full ${
                          srv.online ? 'bg-emerald-400' : 'bg-rose-500'
                        }`}
                      />
                    </div>
                    <div className="text-slate-400">
                      {srv.owned ? 'Local / Owned' : `Shared by ${srv.owner_name}`} ·{' '}
                      {srv.movie_count.toLocaleString()} movies, {srv.show_count.toLocaleString()} shows
                      {srv.online ? ` · ${srv.latency_ms}ms` : ' · Offline'}
                      {srv.is_relay ? ' (Relay)' : ''}
                    </div>
                  </div>
                </div>
                <label className="inline-flex items-center gap-2 cursor-pointer shrink-0 ml-3">
                  <input
                    type="checkbox"
                    checked={srv.enabled}
                    onChange={(e) => handleToggleServer(srv.machine_id, e.target.checked)}
                    className="accent-amber-500 w-4 h-4"
                  />
                  <span className="text-slate-300">Include</span>
                </label>
              </div>
            ))}
          </div>
        </section>

        {/* 3. Hybrid AI Brain */}
        <section className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-bold text-amber-400 uppercase tracking-wider">
            <Sparkles className="w-4 h-4" />
            Hybrid Cloud LLM Curator
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Plexbot&apos;s local IDF taste graph scores your entire Plex + Netflix catalog instantaneously with zero API keys.
            Adding a Gemini, Claude, or OpenAI key unlocks deep natural-language mood curation, custom explanations, outside discoveries, and your AI Taste Portrait.
          </p>

          <form onSubmit={handleSaveLLM} className="space-y-3 bg-slate-900/60 p-4 rounded-xl border border-slate-800">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Active AI Provider</label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-[#0e121b] border border-slate-700 text-sm text-white"
              >
                <option value="none">Local Taste Graph Only (No Cloud LLM)</option>
                <option value="gemini">Google Gemini</option>
                <option value="anthropic">Anthropic Claude</option>
                <option value="openai">OpenAI</option>
              </select>
            </div>

            {provider === 'gemini' && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2">
                  <label className="block text-xs text-slate-400 mb-1">Gemini API Key</label>
                  <input
                    type="password"
                    value={geminiKey}
                    onChange={(e) => setGeminiKey(e.target.value)}
                    placeholder="AIza..."
                    className="w-full px-3 py-2 rounded-lg bg-[#0e121b] border border-slate-700 text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Model</label>
                  <input
                    type="text"
                    value={geminiModel}
                    onChange={(e) => setGeminiModel(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-[#0e121b] border border-slate-700 text-sm text-white"
                  />
                </div>
              </div>
            )}

            {provider === 'anthropic' && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2">
                  <label className="block text-xs text-slate-400 mb-1">Anthropic API Key</label>
                  <input
                    type="password"
                    value={anthropicKey}
                    onChange={(e) => setAnthropicKey(e.target.value)}
                    placeholder="sk-ant-..."
                    className="w-full px-3 py-2 rounded-lg bg-[#0e121b] border border-slate-700 text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Model</label>
                  <input
                    type="text"
                    value={anthropicModel}
                    onChange={(e) => setAnthropicModel(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-[#0e121b] border border-slate-700 text-sm text-white"
                  />
                </div>
              </div>
            )}

            {provider === 'openai' && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2">
                  <label className="block text-xs text-slate-400 mb-1">OpenAI API Key</label>
                  <input
                    type="password"
                    value={openaiKey}
                    onChange={(e) => setOpenaiKey(e.target.value)}
                    placeholder="sk-..."
                    className="w-full px-3 py-2 rounded-lg bg-[#0e121b] border border-slate-700 text-sm text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Model</label>
                  <input
                    type="text"
                    value={openaiModel}
                    onChange={(e) => setOpenaiModel(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-[#0e121b] border border-slate-700 text-sm text-white"
                  />
                </div>
              </div>
            )}

            {llmFeedback && (
              <div
                className={`p-2.5 rounded-lg text-xs flex items-center gap-2 ${
                  llmFeedback.ok
                    ? 'bg-emerald-500/15 text-emerald-200 border border-emerald-500/30'
                    : 'bg-rose-500/15 text-rose-200 border border-rose-500/30'
                }`}
              >
                {llmFeedback.ok && <CheckCircle2 className="w-4 h-4 shrink-0" />}
                {llmFeedback.msg}
              </div>
            )}

            <div className="flex items-center gap-2 pt-1">
              <button
                type="submit"
                disabled={savingLLM}
                className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold text-xs cursor-pointer"
              >
                {savingLLM ? 'Saving...' : 'Save AI Settings'}
              </button>
              {provider !== 'none' && (
                <button
                  type="button"
                  disabled={testingLLM}
                  onClick={handleTestLLM}
                  className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium inline-flex items-center gap-1.5 cursor-pointer"
                >
                  {testingLLM && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Test Connection
                </button>
              )}
            </div>
          </form>
        </section>

        {/* 4. Household Viewing Modes */}
        <section className="space-y-3">
          <div className="text-sm font-bold text-sky-400 uppercase tracking-wider">
            &ldquo;Who&apos;s Watching&rdquo; Modes
          </div>
          <div className="space-y-2">
            {status.profiles.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between px-3 py-2 rounded-xl bg-slate-900/70 border border-slate-800 text-xs"
              >
                <div>
                  <span className="font-semibold text-white">{p.name}</span>
                  {p.description && <span className="text-slate-400 ml-2">— {p.description}</span>}
                </div>
                {!['together', 'me', 'partner'].includes(p.id) && (
                  <button
                    type="button"
                    onClick={() => handleDeleteProfile(p.id)}
                    className="p-1 text-slate-500 hover:text-rose-400 cursor-pointer"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            ))}
          </div>
          <form onSubmit={handleAddProfile} className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={newProfName}
              onChange={(e) => setNewProfName(e.target.value)}
              placeholder="Add custom mode (e.g. Kids, Late Night Horror)..."
              className="flex-1 min-w-[200px] px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-xs text-white"
            />
            <label className="text-xs text-slate-400 inline-flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={newProfInherit}
                onChange={(e) => setNewProfInherit(e.target.checked)}
                className="accent-amber-500"
              />
              Seed from watch history
            </label>
            <button
              type="submit"
              className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-white inline-flex items-center gap-1 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              Add
            </button>
          </form>
        </section>

        {/* Account footer */}
        {status.user && (
          <div className="pt-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <div>
              Signed into Plex as <span className="text-slate-200 font-medium">{status.user.username}</span>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="text-rose-400 hover:text-rose-300 inline-flex items-center gap-1.5 cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" />
              Disconnect Plex
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
