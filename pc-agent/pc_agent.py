"""pc-agent — связь с панелью ESP32-2432S028.

Транспорт берётся из config.ini:
  transport = serial   (по умолчанию) — COM-порт CH340 того же USB-кабеля, что и прошивка
  transport = tcp      — TCP-сервер для варианта по Wi-Fi

Протокол одинаковый: строки JSON через '\\n'.
  агент -> панель: телеметрия (температуры/загрузка/кулера)
  панель -> агент: команды {"cmd": "..."}
"""
from __future__ import annotations
import json
import socket
import threading
import time
import configparser
import os
import sys
import datetime

import telemetry
import control

HERE = os.path.dirname(os.path.abspath(__file__))


class _Tee:
    def __init__(self, stream, path):
        self.s = stream
        try:
            self.f = open(path, "a", encoding="utf-8", buffering=1)  # line-buffered
        except Exception:
            self.f = None
    def write(self, data):
        try: self.s.write(data)
        except Exception: pass
        if self.f:
            try: self.f.write(data)
            except Exception: pass
    def flush(self):
        try: self.s.flush()
        except Exception: pass
        if self.f:
            try: self.f.flush()
            except Exception: pass


# Пишем лог и в консоль, и в файл (при запуске от админа без консоли видно в файле).
sys.stdout = _Tee(sys.stdout, os.path.join(HERE, "pc_agent.log"))
sys.stderr = _Tee(sys.stderr, os.path.join(HERE, "pc_agent.log"))


def load_config() -> dict:
    cp = configparser.ConfigParser()
    cp.read(os.path.join(HERE, "config.ini"), encoding="utf-8")
    s = cp["server"] if "server" in cp else {}
    t = cp["transport"] if "transport" in cp else {}
    return {
        "transport": t.get("type", "serial").strip().lower(),
        "com_port":  t.get("com_port", "COM5"),
        "baud":      int(t.get("baud", "115200")),
        "host":      s.get("host", "0.0.0.0"),
        "port":      int(s.get("port", "8765")),
        "interval_ms": int(s.get("telemetry_interval_ms", "1000")),
        "apps_path": os.path.join(HERE, s.get("apps_file", "apps.json")),
    }


CFG = load_config()


def load_apps() -> list[dict]:
    try:
        with open(CFG["apps_path"], "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except Exception:
        return []


def _ascii_label(name: str, i: int) -> str:
    # LVGL-шрифт без кириллицы: показываем только ASCII, иначе будут квадраты
    clean = "".join(ch for ch in (name or "") if 32 <= ord(ch) < 127).strip()
    return (clean or f"App {i+1}")[:12]


def make_json_line() -> str:
    snap = telemetry.read_telemetry()
    snap["tick"] = int(time.time() % 1_000_000)
    snap["time"] = datetime.datetime.now().strftime("%H:%M")
    # названия кнопок быстрого запуска (панель построит их динамически, до 4)
    snap["apps"] = [{"label": _ascii_label(a.get("name"), i)}
                    for i, a in enumerate(load_apps()[:4])]
    return json.dumps(snap, ensure_ascii=False) + "\n"


def handle_command(line: str):
    try:
        msg = json.loads(line)
    except Exception:
        # строка не JSON (boot-лог, отладка) — игнорируем
        if line.startswith("{"):
            print("bad json:", line[:80])
        return
    cmd = msg.get("cmd", "")
    result = control.execute(cmd, msg, CFG["apps_path"])
    print(f"команда: {cmd} -> {result}")


# ------------------------------------------------------------------ serial
def run_serial():
    try:
        import serial
    except Exception:
        print("Нет pyserial: pip install pyserial", file=sys.stderr)
        raise

    while True:
        try:
            _serial_session(serial)
        except KeyboardInterrupt:
            print("\nостановка")
            return
        except Exception as e:
            # transient-ошибки порта (ресет ESP32, переинициализация CH340) —
            # переподключаемся, а не падаем
            print(f"порт сброшен ({e}); переподключение через 2с", file=sys.stderr)
            time.sleep(2)


def _serial_session(serial):
    ser = serial.Serial(CFG["com_port"], CFG["baud"], timeout=0.1)
    print(f"Открыт {CFG['com_port']} @ {CFG['baud']}. Ctrl+C — выход.")
    # не трогаем DTR/RTS, чтобы не ресетить панель при открытии порта
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    time.sleep(0.3)

    buf = ""
    next_tx = 0.0
    try:
        while True:
            try:
                n = ser.in_waiting
                chunk = ser.read(n if n else 1)
            except OSError:
                raise  # переносим наверх -> переподключение
            if chunk:
                buf += chunk.decode("utf-8", "ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if "cmd" in obj:
                        handle_command(line)
                    elif "hello" in obj:
                        print("панель на связи:", obj["hello"])

            now = time.monotonic()
            if now >= next_tx:
                line = make_json_line()
                ser.write(line.encode("utf-8"))
                try:
                    o = json.loads(line)
                    c = o.get("cpu", {}); g = o.get("gpu", {})
                    print(f"TX cpu t={c.get('t')} l={c.get('load')} | gpu t={g.get('t')} l={g.get('load')} | stor={len(o.get('storage',[]))} fan={len(o.get('fans',[]))}")
                except Exception:
                    pass
                next_tx = now + CFG["interval_ms"] / 1000.0
    finally:
        try:
            ser.close()
        except Exception:
            pass


# ------------------------------------------------------------------ tcp
def run_tcp():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); print("IP этого ПК:", s.getsockname()[0]); s.close()
    except Exception:
        pass
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((CFG["host"], CFG["port"])); srv.listen(4)
    print(f"pc-agent (tcp) слушает {CFG['host']}:{CFG['port']}")
    clients: list[socket.socket] = []
    lock = threading.Lock()

    def broadcast(obj_line: str):
        with lock:
            dead = []
            for c in clients:
                try: c.sendall(obj_line.encode("utf-8"))
                except Exception: dead.append(c)
            for c in dead:
                clients.remove(c)

    def tloop():
        while True:
            broadcast(make_json_line())
            time.sleep(CFG["interval_ms"] / 1000.0)
    threading.Thread(target=tloop, daemon=True).start()

    def client_thread(conn, addr):
        print("панель подключилась:", addr)
        with lock: clients.append(conn)
        buf = ""
        try:
            while True:
                d = conn.recv(256)
                if not d: break
                buf += d.decode("utf-8", "ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if line.strip(): handle_command(line.strip())
        except Exception as e:
            print("client:", e)
        finally:
            with lock:
                if conn in clients: clients.remove(conn)
            conn.close()

    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=client_thread, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nостановка")
    finally:
        srv.close()


def main():
    if CFG["transport"] == "tcp":
        run_tcp()
    else:
        run_serial()


if __name__ == "__main__":
    main()
