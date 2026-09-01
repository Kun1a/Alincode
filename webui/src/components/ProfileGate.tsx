import { FormEvent, useEffect, useState } from "react";

export interface Profile {
  id: string;
  name: string;
}

interface Props {
  onReady: (profile: Profile | null) => void;
}

type Screen = "loading" | "list" | "create" | "unlock" | "error";

async function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
}

export function ProfileGate({ onReady }: Props) {
  const [screen, setScreen] = useState<Screen>("loading");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selected, setSelected] = useState<Profile | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const loadProfiles = async () => {
    const response = await request("/api/profiles");
    if (response.status === 404) {
      onReady(null); // 保留 --web 调试入口的无 Profile 语义。
      return;
    }
    if (!response.ok) {
      throw new Error("本机登录状态无效，请从 AlinCode 桌面端重新打开。");
    }
    const data = await response.json() as Profile[];
    setProfiles(data);
    setScreen(data.length ? "list" : "create");
  };

  useEffect(() => {
    const boot = async () => {
      try {
        const token = new URLSearchParams(location.search).get("token");
        if (token) {
          const response = await request("/api/auth/exchange", {
            method: "POST", body: JSON.stringify({ token }),
          });
          if (!response.ok) throw new Error("本机启动令牌无效，请重新启动 AlinCode。");
          history.replaceState({}, "", location.pathname);
        }
        await loadProfiles();
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "无法加载本机 Profile。");
        setScreen("error");
      }
    };
    void boot();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const creating = screen === "create";
      const path = creating ? "/api/profiles" : `/api/profiles/${selected?.id}/unlock`;
      const body = creating ? { name, password } : { password };
      const response = await request(path, { method: "POST", body: JSON.stringify(body) });
      if (!response.ok) {
        const data = await response.json() as { detail?: string };
        throw new Error(data.detail || "无法解锁 Profile。");
      }
      onReady(await response.json() as Profile);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败，请重试。");
    } finally {
      setSaving(false);
      setPassword("");
    }
  };

  if (screen === "loading") {
    return <main className="profile-gate loading">正在准备本机工作区…</main>;
  }
  if (screen === "error") {
    return <main className="profile-gate"><section className="gate-card"><p className="gate-error">{error}</p></section></main>;
  }

  return (
    <main className="profile-gate">
      <section className="gate-card">
        <header className="gate-brand">
          <img src="/alincode-a-mark.png" alt="AlinCode" />
          <div><strong>AlinCode</strong><span>你的本地 Coding Agent</span></div>
        </header>

        {screen === "list" ? <>
          <h1>选择你的工作区</h1>
          <p className="gate-copy">对话、额度和 API 配置仅保存在这台设备。</p>
          <div className="profile-list">
            {profiles.map((profile) => <button key={profile.id} className="profile-choice" onClick={() => {
              setSelected(profile); setError(""); setScreen("unlock");
            }}>{profile.name}<span>解锁并继续</span></button>)}
          </div>
          <button className="text-button" onClick={() => { setError(""); setScreen("create"); }}>创建新的 Profile</button>
        </> : <form onSubmit={submit}>
          <button type="button" className="back-button" onClick={() => {
            setError(""); setPassword(""); setScreen(profiles.length ? "list" : "create");
          }}>{profiles.length ? "← 返回 Profile 列表" : ""}</button>
          <h1>{screen === "create" ? "创建本机 Profile" : `解锁 ${selected?.name}`}</h1>
          <p className="gate-copy">{screen === "create" ? "设置一个本机密码，用于保护此设备上的 API Key。" : "输入本机密码以继续使用独立的对话与配置。"}</p>
          {screen === "create" ? <label>名称<input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：Alin" /></label> : null}
          <label>密码<input autoFocus={screen === "unlock"} type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="不会保存到浏览器" /></label>
          {error ? <p className="gate-error">{error}</p> : null}
          <button className="primary-button" disabled={saving}>{saving ? "正在处理…" : screen === "create" ? "创建并进入" : "解锁"}</button>
        </form>}
      </section>
    </main>
  );
}
