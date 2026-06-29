import { useEffect, useRef } from "react";
import type { SessionSocketEvent } from "../types/session";

export function useSessionSocket(
  sessionId: string | null,
  onEvent: (event: SessionSocketEvent) => void,
  onConnectionChange?: (connected: boolean) => void,
) {
  const onEventRef = useRef(onEvent);
  const onConnectionChangeRef = useRef(onConnectionChange);

  useEffect(() => {
    onEventRef.current = onEvent;
    onConnectionChangeRef.current = onConnectionChange;
  }, [onConnectionChange, onEvent]);

  useEffect(() => {
    if (!sessionId) return;
    const baseUrl = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000";
    const socket = new WebSocket(`${baseUrl}/ws/sessions/${sessionId}`);
    socket.onopen = () => onConnectionChangeRef.current?.(true);
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as SessionSocketEvent;
        onEventRef.current(event);
      } catch {
        // Ignore malformed external events. Session recovery remains available via REST.
      }
    };
    socket.onerror = () => onConnectionChangeRef.current?.(false);
    socket.onclose = () => onConnectionChangeRef.current?.(false);
    return () => {
      onConnectionChangeRef.current?.(false);
      socket.close();
    };
  }, [sessionId]);
}
