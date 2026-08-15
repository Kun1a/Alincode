// webui/src/lib/protocol.ts
// 与后端 Alincode/web/protocol.py + session.py 的消息契约逐字对应。

export type Block =
  | { kind: "user"; content: string }
  | { kind: "assistant"; content: string; streaming?: boolean }
  | { kind: "tool"; name: string; args: string; state: "running" | "done"; result?: string; isError?: boolean }
  | { kind: "approval"; requestId: string; toolName: string; toolArgs: string; reason: string; state: "pending" | "resolved"; outcome?: string }
  | { kind: "notice"; text: string; tone: "info" | "error" };

export type ServerMsg =
  | { type: "session.info"; session_id: string; workspace: string; model: string; mode: string }
  | { type: "history"; session_id: string; blocks: Block[] }
  | { type: "history.append"; block: Block }
  | { type: "text.delta"; delta: string }
  | { type: "tool.start"; name: string; args: string }
  | { type: "tool.end"; name: string; result: string; is_error: boolean }
  | { type: "approval.request"; request_id: string; tool_name: string; tool_args: string; reason: string }
  | { type: "approval.resolved"; request_id: string; outcome: string }
  | { type: "usage"; input_tokens: number; output_tokens: number; cache_write: number; cache_read: number }
  | { type: "iter"; value: number }
  | { type: "notice"; text: string }
  | { type: "compact"; phase: string; before: number; after: number; error: string }
  | { type: "turn.done" }
  | { type: "turn.error"; message: string };

export type ClientMsg =
  | { type: "chat.send"; text: string }
  | { type: "approval.respond"; request_id: string; outcome: "allow_once" | "allow_forever" | "deny_once" }
  | { type: "turn.cancel" }
  | { type: "session.resume"; session_id: string };
