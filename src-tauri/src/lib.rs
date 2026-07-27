use tauri::Emitter;
use tauri::Manager;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri_plugin_shell::ShellExt;
use std::net::{TcpStream, ToSocketAddrs};
use std::sync::Mutex;
use std::time::Duration;
use std::env;

/// 后端 Python sidecar 进程 PID（托盘退出时用它杀掉整棵进程树，避免残留）
#[derive(Default)]
struct BackendPid(Mutex<Option<u32>>);

/// 彻底结束后端：按存下的 PID 杀掉 Python 子进程树（含 SearXNG 等子进程），
/// 解决关闭/退出后仍残留 python.exe 进程的问题（#3）。
fn kill_backend(app: &tauri::AppHandle) {
    let pid = app
        .state::<BackendPid>()
        .0
        .lock()
        .ok()
        .and_then(|g| *g);
    if let Some(pid) = pid {
        // /T 连同子进程树一起结束，/F 强制结束。
        // 用 spawn 非阻塞发起：taskkill 是独立进程，发起后本进程即可退出，
        // 由它在后台继续清理进程树，避免同步等待 taskkill 杀树导致托盘退出卡顿（#3）。
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .spawn();
    } else {
        // 兜底：PID 没存上（例如本次启动时端口已被上次残留占用而直接复用），
        // 按监听 9845 的进程再清一次，避免残留 python.exe。只杀监听该端口者，不误杀其它 python。
        if let Some(port_pid) = pid_listening_on(9845) {
            let _ = std::process::Command::new("taskkill")
                .args(["/F", "/T", "/PID", &port_pid.to_string()])
                .spawn();
        }
    }
}

/// 查找监听指定端口的进程 PID（Windows netstat 解析），用于退出时兜底清理残留后端
#[cfg(windows)]
fn pid_listening_on(port: u16) -> Option<u32> {
    let out = std::process::Command::new("netstat").args(["-ano"]).output().ok()?;
    let text = String::from_utf8_lossy(&out.stdout);
    let needle = format!(":{}", port);
    for line in text.lines() {
        if line.contains(&needle) && line.to_uppercase().contains("LISTENING") {
            if let Some(pid) = line.split_whitespace().last() {
                if let Ok(pid) = pid.trim().parse::<u32>() {
                    return Some(pid);
                }
            }
        }
    }
    None
}

#[cfg(not(windows))]
fn pid_listening_on(_port: u16) -> Option<u32> {
    None
}

