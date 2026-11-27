"""ランチャー：各スクリプトの実行と表示ページを開くボタンを並べた画面。

起動：launch.bat をダブルクリック、または  python launcher.py
"""
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import scrolledtext

BASE = Path(__file__).resolve().parent
STEPS = [
    ("① データ取得", "data_fetch.py"),
    ("② 予報を計算", "forecast.py"),
    ("③ 予測精度の検証", "backtest.py"),
    ("④ 自己相関を計算", "acf.py"),
    ("⑤ 答え合わせ", "archive.py"),
]
PAGES = [
    ("🌤 週間予報ページ", "web/forecast.html"),
    ("🎯 当たり具合ページ", "web/backtest.html"),
    ("📒 答え合わせページ", "web/archive.html"),
    ("🔁 自己相関ページ", "web/acf.html"),
]


class Launcher:
    def __init__(self, root):
        self.root = root
        root.title("ボラ予報 ランチャー")
        root.geometry("900x540")
        self.buttons = []

        f1 = tk.LabelFrame(root, text="計算", padx=6, pady=6)
        f1.pack(fill="x", padx=10, pady=(10, 4))
        for label, script in STEPS:
            b = tk.Button(f1, text=label, width=14, command=lambda s=[script]: self.run(s))
            b.pack(side="left", padx=4)
            self.buttons.append(b)
        b = tk.Button(f1, text="まとめて ①→②", width=14, bg="#dbeafe",
                      command=lambda: self.run(["data_fetch.py", "forecast.py"], open_page="web/forecast.html"))
        b.pack(side="left", padx=4)
        self.buttons.append(b)

        f2 = tk.LabelFrame(root, text="表示", padx=6, pady=6)
        f2.pack(fill="x", padx=10, pady=4)
        for label, page in PAGES:
            tk.Button(f2, text=label, width=16, command=lambda p=page: self.open(p)).pack(side="left", padx=4)
        tk.Button(f2, text="📁 フォルダを開く", command=lambda: os.startfile(BASE) if os.name == "nt" else None).pack(side="left", padx=4)

        self.log = scrolledtext.ScrolledText(root, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.write("ボタンを押すと実行します。初回は「まとめて ①→②」がおすすめです。\n")

    def write(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def open(self, page):
        path = BASE / page
        webbrowser.open(path.as_uri())

    def run(self, scripts, open_page=None):
        for b in self.buttons:
            b.config(state="disabled")
        threading.Thread(target=self._worker, args=(scripts, open_page), daemon=True).start()

    def _worker(self, scripts, open_page):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        ok = True
        for script in scripts:
            self.root.after(0, self.write, f"\n===== {script} =====\n")
            proc = subprocess.Popen([sys.executable, str(BASE / script)], cwd=BASE, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in proc.stdout:
                self.root.after(0, self.write, line)
            if proc.wait() != 0:
                self.root.after(0, self.write, f"※ {script} がエラーで終了しました\n")
                ok = False
                break
        self.root.after(0, self._done, ok, open_page)

    def _done(self, ok, open_page):
        for b in self.buttons:
            b.config(state="normal")
        if ok and open_page:
            self.open(open_page)


if __name__ == "__main__":
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
