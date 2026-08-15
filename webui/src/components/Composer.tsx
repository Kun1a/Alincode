// webui/src/components/Composer.tsx
import { useState } from "react";
import { useChat } from "../state/ChatContext";

export function Composer() {
  const { state, sendText, cancelTurn } = useChat();
  const [text, setText] = useState("");

  const submit = () => {
    const t = text.trim();
    if (!t || state.busy) return;
    sendText(t);
    setText("");
  };

  return (
    <div className="composer">
      <textarea
        value={text}
        placeholder="输入消息，Enter 发送，Shift+Enter 换行"
        rows={3}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      {state.busy
        ? <button onClick={cancelTurn}>取消</button>
        : <button onClick={submit} disabled={!text.trim()}>发送</button>}
    </div>
  );
}
