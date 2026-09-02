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

fn main() {
    // 声明依赖：desktop_core / searxng 任一文件变化都必须重跑本 build script。
    // 否则 cargo 会缓存跳过 build script，导致"改了 python 却没同步进运行态副本"的漂移
    // （曾出现改完 api.py 后打包副本仍是旧版、接口 404）。
    println!("cargo:rerun-if-changed=../desktop_core");
    println!("cargo:rerun-if-changed=../searxng");

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

    // 关键修复：searxng 自带一整套 Python 环境（含大量 .pyd）。
    // tauri_build::build() 会遍历 resources/ 并嵌入——读 _brotli.cp311-win_amd64.pyd 时
    // 常被 Windows Defender 实时防护的瞬时共享锁挡住（os error 32），导致构建偶发失败。
    // 治本：构建前把 resources/searxng 整个移出，让 tauri_build 根本不碰它；
    // tauri_build 完成后再把 searxng 拷回（拷贝带重试，绕开 Defender）。
    let searx_dst = resources.join("searxng");
    remove_dir_retry(&searx_dst);

    // 此时 resources/ 内无 searxng → tauri_build 不会读 .pyd → 不再 os error 32
    tauri_build::build();

    // tauri_build 完成，把 searxng 拷回资源目录（运行态/打包都需要），拷贝带重试。
    let searx_src = manifest_dir.join("..").join("searxng");
    if searx_src.is_dir() {
        if let Err(e) = sync_dir(&searx_src, &searx_dst) {
            eprintln!("warn: failed to restore searxng into resources: {e}");
        }
        // 同时直接补一份到 target/release/resources（--no-bundle 运行态读取位置），
        // 防止 tauri CLI 资源同步阶段未覆盖 searxng 导致运行态搜索不可用。
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
