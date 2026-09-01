// webui/src/components/MessageList.tsx
import { useEffect, useRef } from "react";
import type { Block } from "../lib/protocol";
import { AssistantBlock } from "./AssistantBlock";
import { ToolBlock } from "./ToolBlock";
import { ApprovalCard } from "./ApprovalCard";

export function MessageList({ blocks }: { blocks: Block[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(function scrollToBottom() {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [blocks]);

  return (
    <div className="message-list">
      {blocks.map((b, i) => {
        const meta = b.kind === "user" ? "你" : b.kind === "assistant" ? "AlinCode" : null;
        let content;
        switch (b.kind) {
          case "user":
            content = <div className="msg user">{b.content}</div>;
            break;
          case "assistant":
            content = <AssistantBlock block={b} />;
            break;
          case "tool":
            content = <ToolBlock block={b} />;
            break;
          case "approval":
            content = <ApprovalCard block={b} />;
            break;
          case "notice":
            content = <div className={`msg notice ${b.tone}`}>{b.text}</div>;
            break;
        }
        return <article key={i} className={`message-row ${b.kind}`}>{meta ? <p className="message-meta">{meta}</p> : null}{content}</article>;
      })}
      <div ref={endRef} />
    </div>
  );
}
