// webui/src/state/ChatContext.tsx
// WebSocket 连接层 + 全局聊天状态。
// 设计：text.delta 高频增量先累积到 bufferRef，requestAnimationFrame 每帧一次性 dispatch，
// 避免每个 token 触发一次渲染；其余低频消息直接 dispatch。
import {
  createContext, useContext, useEffect, useMemo, useReducer, useRef,
  type ReactNode,
} from "react";
import type { ClientMsg, ServerMsg } from "../lib/protocol";
import { chatReducer, initialChatState, type ChatState } from "./chatReducer";

interface ChatApi {
  state: ChatState;
  sendText: (text: string) => void;
  respondApproval: (requestId: string, outcome: "allow_once" | "allow_forever" | "deny_once") => void;
  cancelTurn: () => void;
  resumeSession: (sessionId: string) => void;
  setMode: (mode: "default" | "acceptEdits" | "plan" | "bypassPermissions") => void;
}

const ChatContext = createContext<ChatApi | null>(null);

function wsUrl(): string {
  const proto = location.protocol === "https:" ? "wss://" : "ws://";
  return `${proto}${location.host}/ws`;
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const wsRef = useRef<WebSocket | null>(null);
  const bufferRef = useRef("");       // text.delta 帧内累积
  const rafRef = useRef(0);

  const send = (msg: ClientMsg) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };

  useEffect(function connectWebSocket() {
    const ws = new WebSocket(wsUrl());
    wsRef.current = ws;

    ws.onmessage = (e: MessageEvent<string>) => {
      const msg = JSON.parse(e.data) as ServerMsg;
      if (msg.type === "text.delta") {
        bufferRef.current += msg.delta;
        if (!rafRef.current) {
          rafRef.current = requestAnimationFrame(function flushDeltaBuffer() {
            rafRef.current = 0;
            if (bufferRef.current) {
              dispatch({ type: "text.delta", delta: bufferRef.current });
              bufferRef.current = "";
            }
          });
        }
        return;
      }
      dispatch(msg);
    };
    ws.onclose = () => dispatch({ type: "__local.connected", connected: false });

    return function cleanupWebSocket() {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
      ws.close();
    };
  }, []);

  const api = useMemo<ChatApi>(() => ({
    state,
    sendText: (text) => {
      dispatch({ type: "__local.busy", busy: true }); // 乐观置位，turn.done/error 复位
      send({ type: "chat.send", text });
    },
    respondApproval: (requestId, outcome) =>
      send({ type: "approval.respond", request_id: requestId, outcome }),
    cancelTurn: () => send({ type: "turn.cancel" }),
    resumeSession: (sessionId) => send({ type: "session.resume", session_id: sessionId }),
    setMode: (mode) => send({ type: "mode.set", mode }),
  }), [state]);

  return <ChatContext.Provider value={api}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatApi {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat 必须在 ChatProvider 内使用");
  return ctx;
}
