// webui/src/components/ApprovalCard.tsx
import type { Block } from "../lib/protocol";
import { useChat } from "../state/ChatContext";

const OUTCOMES = [
  ["allow_once", "允许本次"],
  ["allow_forever", "永久允许"],
  ["deny_once", "拒绝"],
] as const;

export function ApprovalCard({ block }: { block: Extract<Block, { kind: "approval" }> }) {
  const { respondApproval } = useChat();
  return (
    <div className={`msg approval ${block.state}`}>
      <div className="approval-title">需要授权：{block.toolName}</div>
      <pre className="approval-args">{block.toolArgs}</pre>
      {block.reason ? <div className="approval-reason">{block.reason}</div> : null}
      {block.state === "pending" ? (
        <div className="approval-actions">
          {OUTCOMES.map(([value, label]) => (
            <button key={value} onClick={() => respondApproval(block.requestId, value)}>
              {label}
            </button>
          ))}
        </div>
      ) : (
        <div className="approval-outcome">已处理：{block.outcome}</div>
      )}
    </div>
  );
}
