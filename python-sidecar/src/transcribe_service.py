"""
RealtimeTranscribe Python Sidecar
负责：麦克风采集、FunASR 双模型推理、Claude 润色、SQLite 持久化
通过 WebSocket (127.0.0.1:9527) 与 Tauri 前端通信
"""
import asyncio
import json
import os
import re
import sys
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import websockets
import aiosqlite
import aiohttp
from dotenv import load_dotenv
from loguru import logger
from anthropic import AsyncAnthropic

# ============================================================
# 配置
# ============================================================
load_dotenv()

WS_HOST = "127.0.0.1"
WS_PORT = 9527
SAMPLE_RATE = 16000
CHUNK_DURATION = 0.6  # 600ms
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION)
OFFLINE_REFRESH_CHUNKS = 999999  # disabled during recording in low-latency mode
LOW_LATENCY_STREAM_ONLY = True
STREAM_COMMIT_INTERVAL = 2.0
STREAM_COMMIT_MIN_CHARS = 8
DATA_DIR = Path(os.getenv("APPDATA", os.path.expanduser("~"))) / "Mekey Lightning" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "transcripts.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> <level>{message}</level>", level="INFO")
logger.add(DATA_DIR / "sidecar.log", rotation="10 MB", retention=5, level="DEBUG")


# ============================================================
# 数据模型
# ============================================================
@dataclass
class Segment:
    id: str
    session_id: str
    text: str
    polished_text: Optional[str]
    start_time: float
    end_time: float
    is_final: bool


# ============================================================
# 数据库
# ============================================================
class Database:
    def __init__(self, path: Path):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    duration_seconds REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS segments (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    polished_text TEXT,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    is_final INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_segments_session ON segments(session_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
            """)
            await db.commit()

    async def create_session(self) -> str:
        sid = str(uuid.uuid4())
        now = time.time()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (sid, "未命名会话", now, now),
            )
            await db.commit()
        return sid

    async def add_segment(self, seg: Segment):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO segments
                   (id, session_id, text, polished_text, start_time, end_time, is_final)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (seg.id, seg.session_id, seg.text, seg.polished_text,
                 seg.start_time, seg.end_time, int(seg.is_final)),
            )
            await db.execute(
                "UPDATE sessions SET updated_at = ?, duration_seconds = ? WHERE id = ?",
                (time.time(), seg.end_time, seg.session_id),
            )
            await db.commit()

    async def update_segment_polish(self, seg_id: str, polished: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE segments SET polished_text = ? WHERE id = ?",
                (polished, seg_id),
            )
            await db.commit()

    async def list_sessions(self, limit: int = 50):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_session_segments(self, session_id: str):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM segments WHERE session_id = ? ORDER BY start_time",
                (session_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def update_session_title(self, session_id: str, title: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, time.time(), session_id),
            )
            await db.commit()

    async def delete_session(self, session_id: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await db.commit()

    async def replace_session_with_polished(self, session_id: str, text: str):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COALESCE(MAX(end_time), 0) FROM segments WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            duration = float(row[0] or 0)
            seg_id = str(uuid.uuid4())
            await db.execute("DELETE FROM segments WHERE session_id = ?", (session_id,))
            await db.execute(
                """INSERT INTO segments
                   (id, session_id, text, polished_text, start_time, end_time, is_final)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (seg_id, session_id, text, None, 0, duration, 1),
            )
            await db.execute(
                "UPDATE sessions SET updated_at = ?, duration_seconds = ? WHERE id = ?",
                (time.time(), duration, session_id),
            )
            await db.commit()
            return Segment(
                id=seg_id,
                session_id=session_id,
                text=text,
                polished_text=None,
                start_time=0,
                end_time=duration,
                is_final=True,
            )


# ============================================================
# ASR 引擎
# ============================================================
class ASREngine:
    def __init__(self):
        self.streaming_model = None
        self.offline_model = None
        self.cache = {}
        self.chunk_config = {
            "chunk_size": [0, 10, 5],  # 600ms 延迟
            "encoder_chunk_look_back": 4,
            "decoder_chunk_look_back": 1,
        }

    def load_models(self):
        """启动时一次性加载到 GPU"""
        from funasr import AutoModel
        logger.info("Loading streaming model (paraformer-zh-streaming)...")
        self.streaming_model = AutoModel(
            model="paraformer-zh-streaming",
            device="cuda:0",
            disable_update=True,
            disable_pbar=True,
        )
        logger.info("Loading offline model (paraformer-zh + vad + punc)...")
        self.offline_model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            device="cuda:0",
            disable_update=True,
            disable_pbar=True,
        )
        logger.info("✓ Models loaded")
        self.warmup_inference()
        logger.info("✓ Models warmed up")

    def warmup_inference(self):
        audio = np.zeros(CHUNK_SAMPLES, dtype=np.float32)
        with suppress(Exception):
            self.stream_chunk(audio)
        with suppress(Exception):
            self.offline_refine([audio])
        self.reset_cache()

    def reset_cache(self):
        self.cache = {}

    def stream_chunk(self, audio: np.ndarray) -> str:
        """流式推理单个 chunk，返回增量文本"""
        res = self.streaming_model.generate(
            input=audio,
            cache=self.cache,
            is_final=False,
            **self.chunk_config,
        )
        if res and res[0].get("text"):
            return res[0]["text"]
        return ""

    def offline_refine(self, audio_chunks: list[np.ndarray]) -> str:
        """对当前缓冲区做离线高精度识别"""
        if not audio_chunks:
            return ""
        full_audio = np.concatenate(audio_chunks)
        if len(full_audio) < SAMPLE_RATE * 0.3:  # 太短跳过
            return ""
        res = self.offline_model.generate(input=full_audio)
        if res and res[0].get("text"):
            return res[0]["text"].strip()
        return ""


