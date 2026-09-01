import { describe, expect, it } from "vitest";
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
});
