import { useState } from "react";
import type { Segment, Session } from "../lib/types";
import { Pencil, Trash2, Sparkles, Download, Clock } from "lucide-react";
import clsx from "clsx";

interface Props {
  sessions: Session[];
  selectedSession: { session: Session; segments: Segment[] } | null;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onPolish: (id: string) => void;
  onExport: () => void;
}

export function SessionList({
  sessions,
  selectedSession,
  onSelect,
  onRename,
  onDelete,
  onPolish,
  onExport,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  const formatDuration = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}分${sec}秒`;
  };

  const formatDate = (ts: number) => {
    return new Date(ts * 1000).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* 左侧列表 */}
      <aside className="w-72 border-r border-zinc-200 bg-white overflow-y-auto flex-shrink-0">
        <div className="p-3 border-b border-zinc-200 text-xs text-zinc-500">
          {sessions.length} 条会话
        </div>
        {sessions.length === 0 && (
          <div className="p-6 text-center text-sm text-zinc-400">暂无历史记录</div>
        )}
        {sessions.map((s) => (
          <div
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={clsx(
              "px-4 py-3 border-b border-zinc-100 cursor-pointer hover:bg-zinc-50 group",
              selectedSession?.session.id === s.id && "bg-blue-50 hover:bg-blue-50",
            )}
          >
            {editingId === s.id ? (
              <input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                onBlur={() => {
                  onRename(s.id, editTitle);
                  setEditingId(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    onRename(s.id, editTitle);
                    setEditingId(null);
                  }
                }}
                onClick={(e) => e.stopPropagation()}
                autoFocus
                className="w-full text-sm font-medium px-2 py-1 border border-zinc-300 rounded outline-none focus:border-blue-500"
              />
            ) : (
              <div className="flex items-start justify-between gap-2">
                <div className="text-sm font-medium text-zinc-900 truncate flex-1">
                  {s.title}
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditingId(s.id);
                    setEditTitle(s.title);
                  }}
                  className="opacity-0 group-hover:opacity-100 text-zinc-400 hover:text-zinc-700"
                >
                  <Pencil className="w-3 h-3" />
                </button>
              </div>
            )}
            <div className="flex items-center gap-3 mt-1 text-xs text-zinc-500">
              <span>{formatDate(s.updated_at)}</span>
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {formatDuration(s.duration_seconds)}
              </span>
            </div>
          </div>
        ))}
      </aside>

      {/* 右侧详情 */}
      <main className="flex-1 overflow-hidden flex flex-col">
        {selectedSession ? (
          <>
            <header className="px-6 py-4 border-b border-zinc-200 bg-white flex items-center justify-between flex-shrink-0">
              <div>
                <h2 className="font-semibold text-zinc-900">
                  {selectedSession.session.title}
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">
                  {formatDate(selectedSession.session.created_at)} ·{" "}
                  {formatDuration(selectedSession.session.duration_seconds)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onPolish(selectedSession.session.id)}
                  className="px-3 py-1.5 rounded-md text-sm text-zinc-700 hover:bg-zinc-100 flex items-center gap-1.5"
                >
                  <Sparkles className="w-4 h-4" />
                  润色全文
                </button>
                <button
                  onClick={onExport}
                  className="px-3 py-1.5 rounded-md text-sm text-zinc-700 hover:bg-zinc-100 flex items-center gap-1.5"
                >
                  <Download className="w-4 h-4" />
                  导出
                </button>
                <button
                  onClick={() => {
                    if (confirm("确定删除这条会话吗？")) {
                      onDelete(selectedSession.session.id);
                    }
                  }}
                  className="px-2 py-1.5 rounded-md text-sm text-red-600 hover:bg-red-50"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </header>

            <div className="flex-1 overflow-y-auto px-6 py-6">
              <div className="max-w-3xl mx-auto space-y-3">
                {selectedSession.segments.map((seg) => (
                  <p
                    key={seg.id}
                    className="text-base leading-relaxed text-zinc-900"
                  >
                    {seg.polished_text || seg.text}
                  </p>
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-zinc-400 text-sm">
            选择左侧会话查看详情
          </div>
        )}
      </main>
    </div>
  );
}
