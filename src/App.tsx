import Dashboard from "@/components/Dashboard";
import PetWindow from "@/components/PetWindow";
import StageWindow from "@/components/StageWindow";
import BackendGuard from "@/components/BackendGuard";

function App() {
  // 检测路径：Tauri 桌宠窗口走 /pet，多角色舞台走 /stage
  const path = window.location.pathname;
  if (path === "/pet") return <PetWindow />;
  if (path === "/stage") return <StageWindow />;
  return (
    <BackendGuard>
      <Dashboard />
    </BackendGuard>
  );
}

export default App;
