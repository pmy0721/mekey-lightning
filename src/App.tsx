import { useCallback, useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { Download, History, Mic, Settings, Sparkles, Square } from "lucide-react";
import clsx from "clsx";

import { useTranscribeWS } from "./hooks/useTranscribeWS";
import type { LLMSettings, Segment, Session, WSMessage } from "./lib/types";
import { TranscriptView } from "./components/TranscriptView";
import { SessionList } from "./components/SessionList";
import { SettingsDialog } from "./components/SettingsDialog";
import { ExportDialog } from "./components/ExportDialog";

type View = "live" | "history";

function normalizeTranscriptText(text: string) {
  return text.replace(/[\s，。,.、！？!?；;：:]+/g, "");
}

export default function App() {
  const [view, setView] = useState<View>("live");
  const [isRecording, setIsRecording] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [draftText, setDraftText] = useState("");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSession, setSelectedSession] = useState<{ session: Session; segments: Segment[] } | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [recordStartTime, setRecordStartTime] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [llmSettings, setLlmSettings] = useState<LLMSettings | null>(null);
  const [polishingSessionId, setPolishingSessionId] = useState<string | null>(null);

  const handleMessage = useCallback((msg: WSMessage) => {
    switch (msg.type) {
      case "recording_started":
        setIsRecording(true);
        setIsStopping(false);
        setCurrentSessionId(msg.session_id);
        setSegments([]);
        setDraftText("");
        setRecordStartTime(Date.now());
        break;
      case "recording_stopped":
        setIsRecording(false);
        setIsStopping(false);
        setRecordStartTime(null);
        send({ action: "list_sessions" });
        break;
      case "draft":
        setDraftText(msg.text);
        break;
      case "final":
        setSegments((prev) => {
          const incoming = normalizeTranscriptText(msg.segment.text);
          if (!incoming) return prev;
          const isDuplicate = prev.slice(-8).some((seg) => {
            const existing = normalizeTranscriptText(seg.text);
            return existing === incoming || existing.endsWith(incoming) || incoming.endsWith(existing);
          });
          return isDuplicate ? prev : [...prev, msg.segment];
        });
        setDraftText("");
        break;
      case "polished":
        setSegments((prev) =>
          prev.map((s) =>
            msg.segment_ids.includes(s.id)
              ? { ...s, polished_text: msg.polished_text }
              : s,
          ),
        );
        break;
      case "polish_started":
        setPolishingSessionId(msg.session_id);
        break;
      case "session_polished":
        setPolishingSessionId(null);
        if (currentSessionId === msg.session_id) {
          setSegments([msg.segment]);
          setDraftText("");
        }
        if (selectedSession?.session.id === msg.session_id) {
          setSelectedSession((cur) => (cur ? { ...cur, segments: [msg.segment] } : cur));
        }
        break;
      case "settings":
        setLlmSettings(msg.data);
        break;
      case "error":
        setPolishingSessionId(null);
        alert(msg.message);
        break;
      case "sessions":
        setSessions(msg.data);
        break;
      case "session_detail": {
        const sess = sessions.find((s) => s.id === msg.session_id);
        if (sess) setSelectedSession({ session: sess, segments: msg.segments });
        break;
      }
    }
  }, [currentSessionId, sessions, selectedSession]);

  const { connected, send } = useTranscribeWS(handleMessage);

  useEffect(() => {
    if (!recordStartTime) {
      setElapsed(0);
      return;
    }
    const timer = setInterval(() => {
      setElapsed((Date.now() - recordStartTime) / 1000);
    }, 500);
    return () => clearInterval(timer);
  }, [recordStartTime]);

  useEffect(() => {
    if (connected) {
      send({ action: "list_sessions" });
      send({ action: "get_settings" });
    }
  }, [connected, send]);

  const requestPolish = useCallback((sessionId: string | null) => {
    if (!sessionId || polishingSessionId) return;
    const hasKey = llmSettings?.llm_provider === "anthropic"
      ? llmSettings.has_anthropic_api_key
      : llmSettings?.has_openai_compatible_api_key;
    if (!hasKey) {
      setShowSettings(true);
      alert("请先在设置中填入 API Key 并选择模型。");
      return;
    }
    send({ action: "polish_session", session_id: sessionId });
  }, [llmSettings, polishingSessionId, send]);

  const toggleRecording = useCallback(() => {
    if (!connected) {
      alert("后端服务未连接");
      return;
    }
    if (isStopping) return;
    if (isRecording) {
      setIsStopping(true);
      setIsRecording(false);
      setRecordStartTime(null);
      send({ action: "stop" });
    } else {
      send({ action: "start" });
    }
  }, [connected, isRecording, isStopping, send]);

  useEffect(() => {
    const unlisteners: Promise<() => void>[] = [];
    unlisteners.push(listen("shortcut:toggle-recording", toggleRecording));
    unlisteners.push(listen("shortcut:polish-now", () => requestPolish(currentSessionId)));
    unlisteners.push(
      listen("shortcut:export-now", () => {
        if (currentSessionId || selectedSession) setShowExport(true);
      }),
    );
    return () => {
      unlisteners.forEach((p) => p.then((fn) => fn()));
    };
  }, [toggleRecording, requestPolish, currentSessionId, selectedSession]);

  const formatElapsed = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
  };

  const currentPolishing = polishingSessionId === currentSessionId;

  return (
    <div className="h-screen flex flex-col bg-zinc-50">
      <header className="px-6 py-3 border-b border-zinc-200 bg-white flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-6">
          <h1 className="text-base font-semibold text-zinc-900">实时转录</h1>
          <nav className="flex gap-1">
            <button
              onClick={() => setView("live")}
              className={clsx("px-3 py-1.5 rounded-md text-sm transition-colors", view === "live" ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100")}
            >
              <Mic className="w-4 h-4 inline-block mr-1.5 -mt-0.5" />
              实时
            </button>
            <button
              onClick={() => setView("history")}
              className={clsx("px-3 py-1.5 rounded-md text-sm transition-colors", view === "history" ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100")}
            >
              <History className="w-4 h-4 inline-block mr-1.5 -mt-0.5" />
              历史
            </button>
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <span className={clsx("text-xs px-2 py-1 rounded", connected ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700")}>
            {connected ? "● 已连接" : "○ 未连接"}
          </span>
          <button onClick={() => setShowSettings(true)} className="p-2 rounded hover:bg-zinc-100 text-zinc-600" title="设置">
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </header>

      {view === "live" ? (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-6 py-4 bg-white border-b border-zinc-200 flex items-center justify-between flex-shrink-0">
            <button
              onClick={toggleRecording}
              disabled={!connected || isStopping}
              className={clsx(
                "px-5 py-2.5 rounded-lg text-sm font-medium transition-all flex items-center gap-2",
                isRecording ? "bg-red-500 hover:bg-red-600 text-white" : "bg-zinc-900 hover:bg-zinc-800 text-white",
                (!connected || isStopping) && "opacity-50 cursor-not-allowed",
              )}
            >
              {isStopping ? (
                <>
                  <Square className="w-4 h-4" />
                  正在停止
                </>
              ) : isRecording ? (
                <>
                  <Square className="w-4 h-4" />
                  停止录音
                </>
              ) : (
                <>
                  <Mic className="w-4 h-4" />
                  开始录音
                </>
              )}
            </button>

            <div className="flex items-center gap-4">
              {isRecording && (
                <div className="flex items-center gap-2 text-sm text-zinc-700">
                  <span className="w-2 h-2 rounded-full bg-red-500 recording-pulse" />
                  <span className="font-mono">{formatElapsed(elapsed)}</span>
                </div>
              )}

              <button
                onClick={() => requestPolish(currentSessionId)}
                disabled={!currentSessionId || isRecording || currentPolishing}
                className="px-3 py-1.5 rounded-md text-sm text-zinc-700 hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                title="Ctrl+Shift+P"
              >
                <Sparkles className="w-4 h-4" />
                {currentPolishing ? "润色中..." : "润色"}
              </button>

              <button
                onClick={() => setShowExport(true)}
                disabled={!currentSessionId && segments.length === 0}
                className="px-3 py-1.5 rounded-md text-sm text-zinc-700 hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                title="Ctrl+Shift+E"
              >
                <Download className="w-4 h-4" />
                导出 Obsidian
              </button>
            </div>
          </div>

          <TranscriptView segments={segments} draftText={draftText} />

          <footer className="px-6 py-2 border-t border-zinc-200 bg-white text-xs text-zinc-500 flex gap-4 flex-shrink-0">
            <span><kbd className="px-1.5 py-0.5 bg-zinc-100 rounded text-zinc-700 font-mono">Ctrl+Shift+R</kbd> 录音</span>
            <span><kbd className="px-1.5 py-0.5 bg-zinc-100 rounded text-zinc-700 font-mono">Ctrl+Shift+P</kbd> 润色</span>
            <span><kbd className="px-1.5 py-0.5 bg-zinc-100 rounded text-zinc-700 font-mono">Ctrl+Shift+E</kbd> 导出</span>
          </footer>
        </div>
      ) : (
        <SessionList
          sessions={sessions}
          selectedSession={selectedSession}
          onSelect={(id) => send({ action: "get_session", session_id: id })}
          onRename={(id, title) => send({ action: "rename_session", session_id: id, title })}
          onDelete={(id) => {
            send({ action: "delete_session", session_id: id });
            setSelectedSession(null);
          }}
          onPolish={(id) => requestPolish(id)}
          onExport={() => setShowExport(true)}
        />
      )}

      {showSettings && (
        <SettingsDialog
          llmSettings={llmSettings}
          onSaveLLM={(settings) => send({ action: "save_settings", settings })}
          onClose={() => setShowSettings(false)}
        />
      )}
      {showExport && (
        <ExportDialog
          segments={view === "live" ? segments : selectedSession?.segments ?? []}
          sessionId={view === "live" ? currentSessionId : selectedSession?.session.id ?? null}
          duration={view === "live" ? elapsed : selectedSession?.session.duration_seconds ?? 0}
          onClose={() => setShowExport(false)}
        />
      )}
    </div>
  );
}
