// webui/src/components/MessageList.tsx
import { useEffect, useRef } from "react";
import type { Block } from "../lib/protocol";
import { AssistantBlock } from "./AssistantBlock";
import { WorkflowBlock, type WorkflowItem } from "./WorkflowBlock";

function isWorkflowItem(block: Block): block is WorkflowItem {
  return block.kind === "approval" || block.kind === "tool";
}

export function MessageList({ blocks }: { blocks: Block[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(function scrollToBottom() {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [blocks]);

  let assistantLabelShown = false;
  return (
    <div className="message-list">
      {blocks.reduce<React.ReactNode[]>((items, b, i) => {
        if (isWorkflowItem(b)) {
          const previous = blocks[i - 1];
          if (previous && isWorkflowItem(previous)) return items;
          const workflow = blocks.slice(i)
            .filter((block, offset) => offset === 0 || isWorkflowItem(blocks[i + offset - 1]))
            .filter(isWorkflowItem);
          items.push(<WorkflowBlock key={`workflow-${i}`} blocks={workflow} />);
          return items;
        }
        if (b.kind === "user") assistantLabelShown = false;
        const meta = b.kind === "user" ? "你"
          : b.kind === "assistant" && !assistantLabelShown ? "AlinCode" : null;
        if (b.kind === "assistant") assistantLabelShown = true;
        let content;
        switch (b.kind) {
          case "user":
            content = <div className="msg user">{b.content}</div>;
            break;
          case "assistant":
            content = <AssistantBlock block={b} />;
            break;
          case "notice":
            content = <div className={`msg notice ${b.tone}`}>{b.text}</div>;
            break;
        }
        items.push(<article key={i} className={`message-row ${b.kind}`}>{meta ? <p className="message-meta">{meta}</p> : null}{content}</article>);
        return items;
      }, [])}
      <div ref={endRef} />
    </div>
  );
}
