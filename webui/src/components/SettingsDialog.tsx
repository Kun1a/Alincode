import { FormEvent, useEffect, useState } from "react";

interface Props { onClose: () => void; onLock: () => void; }
type Provider = { protocol: string; model: string; base_url: string; api_key: string };

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
  const [workspace, setWorkspace] = useState("");
  const [budget, setBudget] = useState("0");
  const [message, setMessage] = useState("");

  useEffect(() => { void Promise.all([
    fetch("/api/profile/provider").then(async r => r.ok ? r.json() as Promise<Provider> : null),
    json("/api/profile/workspace") as Promise<{ path: string }>,
    json("/api/profile/budget") as Promise<{ budget: number }>,
  ]).then(([saved, directory, usage]) => {
    if (saved) setProvider({ ...saved, api_key: "" });
    setWorkspace(directory.path); setBudget(String(usage.budget));
  }).catch(error => setMessage(error instanceof Error ? error.message : "无法读取设置")); }, []);

  const save = async (event: FormEvent) => {
    event.preventDefault(); setMessage("");
    try {
      await json("/api/profile/provider", { method: "PUT", body: JSON.stringify(provider) });
      await json("/api/profile/workspace", { method: "PUT", body: JSON.stringify({ path: workspace }) });
      await json("/api/profile/budget", { method: "PUT", body: JSON.stringify({ budget: Number(budget) }) });
      setProvider(current => ({ ...current, api_key: "" }));
      location.reload(); // Provider 与工作目录变更后创建新的 Profile 专属 Agent 上下文。
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
  };

  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
    <form className="settings-dialog" onSubmit={save} onMouseDown={event => event.stopPropagation()}>
      <header><div><strong>设置</strong><span>仅保存在这台设备</span></div><button type="button" onClick={onClose}>关闭</button></header>
      <label>协议<select value={provider.protocol} onChange={e => setProvider({ ...provider, protocol: e.target.value })}><option value="openai">OpenAI 兼容</option><option value="anthropic">Anthropic</option></select></label>
      <label>Base URL<input value={provider.base_url} onChange={e => setProvider({ ...provider, base_url: e.target.value })} placeholder="https://api.example.com" /></label>
      <label>模型<input value={provider.model} onChange={e => setProvider({ ...provider, model: e.target.value })} placeholder="deepseek-chat" /></label>
      <label>API Key<input type="password" value={provider.api_key} onChange={e => setProvider({ ...provider, api_key: e.target.value })} placeholder="保存时输入；不会显示或保存在浏览器" /></label>
      <label>项目目录<input value={workspace} onChange={e => setWorkspace(e.target.value)} placeholder="E:\\Projects\\example" /></label>
      <label>本地 token 预算（0 为不限）<input type="number" min="0" value={budget} onChange={e => setBudget(e.target.value)} /></label>
      {message ? <p className="settings-message">{message}</p> : null}
      <footer><button type="button" className="text-button" onClick={onLock}>锁定 Profile</button><button className="primary-button">保存设置</button></footer>
    </form>
  </div>;
}
