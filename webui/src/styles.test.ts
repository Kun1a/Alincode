import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const stylesheet = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

describe("desktop chat stylesheet", () => {
  it("defines the approved deep-ocean three-column workspace", () => {
    expect(stylesheet).toContain("--chat-night: #07131e");
    expect(stylesheet).toContain("grid-template-columns: 268px minmax(500px, 1fr) 306px");
    expect(stylesheet).toContain("@media (max-width: 900px)");
  });

  it("keeps history rows compact instead of stretching them across the sidebar", () => {
    expect(stylesheet).toContain("align-content: start");
    expect(stylesheet).toContain("grid-auto-rows: min-content");
  });
});
