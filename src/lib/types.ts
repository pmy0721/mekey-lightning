export interface Segment {
  id: string;
  session_id: string;
  text: string;
  polished_text: string | null;
  start_time: number;
  end_time: number;
  is_final: boolean;
}

export interface Session {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  duration_seconds: number;
}

export interface LLMSettings {
  llm_provider: "anthropic" | "siliconflow" | "openai-compatible";
  llm_base_url: string;
  llm_model: string;
  has_anthropic_api_key: boolean;
  has_openai_compatible_api_key: boolean;
}

export type WSMessage =
  | { type: "ready" }
  | { type: "recording_started"; session_id: string }
  | { type: "recording_stopped"; session_id: string }
  | { type: "draft"; session_id: string; text: string; timestamp: number }
  | { type: "final"; segment: Segment }
  | { type: "polished"; segment_ids: string[]; polished_text: string }
  | { type: "polish_started"; session_id: string }
  | { type: "session_polished"; session_id: string; polished_text: string; segment: Segment }
  | { type: "settings"; data: LLMSettings; saved?: boolean }
  | { type: "error"; message: string }
  | { type: "sessions"; data: Session[] }
  | { type: "session_detail"; session_id: string; segments: Segment[] };
