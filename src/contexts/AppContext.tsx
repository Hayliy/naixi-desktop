import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { apiGet } from "@/lib/api";

export interface ProviderConfig {
  api_key: string;
  api_url: string;
  model: string;
  type?: string; // 服务能力类型：chat/vision/image/video/audio/embedding
}

export interface AppConfig {
  api_providers: Record<string, ProviderConfig>;
  platform_configs: Record<string, any>;
}

interface AppContextType {
  config: AppConfig;
  loaded: boolean;
  refreshConfig: () => void;
}

const defaultConfig: AppConfig = {
  api_providers: {},
  platform_configs: {},
};

const AppContext = createContext<AppContextType>({
  config: defaultConfig,
  loaded: false,
  refreshConfig: () => {},
});

export function AppProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig>(defaultConfig);
  const [loaded, setLoaded] = useState(false);

  const refreshConfig = () => {
    apiGet<AppConfig>("/api/desktop/config")
      .then((d) => {
        if (d?.api_providers) setConfig(d);
        setLoaded(true);
      })
      .catch(() => {
        // 启动竞态：app 启动早于后端监听时首次请求会失败。
        // 此前这里直接 setLoaded(true) 吞掉错误且不再重试，导致设置页供应商列表恒空（直到重启才恢复）。
        // 改为指数退避重试，最多 5 次。
        setLoaded(true);
        const retry = (attempt: number) => {
          if (attempt > 5) return;
          const delay = Math.min(1000 * 2 ** (attempt - 1), 15000);
          setTimeout(() => {
            apiGet<AppConfig>("/api/desktop/config")
              .then((d2) => {
                if (d2?.api_providers) setConfig(d2);
              })
              .catch(() => retry(attempt + 1));
          }, delay);
        };
        retry(1);
      });
  };

  useEffect(() => {
    refreshConfig();
  }, []);

  return (
    <AppContext.Provider value={{ config, loaded, refreshConfig }}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppConfig() {
  return useContext(AppContext);
}
