"""Выполняемые с экрана ESP32 действия на ПК (только Windows).

  sleep / shutdown / restart
  vol_up / vol_down / mute           — через виртуальные клавиши (SendInput)
  play / next / prev                 — медиа-клавиши
  launch idx=N                       — запуск приложения из apps.json
"""
from __future__ import annotations
import ctypes
import json
import os
import subprocess
import time as _time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.windll.kernel32

# Виртуальные коды клавиш мультимедиа/громкости
VK_VOLUME_MUTE   = 0xAD
VK_VOLUME_DOWN   = 0xAE
VK_VOLUME_UP     = 0xAF
VK_MEDIA_NEXT    = 0xB0
VK_MEDIA_PREV    = 0xB1
VK_MEDIA_STOP    = 0xB2
VK_MEDIA_PLAY    = 0xB3

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP       = 0x0002


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        # union must be as large as MOUSEINPUT, иначе Windows отклоняет SendInput
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]
    _anonymous_ = ("i",)
    _fields_ = [("type", wintypes.DWORD), ("i", _I)]


def _press_vk(vk: int):
    down = INPUT(INPUT_KEYBOARD)
    down.ki.wVk = vk
    up = INPUT(INPUT_KEYBOARD)
    up.ki.wVk = vk
    up.ki.dwFlags = KEYEVENTF_KEYUP
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    _time.sleep(0.03)
    n = user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
    if n == 0:
        print("SendInput=0, err=", ctypes.get_last_error(),
              "(обычно UIPI: фокус-окно админское — агенту тоже нужны права)")


# ------------------------------------------------------------------ power
def sleep():
    # SetSuspendState(bHibernate, bForce, bWakeupEventsDisabled)
    kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS (сброс блокировок)
    ctypes.windll.powrprof.SetSuspendState(0, 1, 0)


def shutdown():
    subprocess.run(["shutdown", "/s", "/t", "5", "/c",
                    "Выключение с панели ESP32 (отмена: shutdown /a)"])


def restart():
    subprocess.run(["shutdown", "/r", "/t", "5"])


# ------------------------------------------------------------------ volume / media
def vol_up():   _press_vk(VK_VOLUME_UP)
def vol_down(): _press_vk(VK_VOLUME_DOWN)
def mute():     _press_vk(VK_VOLUME_MUTE)
def play():     _press_vk(VK_MEDIA_PLAY)
def next_track(): _press_vk(VK_MEDIA_NEXT)
def prev_track(): _press_vk(VK_MEDIA_PREV)


# ------------------------------------------------------------------ apps
def _load_apps(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def launch_app(idx: int, apps_path: str):
    apps = _load_apps(apps_path)
    if not (0 <= idx < len(apps)):
        return
    a = apps[idx]
    cmd = a.get("path")
    args = a.get("args", [])
    if not cmd:
        return
    cmd = os.path.expandvars(os.path.expanduser(cmd))
    args = [os.path.expandvars(os.path.expanduser(str(x))) for x in args]
    if a.get("shell") or cmd.endswith(".lnk") or os.path.isdir(cmd):
        os.system(f'start "" "{cmd}"')
    else:
        shell32 = ctypes.windll.shell32
        ret = shell32.ShellExecuteW(None, "open", cmd, " ".join(args), None, 1)
        if int(ret) <= 32:   # <=32 это код ошибки SE_ERR_*
            print(f"ShellExecuteW failed code={int(ret)} для: {cmd}")


# ------------------------------------------------------------------ dispatcher
def execute(cmd: str, payload: dict, apps_path: str) -> str:
    if cmd == "sleep":        sleep(); return "сон"
    if cmd == "shutdown":     shutdown(); return "выключение"
    if cmd == "restart":      restart(); return "перезагрузка"
    if cmd == "vol_up":       vol_up(); return "громкость +"
    if cmd == "vol_down":     vol_down(); return "громкость -"
    if cmd == "mute":         mute(); return "mute"
    if cmd == "play":         play(); return "play/pause"
    if cmd == "next":         next_track(); return "next"
    if cmd == "prev":         prev_track(); return "prev"
    if cmd == "launch":
        idx = int(payload.get("idx", 0))
        launch_app(idx, apps_path)
        return f"запуск #{idx}"
    return f"неизвестная команда: {cmd}"
