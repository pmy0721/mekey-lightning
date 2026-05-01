import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { FolderOpen, X } from "lucide-react";
import type { LLMSettings } from "../lib/types";

type Provider = "anthropic" | "siliconflow" | "openai-compatible";

interface Props {
  llmSettings: LLMSettings | null;
  onSaveLLM: (settings: {
    llm_provider: Provider;
    llm_base_url?: string;
    llm_model: string;
    anthropic_api_key?: string;
    openai_compatible_api_key?: string;
  }) => void;
  onClose: () => void;
}

const MODELS: Record<Provider, Array<{ value: string; label: string }>> = {
  siliconflow: [
    { value: "deepseek-ai/DeepSeek-V4-Flash", label: "DeepSeek V4 Flash" },
    { value: "deepseek-ai/DeepSeek-V3", label: "DeepSeek V3" },
    { value: "Qwen/Qwen2.5-72B-Instruct", label: "Qwen2.5 72B Instruct" },
  ],
  "openai-compatible": [
    { value: "deepseek-ai/DeepSeek-V4-Flash", label: "deepseek-ai/DeepSeek-V4-Flash" },
  ],
  anthropic: [
    { value: "claude-3-5-sonnet-latest", label: "Claude 3.5 Sonnet" },
    { value: "claude-3-5-haiku-latest", label: "Claude 3.5 Haiku" },
    { value: "claude-3-opus-latest", label: "Claude 3 Opus" },
  ],
};

const DEFAULT_BASE_URL: Record<Provider, string> = {
  siliconflow: "https://api.siliconflow.cn/v1",
  "openai-compatible": "https://api.siliconflow.cn/v1",
  anthropic: "",
};

export function SettingsDialog({ llmSettings, onSaveLLM, onClose }: Props) {
  const [vaultPath, setVaultPath] = useState("");
  const [provider, setProvider] = useState<Provider>("siliconflow");
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URL.siliconflow);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("deepseek-ai/DeepSeek-V4-Flash");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    invoke<string | null>("get_obsidian_vault_path").then((p) => {
      if (p) setVaultPath(p);
    });
  }, []);

  useEffect(() => {
    if (!llmSettings) return;
    setProvider(llmSettings.llm_provider);
    setBaseUrl(llmSettings.llm_base_url || DEFAULT_BASE_URL[llmSettings.llm_provider]);
    setModel(llmSettings.llm_model);
  }, [llmSettings]);

  const pickFolder = async () => {
    const selected = await open({
      directory: true,
      multiple: false,
      title: "选择 Obsidian 转录目录",
    });
    if (selected && typeof selected === "string") setVaultPath(selected);
  };

  const changeProvider = (next: Provider) => {
    setProvider(next);
    setBaseUrl(DEFAULT_BASE_URL[next]);
    setModel(MODELS[next][0].value);
    setApiKey("");
  };

  const hasKey = provider === "anthropic"
    ? llmSettings?.has_anthropic_api_key
    : llmSettings?.has_openai_compatible_api_key;

  const save = async () => {
    await invoke("set_obsidian_vault_path", { path: vaultPath });
    onSaveLLM({
      llm_provider: provider,
      llm_base_url: baseUrl.trim() || DEFAULT_BASE_URL[provider],
      llm_model: model,
      anthropic_api_key: provider === "anthropic" ? apiKey.trim() || undefined : undefined,
      openai_compatible_api_key: provider !== "anthropic" ? apiKey.trim() || undefined : undefined,
    });
    setApiKey("");
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-[600px] max-w-[90vw]">
        <header className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
          <h2 className="font-semibold text-zinc-900">设置</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-700">
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="p-5 space-y-5">
          <section>
            <label className="block text-sm font-medium text-zinc-700 mb-2">
              Obsidian Vault 路径
            </label>
            <div className="flex gap-2">
              <input
                value={vaultPath}
                onChange={(e) => setVaultPath(e.target.value)}
                placeholder="尚未配置"
                className="flex-1 px-3 py-2 border border-zinc-300 rounded-md text-sm outline-none focus:border-blue-500"
              />
              <button
                onClick={pickFolder}
                className="px-3 py-2 bg-zinc-100 hover:bg-zinc-200 rounded-md text-sm flex items-center gap-1.5"
              >
                <FolderOpen className="w-4 h-4" />
                浏览
              </button>
            </div>
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="block text-sm font-medium text-zinc-700">
                润色模型
              </label>
              <span className="text-xs text-zinc-500">
                {hasKey ? "API Key 已配置" : "API Key 未配置"}
              </span>
            </div>

            <select
              value={provider}
              onChange={(e) => changeProvider(e.target.value as Provider)}
              className="w-full px-3 py-2 border border-zinc-300 rounded-md text-sm outline-none focus:border-blue-500 bg-white"
            >
              <option value="siliconflow">硅基流动 / SiliconFlow</option>
              <option value="openai-compatible">OpenAI 兼容接口</option>
              <option value="anthropic">Anthropic Claude</option>
            </select>

            {provider !== "anthropic" && (
              <input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.siliconflow.cn/v1"
                className="w-full px-3 py-2 border border-zinc-300 rounded-md text-sm outline-none focus:border-blue-500"
              />
            )}

            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              list="llm-models"
              className="w-full px-3 py-2 border border-zinc-300 rounded-md text-sm outline-none focus:border-blue-500"
            />
            <datalist id="llm-models">
              {MODELS[provider].map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </datalist>

            <input
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              type="password"
              placeholder={hasKey ? "留空则继续使用已保存的 API Key" : "填入 API Key"}
              className="w-full px-3 py-2 border border-zinc-300 rounded-md text-sm outline-none focus:border-blue-500"
            />
          </section>
        </div>

        <footer className="px-5 py-3 border-t border-zinc-200 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-md text-sm text-zinc-700 hover:bg-zinc-100"
          >
            取消
          </button>
          <button
            onClick={save}
            className="px-4 py-1.5 rounded-md text-sm bg-zinc-900 hover:bg-zinc-800 text-white"
          >
            {saved ? "已保存" : "保存"}
          </button>
        </footer>
      </div>
    </div>
  );
}
