import { useEffect, useRef } from "react";
import type { Segment } from "../lib/types";

interface Props {
  segments: Segment[];
  draftText: string;
}

export function TranscriptView({ segments, draftText }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [segments, draftText]);

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
      <div className="max-w-3xl mx-auto">
        {segments.length === 0 && !draftText && (
          <div className="text-center py-20 text-zinc-400">
            <p className="text-sm">点击“开始录音”或按 Ctrl+Shift+R 开始转录</p>
          </div>
        )}

        {(segments.length > 0 || draftText) && (
          <p className="leading-loose text-base text-zinc-800 whitespace-pre-wrap break-words">
            {segments.map((seg) => (
              <span key={seg.id}>{seg.polished_text || seg.text}</span>
            ))}
            {draftText && (
              <span className="text-zinc-400 italic">
                {draftText}
                <span className="inline-block w-1 h-4 bg-zinc-400 ml-0.5 animate-pulse" />
              </span>
            )}
          </p>
        )}
      </div>
    </div>
  );
}
