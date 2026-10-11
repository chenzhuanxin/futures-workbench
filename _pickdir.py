# -*- coding: utf-8 -*-
"""系统原生文件夹 / 另存为 对话框。

浏览器出于安全限制无法获取用户选择的真实磁盘路径，所以这里借助 tkinter
弹出一个系统原生对话框，把用户选中的路径交给调用方。

两种调用方式：
  · 源码运行：app.py 以子进程方式执行本文件
      python _pickdir.py dir "初始目录" "标题" [结果文件]
  · 打包成 exe：app.py 以 `本程序 --pickdir dir ...` 再启动一个自身进程
      app.exe --pickdir dir "初始目录" "标题" [结果文件]

结果同时写到标准输出和（若给了路径）结果文件。写文件是为了在无控制台的
Windows GUI 子系统下也能可靠回传路径。
"""

import sys


def pick(mode="dir", initial="", title="选择文件夹"):
    """弹出原生对话框，返回绝对路径；用户取消或无 GUI 环境时返回 ""。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:          # 无 GUI 环境
        sys.stderr.write(f"ERR:{e}\n")
        return ""

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        if mode == "save":
            path = filedialog.asksaveasfilename(
                title=title,
                initialdir=initial or None,
                defaultextension=".xlsx",
                filetypes=[("Excel 工作簿", "*.xlsx"),
                           ("CSV 文件(UTF-8 BOM)", "*.csv"),
                           ("所有文件", "*.*")],
            )
        else:
            path = filedialog.askdirectory(title=title, initialdir=initial or None)
        return path or ""
    except Exception as e:
        sys.stderr.write(f"ERR:{e}\n")
        return ""
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    mode = args[0] if args else "dir"          # dir | save
    initial = args[1] if len(args) > 1 else ""
    title = args[2] if len(args) > 2 else "选择文件夹"
    outfile = args[3] if len(args) > 3 else ""

    path = pick(mode, initial, title)

    if outfile:
        try:
            with open(outfile, "w", encoding="utf-8") as f:
                f.write(path or "")
        except Exception as e:
            sys.stderr.write(f"ERR:write {e}\n")

    try:
        print(path or "")
        sys.stdout.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
