import { FormEvent, useEffect, useState } from "react";

type McpServer = { type: "stdio"; command: string; args: string[] } | { type: "http"; url: string };
type Skill = { name: string; description: string; source: string };
interface Props { onClose: () => void; }

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  const body = await response.json() as T & { detail?: string };
  if (!response.ok) throw new Error(body.detail || "请求失败");
  return body;
}

function McpForm({ servers, onSaved, onClose }: { servers: Record<string, McpServer>; onSaved: () => void; onClose: () => void }) {
  const [name, setName] = useState("");
  const [type, setType] = useState<"stdio" | "http">("stdio");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [message, setMessage] = useState("");
  const save = async (event: FormEvent) => {
    event.preventDefault();
    const server = type === "stdio" ? { type, command: command.trim(), args: args.split(/\s+/).filter(Boolean) } : { type, url: url.trim() };
    try {
      await json("/api/profile/mcp", { method: "PUT", body: JSON.stringify({ servers: { ...servers, [name.trim()]: server } }) });
      onSaved(); onClose();
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存 MCP 失败"); }
  };
  return <div className="modal-backdrop nested-modal" role="presentation" onMouseDown={onClose}>
    <form className="settings-dialog mcp-form" onSubmit={save} onMouseDown={event => event.stopPropagation()}>
      <header><div><strong>添加 MCP Server</strong><span>保存后在下一次新对话中加载</span></div><button type="button" onClick={onClose}>关闭</button></header>
      <label>名称<input required value={name} onChange={event => setName(event.target.value)} placeholder="filesystem" /></label>
      <label>类型<select value={type} onChange={event => setType(event.target.value as "stdio" | "http")}><option value="stdio">stdio</option><option value="http">HTTP</option></select></label>
      {type === "stdio" ? <><label>启动命令<input required value={command} onChange={event => setCommand(event.target.value)} placeholder="npx" /></label><label>参数（空格分隔）<input value={args} onChange={event => setArgs(event.target.value)} placeholder="-y @modelcontextprotocol/server-filesystem" /></label></> : <label>MCP URL<input required value={url} onChange={event => setUrl(event.target.value)} placeholder="https://example.com/mcp" /></label>}
      {message ? <p className="settings-message">{message}</p> : null}
      <footer><span /><button className="primary-button compact-primary">保存 MCP</button></footer>
    </form>
  </div>;
}

export function PluginsDialog({ onClose }: Props) {
  const [servers, setServers] = useState<Record<string, McpServer>>({});
  const [skills, setSkills] = useState<Skill[]>([]);
  const [message, setMessage] = useState("");
  const [addingMcp, setAddingMcp] = useState(false);
  const load = () => void Promise.all([json<{ servers: Record<string, McpServer> }>("/api/profile/mcp"), json<Skill[]>("/api/profile/skills")])
    .then(([mcp, loadedSkills]) => { setServers(mcp.servers); setSkills(loadedSkills); })
    .catch(error => setMessage(error instanceof Error ? error.message : "无法读取插件"));
  useEffect(load, []);

  const removeMcp = async (name: string) => {
    const next = { ...servers };
    delete next[name];
    try { await json("/api/profile/mcp", { method: "PUT", body: JSON.stringify({ servers: next }) }); setServers(next); }
    catch (error) { setMessage(error instanceof Error ? error.message : "删除 MCP 失败"); }
  };
  const openSkillDirectory = async () => {
    try { await json("/api/profile/open-skill-directory", { method: "POST" }); load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "无法打开 Skill 目录"); }
  };

  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="settings-dialog plugins-dialog" role="dialog" aria-modal="true" aria-label="插件" onMouseDown={event => event.stopPropagation()}>
      <header><div><strong>插件</strong><span>每个项目的 MCP 与 Skill 配置</span></div><button onClick={onClose}>关闭</button></header>
      <section className="plugin-section"><div className="plugin-heading"><div><strong>MCP Server</strong><span>保存后在下一次新对话中加载</span></div><button onClick={() => setAddingMcp(true)}>＋ 添加 MCP</button></div>
        {Object.entries(servers).length ? <div className="workspace-list">{Object.entries(servers).map(([name, server]) => <div key={name}><span><b>{name}</b> · {server.type === "stdio" ? `${server.command} ${server.args.join(" ")}` : server.url}</span><button onClick={() => void removeMcp(name)}>移除</button></div>)}</div> : <p className="settings-hint">还没有配置 MCP Server。</p>}
      </section>
      <section className="plugin-section"><div className="plugin-heading"><div><strong>Skills</strong><span>项目级 Skill 会在每轮对话前自动扫描</span></div><button onClick={() => void openSkillDirectory()}>＋ 添加 Skill</button></div>
        {skills.length ? <div className="workspace-list">{skills.map(skill => <div key={skill.name}><span><b>{skill.name}</b> · {skill.description}（{skill.source}）</span></div>)}</div> : <p className="settings-hint">未发现 Skill。点击“添加 Skill”打开 <code>.Alincode/skills</code> 目录后，新建 <code>&lt;名称&gt;/SKILL.md</code>。</p>}
      </section>
      {message ? <p className="settings-message">{message}</p> : null}
    </section>
    {addingMcp ? <McpForm servers={servers} onSaved={load} onClose={() => setAddingMcp(false)} /> : null}
  </div>;
}
