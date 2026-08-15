// webui/src/components/AssistantBlock.tsx
import { lazy, memo, Suspense } from "react";
import type { Block } from "../lib/protocol";

const Markdown = lazy(() => import("react-markdown"));

export const AssistantBlock = memo(function AssistantBlock(
  { block }: { block: Extract<Block, { kind: "assistant" }> },
) {
  if (block.streaming) {
    // 流式中：纯文本（与 TUI StreamText 行为一致）
    return <div className="msg assistant streaming">● {block.content}</div>;
  }
  return (
    <div className="msg assistant">
      <Suspense fallback={<pre className="md-fallback">{block.content}</pre>}>
        <Markdown>{block.content}</Markdown>
      </Suspense>
    </div>
  );
});
