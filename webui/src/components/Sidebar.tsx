import { useEffect, useState } from "react";
import { useChat } from "../state/ChatContext";
import type { Profile } from "./ProfileGate";

interface Session { id: string; title: string; modified_at: string; }

export function Sidebar({ profile, onNewChat, onPlugins }: {
  profile: Profile; onNewChat: () => void; onPlugins: () => void;
}) {
  const { state, resumeSession, newSession } = useChat();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [menu, setMenu] = useState<Session | null>(null);
  const [renameTarget, setRenameTarget] = useState<Session | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");

  const loadSessions = () => {
    void fetch("/api/sessions").then(async (response) => {
      if (response.ok) setSessions(await response.json() as Session[]);
    });
  };
  useEffect(loadSessions, [state.sessionId]);

  const rename = async () => {
    if (!renameTarget || !title.trim()) return;
    const response = await fetch(`/api/sessions/${renameTarget.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
    });
    if (!response.ok) { setMessage("重命名失败，请检查标题。"); return; }
    setRenameTarget(null); setMenu(null); setMessage(""); loadSessions();
  };

  const remove = async () => {
    if (!deleteTarget) return;
    const removedId = deleteTarget.id;
    const response = await fetch(`/api/sessions/${removedId}`, { method: "DELETE" });
    if (!response.ok) { setMessage("删除失败，请稍后重试。"); return; }
    setDeleteTarget(null); setMenu(null); setMessage("");
    if (state.sessionId === removedId) newSession();
    loadSessions();
  };

  return <aside className="sidebar">
    <header className="sidebar-brand">
      <img src="/alincode-a-mark.png" alt="AlinCode" />
      <div><strong>AlinCode</strong><span>你的本地 Coding Agent</span></div>
    </header>
    <button className="new-chat" onClick={onNewChat} disabled={state.busy}>＋ 新建对话</button>
    <button className="sidebar-plugins" onClick={onPlugins}>⌘ 插件</button>
    <p className="sidebar-label">对话历史</p>
    <div className="session-list">
      {sessions.length ? sessions.map((session) => <div className={session.id === state.sessionId ? "session-row active" : "session-row"} key={session.id}>
        <button className="session-item" onClick={() => resumeSession(session.id)}>{session.title || "新对话"}</button>
        <button className="session-more" aria-label={`管理 ${session.title || "新对话"}`} onClick={() => setMenu(session)}>⋯</button>
      </div>)
        : <p className="empty-history">还没有历史对话</p>}
    </div>
    <footer className="sidebar-profile">
      <span aria-hidden="true">{profile.name.slice(0, 1).toUpperCase()}</span>
      <div><strong>{profile.name}</strong><small>仅保存在这台设备</small></div>
    </footer>
    {menu ? <div className="modal-backdrop" role="presentation" onMouseDown={() => setMenu(null)}><section className="settings-dialog history-dialog" onMouseDown={event => event.stopPropagation()}><header><div><strong>{menu.title || "新对话"}</strong><span>仅影响当前本机 Profile</span></div><button onClick={() => setMenu(null)}>关闭</button></header><div className="history-actions"><button onClick={() => { setTitle(menu.title); setRenameTarget(menu); }}>✎ 重命名</button><button className="history-delete" onClick={() => setDeleteTarget(menu)}>⌫ 删除对话</button></div></section></div> : null}
    {renameTarget ? <div className="modal-backdrop" role="presentation" onMouseDown={() => setRenameTarget(null)}><section className="settings-dialog history-dialog" onMouseDown={event => event.stopPropagation()}><header><div><strong>重命名对话</strong><span>自定义标题会覆盖自动标题</span></div><button onClick={() => setRenameTarget(null)}>关闭</button></header><label>标题<input value={title} maxLength={80} onChange={event => setTitle(event.target.value)} /></label>{message ? <p className="settings-message">{message}</p> : null}<footer><span /><button className="primary-button compact-primary" onClick={() => void rename()}>保存</button></footer></section></div> : null}
    {deleteTarget ? <div className="modal-backdrop" role="presentation" onMouseDown={() => setDeleteTarget(null)}><section className="settings-dialog history-dialog" onMouseDown={event => event.stopPropagation()}><header><div><strong>删除对话？</strong><span>此操作不可撤销</span></div><button onClick={() => setDeleteTarget(null)}>关闭</button></header><p className="settings-hint">会删除“{deleteTarget.title || "新对话"}”的本地历史记录。</p>{message ? <p className="settings-message">{message}</p> : null}<footer><button onClick={() => setDeleteTarget(null)}>取消</button><button className="history-delete-button" onClick={() => void remove()}>删除</button></footer></section></div> : null}
  </aside>;
}
