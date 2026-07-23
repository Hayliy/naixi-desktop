"""清理奶昔残留卸载注册表项（备份后删除），让今天 setup.exe /S 能正常落地。"""
import winreg
import json
import os

KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\奶昔"
BACKUP = r"D:\数据\Naixi-旧版留档\Naixi-旧版留档_20260723\registry_uninstall_naixi.json"


def enum_values(k):
    vals = {}
    cnt = winreg.QueryInfoKey(k)[1]
    for i in range(cnt):
        name, data, typ = winreg.EnumValue(k, i)
        vals[name] = data
    return vals


def del_key_tree(hive, path):
    try:
        winreg.DeleteKey(hive, path)
        return
    except OSError:
        pass
    # 有子键则递归删
    with winreg.OpenKey(hive, path) as k:
        subs = [winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])]
    for s in subs:
        del_key_tree(hive, path + "\\" + s)
    winreg.DeleteKey(hive, path)


def main():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH) as k:
            vals = enum_values(k)
    except FileNotFoundError:
        print("注册表项不存在，无需清理")
        return

    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w", encoding="utf-8") as f:
        json.dump(vals, f, ensure_ascii=False, indent=2)
    print("已备份 %d 个值 -> %s" % (len(vals), BACKUP))

    del_key_tree(winreg.HKEY_CURRENT_USER, KEY_PATH)
    print("已删除残留注册表项:", KEY_PATH)


if __name__ == "__main__":
    main()
