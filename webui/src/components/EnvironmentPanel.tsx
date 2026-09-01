import { useEffect, useState } from "react";
import { useChat } from "../state/ChatContext";

interface ProviderSummary {
  protocol: string;
  model: string;
}

function protocolLabel(protocol: string | undefined): string {
  if (protocol === "anthropic") return "Anthropic 兼容";
  if (protocol === "openai") return "OpenAI 兼容";
  return "未配置";
}

export function EnvironmentPanel() {
  const { state } = useChat();
  const [provider, setProvider] = useState<ProviderSummary | null>(null);

  useEffect(function loadProviderSummary() {
    let ignore = false;

    async function requestProviderSummary() {
      try {
        const response = await fetch("/api/profile/provider");
        if (!response.ok) return;
        const data = await response.json() as Partial<ProviderSummary>;
        if (!ignore && typeof data.protocol === "string" && typeof data.model === "string") {
          setProvider({ protocol: data.protocol, model: data.model });
        }
      } catch {
        // 设置尚未保存或本机服务不可用时，保留可理解的空状态。
      }
    }

    void requestProviderSummary();
    return function ignoreStaleProviderResponse() { ignore = true; };
  }, []);

  const model = state.model || provider?.model || "未配置模型";
  const workspace = state.workspace || "尚未选择项目目录";
  const hasBudget = state.budget > 0;
  const budgetRatio = hasBudget ? Math.min(100, Math.round(state.usedTokens / state.budget * 100)) : 0;

  return (
    <aside className="environment-panel" aria-label="当前环境">
      <header className="environment-heading"><h2>当前环境</h2><span>本地</span></header>
      <section className="environment-card">
        <p className="environment-label">会话</p>
        <dl>
          <div><dt>连接</dt><dd>{state.connected ? "已连接" : "未连接"}</dd></div>
          <div><dt>模型</dt><dd>{model}</dd></div>
          <div><dt>协议</dt><dd>{protocolLabel(provider?.protocol)}</dd></div>
        </dl>
      </section>
      <section className="environment-card">
        <p className="environment-label">工作目录</p>
        <p className="environment-workspace" title={workspace}>{workspace}</p>
      </section>
      <section className="environment-card">
        <p className="environment-label">本地额度</p>
        <p className="environment-usage"><strong>{state.usedTokens.toLocaleString()}</strong> tokens</p>
        {hasBudget ? <><div className="environment-progress" aria-label={`本地预算已使用 ${budgetRatio}%`}><span style={{ width: `${budgetRatio}%` }} /></div><p className="environment-note">预算 {state.budget.toLocaleString()} tokens</p></> : <p className="environment-note">未设置上限</p>}
      </section>
    </aside>
  );
}
