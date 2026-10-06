import json, os, tempfile, traceback
os.environ.setdefault("LHM_DIR", r"C:\LHM")
out = os.path.join(tempfile.gettempdir(), "lhm_probe.json")
try:
    import telemetry
    d = telemetry.read_telemetry()
    d["_admin"] = bool(os.getlogin and __import__("ctypes").windll.shell32.IsUserAnAdmin())
    open(out, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
except Exception as e:
    open(out, "w", encoding="utf-8").write("ERR: " + traceback.format_exc())
