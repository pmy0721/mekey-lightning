import { useEffect, useRef, useState, useCallback } from "react";
import type { WSMessage } from "../lib/types";

const WS_URL = "ws://127.0.0.1:9527";

export function useTranscribeWS(onMessage: (msg: WSMessage) => void) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const onMessageRef = useRef(onMessage);

  // 保持 onMessage 引用最新（避免重连时丢回调）
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log("[WS] connected");
      setConnected(true);
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as WSMessage;
        onMessageRef.current(msg);
      } catch (err) {
        console.error("[WS] parse error:", err);
      }
    };

    ws.onclose = () => {
      console.log("[WS] disconnected, retrying in 2s...");
      setConnected(false);
      wsRef.current = null;
      reconnectTimerRef.current = window.setTimeout(connect, 2000);
    };

    ws.onerror = (e) => {
      console.warn("[WS] error:", e);
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
      }
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((cmd: object) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(cmd));
    } else {
      console.warn("[WS] not connected, cannot send:", cmd);
    }
  }, []);

  return { connected, send };
}
