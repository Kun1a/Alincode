// webui/src/App.tsx
import { useState } from "react";
import { ProfileGate, type Profile } from "./components/ProfileGate";
import { ChatProvider } from "./state/ChatContext";
import { ChatView } from "./components/ChatView";

export default function App() {
  const [profile, setProfile] = useState<Profile | null | undefined>(undefined);
  if (profile === undefined) return <ProfileGate onReady={setProfile} />;
  return (
    <ChatProvider>
      <ChatView profile={profile} onLock={() => setProfile(undefined)} />
    </ChatProvider>
  );
}
