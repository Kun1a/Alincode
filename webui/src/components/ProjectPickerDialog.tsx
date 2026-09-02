import { useEffect, useState } from "react";

type Workspaces = { paths: string[]; active_path: string };

interface Props { onClose: () => void; onStart: (workspace: string) => void; }

async function readJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  const body = await response.json() as T & { detail?: string };
  if (!response.ok) throw new Error(body.detail || "请求失败");
  return body;
}

export function ProjectPickerDialog({ onClose, onStart }: Props) {
  const [workspaces, setWorkspaces] = useState<Workspaces>({ paths: [], active_path: "" });
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");

  useEffect(function loadWorkspaces() {
    void readJson<Workspaces>("/api/profile/workspaces")
      .then(data => { setWorkspaces(data); setSelected(data.active_path); })
      .catch(error => setMessage(error instanceof Error ? error.message : "无法读取项目目录"));
  }, []);

  const pickFolder = async () => {
    setMessage("");
    try {
      const { path } = await readJson<{ path: string }>("/api/profile/pick-folder", { method: "POST" });
      if (!path) return;
      setWorkspaces(current => ({ ...current, paths: current.paths.includes(path) ? current.paths : [...current.paths, path] }));
      setSelected(path);
    } catch (error) { setMessage(error instanceof Error ? error.message : "无法打开文件夹选择器"); }
  };

  const start = async () => {
    if (!selected) { setMessage("请选择一个项目目录"); return; }
    setMessage("");
    try {
      const paths = workspaces.paths.includes(selected) ? workspaces.paths : [...workspaces.paths, selected];
      await readJson<Workspaces>("/api/profile/workspaces", {
        method: "PUT", body: JSON.stringify({ paths, active_path: selected }),
      });
      onStart(selected);
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存项目目录失败"); }
  };

  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="settings-dialog project-picker" role="dialog" aria-modal="true" aria-label="选择项目目录" onMouseDown={event => event.stopPropagation()}>
      <header><div><strong>选择项目目录</strong><span>新对话会在所选目录中运行工具与加载项目配置</span></div><button onClick={onClose}>关闭</button></header>
      <div className="project-options">
        {workspaces.paths.map(path => <button key={path} className={selected === path ? "project-option active" : "project-option"} onClick={() => setSelected(path)}><span>▣</span>{path}</button>)}
        {workspaces.paths.length === 0 ? <p className="settings-hint">尚未添加项目目录。</p> : null}
      </div>
      <button className="folder-button" onClick={pickFolder}>⌁ 打开文件夹</button>
      {message ? <p className="settings-message">{message}</p> : null}
      <footer><span className="settings-hint">选择后将作为当前项目保存</span><button className="primary-button compact-primary" onClick={start}>开始新对话</button></footer>
    </section>
  </div>;
}