/// 显示并聚焦主窗口（从托盘恢复）
fn show_main_window(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

/// 构建系统托盘：图标用应用自带图标，菜单含「显示主窗口 / 退出奶昔」，
/// 左键单击托盘也可唤回主窗口。解决关窗后无托盘图标、只能强制卸载的问题（#4）。
fn setup_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    let show_item = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "退出奶昔", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

    let mut builder = TrayIconBuilder::with_id("naixi-tray")
        .menu(&menu)
        .tooltip("奶昔 · 桌面智能体")
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_main_window(app),
            "quit" => {
                kill_backend(app);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendPid::default())
        .invoke_handler(tauri::generate_handler![start_backend, restart_backend])
        .setup(|app| {
            // 启动 Python 桌面后端；失败（如未检测到 Python）时通知前端显示提示，而非静默退出
            if let Err(e) = spawn_backend(app.handle()) {
                let _ = app.emit("backend-error", e.clone());
                eprintln!("桌面后端启动失败: {}", e);
            }
            // 创建系统托盘图标（关窗最小化到托盘后可从此处唤回或退出）
            if let Err(e) = setup_tray(app.handle()) {
                eprintln!("系统托盘创建失败: {}", e);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // 关闭主窗口时不退出进程，改为隐藏到托盘（保留后端与桌宠）；
            // 需要彻底退出请用托盘菜单「退出奶昔」。
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    let _ = window.hide();
                    api.prevent_close();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// 从可执行文件所在目录及其父目录、resources 子目录向上查找某个相对子路径。
/// 用于双击裸 exe（target/release/naixi-desktop.exe）或安装目录下，
/// 当 resource_dir() 解析不到 sidecar / python-embed 时的兜底，
/// 保证「双击 exe 即自启后端」在任意放置位置都能成立。
fn find_from_exe(sub: &[&str]) -> Option<std::path::PathBuf> {
    let exe = env::current_exe().ok()?;
    let exe_dir = exe.parent()?;
    let bases = [
        exe_dir.to_path_buf(),
        exe_dir
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| exe_dir.to_path_buf()),
        exe_dir.join("resources"),
        exe_dir
            .parent()
            .map(|p| p.join("resources"))
            .unwrap_or_else(|| exe_dir.join("resources")),
    ];
    for base in bases.iter() {
        let mut p = base.clone();
        for s in sub {
            p = p.join(s);
        }
        if p.exists() {
            return Some(p);
        }
    }
    None
}

/// 解析后端脚本路径（开发模式用项目目录，打包后用资源目录，并兜底 exe 所在目录）
fn backend_script(app: &tauri::AppHandle) -> std::path::PathBuf {
    if cfg!(debug_assertions) {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("sidecar")
            .join("naixi_api.py")
    } else {
        // 优先资源目录（单层/双层 resources 都试），其次从 exe 所在目录向上查找。
        // 这样无论双击 target/release 下的裸 exe，还是 NSIS 安装目录，都能定位到 sidecar 脚本。
        let res = app
            .path()
            .resource_dir()
            .unwrap_or_else(|_| std::path::PathBuf::from("."));
        let candidates = [
            res.join("sidecar").join("naixi_api.py"),
            res.join("resources").join("sidecar").join("naixi_api.py"),
        ];
        for c in candidates.iter() {
            if c.exists() {
                return c.clone();
            }
        }
        if let Some(p) = find_from_exe(&["sidecar", "naixi_api.py"]) {
            return p;
        }
        // 最终回退（若仍不存在，由调用方报中文错误）
        res.join("sidecar").join("naixi_api.py")
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
/// 3. 再从 exe 所在目录向上查找嵌入式 Python（双击裸 exe 兜底）
/// 4. 回退系统 PATH 中的 python
/// 不硬编码任何用户专属绝对路径，保证换机/换用户仍可启动
fn resolve_python(app: &tauri::AppHandle) -> String {
    if let Ok(p) = std::env::var("NAIXI_PYTHON_PATH") {
        if !p.trim().is_empty() {
            return p;
        }
    }
    if !cfg!(debug_assertions) {
        let mut candidates: Vec<std::path::PathBuf> = Vec::new();
        if let Ok(rd) = app.path().resource_dir() {
            // 打包态资源可能落在单层 python-embed，也可能因源路径带
            // resources/ 前缀而落在双层 resources/resources/python-embed，两种都兜底查找，
            // 避免找不到嵌入式 Python 而回退系统 python 导致后端起不来、资源库为空。
            candidates.push(rd.join("python-embed").join("python.exe"));
            candidates.push(rd.join("resources").join("python-embed").join("python.exe"));
        }
        // 从 exe 所在目录向上查找（双击裸 exe / 安装目录兜底）
        if let Some(p) = find_from_exe(&["python-embed", "python.exe"]) {
            candidates.push(p);
        }
        if let Some(p) = find_from_exe(&["resources", "python-embed", "python.exe"]) {
            candidates.push(p);
        }
        for embed in candidates.iter() {
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
        Ok((_rx, child)) => {
            // 记录 Python 子进程 PID，供退出时杀进程树用（解决残留进程 #3）
            if let Some(state) = app.try_state::<BackendPid>() {
                if let Ok(mut g) = state.0.lock() {
                    *g = Some(child.pid());
                }
            }
            Ok(())
        }
        Err(e) => Err(format!("后端进程启动失败: {}", e)),
    }
}

/// 供前端「启动后端」按钮调用（仅在后端未运行时拉起，避免重复）
#[tauri::command]
fn start_backend(app: tauri::AppHandle) -> Result<(), String> {
    spawn_backend(&app)
}

/// 供前端「重启后端」按钮调用：先彻底结束旧进程并确认端口释放，再重新拉起。
/// 解决旧逻辑「后端卡死/死透时，仅 spawn 会因端口占用检查而跳过、导致重启无效」的问题。
#[tauri::command]
fn restart_backend(app: tauri::AppHandle) -> Result<(), String> {
    // 1. 确定当前后端 PID（优先 state 中记录的子进程 PID，否则回退到监听 9845 的进程）
    let pid = {
        let g = app.state::<BackendPid>().0.lock().ok().and_then(|g| *g);
        g.or_else(|| pid_listening_on(9845))
    };
    // 2. 强制结束整个进程树（同步等待 taskkill 完成，确保旧进程被清掉）
    if let Some(pid) = pid {
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .status();
    } else if let Some(port_pid) = pid_listening_on(9845) {
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/T", "/PID", &port_pid.to_string()])
            .status();
    }
    // 3. 阻塞等待端口真正释放（最多约 5 秒），避免 spawn_backend 的端口占用检查误判而跳过拉起
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    while std::time::Instant::now() < deadline {
        if !port_in_use("127.0.0.1:9845") {
            break;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    // 4. 重新拉起后端
    spawn_backend(&app)
}
