use tauri::Emitter;
use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![start_backend])
        .setup(|app| {
            // 启动 Python 桌面后端；失败（如未检测到 Python）时通知前端显示提示，而非静默退出
            if let Err(e) = spawn_backend(app.handle()) {
                let _ = app.emit("backend-error", e.clone());
                eprintln!("桌面后端启动失败: {}", e);
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// 解析后端脚本路径（开发模式用项目目录，打包后用资源目录）
fn backend_script(app: &tauri::AppHandle) -> std::path::PathBuf {
    if cfg!(debug_assertions) {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("sidecar")
            .join("naixi_api.py")
    } else {
        app.path()
            .resource_dir()
            .unwrap_or_else(|_| std::path::PathBuf::from("."))
            .join("sidecar")
            .join("naixi_api.py")
    }
}

/// 端口是否已被占用（避免重复拉起导致僵尸进程）
fn port_in_use(addr: &str) -> bool {
    if let Ok(mut iter) = addr.to_socket_addrs() {
        if let Some(sa) = iter.next() {
            return TcpStream::connect_timeout(&sa, Duration::from_millis(300)).is_ok();
        }
    }
    false
}

/// 解析 Python 解释器路径：
/// 1. 环境变量 NAIXI_PYTHON_PATH 优先（调试/自定义）
/// 2. 打包后优先用自包含的嵌入式 Python（resources/python-embed/python.exe）
/// 3. 回退系统 PATH 中的 python
/// 不硬编码任何用户专属绝对路径，保证换机/换用户仍可启动
fn resolve_python(app: &tauri::AppHandle) -> String {
    if let Ok(p) = std::env::var("NAIXI_PYTHON_PATH") {
        if !p.trim().is_empty() {
            return p;
        }
    }
    if !cfg!(debug_assertions) {
        if let Ok(rd) = app.path().resource_dir() {
            let embed = rd.join("python-embed").join("python.exe");
            if embed.exists() {
                return embed.to_string_lossy().to_string();
            }
        }
    }
    "python".to_string()
}

/// 启动桌面后端：先预检 Python 解释器与端口占用，再拉起 sidecar。
/// 任何失败都返回中文错误信息，供前端展示。
fn spawn_backend(app: &tauri::AppHandle) -> Result<(), String> {
    let script = backend_script(app);
    if !script.exists() {
        return Err(format!("后端脚本不存在: {}", script.display()));
    }
    let python_path = resolve_python(app);
    // 预检：解释器是否可用
    match std::process::Command::new(&python_path).arg("--version").status() {
        Ok(_) => {}
        Err(_) => {
            return Err(
                "未检测到 Python 运行环境，请先安装 Python 3.10+，或在环境变量 NAIXI_PYTHON_PATH 中指定解释器路径"
                    .to_string(),
            );
        }
    }
    // 端口已占用说明后端已在运行，避免重复拉起
    if port_in_use("127.0.0.1:9845") {
        return Ok(());
    }
    let shell = app.shell();
    match shell
        .command(python_path)
        .arg(script.to_string_lossy().to_string())
        .spawn()
    {
        Ok((_rx, _child)) => Ok(()),
        Err(e) => Err(format!("后端进程启动失败: {}", e)),
    }
}

/// 供前端「重启后端」按钮调用
#[tauri::command]
fn start_backend(app: tauri::AppHandle) -> Result<(), String> {
    spawn_backend(&app)
}
