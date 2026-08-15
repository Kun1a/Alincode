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
        switch (b.kind) {
          case "user":
            return <div key={i} className="msg user">{b.content}</div>;
          case "assistant":
            return <AssistantBlock key={i} block={b} />;
          case "tool":
            return <ToolBlock key={i} block={b} />;
          case "approval":
            return <ApprovalCard key={i} block={b} />;
          case "notice":
            return <div key={i} className={`msg notice ${b.tone}`}>{b.text}</div>;
        }
      })}
      <div ref={endRef} />
    </div>
  );
}
