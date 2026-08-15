// webui/src/App.tsx
import { ChatProvider } from "./state/ChatContext";
import { ChatView } from "./components/ChatView";

export default function App() {
  return (
    <ChatProvider>
      <ChatView />
    </ChatProvider>
  );
}
