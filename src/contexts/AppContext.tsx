import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { apiGet } from "@/lib/api";

export interface ProviderConfig {
  api_key: string;
  api_url: string;
  model: string;
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
      .catch(() => setLoaded(true));
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
