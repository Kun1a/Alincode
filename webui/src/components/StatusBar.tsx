// webui/src/components/StatusBar.tsx
import { useChat } from "../state/ChatContext";

export function StatusBar() {
  const { state } = useChat();
  return (
    <div className="status-bar">
      <span>{state.connected ? "已连接" : "未连接"}</span>
      <span>会话 {state.sessionId || "—"}</span>
      <span>本地用量 {state.usedTokens || 0}{state.budget ? ` / ${state.budget}` : " tokens"}</span>
      {state.budgetBlocked ? <span className="busy">预算已用尽</span> : null}
      {state.iter > 0 ? <span>轮 {state.iter}</span> : null}
      {state.busy ? <span className="busy">运行中…</span> : null}
    </div>
  );
}
