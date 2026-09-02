import { FormEvent, useEffect, useState } from "react";

interface Props { onClose: () => void; onLock: () => void; }
type Provider = { protocol: string; model: string; base_url: string; api_key: string };
type Workspaces = { paths: string[]; active_path: string };
type McpServer = { type: "stdio"; command: string; args: string[] } | { type: "http"; url: string };
type Skill = { name: string; description: string; source: string };

async function json(path: string, init?: RequestInit) {
  const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const body = await response.json() as { detail?: string };
    throw new Error(body.detail || "保存失败");
  }
  return response.json();
}

export function SettingsDialog({ onClose, onLock }: Props) {
  const [provider, setProvider] = useState<Provider>({ protocol: "openai", model: "", base_url: "", api_key: "" });
  const [workspaces, setWorkspaces] = useState<Workspaces>({ paths: [], active_path: "" });
  const [workspaceInput, setWorkspaceInput] = useState("");
  const [budget, setBudget] = useState("0");
  const [mcpServers, setMcpServers] = useState<Record<string, McpServer>>({});
  const [mcpName, setMcpName] = useState("");
  const [mcpType, setMcpType] = useState<"stdio" | "http">("stdio");
  const [mcpCommand, setMcpCommand] = useState("");
  const [mcpArgs, setMcpArgs] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => { void Promise.all([
    fetch("/api/profile/provider").then(async r => r.ok ? r.json() as Promise<Provider> : null),
    json("/api/profile/workspaces") as Promise<Workspaces>,
    json("/api/profile/budget") as Promise<{ budget: number }>,
    json("/api/profile/mcp") as Promise<{ servers: Record<string, McpServer> }>,
    fetch("/api/profile/skills").then(async r => r.ok ? r.json() as Promise<Skill[]> : []),
  ]).then(([saved, directory, usage, mcp, loadedSkills]) => {
    if (saved) setProvider({ ...saved, api_key: "" });
    setWorkspaces(directory); setWorkspaceInput(directory.active_path); setBudget(String(usage.budget)); setMcpServers(mcp.servers); setSkills(loadedSkills);
  }).catch(error => setMessage(error instanceof Error ? error.message : "无法读取设置")); }, []);

  const save = async (event: FormEvent) => {
    event.preventDefault(); setMessage("");
    try {
      await json("/api/profile/provider", { method: "PUT", body: JSON.stringify(provider) });
      await json("/api/profile/workspaces", { method: "PUT", body: JSON.stringify(workspaces) });
      await json("/api/profile/budget", { method: "PUT", body: JSON.stringify({ budget: Number(budget) }) });
      await json("/api/profile/mcp", { method: "PUT", body: JSON.stringify({ servers: mcpServers }) });
      setProvider(current => ({ ...current, api_key: "" }));
      location.reload(); // Provider 与工作目录变更后创建新的 Profile 专属 Agent 上下文。
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
  };

  const addWorkspace = () => {
    const path = workspaceInput.trim();
    if (!path) return;
    setWorkspaces(current => ({
      paths: current.paths.includes(path) ? current.paths : [...current.paths, path],
      active_path: current.active_path || path,
    }));
    setWorkspaceInput("");
  };

  const removeWorkspace = (path: string) => {
    setWorkspaces(current => {
      const paths = current.paths.filter(item => item !== path);
      return { paths, active_path: current.active_path === path ? (paths[0] || "") : current.active_path };
    });
  };

  const addMcpServer = () => {
    const name = mcpName.trim();
    if (!name) return;
    const server: McpServer = mcpType === "stdio"
      ? { type: "stdio", command: mcpCommand.trim(), args: mcpArgs.split(/\s+/).filter(Boolean) }
      : { type: "http", url: mcpUrl.trim() };
    setMcpServers(current => ({ ...current, [name]: server }));
    setMcpName(""); setMcpCommand(""); setMcpArgs(""); setMcpUrl("");
  };

  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
    <form className="settings-dialog" onSubmit={save} onMouseDown={event => event.stopPropagation()}>
      <header><div><strong>设置</strong><span>仅保存在这台设备</span></div><button type="button" onClick={onClose}>关闭</button></header>
      <label>协议<select value={provider.protocol} onChange={e => setProvider({ ...provider, protocol: e.target.value })}><option value="openai">OpenAI 兼容</option><option value="anthropic">Anthropic</option></select></label>
      <label>Base URL<input value={provider.base_url} onChange={e => setProvider({ ...provider, base_url: e.target.value })} placeholder="https://api.example.com" /></label>
      <label>模型<input value={provider.model} onChange={e => setProvider({ ...provider, model: e.target.value })} placeholder="deepseek-chat" /></label>
      <label>API Key<input type="password" value={provider.api_key} onChange={e => setProvider({ ...provider, api_key: e.target.value })} placeholder="保存时输入；不会显示或保存在浏览器" /></label>
      <label>当前项目目录<select value={workspaces.active_path} onChange={e => setWorkspaces(current => ({ ...current, active_path: e.target.value }))}>{workspaces.paths.length ? workspaces.paths.map(path => <option key={path} value={path}>{path}</option>) : <option value="">请添加项目目录</option>}</select></label>
      <label>添加项目目录<input value={workspaceInput} onChange={e => setWorkspaceInput(e.target.value)} placeholder="E:\\Projects\\example" /></label>
      <button type="button" onClick={addWorkspace}>加入项目列表</button>
      {workspaces.paths.length > 1 ? <div className="workspace-list">{workspaces.paths.map(path => <div key={path}><span>{path}</span><button type="button" onClick={() => removeWorkspace(path)}>移除</button></div>)}</div> : null}
      <label>MCP Server 名称<input value={mcpName} onChange={e => setMcpName(e.target.value)} placeholder="filesystem" /></label>
      <label>MCP 类型<select value={mcpType} onChange={e => setMcpType(e.target.value as "stdio" | "http")}><option value="stdio">stdio</option><option value="http">HTTP</option></select></label>
      {mcpType === "stdio" ? <><label>启动命令<input value={mcpCommand} onChange={e => setMcpCommand(e.target.value)} placeholder="npx" /></label><label>参数（空格分隔）<input value={mcpArgs} onChange={e => setMcpArgs(e.target.value)} placeholder="-y @modelcontextprotocol/server-filesystem" /></label></> : <label>MCP URL<input value={mcpUrl} onChange={e => setMcpUrl(e.target.value)} placeholder="https://example.com/mcp" /></label>}
      <button type="button" onClick={addMcpServer}>加入 MCP Server</button>
      {Object.keys(mcpServers).length ? <div className="workspace-list">{Object.entries(mcpServers).map(([name, server]) => <div key={name}><span>{name} · {server.type === "stdio" ? server.command : server.url}</span><button type="button" onClick={() => setMcpServers(current => { const next = { ...current }; delete next[name]; return next; })}>移除</button></div>)}</div> : null}
      <label>已发现 Skill<span className="settings-hint">项目级 Skill 放在 <code>.Alincode/skills/&lt;名称&gt;/SKILL.md</code>；下一轮对话会重新扫描。</span></label>
      {skills.length ? <div className="workspace-list">{skills.map(skill => <div key={skill.name}><span>{skill.name} · {skill.description}（{skill.source}）</span></div>)}</div> : <p className="settings-hint">当前项目没有可用 Skill。</p>}
      <label>本地 token 预算（0 为不限）<input type="number" min="0" value={budget} onChange={e => setBudget(e.target.value)} /></label>
      {message ? <p className="settings-message">{message}</p> : null}
      <footer><button type="button" className="text-button" onClick={onLock}>锁定 Profile</button><button className="primary-button">保存设置</button></footer>
    </form>
  </div>;
}