# ============================================================
# Claude 润色
# ============================================================
POLISH_PROMPT = """你是专业的口述文字整理助手。请整理以下口述转录文本：

要求：
1. 修正同音错别字，特别注意技术术语（如"鸿蒙/HarmonyOS"、"Transformer"、"注意力机制"、"嵌入"等）
2. 删除"嗯"、"啊"、"那个"、"就是说"等口癖词
3. 将口语化表达转为书面语，但保留原意和说话人风格
4. 添加合理的段落分隔
5. 数字、英文术语标准化（"二零二四"→"2024"，"AI"保持英文）

原文：
{text}

直接输出整理后的文本，不要解释、不要添加标题。"""


class AppSettings:
    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "llm_provider": "siliconflow",
            "llm_base_url": "https://api.siliconflow.cn/v1",
            "llm_model": "deepseek-ai/DeepSeek-V4-Flash",
            "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
            "openai_compatible_api_key": os.getenv("OPENAI_COMPATIBLE_API_KEY", ""),
        }
        self.load()

    def load(self):
        if not self.path.exists():
            return
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.update({k: v for k, v in stored.items() if v is not None})
        except Exception as e:
            logger.warning(f"Failed to load settings: {e}")

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def public(self) -> dict:
        return {
            "llm_provider": self.data.get("llm_provider", "siliconflow"),
            "llm_base_url": self.data.get("llm_base_url", "https://api.siliconflow.cn/v1"),
            "llm_model": self.data.get("llm_model", "deepseek-ai/DeepSeek-V4-Flash"),
            "has_anthropic_api_key": bool(self.data.get("anthropic_api_key")),
            "has_openai_compatible_api_key": bool(self.data.get("openai_compatible_api_key")),
        }

    def update_llm(self, payload: dict):
        self.data["llm_provider"] = payload.get("llm_provider", "siliconflow")
        self.data["llm_base_url"] = payload.get("llm_base_url") or self.data.get("llm_base_url")
        self.data["llm_model"] = payload.get("llm_model") or self.data.get("llm_model")
        anthropic_key = payload.get("anthropic_api_key")
        if anthropic_key:
            self.data["anthropic_api_key"] = anthropic_key.strip()
        compatible_key = payload.get("openai_compatible_api_key")
        if compatible_key:
            self.data["openai_compatible_api_key"] = compatible_key.strip()
        self.save()


