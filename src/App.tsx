import Dashboard from "@/components/Dashboard";
import PetWindow from "@/components/PetWindow";
import StageWindow from "@/components/StageWindow";
import BackendGuard from "@/components/BackendGuard";
import { ZoomInitializer } from "@/lib/zoom";

function App() {
  // 检测路径：Tauri 桌宠窗口走 /pet，多角色舞台走 /stage
  const path = window.location.pathname;
  // 界面缩放：每个窗口都要应用（zoom 存 localStorage，同源跨窗口共享）
  if (path === "/pet") return <><ZoomInitializer /><PetWindow /></>;
  if (path === "/stage") return <><ZoomInitializer /><StageWindow /></>;
  return (
    <BackendGuard>
      <ZoomInitializer />
      <Dashboard />
    </BackendGuard>
  );
}

export default App;
