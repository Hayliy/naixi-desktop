import re

SRC = r"D:\naixi_desktop\src-tauri\installer.nsi"
OUT = r"D:\naixi_desktop\src-tauri\installer_rendered.nsi"

src = open(SRC, encoding="utf-8-sig").read()

# Remove {{#each ...}} ... {{/each}} (non-greedy, multiline)
src = re.sub(r"{{#each[^}]*}}.*?{{/each}}", "", src, flags=re.DOTALL)
# Remove {{#if ...}} ... {{/if}} (non-greedy, multiline)
src = re.sub(r"{{#if[^}]*}}.*?{{/if}}", "", src, flags=re.DOTALL)

mapping = {
    "compression": "lzma",
    "signed_plugins_path": "",
    "installer_hooks": "",
    "manufacturer": "Naixi",
    "product_name": "奶昔",
    "version": "0.1.0",
    "version_with_build": "0.1.0.0",
    "homepage": "",
    "install_mode": "currentUser",
    "license": "",
    "installer_icon": r"D:\naixi_desktop\src-tauri\icons\icon.ico",
    "main_binary_name": "naixi",
    "main_binary_path": r"D:\naixi_desktop\src-tauri\icons\icon.ico",
    "bundle_id": "com.naixi.desktop",
    "copyright": "Naixi",
    "out_file": "test_setup.exe",
    "arch": "x64",
    "additional_plugins_path": r"D:\naixi_desktop\src-tauri\installer",
    "allow_downgrades": "false",
    "install_webview2_mode": "download",
    "webview2_installer_args": "",
    "webview2_bootstrapper_path": "",
    "webview2_installer_path": "",
    "minimum_webview2_version": "1.0.0",
    "estimated_size": "420",
    "start_menu_folder": "奶昔",
    "DISPLAYLANGUAGESELECTOR": "false",
    "INSTALLMODE": "currentUser",
    "uninstaller_sign_cmd": "",
}

def repl(m):
    key = m.group(1)
    return mapping.get(key, "")

src = re.sub(r"{{(\w+)}}", repl, src)

left = re.findall(r"{{[^}]*}}", src)
print("remaining unresolved {{}}:", left)

open(OUT, "w", encoding="utf-8").write(src)
print("rendered ->", OUT)
