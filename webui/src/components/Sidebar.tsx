import { useEffect, useState } from "react";
import { useChat } from "../state/ChatContext";

interface Session { id: string; title: string; modified_at: string; }

export function Sidebar() {
  const { state, resumeSession } = useChat();
  const [sessions, setSessions] = useState<Session[]>([]);

  useEffect(() => {
    void fetch("/api/sessions").then(async (response) => {
      if (response.ok) setSessions(await response.json() as Session[]);
    });
  }, [state.sessionId]);

  return <aside className="sidebar">
    <button className="new-chat" onClick={() => location.reload()}>＋ 新建对话</button>
    <p className="sidebar-label">对话历史</p>
    <div className="session-list">
      {sessions.length ? sessions.map((session) => <button key={session.id}
        className={session.id === state.sessionId ? "session-item active" : "session-item"}
        onClick={() => resumeSession(session.id)}>{session.title || "新对话"}</button>)
        : <p className="empty-history">还没有历史对话</p>}
    </div>
  </aside>;
}
