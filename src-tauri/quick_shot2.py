import os, time, subprocess, ctypes
from ctypes import wintypes
from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
GetWindowTextLength = user32.GetWindowTextLengthW
GetWindowText = user32.GetWindowTextW
IsWindowVisible = user32.IsWindowVisible
EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetClientRect = user32.GetClientRect
PrintWindow = user32.PrintWindow

def find_main():
    res = []
    def cb(hwnd, lp):
        if not IsWindowVisible(hwnd):
            return True
        n = GetWindowTextLength(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowText(hwnd, buf, n + 1)
        t = buf.value
        if "奶昔" in t and "安装" in t:
            rect = ctypes.wintypes.RECT()
            GetClientRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w == 540 and h == 430:
                res.append(hwnd)
        return True
    EnumWindows(EnumWindowsProc(cb), 0)
    return res[0] if res else None

def screenshot(hwnd, path):
    rect = ctypes.wintypes.RECT()
    GetClientRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(hwnd, memdc, 2)  # PW_CLIENTONLY
    bmi = ctypes.create_string_buffer(40)
    ctypes.memset(bmi, 0, 40)
    ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint32))[0] = 40
    ctypes.cast(bmi, ctypes.POINTER(ctypes.c_int32))[1] = w
    ctypes.cast(bmi, ctypes.POINTER(ctypes.c_int32))[2] = h
    ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint16))[5] = 1
    ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint16))[6] = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, bmi, 0)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    img = img.convert("RGB")
    img.save(path)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc)
    print("SAVED", path, (w, h))

proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
time.sleep(2.5)
hwnd = find_main()
if hwnd:
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.ShowWindow(hwnd, 1)
    user32.UpdateWindow(hwnd)
    time.sleep(0.3)
    screenshot(hwnd, r"D:\naixi_desktop\src-tauri\tf_real_page1.png")
else:
    print("NOT FOUND")
proc.terminate()
