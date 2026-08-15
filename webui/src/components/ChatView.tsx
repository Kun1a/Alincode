// webui/src/components/ChatView.tsx
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { StatusBar } from "./StatusBar";
import { useChat } from "../state/ChatContext";

export function ChatView() {
  const { state } = useChat();
  return (
    <div className="chat-view">
      <StatusBar />
      <MessageList blocks={state.blocks} />
      <Composer />
    </div>
  );
}
