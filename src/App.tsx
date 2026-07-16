import Dashboard from "@/components/Dashboard";
import PetWindow from "@/components/PetWindow";

function App() {
  // 检测路径：Tauri 桌宠窗口走 /pet
  const isPet = window.location.pathname === "/pet";
  return isPet ? <PetWindow /> : <Dashboard />;
}

export default App;
