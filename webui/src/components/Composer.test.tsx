import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Composer } from "./Composer";
import { ChatProvider } from "../state/ChatContext";

describe("Composer", () => {
  it("offers one native file-picker entry", () => {
    const html = renderToStaticMarkup(<ChatProvider><Composer /></ChatProvider>);

    expect(html).toContain('aria-label="添加文件"');
  });
});
