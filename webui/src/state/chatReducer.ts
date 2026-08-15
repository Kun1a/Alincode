// webui/src/state/chatReducer.ts
// 纯函数状态机：ServerMsg（含本地补充动作）→ ChatState。
import type { Block, ServerMsg } from "../lib/protocol";

export interface ChatState {
  blocks: Block[];
  busy: boolean;
  connected: boolean;
  sessionId: string;
  inputTokens: number;
  outputTokens: number;
  iter: number;
}

export const initialChatState: ChatState = {
  blocks: [], busy: false, connected: false, sessionId: "",
  inputTokens: 0, outputTokens: 0, iter: 0,
};

/** 本地动作：前端私有状态补丁（busy 乐观置位 / 断连标记），不经后端。 */
export type LocalMsg =
  | { type: "__local.busy"; busy: boolean }
  | { type: "__local.connected"; connected: boolean };

/** 把流式增量折叠进最后一个 assistant 块；否则新开一块。 */
function pushDelta(blocks: Block[], delta: string): Block[] {
  const last = blocks[blocks.length - 1];
  if (last && last.kind === "assistant" && last.streaming) {
    return [...blocks.slice(0, -1), { ...last, content: last.content + delta }];
  }
  return [...blocks, { kind: "assistant", content: delta, streaming: true }];
}

/** 收尾最后一个流式块（tool.start / turn.done / turn.error 前调用）。 */
function seal(blocks: Block[]): Block[] {
  const last = blocks[blocks.length - 1];
  if (last && last.kind === "assistant" && last.streaming) {
    return [...blocks.slice(0, -1), { ...last, streaming: false }];
  }
  return blocks;
}

export function chatReducer(state: ChatState, msg: ServerMsg | LocalMsg): ChatState {
  if (msg.type === "__local.busy") {
    return { ...state, busy: msg.busy };
  }
  if (msg.type === "__local.connected") {
    return { ...state, connected: msg.connected };
  }
  switch (msg.type) {
    case "session.info":
      return { ...state, connected: true, sessionId: msg.session_id };
    case "history":
      return { ...state, blocks: msg.blocks, busy: false, sessionId: msg.session_id };
    case "history.append":
      return { ...state, blocks: [...state.blocks, msg.block] };
    case "text.delta":
      return { ...state, blocks: pushDelta(state.blocks, msg.delta) };
    case "tool.start":
      return {
        ...state,
        blocks: [...seal(state.blocks),
                 { kind: "tool", name: msg.name, args: msg.args, state: "running" }],
      };
    case "tool.end": {
      // 配对策略：最近一个同名 running 工具块（与 TUI 顺序语义一致）
      const blocks = seal(state.blocks);
      for (let i = blocks.length - 1; i >= 0; i--) {
        const b = blocks[i];
        if (b.kind === "tool" && b.name === msg.name && b.state === "running") {
          const done: Block = { ...b, state: "done", result: msg.result, isError: msg.is_error };
          return { ...state, blocks: [...blocks.slice(0, i), done, ...blocks.slice(i + 1)] };
        }
      }
      return { ...state, blocks: [...blocks,
        { kind: "tool", name: msg.name, args: "", state: "done", result: msg.result, isError: msg.is_error }] };
    }
    case "approval.request":
      return {
        ...state,
        blocks: [...seal(state.blocks),
                 { kind: "approval", requestId: msg.request_id, toolName: msg.tool_name,
                   toolArgs: msg.tool_args, reason: msg.reason, state: "pending" }],
      };
    case "approval.resolved":
      return {
        ...state,
        blocks: state.blocks.map((b) =>
          b.kind === "approval" && b.requestId === msg.request_id
            ? { ...b, state: "resolved", outcome: msg.outcome }
            : b),
      };
    case "usage":
      return { ...state, inputTokens: msg.input_tokens, outputTokens: msg.output_tokens };
    case "iter":
      return { ...state, iter: msg.value };
    case "notice":
      return { ...state, blocks: [...state.blocks, { kind: "notice", text: msg.text, tone: "info" }] };
    case "compact":
      return {
        ...state,
        blocks: [...state.blocks, {
          kind: "notice", tone: "info",
          text: msg.error ? `上下文压缩失败: ${msg.error}`
                           : `上下文压缩 ${msg.phase}: ${msg.before} → ${msg.after} tokens`,
        }],
      };
    case "turn.error":
      return {
        ...state, busy: false,
        blocks: [...seal(state.blocks), { kind: "notice", text: msg.message, tone: "error" }],
      };
    case "turn.done":
      return { ...state, busy: false, blocks: seal(state.blocks) };
    default:
      return state;
  }
}
