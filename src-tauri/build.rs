use std::fs;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

/// 拷贝单文件，遇到 Windows Defender 实时防护的瞬时共享锁（os error 32/33）时重试。
/// Defender 在扫描 .pyd/.dll 时会短暂持有共享锁，导致 fs::copy 偶发 ERROR_SHARING_VIOLATION；
/// 重试若干次即可绕过（Defender 扫完即释放句柄）。
fn copy_with_retry(src: &Path, dst: &Path) -> std::io::Result<()> {
    let mut last_err = None;
    for attempt in 0..12 {
        match fs::copy(src, dst) {
            Ok(_) => return Ok(()),
            Err(e) => {
                let raw = e.raw_os_error().unwrap_or(0);
                if raw == 32 || raw == 33 {
                    // ERROR_SHARING_VIOLATION / ERROR_LOCK_VIOLATION：共享冲突，稍候重试
                    thread::sleep(Duration::from_millis(150 * (attempt + 1)));
                    last_err = Some(e);
                    continue;
                }
                return Err(e);
            }
        }
    }
    Err(last_err.unwrap_or_else(|| {
        std::io::Error::new(std::io::ErrorKind::Other, "copy retry exhausted (os error 32)")
    }))
}

/// 递归删除目录，遇到 Defender 瞬时锁（os error 32）时重试。
fn remove_dir_retry(dir: &Path) {
    if !dir.exists() {
        return;
    }
    for attempt in 0..12 {
        match fs::remove_dir_all(dir) {
            Ok(_) => return,
            Err(e) => {
                let raw = e.raw_os_error().unwrap_or(0);
                if raw == 32 || raw == 33 {
                    thread::sleep(Duration::from_millis(150 * (attempt + 1)));
                    continue;
                }
                eprintln!("warn: failed to remove {}: {e}", dir.display());
                return;
            }
        }
    }
    eprintln!("warn: failed to remove {} after retries (os error 32)", dir.display());
}

/// 递归拷贝目录，跳过 __pycache__ 与 *.pyc/*.bak/*.log（运行时不需要，且会随开发变大）。
fn sync_dir(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let path = entry.path();
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if path.is_dir() {
            if name_str == "__pycache__" || name_str == ".git" {
                continue;
            }
            sync_dir(&path, &dst.join(&name))?;
        } else {
            // 跳过不需要的运行时代码产物：缓存、备份、日志、调试产物。
            // 尤其 .bak：曾发现旧源码备份被打进安装包，既臃肿又可能含过时漏洞代码。
            if name_str.ends_with(".pyc")
                || name_str.ends_with(".bak")
                || name_str.ends_with(".log")
            {
                continue;
            }
            copy_with_retry(&path, &dst.join(&name))?;
        }
    }
    Ok(())
}

/// 预热读取：以只读方式逐个打开文件（带重试），逼 Windows Defender 在
/// tauri_build 枚举 resources/ 之前把这些新拷入的文件扫完，避免 tauri_build
/// 内部读文件时撞上 Defender 的瞬时共享锁（os error 32）。
fn warm_read_retry(dir: &Path) {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let entries = match fs::read_dir(&d) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
                continue;
            }
            for attempt in 0..12 {
                match fs::File::open(&p) {
                    Ok(mut f) => {
                        let mut buf = [0u8; 4096];
                        let _ = std::io::Read::read(&mut f, &mut buf);
                        break;
                    }
                    Err(e) => {
                        let raw = e.raw_os_error().unwrap_or(0);
                        if raw == 32 || raw == 33 {
                            thread::sleep(Duration::from_millis(150 * (attempt + 1)));
                            continue;
                        }
                        break;
                    }
                }
            }
        }
    }
}