class Polisher:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    async def polish(self, text: str) -> Optional[str]:
        provider = self.settings.data.get("llm_provider", "siliconflow")
        if provider == "anthropic":
            return await self._polish_anthropic(text)
        return await self._polish_openai_compatible(text)

    async def _polish_anthropic(self, text: str) -> Optional[str]:
        api_key = self.settings.data.get("anthropic_api_key", "")
        if not api_key:
            logger.warning("Anthropic API key not set, skip polishing")
            return None
        if not text.strip():
            return None
        try:
            client = AsyncAnthropic(api_key=api_key)
            msg = await client.messages.create(
                model=self.settings.data.get("llm_model", "claude-3-5-sonnet-latest"),
                max_tokens=4096,
                messages=[{"role": "user", "content": POLISH_PROMPT.format(text=text)}],
            )
            return msg.content[0].text.strip()
        except Exception as e:
            logger.error(f"Polish failed: {e}")
            return None

    async def _polish_openai_compatible(self, text: str) -> Optional[str]:
        api_key = self.settings.data.get("openai_compatible_api_key", "")
        base_url = (self.settings.data.get("llm_base_url") or "https://api.siliconflow.cn/v1").rstrip("/")
        model = self.settings.data.get("llm_model", "deepseek-ai/DeepSeek-V4-Flash")
        if not api_key:
            logger.warning("OpenAI-compatible API key not set, skip polishing")
            return None
        if not text.strip():
            return None

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": POLISH_PROMPT.format(text=text)}],
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status >= 400:
                        logger.error(f"Polish failed ({resp.status}): {data}")
                        return None
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"OpenAI-compatible polish failed: {e}")
            return None


