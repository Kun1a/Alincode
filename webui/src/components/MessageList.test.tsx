import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MessageList } from "./MessageList";

describe("MessageList", () => {
  it("groups consecutive tools into one workflow card", () => {
    const html = renderToStaticMarkup(<MessageList blocks={[
      { kind: "tool", name: "read_file", args: "{}", state: "done", result: "text", isError: false, startedAt: 100, durationMs: 20 },
      { kind: "tool", name: "grep", args: "{}", state: "done", result: "match", isError: false, startedAt: 130, durationMs: 30 },
      { kind: "assistant", content: "已完成" },
    ]} />);

    expect(html).toContain("执行工作流");
    expect(html).toContain("read_file");
    expect(html).toContain("grep");
    expect(html).toContain("已完成");
  });

  it("shows the assistant label only once within a user turn", () => {
    const html = renderToStaticMarkup(<MessageList blocks={[
      { kind: "user", content: "请处理" },
      { kind: "assistant", content: "我先检查文件。" },
      { kind: "assistant", content: "检查完成。" },
    ]} />);

    expect(html.match(/AlinCode/g)).toHaveLength(1);
  });
});
