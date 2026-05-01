import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { X } from "lucide-react";
import type { Segment } from "../lib/types";

interface Props {
  segments: Segment[];
  sessionId: string | null;
  duration: number;
  onClose: () => void;
}

export function ExportDialog({ segments, sessionId, duration, onClose }: Props) {
  const defaultTitle = new Date().toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }) + " 口述笔记";

  const [title, setTitle] = useState(defaultTitle);
  const [tags, setTags] = useState("");
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [usePolished, setUsePolished] = useState(true);

  const buildContent = () => {
    return segments
      .map((s) => s.polished_text && usePolished ? s.polished_text : s.text)
      .join("\n\n");
  };

  const doExport = async () => {
    if (!sessionId) {
      setError("没有可导出的会话");
      return;
    }
    setExporting(true);
    setError(null);
    try {
      const tagList = tags
        .split(/[,，\s]+/)
        .map((t) => t.trim())
        .filter(Boolean);

      const path = await invoke<string>("export_to_obsidian", {
        payload: {
          title,
          content: buildContent(),
          tags: tagList,
          session_id: sessionId,
          duration_seconds: duration,
        },
      });
      setResult(path);
    } catch (e) {
      setError(typeof e === "string" ? e : String(e));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-[520px] max-w-[90vw]">
        <header className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
          <h2 className="font-semibold text-zinc-900">导出到 Obsidian</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-700">
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="p-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-zinc-700 mb-1.5">标题</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 border border-zinc-300 rounded-md text-sm outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-700 mb-1.5">
              标签（用逗号或空格分隔）
            </label>
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="例如：大模型,学习笔记"
              className="w-full px-3 py-2 border border-zinc-300 rounded-md text-sm outline-none focus:border-blue-500"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-zinc-700">
            <input
              type="checkbox"
              checked={usePolished}
              onChange={(e) => setUsePolished(e.target.checked)}
            />
            优先使用 Claude 润色版本（如果存在）
          </label>

          <div className="text-xs text-zinc-500 bg-zinc-50 rounded p-3 max-h-32 overflow-y-auto">
            <p className="font-medium text-zinc-700 mb-1">预览（前 200 字）：</p>
            <p>{buildContent().slice(0, 200)}...</p>
          </div>

          {error && (
            <div className="text-sm text-red-600 bg-red-50 rounded p-3">{error}</div>
          )}
          {result && (
            <div className="text-sm text-green-700 bg-green-50 rounded p-3">
              ✓ 已导出到：<br />
              <code className="text-xs break-all">{result}</code>
            </div>
          )}
        </div>

        <footer className="px-5 py-3 border-t border-zinc-200 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-md text-sm text-zinc-700 hover:bg-zinc-100"
          >
            关闭
          </button>
          <button
            onClick={doExport}
            disabled={exporting || segments.length === 0}
            className="px-4 py-1.5 rounded-md text-sm bg-zinc-900 hover:bg-zinc-800 text-white disabled:opacity-50"
          >
            {exporting ? "导出中..." : "导出"}
          </button>
        </footer>
      </div>
    </div>
  );
}