/// 递归收集目录下所有待打包文件，返回 (相对 resources 的路径字符串, 字节大小)。
/// 跳过 __pycache__ 与 *.pyc/*.bak/*.log（与 sync_dir 一致）。
fn collect_pack_files(root: &Path, base: &Path, out: &mut Vec<(String, u64)>) {
    let entries = match fs::read_dir(root) {
        Ok(e) => e,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let p = entry.path();
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if p.is_dir() {
            if name_str == "__pycache__" || name_str == ".git" {
                continue;
            }
            collect_pack_files(&p, base, out);
        } else {
            if name_str.ends_with(".pyc")
                || name_str.ends_with(".bak")
                || name_str.ends_with(".log")
            {
                continue;
            }
            let rel = p
                .strip_prefix(base)
                .unwrap_or(&p)
                .to_string_lossy()
                .replace('\\', "/");
            let sz = entry.metadata().map(|m| m.len()).unwrap_or(0);
            out.push((rel, sz));
        }
    }
}

/// 把散文件资源聚合成「按体积均分的多个 7z 卷」+ 卷数清单，根治：
///  1) NSIS 逐个 File 解压上万文件造成的安装卡顿（#1/#6）；
///  2) 单个聚合包一次性异步解压导致进度「只有 0%→100%」跳变（#2）；
///  3) 超时分支误删归档导致 SearXNG 等资源缺失（#3）。
/// 打包 src-tauri/resources 下的 desktop_core / data / python-embed / searxng 到
/// resources/_bundle/res_part_01.7z ...，并把 7z.exe/7z.dll + part_count.txt 一并拷入。
fn pack_resources_7z() {
    let manifest_dir = PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR not set by cargo"),
    );
    let resources = manifest_dir.join("resources");
    let bundle = resources.join("_bundle");
    let _ = fs::create_dir_all(&bundle);

    // 定位 7z 命令行工具（本机常见安装路径 + PATH 回退）
    let seven_zip = ["D:\\软件\\7-Zip\\7z.exe", "C:\\Program Files\\7-Zip\\7z.exe",
                     "C:\\Program Files (x86)\\7-Zip\\7z.exe"]
        .iter()
        .find(|p| Path::new(p).is_file())
        .map(|p| p.to_string())
        .or_else(|| {
            std::process::Command::new("where")
                .arg("7z.exe")
                .output()
                .ok()
                .and_then(|o| {
                    let s = String::from_utf8_lossy(&o.stdout);
                    s.lines().next().map(|l| l.trim().to_string())
                })
        });

    let seven_zip = match seven_zip {
        Some(p) => p,
        None => {
            eprintln!("error: 未找到 7z.exe，无法打包资源聚合包；请安装 7-Zip 或调整 build.rs 中的路径");
            std::process::exit(1);
        }
    };

    // 待打包的子目录（与 tauri.conf.json 原 bundle.resources 对应，避免漏打运行时必需资源）
    let dirs = ["desktop_core", "data", "python-embed", "searxng"];
    if !dirs.iter().any(|d| resources.join(d).is_dir()) {
        eprintln!("warn: resources 下无可打包目录，跳过 7z 打包");
        let _ = fs::write(bundle.join("part_count.txt"), "0");
        return;
    }

    // 收集全部文件（相对 resources 的路径 + 大小）
    let mut files: Vec<(String, u64)> = Vec::new();
    for d in dirs.iter() {
        let root = resources.join(d);
        if root.is_dir() {
            collect_pack_files(&root, &resources, &mut files);
        }
    }
    if files.is_empty() {
        let _ = fs::write(bundle.join("part_count.txt"), "0");
        return;
    }

    // 大文件优先，利于首次适应装箱，使每卷体积更均衡
    files.sort_by(|a, b| b.1.cmp(&a.1));
    let total: u64 = files.iter().map(|(_, s)| *s).sum();

    // 目标每卷原始体积 ~60MB；卷数 clamp 到 [1, 40]
    let target_part: u64 = 60 * 1024 * 1024;
    let mut n: usize = ((total + target_part - 1) / target_part).clamp(1, 40) as usize;

    // 首次适应装箱：把每个文件放入当前最小的一组
    let mut groups: Vec<Vec<String>> = vec![Vec::new(); n];
    let mut group_sz = vec![0u64; n];
    for (rel, sz) in files {
        let mut idx = 0usize;
        for g in 1..n {
            if group_sz[g] < group_sz[idx] {
                idx = g;
            }
        }
        groups[idx].push(rel);
        group_sz[idx] += sz;
    }
    // 丢弃空组
    groups.retain(|g| !g.is_empty());
    n = groups.len();

    // 清掉旧卷，避免残留
    let _ = fs::remove_file(bundle.join("app_res.7z"));
    if let Ok(rd) = fs::read_dir(&bundle) {
        for entry in rd.flatten() {
            let fname = entry.file_name();
            let ns = fname.to_string_lossy();
            if ns.starts_with("res_part_") && ns.ends_with(".7z") {
                let _ = fs::remove_file(entry.path());
            }
        }
    }

    // 在 resources 目录下打包，使归档内路径为 desktop_core/... 等，
    // 安装器逐卷解压到 $INSTDIR/resources 即得正确布局（与旧逐文件 File 一致）。
    eprintln!("info: 打包资源聚合包 (7z, {n} 卷) ...");
    for (i, g) in groups.iter().enumerate() {
        let name = format!("res_part_{:02}.7z", i + 1);
        let arc_path = bundle.join(&name);
        // 把待压缩文件清单写入临时 .lst，再用 `-i@list` 传给 7z。
        // 严禁把上万条长路径直接当命令行参数：Windows CreateProcess 命令行上限
        // 32767 字符，嵌套深的 searxng 一组上千文件即触发 os error 206（命令行太长）。
        let list_path = bundle.join(format!("res_part_{:02}.lst", i + 1));
        {
            let mut list_content = String::with_capacity(g.len() * 64);
            for rel in g {
                // 7z 清单用正斜杠或反斜杠皆可（已相对 resources/），这里统一反斜杠更稳妥。
                let line = rel.replace('/', "\\");
                list_content.push_str(&line);
                list_content.push('\n');
            }
            if let Err(e) = fs::write(&list_path, list_content) {
                eprintln!("error: 写 7z 清单 {} 失败: {e}", list_path.display());
                std::process::exit(1);
            }
        }
        let mut cmd = std::process::Command::new(&seven_zip);
        cmd.current_dir(&resources)
            .arg("a")
            .arg("-t7z")
            .arg("-mx=7")
            .arg("-mmt=on")
            .arg("-bsp0") // 安静，不向 stderr 吐进度
            .arg(arc_path.to_string_lossy().as_ref())
            .arg(format!("-i@{}", list_path.to_string_lossy()));
        match cmd.status() {
            Ok(s) if s.success() => {}
            Ok(s) => {
                eprintln!("error: 7z 打包失败（{:?}，卷 {}），终止构建", s, name);
                std::process::exit(1);
            }
            Err(e) => {
                eprintln!("error: 无法启动 7z（{e}），终止构建");
                std::process::exit(1);
            }
        }
        // 清临时清单（失败不致命，下一轮打包前会整体重算）
        let _ = fs::remove_file(&list_path);
    }

    // 卷数清单（纯整数，无换行，供安装器运行时读取）
    if let Err(e) = fs::write(bundle.join("part_count.txt"), format!("{}", n)) {
        eprintln!("error: 写 part_count.txt 失败: {e}");
        std::process::exit(1);
    }

    // 拷贝 7z 解压工具（7z.exe 依赖同目录 7z.dll）
    let seven_dir = Path::new(&seven_zip).parent().unwrap();
    for f in ["7z.exe", "7z.dll"] {
        let src = seven_dir.join(f);
        let dst = bundle.join(f);
        if src.is_file() {
            if let Err(e) = fs::copy(&src, &dst) {
                eprintln!("error: 拷贝 {f} 失败: {e}");
                std::process::exit(1);
            }
        }
    }
    eprintln!(
        "info: 资源聚合包已生成：{} 卷 (共 {n} 卷)",
        bundle.join("res_part_01.7z").display()
    );
}

