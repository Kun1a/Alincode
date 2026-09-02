// webui/src/components/ChatView.tsx
import { useState } from "react";
import type { Profile } from "./ProfileGate";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { StatusBar } from "./StatusBar";
import { Sidebar } from "./Sidebar";
import { SettingsDialog } from "./SettingsDialog";
import { EnvironmentPanel } from "./EnvironmentPanel";
import { ProjectPickerDialog } from "./ProjectPickerDialog";
import { PluginsDialog } from "./PluginsDialog";
import { useChat } from "../state/ChatContext";

export function ChatView({ profile, onLock }: { profile: Profile | null; onLock: () => void }) {
  const { state, setMode, newSession } = useChat();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [projectPickerOpen, setProjectPickerOpen] = useState(false);
  const [pluginsOpen, setPluginsOpen] = useState(false);
  const workspaceParts = state.workspace.split(/[\\/]/).filter(Boolean);
  const workspaceName = workspaceParts[workspaceParts.length - 1] || "未选择项目目录";
  return (
    <div className="desktop-shell">
      {profile ? <Sidebar profile={profile} onNewChat={() => setProjectPickerOpen(true)} onPlugins={() => setPluginsOpen(true)} /> : null}
      <main className="chat-view">
        <div className="chat-topbar"><div><strong>{state.sessionId ? "当前对话" : "新建对话"}</strong><span>{workspaceName}</span></div><div className="chat-actions"><label>执行模式<select aria-label="执行模式" value={state.mode || "default"} disabled={state.busy} onChange={(event) => setMode(event.target.value as "default" | "acceptEdits" | "plan" | "bypassPermissions")}><option value="default">默认审批</option><option value="acceptEdits">自动审批编辑</option><option value="plan">规划模式</option><option value="bypassPermissions">跳过审批</option></select></label>{profile ? <button onClick={() => setSettingsOpen(true)}>设置</button> : null}</div></div>
        <StatusBar />
        <MessageList blocks={state.blocks} />
        <Composer />
      </main>
      {profile ? <EnvironmentPanel /> : null}
      {settingsOpen ? <SettingsDialog onClose={() => setSettingsOpen(false)} onLock={() => { setSettingsOpen(false); void fetch("/api/profile/lock", { method: "POST" }).then(onLock); }} /> : null}
      {projectPickerOpen ? <ProjectPickerDialog onClose={() => setProjectPickerOpen(false)} onStart={(workspace) => { setProjectPickerOpen(false); newSession(workspace); }} /> : null}
      {pluginsOpen ? <PluginsDialog onClose={() => setPluginsOpen(false)} /> : null}
    </div>
  );
}
