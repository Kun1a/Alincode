import { describe, expect, it, vi } from "vitest";
import { chatReducer, initialChatState } from "./chatReducer";

describe("chatReducer", () => {
  it("retains the environment supplied by session.info", () => {
    const state = chatReducer(initialChatState, {
      type: "session.info",
      session_id: "session-a",
      workspace: "E:\\Projects\\demo",
      model: "deepseek-chat",
      mode: "desktop",
    });

    expect(state).toMatchObject({
      connected: true,
      sessionId: "session-a",
      workspace: "E:\\Projects\\demo",
      model: "deepseek-chat",
      mode: "desktop",
    });
  });

  it("records a visible duration for a completed tool", () => {
    const now = vi.spyOn(Date, "now").mockReturnValueOnce(100).mockReturnValueOnce(250);
    const started = chatReducer(initialChatState, { type: "tool.start", name: "read_file", args: "{}" });
    const finished = chatReducer(started, { type: "tool.end", name: "read_file", result: "ok", is_error: false });
    const tool = finished.blocks[0];

    expect(tool).toMatchObject({ kind: "tool", startedAt: 100, durationMs: 150 });
    now.mockRestore();
  });

  it("uses the server-measured duration when it is available", () => {
    const started = chatReducer(initialChatState, { type: "tool.start", name: "read_file", args: "{}" });
    const finished = chatReducer(started, {
      type: "tool.end", name: "read_file", result: "ok", is_error: false, duration_ms: 420,
    });

    expect(finished.blocks[0]).toMatchObject({ kind: "tool", durationMs: 420 });
  });
});