#[allow(dead_code)]
fn main() {
    // 声明依赖：desktop_core / searxng 任一文件变化都必须重跑本 build script。
    // 否则 cargo 会缓存跳过 build script，导致"改了 python 却没同步进运行态副本"的漂移
    // （曾出现改完 api.py 后打包副本仍是旧版、接口 404）。
    println!("cargo:rerun-if-changed=../desktop_core");
    println!("cargo:rerun-if-changed=../searxng");
    // 资源聚合包依赖这些目录的内容；任一项变化都需重打包，否则安装包拿到旧 7z。
    println!("cargo:rerun-if-changed=resources/desktop_core");
    println!("cargo:rerun-if-changed=resources/data");
    println!("cargo:rerun-if-changed=resources/python-embed");
    println!("cargo:rerun-if-changed=resources/searxng");
    println!("cargo:rerun-if-changed=sidecar");

    let manifest_dir = PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR not set by cargo"),
    ); // src-tauri
    let resources = manifest_dir.join("resources");

    // 把开发源 desktop_core/ 同步进打包资源 resources/desktop_core/（纯 Python，无 .pyd，安全）。
    let src = manifest_dir.join("..").join("desktop_core");
    let dst = resources.join("desktop_core");
    if src.is_dir() {
        if let Err(e) = sync_dir(&src, &dst) {
            eprintln!("warn: failed to sync desktop_core into resources: {e}");
        }
    }

    // searxng 必须先落到 resources/searxng 再调 tauri_build::build()。
    //
    // 历史坑（本次修复）：旧实现是「构建前把 resources/searxng 整个移走 → tauri_build::build()
    // → 之后再拷回」，本意是躲开 Defender 对 .pyd 的瞬时共享锁（os error 32）。
    // 但 tauri_build 会校验 bundle.resources 里每个 glob 至少匹配到一个文件，
    // 此时 searxng 恰好不在资源目录里，于是直接报
    //   glob pattern resources/searxng/**/* path not found or didn't match any files
    // 并中止构建；更糟的是报错后「拷回 searxng」的代码永不执行，资源目录被清空。
    // 正解：先把 searxng 同步好，再让 tauri_build 看到完整资源；防锁改用预热读取。
    let searx_src = manifest_dir.join("..").join("searxng");
    let searx_dst = resources.join("searxng");
    if searx_src.is_dir() {
        if let Err(e) = sync_dir(&searx_src, &searx_dst) {
            eprintln!("warn: failed to sync searxng into resources: {e}");
        }
        warm_read_retry(&searx_dst);
    } else {
        // 缺少 searxng 会让 glob 空匹配 → tauri_build 直接失败，故此处明确报错提示。
        eprintln!(
            "warn: 未找到 {}（内置 SearXNG 缺席，安装包将缺少离线搜索）",
            searx_src.display()
        );
    }

    // 先把散文件资源聚合成单个 7z（+ 拷入 7z 解压工具），再交给 tauri_build。
    // 注意：tauri.conf.json 的 bundle.resources 已改为只收 resources/_bundle/*，
    // 故此处必须先生成 _bundle，否则 glob 空匹配 → tauri_build 直接失败。
    pack_resources_7z();

    tauri_build::build();

    // tauri_build 完成，再补一份到 target/release/resources（--no-bundle 运行态读取位置），
    // 防止 tauri CLI 资源同步阶段未覆盖 searxng 导致运行态搜索不可用。
    if searx_src.is_dir() {
        let release_res = manifest_dir
            .join("..")
            .join("target")
            .join("release")
            .join("resources")
            .join("searxng");
        if let Err(e) = sync_dir(&searx_src, &release_res) {
            eprintln!("warn: failed to stage searxng into target/release/resources: {e}");
        }
    }
}
