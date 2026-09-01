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
});
