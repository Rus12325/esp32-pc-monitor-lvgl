"""Тест: выводит все используемые строки с указанием, какие символы не-ASCII."""
import re
s = open("D:/ЗАИ/esp32-pc-monitor/firmware/src/main.cpp", encoding="utf-8").read()
str_re = re.compile(r'"([^"]*)"')
for m in str_re.finditer(s):
    txt = m.group(1)
    if any(ord(c) >= 0x400 for c in txt):
        print("Cyrillic:", repr(txt[:30]), "-> chars:", [f"0x{ord(c):04x}" for c in txt if ord(c)>=0x400])
print("---done---")