# ============================================================
# 主服务
# ============================================================
class TranscribeService:
    def __init__(self):
        self.asr = ASREngine()
        self.db = Database(DB_PATH)
        self.settings = AppSettings(SETTINGS_PATH)
        self.polisher = Polisher(self.settings)
        self.clients: set[websockets.WebSocketServerProtocol] = set()

        self.is_recording = False
        self.current_session_id: Optional[str] = None
        self.session_start_time: float = 0
        self.chunk_count = 0
        self.last_offline_text = ""
        self.current_stream_text = ""
        self.last_draft_sent = ""
        self.committed_stream_text = ""
        self.committed_stream_len = 0
        self.last_stream_commit_time = 0.0
        self.stream_commit_start_time = 0.0
        self.last_final_compact = ""
        self.offline_buffer: list[np.ndarray] = []
        self.offline_buffer_start: float = 0
        self.offline_refine_task: Optional[asyncio.Task] = None
        self.pending_polish_buffer: list[Segment] = []

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.audio_queue: Optional[asyncio.Queue] = None
        self.refine_lock: Optional[asyncio.Lock] = None
        self.stream_commit_lock: Optional[asyncio.Lock] = None

    # ----- WebSocket 通信 -----
    async def broadcast(self, msg: dict):
        if not self.clients:
            return
        data = json.dumps(msg, ensure_ascii=False)
        await asyncio.gather(
            *[self._safe_send(c, data) for c in self.clients],
            return_exceptions=True,
        )

    async def _safe_send(self, client, data):
        try:
            await client.send(data)
        except Exception:
            pass

    async def handle_client(self, websocket):
        self.clients.add(websocket)
        logger.info(f"Client connected ({len(self.clients)} total)")
        try:
            await websocket.send(json.dumps({"type": "ready"}))
            async for message in websocket:
                try:
                    cmd = json.loads(message)
                    await self.handle_command(cmd)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {message}")
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            logger.info(f"Client disconnected ({len(self.clients)} total)")

    async def handle_command(self, cmd: dict):
        action = cmd.get("action")
        if action == "start":
            await self.start_recording()
        elif action == "stop":
            await self.stop_recording()
        elif action == "list_sessions":
            sessions = await self.db.list_sessions()
            await self.broadcast({"type": "sessions", "data": sessions})
        elif action == "get_session":
            sid = cmd.get("session_id")
            segs = await self.db.get_session_segments(sid)
            await self.broadcast({"type": "session_detail", "session_id": sid, "segments": segs})
        elif action == "polish_session":
            sid = cmd.get("session_id")
            await self.polish_session(sid)
        elif action == "get_settings":
            await self.broadcast({"type": "settings", "data": self.settings.public()})
        elif action == "save_settings":
            self.settings.update_llm(cmd.get("settings", {}))
            await self.broadcast({"type": "settings", "data": self.settings.public(), "saved": True})
        elif action == "rename_session":
            await self.db.update_session_title(cmd["session_id"], cmd["title"])
            sessions = await self.db.list_sessions()
            await self.broadcast({"type": "sessions", "data": sessions})
        elif action == "delete_session":
            await self.db.delete_session(cmd["session_id"])
            sessions = await self.db.list_sessions()
            await self.broadcast({"type": "sessions", "data": sessions})
        else:
            logger.warning(f"Unknown action: {action}")

    # ----- 录音控制 -----
    async def start_recording(self):
        if self.is_recording:
            return
        self.current_session_id = await self.db.create_session()
        self.session_start_time = time.time()
        self.chunk_count = 0
        self.last_offline_text = ""
        self.current_stream_text = ""
        self.last_draft_sent = ""
        self.committed_stream_text = ""
        self.committed_stream_len = 0
        self.last_stream_commit_time = 0.0
        self.stream_commit_start_time = 0.0
        self.last_final_compact = ""
        self.offline_buffer = []
        self.offline_buffer_start = 0
        self.asr.reset_cache()
        self._drain_audio_queue()
        self.is_recording = True
        await self.broadcast({
            "type": "recording_started",
            "session_id": self.current_session_id,
        })
        logger.info(f"▶ Recording started: {self.current_session_id}")

    async def stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False
        # 处理残留缓冲
        asyncio.create_task(self._finalize_after_stop())
        await self.broadcast({
            "type": "recording_stopped",
            "session_id": self.current_session_id,
        })
        logger.info(f"⏹ Recording stopped: {self.current_session_id}")

    # ----- 音频处理 -----
    def _drain_audio_queue(self):
        if self.audio_queue is None:
            return
        while True:
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _enqueue_audio(self, audio: np.ndarray):
        if self.audio_queue is None:
            return
        try:
            self.audio_queue.put_nowait(audio)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self.audio_queue.get_nowait()
            with suppress(asyncio.QueueFull):
                self.audio_queue.put_nowait(audio)

    def audio_callback(self, indata, frames, time_info, status):
        """sounddevice 回调（在独立线程中执行）"""
        if status:
            logger.warning(f"Audio status: {status}")
        if not self.is_recording or self.audio_queue is None:
            return
        # 拷贝并塞入异步队列
        audio = indata[:, 0].copy().astype(np.float32)
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._enqueue_audio, audio)

    async def audio_processor(self):
        """从队列取音频，做流式推理 + 定期离线校正"""
        while True:
            try:
                audio = await self.audio_queue.get()
            except asyncio.CancelledError:
                break

            if not self.is_recording:
                continue

            # 流式推理
            try:
                draft = await asyncio.to_thread(self.asr.stream_chunk, audio)
                if draft:
                    draft = self._update_stream_text(draft)
                    draft = self._current_draft_text()
                if draft and draft != self.last_draft_sent:
                    self.last_draft_sent = draft
                    await self.broadcast({
                        "type": "draft",
                        "session_id": self.current_session_id,
                        "text": draft,
                        "timestamp": time.time() - self.session_start_time,
                    })
            except Exception as e:
                logger.error(f"Streaming inference error: {e}")

            if LOW_LATENCY_STREAM_ONLY:
                await self._maybe_commit_stream_text()
                continue

            now = time.time() - self.session_start_time
            if not self.offline_buffer:
                self.offline_buffer_start = max(0, now - CHUNK_DURATION)
            self.offline_buffer.append(audio)
            self.chunk_count += 1

            # 每 N 个 chunk 做离线校正
            if self.chunk_count >= OFFLINE_REFRESH_CHUNKS:
                self._schedule_offline_refine(now)

    def _schedule_offline_refine(self, end_time: float):
        if self.offline_refine_task and not self.offline_refine_task.done():
            return
        if not self.offline_buffer:
            return
        audio_chunks = self.offline_buffer
        start_time = self.offline_buffer_start
        session_id = self.current_session_id
        self.offline_buffer = []
        self.offline_buffer_start = 0
        self.chunk_count = 0
        self.offline_refine_task = asyncio.create_task(
            self._do_offline_refine(audio_chunks, session_id, start_time, end_time),
        )

    async def _finalize_after_stop(self):
        await asyncio.sleep(0.25)
        if LOW_LATENCY_STREAM_ONLY:
            await self._finalize_stream_text()
            self.asr.reset_cache()
            self._drain_audio_queue()
            return
        if self.offline_buffer:
            audio_chunks = self.offline_buffer
            start_time = self.offline_buffer_start
            end_time = time.time() - self.session_start_time
            session_id = self.current_session_id
            self.offline_buffer = []
            self.offline_buffer_start = 0
            self.chunk_count = 0
            await self._do_offline_refine(audio_chunks, session_id, start_time, end_time)
        self.asr.reset_cache()
        self._drain_audio_queue()

    async def _finalize_stream_text(self):
        await self._commit_stream_text(force=True)

    async def _maybe_commit_stream_text(self):
        now = time.time() - self.session_start_time
        pending = self._current_draft_text()
        if len("".join(pending.split())) < STREAM_COMMIT_MIN_CHARS:
            return
        if now - self.last_stream_commit_time < STREAM_COMMIT_INTERVAL:
            return
        await self._commit_stream_text(force=False)

    async def _commit_stream_text(self, force: bool):
        if self.stream_commit_lock is None:
            self.stream_commit_lock = asyncio.Lock()
        async with self.stream_commit_lock:
            await self._commit_stream_text_locked(force)

    async def _commit_stream_text_locked(self, force: bool):
        if not self.current_session_id:
            return
        pending = self._current_draft_text().strip()
        if not pending:
            return
        if not force and len("".join(pending.split())) < STREAM_COMMIT_MIN_CHARS:
            return

        raw_pending = self._collapse_exact_repeat(pending)
        raw_pending = self._dedupe_against_last_final(raw_pending)
        if not raw_pending:
            self.committed_stream_text = self._append_stream_text(self.committed_stream_text, pending)
            self.committed_stream_len = len(self.current_stream_text)
            self.last_draft_sent = ""
            return
        text = self._punctuate_stream_text(raw_pending, final=force)
        if not text:
            return
        now = time.time() - self.session_start_time
        start_time = self.stream_commit_start_time
        self.last_final_compact = self._compact_text(raw_pending)
        self.committed_stream_text = self._append_stream_text(self.committed_stream_text, raw_pending)
        self.committed_stream_len = len(self.current_stream_text)
        self.stream_commit_start_time = now
        self.last_stream_commit_time = now
        self.last_draft_sent = ""
        seg = Segment(
            id=str(uuid.uuid4()),
            session_id=self.current_session_id,
            text=text,
            polished_text=None,
            start_time=start_time,
            end_time=now,
            is_final=True,
        )
        await self.db.add_segment(seg)
        await self.broadcast({
            "type": "final",
            "segment": asdict(seg),
        })
        self.pending_polish_buffer.append(seg)

    def _current_draft_text(self) -> str:
        current = self.current_stream_text.strip()
        committed = self.committed_stream_text.strip()
        if not committed:
            return current

        current_compact = "".join(current.split())
        committed_compact = "".join(committed.split())
        if current_compact.startswith(committed_compact):
            return self._drop_compact_prefix(current, len(committed_compact)).strip()
        if committed_compact.endswith(current_compact):
            return ""
        return self._remove_prefix_overlap(committed, current, min_overlap=2).strip()

    @staticmethod
    def _drop_compact_prefix(text: str, compact_len: int) -> str:
        consumed = 0
        for i, ch in enumerate(text):
            if not ch.isspace():
                consumed += 1
            if consumed >= compact_len:
                return text[i + 1 :]
        return ""

    @staticmethod
    def _punctuate_stream_text(text: str, final: bool = True) -> str:
        text = TranscribeService._normalize_for_punctuation(text)
        if not text:
            return ""
        if any(ch in text for ch in "。！？!?"):
            return TranscribeService._normalize_existing_punctuation(text)

        parts = TranscribeService._split_stream_clause(text)
        sentence_end = TranscribeService._infer_sentence_end(text)
        body = "，".join(parts).strip("，")
        if final:
            return body + sentence_end
        return body + sentence_end if sentence_end in "？！" else body

    @staticmethod
    def _normalize_for_punctuation(text: str) -> str:
        text = re.sub(r"\s+", "", text or "")
        text = text.translate(str.maketrans({
            ",": "，",
            ".": "。",
            "?": "？",
            "!": "！",
            ";": "；",
            ":": "：",
        }))
        text = re.sub(r"[，。！？；：、]+$", "", text)
        text = re.sub(r"^(然后|那么|就是|就是)", "", text)
        return text.strip(" ，。,.、")

    @staticmethod
    def _normalize_existing_punctuation(text: str) -> str:
        text = re.sub(r"[，,]{2,}", "，", text)
        text = re.sub(r"[。\\.]{2,}", "。", text)
        text = re.sub(r"[！？!?]{2,}", lambda m: "？" if "？" in m.group(0) or "?" in m.group(0) else "！", text)
        return text if text[-1] in "。！？" else text + "。"

    @staticmethod
    def _split_stream_clause(text: str) -> list[str]:
        comma_before = (
            "但是",
            "不过",
            "所以",
            "因为",
            "如果",
            "其实",
            "另外",
            "接下来",
            "首先",
            "其次",
            "最后",
            "比如说",
            "比如",
            "也就是说",
            "换句话说",
            "同时",
            "而且",
            "然后",
            "那么",
            "于是",
        )
        comma_after = (
            "的话",
            "的时候",
            "以后",
            "之前",
            "之后",
            "一方面",
            "另一方面",
            "第一个",
            "第二个",
            "第三个",
        )

        for marker in comma_before:
            text = text.replace(marker, f"，{marker}")
        for marker in comma_after:
            text = text.replace(marker, f"{marker}，")
        text = re.sub(r"如果([^，]{2,12})(我们|就|再|可以|要|需要)", r"如果\1，\2", text)
        text = re.sub(r"因为([^，]{2,14})(所以|就|才|会)", r"因为\1，\2", text)
        text = re.sub(r"，+", "，", text).strip("，")
        text = re.sub(r"(我|我们|你|你们|他|他们|她|她们)，接下来", r"\1接下来", text)

        parts: list[str] = []
        for raw_part in [p for p in text.split("，") if p]:
            if raw_part:
                parts.append(raw_part)
        return parts or [text]

    @staticmethod
    def _infer_sentence_end(text: str) -> str:
        question_markers = (
            "什么",
            "怎么",
            "为什么",
            "是不是",
            "能不能",
            "可不可以",
            "有没有",
            "对不对",
            "行不行",
            "吗",
            "呢",
        )
        exclamation_patterns = (
            r"太.+了$",
            r"真是.+",
            r"(特别|非常|真的)(好|棒|厉害|夸张|离谱|重要)$",
            r"千万(不要|别|记得)",
        )
        if any(marker in text for marker in question_markers):
            return "？"
        if any(re.search(pattern, text) for pattern in exclamation_patterns) and len(text) <= 24:
            return "！"
        return "。"

    async def _do_offline_refine(
        self,
        audio_chunks: list[np.ndarray],
        session_id: Optional[str],
        start_time: float,
        end_time: float,
    ):
        if self.refine_lock is None:
            self.refine_lock = asyncio.Lock()
        async with self.refine_lock:
            await self._do_offline_refine_locked(audio_chunks, session_id, start_time, end_time)

    async def _do_offline_refine_locked(
        self,
        audio_chunks: list[np.ndarray],
        session_id: Optional[str],
        start_time: float,
        end_time: float,
    ):
        if not session_id:
            return
        try:
            text = await asyncio.to_thread(self.asr.offline_refine, audio_chunks)
            text = self._clean_final_text(text)
            if not text:
                return

            seg = Segment(
                id=str(uuid.uuid4()),
                session_id=session_id,
                text=text,
                polished_text=None,
                start_time=start_time,
                end_time=end_time,
                is_final=True,
            )
            await self.db.add_segment(seg)
            await self.broadcast({
                "type": "final",
                "segment": asdict(seg),
            })
            self.pending_polish_buffer.append(seg)

            # 累积约 30 秒触发异步润色
            total_duration = sum(
                s.end_time - s.start_time for s in self.pending_polish_buffer
            )
            if total_duration >= 30:
                asyncio.create_task(self._polish_buffer())
        except Exception as e:
            logger.error(f"Offline refine error: {e}")

    def _clean_final_text(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        text = self._collapse_exact_repeat(text)
        if self.last_offline_text:
            text = self._remove_prefix_overlap(self.last_offline_text, text)
        if text:
            self.last_offline_text = text
        return text.strip()

    def _update_stream_text(self, text: str) -> str:
        text = self._collapse_exact_repeat((text or "").strip())
        if not text:
            return self.current_stream_text

        prev = self.current_stream_text
        if not prev:
            self.current_stream_text = text
            return self.current_stream_text

        prev_compact = "".join(prev.split())
        text_compact = "".join(text.split())
        if text_compact.startswith(prev_compact):
            self.current_stream_text = text
        elif prev_compact.endswith(text_compact):
            self.current_stream_text = prev
        else:
            suffix = self._remove_prefix_overlap(prev, text, min_overlap=2)
            if suffix:
                separator = "" if self._is_cjk_join(prev, suffix) else " "
                self.current_stream_text = f"{prev}{separator}{suffix}".strip()

        self.current_stream_text = self._collapse_exact_repeat(self.current_stream_text)
        return self.current_stream_text

    def _append_stream_text(self, base: str, addition: str) -> str:
        addition = self._collapse_exact_repeat((addition or "").strip())
        if not addition:
            return base.strip()
        if not base:
            return addition
        base_compact = "".join(base.split())
        addition_compact = "".join(addition.split())
        if base_compact.endswith(addition_compact):
            return base.strip()
        if addition_compact.startswith(base_compact):
            return addition.strip()
        suffix = self._remove_prefix_overlap(base, addition, min_overlap=2)
        if not suffix:
            return base.strip()
        separator = "" if self._is_cjk_join(base, suffix) else " "
        return f"{base}{separator}{suffix}".strip()

    def _dedupe_against_last_final(self, text: str) -> str:
        text = self._collapse_exact_repeat((text or "").strip())
        if not text or not self.last_final_compact:
            return text

        current_compact = self._compact_text(text)
        if not current_compact:
            return ""
        if current_compact == self.last_final_compact:
            return ""
        if self.last_final_compact.endswith(current_compact):
            return ""
        if current_compact.startswith(self.last_final_compact):
            return self._drop_compact_prefix(text, len(self.last_final_compact)).strip()
        return self._remove_prefix_overlap_compact(self.last_final_compact, text, min_overlap=4)

    @staticmethod
    def _compact_text(text: str) -> str:
        return re.sub(r"[\s，。,.、！？!?；;：:]+", "", text or "")

    @staticmethod
    def _is_cjk_join(left: str, right: str) -> bool:
        if not left or not right:
            return True
        return "\u4e00" <= left[-1] <= "\u9fff" or "\u4e00" <= right[0] <= "\u9fff"

    @staticmethod
    def _collapse_exact_repeat(text: str) -> str:
        compact = "".join(text.split())
        if len(compact) % 2 != 0:
            return text
        half = len(compact) // 2
        if half == 0 or compact[:half] != compact[half:]:
            return text
        result = []
        seen = 0
        for ch in text:
            if not ch.isspace() and seen >= half:
                continue
            result.append(ch)
            if not ch.isspace():
                seen += 1
        return "".join(result).strip()

    @staticmethod
    def _remove_prefix_overlap(prev: str, cur: str, min_overlap: int = 6) -> str:
        prev_compact = "".join(prev.split())
        cur_compact = "".join(cur.split())
        max_len = min(len(prev_compact), len(cur_compact))
        overlap = 0
        for size in range(max_len, 0, -1):
            if prev_compact[-size:] == cur_compact[:size]:
                overlap = size
                break
        if overlap < min_overlap:
            return cur
        consumed = 0
        cut_at = 0
        for i, ch in enumerate(cur):
            if not ch.isspace():
                consumed += 1
            if consumed >= overlap:
                cut_at = i + 1
                break
        return cur[cut_at:].strip()

    @staticmethod
    def _remove_prefix_overlap_compact(prev_compact: str, cur: str, min_overlap: int = 6) -> str:
        cur_compact = TranscribeService._compact_text(cur)
        max_len = min(len(prev_compact), len(cur_compact))
        overlap = 0
        for size in range(max_len, 0, -1):
            if prev_compact[-size:] == cur_compact[:size]:
                overlap = size
                break
        if overlap < min_overlap:
            return cur
        return TranscribeService._drop_compact_prefix(cur, overlap).strip()

    async def _polish_buffer(self):
        if not self.pending_polish_buffer:
            return
        buffer = self.pending_polish_buffer.copy()
        self.pending_polish_buffer.clear()

        raw_text = "".join(s.text for s in buffer)
        polished = await self.polisher.polish(raw_text)
        if not polished:
            return

        # 简单策略：把润色结果按比例分配回原 segments（保留可追溯性）
        # 这里把润色文本作为新事件推送，前端可以选择展示哪个版本
        for seg in buffer:
            await self.db.update_segment_polish(seg.id, polished)
        await self.broadcast({
            "type": "polished",
            "segment_ids": [s.id for s in buffer],
            "polished_text": polished,
        })

    async def polish_session(self, session_id: str):
        """手动润色整个会话"""
        if not session_id:
            return
        segs = await self.db.get_session_segments(session_id)
        full_text = "".join((s.get("polished_text") or s["text"]) for s in segs)
        await self.broadcast({"type": "polish_started", "session_id": session_id})
        polished = await self.polisher.polish(full_text)
        if not polished:
            await self.broadcast({
                "type": "error",
                "message": "润色失败：请检查 API Key 和模型设置。",
            })
            return

        seg = await self.db.replace_session_with_polished(session_id, polished)
        await self.broadcast({
            "type": "session_polished",
            "session_id": session_id,
            "polished_text": polished,
            "segment": asdict(seg),
        })

    # ----- 启动入口 -----
    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.audio_queue = asyncio.Queue(maxsize=2)
        self.refine_lock = asyncio.Lock()
        self.stream_commit_lock = asyncio.Lock()

        await self.db.init()
        self.asr.load_models()

        # 启动音频流（始终开启，用 is_recording 控制是否处理）
        stream = sd.InputStream(
            callback=self.audio_callback,
            channels=1,
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_SAMPLES,
            dtype="float32",
        )
        stream.start()
        logger.info(f"🎤 Audio stream started @ {SAMPLE_RATE}Hz")

        # 启动音频处理协程
        processor_task = asyncio.create_task(self.audio_processor())

        # 启动 WebSocket 服务
        async with websockets.serve(self.handle_client, WS_HOST, WS_PORT):
            print("READY", flush=True)  # Tauri 主进程检测此信号
            logger.info(f"🚀 WebSocket server listening on ws://{WS_HOST}:{WS_PORT}")
            try:
                await asyncio.Future()  # run forever
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                processor_task.cancel()
                with suppress(asyncio.CancelledError):
                    await processor_task
                stream.stop()
                stream.close()


# ============================================================
# 入口
# ============================================================
def warmup():
    """仅触发模型下载，不启动服务"""
    engine = ASREngine()
    engine.load_models()
    logger.info("✓ Warmup complete, models cached locally")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--warmup":
        warmup()
        sys.exit(0)

    service = TranscribeService()
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
