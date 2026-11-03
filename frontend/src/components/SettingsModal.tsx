import React, { useState } from 'react';
import {
  CheckCircle2,
  HardDrive,
  Loader2,
  LogOut,
  Plus,
  RefreshCw,
  Server,
  Sparkles,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import { api } from '../api';
import { AppStatus } from '../types';

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

  const [newProfName, setNewProfName] = useState('');
  const [newProfInherit, setNewProfInherit] = useState(true);

  if (!open) return null;

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
          <h2 className="text-xl font-bold text-white">Servers, AI Brain &amp; Profiles</h2>
          <button
            onClick={onClose}
            className="p-2 rounded-full hover:bg-slate-800 text-slate-400 hover:text-white cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 1. Hybrid AI Brain */}
        <section className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-bold text-amber-400 uppercase tracking-wider">
            <Sparkles className="w-4 h-4" />
            Hybrid Cloud LLM Curator
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Plexbot&apos;s local IDF taste graph scores your entire catalog instantaneously with zero API keys.
            Adding a Gemini, Claude, or OpenAI key unlocks deep natural-language mood curation, custom explanations, outside-Plex discoveries, and your AI Taste Portrait.
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

        {/* 2. Connected Local & Shared Plex Servers */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-bold text-emerald-400 uppercase tracking-wider">
              <Server className="w-4 h-4" />
              Connected Plex Servers ({status.servers.length})
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
              Re-Sync All Libraries
            </button>
          </div>

          <div className="space-y-2">
            {status.servers.map((srv) => (
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

        {/* 3. Household Viewing Modes */}
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
