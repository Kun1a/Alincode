// webui/src/components/ChatView.tsx
import { useState } from "react";
import type { Profile } from "./ProfileGate";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { StatusBar } from "./StatusBar";
import { Sidebar } from "./Sidebar";
import { SettingsDialog } from "./SettingsDialog";
import { EnvironmentPanel } from "./EnvironmentPanel";
import { useChat } from "../state/ChatContext";

export function ChatView({ profile, onLock }: { profile: Profile | null; onLock: () => void }) {
  const { state } = useChat();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const workspaceParts = state.workspace.split(/[\\/]/).filter(Boolean);
  const workspaceName = workspaceParts[workspaceParts.length - 1] || "未选择项目目录";
  return (
    <div className="desktop-shell">
      {profile ? <Sidebar profile={profile} /> : null}
      <main className="chat-view">
        <div className="chat-topbar"><div><strong>{state.sessionId ? "当前对话" : "新建对话"}</strong><span>{workspaceName}</span></div>{profile ? <button onClick={() => setSettingsOpen(true)}>设置</button> : null}</div>
        <StatusBar />
        <MessageList blocks={state.blocks} />
        <Composer />
      </main>
      {profile ? <EnvironmentPanel /> : null}
      {settingsOpen ? <SettingsDialog onClose={() => setSettingsOpen(false)} onLock={() => { setSettingsOpen(false); void fetch("/api/profile/lock", { method: "POST" }).then(onLock); }} /> : null}
    </div>
  );
}
