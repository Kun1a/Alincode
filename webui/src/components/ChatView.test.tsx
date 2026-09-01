import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChatView } from "./ChatView";
import { ChatProvider } from "../state/ChatContext";

describe("ChatView", () => {
  it("shows the read-only environment panel for an unlocked Profile", () => {
    const html = renderToStaticMarkup(
      <ChatProvider>
        <ChatView profile={{ id: "profile-a", name: "Alin" }} onLock={() => undefined} />
      </ChatProvider>,
    );

    expect(html).toContain("当前环境");
  });

  it("shows the product brand and the unlocked Profile in the sidebar", () => {
    const html = renderToStaticMarkup(
      <ChatProvider>
        <ChatView profile={{ id: "profile-a", name: "Alin" }} onLock={() => undefined} />
      </ChatProvider>,
    );

    expect(html).toContain("AlinCode");
    expect(html).toContain("你的本地 Coding Agent");
    expect(html).toContain("仅保存在这台设备");
  });
});
