use tauri::Manager;
use tauri_plugin_shell::ShellExt;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // 启动 Python 桌面后端
            let sidecar_dir = app
                .path()
                .resource_dir()
                .unwrap_or_else(|_| std::path::PathBuf::from("."))
                .join("sidecar");
            let script_path = sidecar_dir.join("naixi_api.py");

            // 开发模式：使用项目目录
            let script = if cfg!(debug_assertions) {
                std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("sidecar")
                    .join("naixi_api.py")
            } else {
                script_path
            };

            if script.exists() {
                let shell = app.shell();
                // Python 解释器解析：环境变量 NAIXI_PYTHON_PATH 优先，否则回退系统 PATH 中的 python
                // 不硬编码任何用户专属绝对路径，保证换机/换用户仍可启动
                let python_path = std::env::var("NAIXI_PYTHON_PATH")
                    .unwrap_or_else(|_| "python".to_string());
                match shell.command(python_path)
                    .arg(script.to_string_lossy().to_string())
                    .spawn()
                {
                    Ok((_rx, _child)) => {
                        // _child 由 Tauri 管理生命周期
                    }
                    Err(e) => {
                        eprintln!("桌面后端启动失败: {}", e);
                    }
                }
            } else {
                eprintln!("桌面后端脚本不存在: {:?}", script);
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
