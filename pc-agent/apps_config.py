"""apps_config.py — графический редактор кнопок быстрого запуска для панели ESP32.

Открывает apps.json, позволяет добавлять/редактировать/удалять/переставлять
приложения, выбирать файл через диалог, задавать аргументы, и сохранять.
Кнопки на экране панели соответствуют списку по порядку (App 1 = 1-й элемент).

Запуск:  python apps_config.py     (или двойным кликом apps_config.bat)
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
APPS_FILE = os.path.join(HERE, "apps.json")


def load_apps() -> list[dict]:
    try:
        with open(APPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_apps(apps: list[dict]):
    with open(APPS_FILE, "w", encoding="utf-8") as f:
        json.dump(apps, f, ensure_ascii=False, indent=2)


class AppRow:
    def __init__(self, name="", path="", args="", shell=False):
        self.name, self.path, self.args, self.shell = name, path, args, shell

    def to_dict(self):
        d = {"name": self.name, "path": self.path}
        if self.args:
            d["args"] = [a for a in self.args.split() if a]
        if self.shell:
            d["shell"] = True
        return d

    @staticmethod
    def from_dict(d):
        return AppRow(d.get("name", ""), d.get("path", ""),
                      " ".join(str(x) for x in d.get("args", [])),
                      bool(d.get("shell", False)))


class Editor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Панель ESP32 — быстрый запуск (apps.json)")
        self.geometry("720x480")
        self.apps: list[AppRow] = [AppRow.from_dict(d) for d in load_apps()]
        self.dirty = tk.BooleanVar(value=False)
        self._build()
        self._refresh()

    def _build(self):
        top = ttk.Frame(self, padding=8); top.pack(fill="x")
        ttk.Label(top, text="Каждая строка — одна кнопка на экране (по порядку):",
                  ).pack(anchor="w")

        cols = ("n", "p", "a")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", height=12)
        self.tree.heading("#0", text="#"); self.tree.column("#0", width=40, anchor="center")
        self.tree.heading("n", text="Название кнопки"); self.tree.column("n", width=170)
        self.tree.heading("p", text="Путь (.exe / папка / URL)"); self.tree.column("p", width=300)
        self.tree.heading("a", text="Аргументы"); self.tree.column("a", width=150)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree.bind("<Double-1>", lambda e: self.edit())

        f = ttk.Frame(self, padding=8); f.pack(fill="x")
        for text, cmd in [
            ("Добавить", self.add), ("Изменить", self.edit), ("Удалить", self.remove),
            ("Выше", lambda: self.move(-1)), ("Ниже", lambda: self.move(+1)),
            ("Тест-запуск", self.test_run), ("Сохранить", self.save),
        ]:
            ttk.Button(f, text=text, command=cmd).pack(side="left", padx=3)

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, a in enumerate(self.apps):
            self.tree.insert("", "end", iid=str(i), text=str(i + 1),
                             values=(a.name or f"App {i+1}", a.path, a.args))

    def _sel(self):
        s = self.tree.selection()
        return int(s[0]) if s else -1

    def _dialog(self, row: AppRow | None):
        win = tk.Toplevel(self); win.title("Приложение"); win.grab_set()
        win.resizable(False, False)
        g = ttk.Frame(win, padding=12); g.pack()
        name = tk.StringVar(value=row.name if row else "")
        path = tk.StringVar(value=row.path if row else "")
        args = tk.StringVar(value=row.args if row else "")
        shell = tk.BooleanVar(value=row.shell if row else False)

        def brow():
            if os.path.isdir(path.get()):
                p = filedialog.askdirectory(initialdir=path.get() or None)
            else:
                p = filedialog.askopenfilename(title="Выбери .exe / ярлык")
            if p:
                path.set(p)
                if not name.get():
                    name.set(os.path.splitext(os.path.basename(p))[0])
        def bdir():
            p = filedialog.askdirectory(title="Выбери папку")
            if p: path.set(p); shell.set(True)

        for r, (lbl, var, browse) in enumerate([
            ("Название", name, None), ("Путь", path, brow), ("Аргументы", args, None)]):
            ttk.Label(g, text=lbl).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(g, textvariable=var, width=52).grid(row=r, column=1, pady=3, sticky="we")
            if lbl == "Путь":
                ttk.Button(g, text="Файл…", command=browse).grid(row=r, column=2, padx=4)
                ttk.Button(g, text="Папка…", command=bdir).grid(row=r, column=3)
        ttk.Checkbutton(g, text="папка/ссылка (shell)", variable=shell).grid(
            row=3, column=1, sticky="w")

        btns = ttk.Frame(g); btns.grid(row=4, column=0, columnspan=4, pady=10, sticky="e")
        res = {}
        def ok():
            if not path.get():
                messagebox.showwarning("Путь", "Укажи путь к файлу или папке", parent=win); return
            res["data"] = AppRow(name.get() or "App", path.get(), args.get(), shell.get())
            win.destroy()
        ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Отмена", command=win.destroy).pack(side="left")
        win.wait_window()
        return res.get("data")

    def add(self):
        r = self._dialog(None)
        if r: self.apps.append(r); self.dirty.set(True); self._refresh()

    def edit(self):
        i = self._sel()
        if i < 0: return
        r = self._dialog(self.apps[i])
        if r: self.apps[i] = r; self.dirty.set(True); self._refresh(); self.tree.selection_set(str(i))

    def remove(self):
        i = self._sel()
        if i < 0: return
        del self.apps[i]; self.dirty.set(True); self._refresh()

    def move(self, d):
        i = self._sel()
        j = i + d
        if i < 0 or j < 0 or j >= len(self.apps): return
        self.apps[i], self.apps[j] = self.apps[j], self.apps[i]
        self.dirty.set(True); self._refresh(); self.tree.selection_set(str(j))

    def test_run(self):
        i = self._sel()
        if i < 0: return
        a = self.apps[i]
        try:
            if a.shell or os.path.isdir(a.path):
                os.system(f'start "" "{a.path}"')
            else:
                subprocess.Popen([a.path] + [x for x in a.args.split() if x])
        except Exception as e:
            messagebox.showerror("Не запустилось", str(e))

    def save(self):
        try:
            save_apps([a.to_dict() for a in self.apps])
            self.dirty.set(False)
            messagebox.showinfo("Сохранено", f"Записано {len(self.apps)} приложений в\n{APPS_FILE}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def _on_close(self):
        if self.dirty.get() and not messagebox.askokcancel(
                "Выход", "Есть несохранённые изменения. Выйти без сохранения?"):
            return
        self.destroy()


if __name__ == "__main__":
    app = Editor()
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.mainloop()
