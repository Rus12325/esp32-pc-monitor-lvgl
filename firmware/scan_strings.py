import re, sys
p = r"D:/ЗАИ/esp32-pc-monitor/firmware/src/main.cpp"
s = open(p, encoding="utf-8").read()

# строки с кириллицей (только внутри "...")
str_re = re.compile(r'"([^"]*)"')
bad = [m.group(1) for m in str_re.finditer(s) if any(ord(c) >= 0x400 for c in m.group(1))]
print("rendered strings with cyrillic:", len(bad))
for b in bad[:40]:
    print("   ", b[:50])

codes = set()
for b in bad:
    codes |= {ord(c) for c in b if ord(c) >= 0x400 or ord(c) == 0xB0}
# всё кириллическое покрытие + Ёё + градус, чтобы гарантировать
codes |= set(range(0x410, 0x450)) | {0x401, 0x451, 0xB0}
try:
    a = open(r"D:/ЗАИ/esp32-pc-monitor/pc-agent/apps.json", encoding="utf-8").read()
    codes |= {ord(c) for c in a if ord(c) >= 0x400}
except Exception:
    pass
sym = "".join(chr(c) for c in sorted(codes) if c <= 0x4FF)
open(r"C:\esp32-build\syms.txt", "w", encoding="utf-8").write(sym)
print("syms.txt glyphs:", len(sym))
