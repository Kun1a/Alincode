import { useState } from "react";
import type { Block } from "../lib/protocol";

type Tool = Extract<Block, { kind: "tool" }>;

function formatDuration(value?: number): string | null {
  if (value === undefined) return null;
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} 秒`;
}

export function WorkflowBlock({ blocks }: { blocks: Tool[] }) {
  const [expanded, setExpanded] = useState(true);
  const running = blocks.some((block) => block.state === "running");
  const errors = blocks.filter((block) => block.isError).length;
  const completed = blocks.filter((block) => block.state === "done").length;
  const first = blocks[0];
  const last = blocks[blocks.length - 1];
  const firstStartedAt = first?.startedAt;
  const lastStartedAt = last?.startedAt;
  const lastDuration = last?.durationMs;
  const total = firstStartedAt === undefined || lastStartedAt === undefined || lastDuration === undefined
    ? undefined
    : Math.max(0, lastStartedAt + lastDuration - firstStartedAt);
  const summary = running ? "正在分析并执行" : errors ? `${errors} 个步骤失败` : `已完成 ${completed} 个步骤`;

  return (
    <section className={`workflow-block ${running ? "running" : "done"}`}>
      <button className="workflow-header" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
        <span className="workflow-chevron">{expanded ? "⌄" : "›"}</span>
        <span className="workflow-title">执行工作流</span>
        <span className="workflow-summary">{summary}</span>
        {formatDuration(total) ? <span className="workflow-duration">{formatDuration(total)}</span> : null}
      </button>
      {expanded ? <div className="workflow-steps">
        {blocks.map((block, index) => <article className="workflow-step" key={`${block.name}-${index}`}>
          <span className={`workflow-dot ${block.state === "running" ? "is-running" : block.isError ? "is-error" : ""}`} />
          <div className="workflow-step-line">
            <strong>{block.state === "running" ? "正在调用" : block.isError ? "调用失败" : "已调用"} · {block.name}</strong>
            {formatDuration(block.durationMs) ? <time>{formatDuration(block.durationMs)}</time> : null}
          </div>
          {block.args ? <pre className="workflow-detail">{block.args}</pre> : null}
          {block.result ? <pre className="workflow-detail result">{block.result}</pre> : null}
        </article>)}
      </div> : null}
    </section>
  );
}
