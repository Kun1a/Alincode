// webui/src/components/ToolBlock.tsx
import type { Block } from "../lib/protocol";

export function ToolBlock({ block }: { block: Extract<Block, { kind: "tool" }> }) {
  return (
    <details className="msg tool" open={block.state === "running"}>
      <summary>
        <span className="tool-icon">⚙</span> {block.name}
        {block.state === "running" ? <span className="tool-running"> Running…</span> : null}
        {block.isError ? <span className="tool-error"> 失败</span> : null}
      </summary>
      {block.args ? <pre className="tool-args">{block.args}</pre> : null}
      {block.result ? <pre className="tool-result">{block.result}</pre> : null}
    </details>
  );
}
