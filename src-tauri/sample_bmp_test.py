import subprocess, time, ctypes, sys
from ctypes import wintypes
from PIL import ImageGrab

EXE = r"D:\naixi_desktop\src-tauri\bmp_test.exe"
TITLE = "Bitmap Render Test"
OUT = r"D:\naixi_desktop\src-tauri\bmp_test_shot.png"

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

def find_window(title):
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)

p = subprocess.Popen([EXE])
time.sleep(4)
box = find_window(TITLE)
print("window rect:", box)
if not box:
    print("WINDOW NOT FOUND")
    p.terminate()
    sys.exit(1)

# bring to front
user32.SetForegroundWindow(box and user32.FindWindowW(None, TITLE))
time.sleep(0.5)
img = ImageGrab.grab(bbox=box)
img.save(OUT)
print("saved", OUT, img.size)

# scan for blue pixels
px = img.load()
W, H = img.size
cnt = 0
minx = miny = 10**9
maxx = maxy = -1
for y in range(H):
    for x in range(W):
        r, g, b = px[x, y][:3]
        if b > 200 and r < 60 and g < 60:
            cnt += 1
            if x < minx: minx = x
            if x > maxx: maxx = x
            if y < miny: miny = y
            if y > maxy: maxy = y
print("BLUE pixel count:", cnt)
if cnt > 0:
    print("blue bbox in window:", (minx, miny, maxx, maxy))
    print("=> BITMAP RENDERED OK")
else:
    print("=> BITMAP NOT RENDERED (no blue pixels)")
p.terminate()
