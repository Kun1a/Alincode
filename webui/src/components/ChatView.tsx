// webui/src/components/ChatView.tsx
import { useState } from "react";
import type { Profile } from "./ProfileGate";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { StatusBar } from "./StatusBar";
import { Sidebar } from "./Sidebar";
import { SettingsDialog } from "./SettingsDialog";
import { useChat } from "../state/ChatContext";

export function ChatView({ profile, onLock }: { profile: Profile | null; onLock: () => void }) {
  const { state } = useChat();
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <div className="desktop-shell">
      {profile ? <Sidebar /> : null}
      <div className="chat-view">
        <div className="chat-topbar"><span>{profile ? profile.name : "AlinCode Web"}</span>{profile ? <button onClick={() => setSettingsOpen(true)}>设置</button> : null}</div>
        <StatusBar />
        <MessageList blocks={state.blocks} />
        <Composer />
      </div>
      {settingsOpen ? <SettingsDialog onClose={() => setSettingsOpen(false)} onLock={() => { setSettingsOpen(false); void fetch("/api/profile/lock", { method: "POST" }).then(onLock); }} /> : null}
    </div>
  );
}
