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
      <span className="composer-plus" aria-hidden="true">＋</span>
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
        ? <button aria-label="取消运行" onClick={cancelTurn}>取消</button>
        : <button aria-label="发送消息" onClick={submit} disabled={!text.trim()}>↑</button>}
    </div>
  );
}
