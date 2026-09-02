import { useState } from "react";
import type { Block } from "../lib/protocol";
import { ApprovalCard } from "./ApprovalCard";

type Tool = Extract<Block, { kind: "tool" }>;
type Approval = Extract<Block, { kind: "approval" }>;
export type WorkflowItem = Tool | Approval;

function formatDuration(value?: number): string | null {
  if (value === undefined) return null;
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} 秒`;
}

export function WorkflowBlock({ blocks }: { blocks: WorkflowItem[] }) {
  const [expanded, setExpanded] = useState(true);
  const tools = blocks.filter((block): block is Tool => block.kind === "tool");
  const approvals = blocks.filter((block): block is Approval => block.kind === "approval");
  const running = tools.some((block) => block.state === "running");
  const waitingApproval = approvals.some((block) => block.state === "pending");
  const errors = tools.filter((block) => block.isError).length;
  const completed = tools.filter((block) => block.state === "done").length;
  const first = tools[0];
  const last = tools[tools.length - 1];
  const firstStartedAt = first?.startedAt;
  const lastStartedAt = last?.startedAt;
  const lastDuration = last?.durationMs;
  const measuredDurations = tools.map((block) => block.durationMs).filter((value): value is number => value !== undefined);
  const total = firstStartedAt !== undefined && lastStartedAt !== undefined && lastDuration !== undefined
    ? Math.max(0, lastStartedAt + lastDuration - firstStartedAt)
    : tools.length > 0 && measuredDurations.length === tools.length
      ? measuredDurations.reduce((sum, value) => sum + value, 0)
      : undefined;
  const summary = waitingApproval ? "等待授权"
    : running ? "正在分析并执行"
      : errors ? `${errors} 个步骤失败`
        : `${approvals.length ? `已授权 ${approvals.length} 次 · ` : ""}已完成 ${completed} 个步骤`;

  return (
    <section className={`workflow-block ${running ? "running" : "done"}`}>
      <button className="workflow-header" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
        <span className="workflow-chevron">{expanded ? "⌄" : "›"}</span>
        <span className="workflow-title">执行工作流</span>
        <span className="workflow-summary">{summary}</span>
        {formatDuration(total) ? <span className="workflow-duration">{formatDuration(total)}</span> : null}
      </button>
      {expanded ? <div className="workflow-steps">
        {blocks.map((block, index) => block.kind === "approval" ? <article className="workflow-step approval-step" key={`${block.requestId}-${index}`}>
          <span className="workflow-dot is-approval" />
          <div className="workflow-step-line">
            <strong>{block.state === "pending" ? "需要授权" : "已授权"} · {block.toolName}</strong>
            <time>{block.state === "pending" ? "等待确认" : block.outcome}</time>
          </div>
          <ApprovalCard block={block} compact />
        </article> : <article className="workflow-step" key={`${block.name}-${index}`}>
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
