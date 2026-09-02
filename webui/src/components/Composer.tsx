// webui/src/components/Composer.tsx
import { useState } from "react";
import { useChat } from "../state/ChatContext";

export function Composer() {
  const { state, sendText, cancelTurn } = useChat();
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<string[]>([]);
  const [attachmentError, setAttachmentError] = useState("");

  const submit = () => {
    const t = text.trim();
    if (!t || state.busy) return;
    sendText(t, attachments);
    setText("");
    setAttachments([]);
  };

  const pickFiles = async () => {
    setAttachmentError("");
    try {
      const response = await fetch("/api/profile/pick-files", { method: "POST" });
      const body = await response.json() as { paths?: string[]; detail?: string };
      if (!response.ok) throw new Error(body.detail || "无法打开文件选择器");
      setAttachments(current => [...new Set([...current, ...(body.paths ?? [])])]);
    } catch (error) { setAttachmentError(error instanceof Error ? error.message : "无法添加文件"); }
  };

  const removeAttachment = (path: string) => setAttachments(current => current.filter(item => item !== path));
  const displayName = (path: string) => path.split(/[\\/]/).pop() || path;

  return (
    <div className="composer-area">
      {attachments.length > 0 ? <div className="attachment-list">{attachments.map(path => <span className="attachment-chip" key={path}>▣ {displayName(path)}<button aria-label={`移除 ${displayName(path)}`} onClick={() => removeAttachment(path)}>×</button></span>)}</div> : null}
      {attachmentError ? <p className="attachment-error">{attachmentError}</p> : null}
      <div className="composer">
        <button className="composer-plus" aria-label="添加文件" onClick={() => void pickFiles()} disabled={state.busy}>＋</button>
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
    </div>
  );
}
