import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog
import threading
import time
import json
import os
import base64

# 配置文件
CFG = "comfig.yml"
debug = False


# ---------- 日志重定向 ----------
class LogBox:
    def __init__(self, widget):
        self.widget = widget

    def write(self, s):
        if s.strip():
            self.widget.insert("end", f"{time.strftime('%m-%d %H:%M:%S')}  {s.strip()}\n")
            self.widget.see("end")

    def flush(self): pass


# ---------- 网络/认证 ----------
content1 = []


def load_account():
    global content1
    if not os.path.exists(CFG):
        return False
    try:
        with open(CFG, "rb") as f:
            content1 = base64.b64decode(f.read()).decode().split(",")
            lbl_usr["text"] = f"用户名: {content1[0]} \n密码: {content1[1]}"
            lbl_usr["bg"] = "lightgreen"
        return len(content1) == 2
    except Exception:
        os.remove(CFG);
        return False


def write_account():
    def save():
        user = e1.get().strip();
        pwd = e2.get().strip()
        if not user or not pwd: messagebox.showerror("错误", "不能为空"); return
        with open(CFG, "wb") as f:
            f.write(base64.b64encode(f"{user},{pwd}".encode()))
        top.destroy();
        load_account();
        log.write("账号已保存")

    top = tk.Toplevel();
    top.title("录入账号");
    top.geometry("400x250");
    top.wm_attributes("-topmost", True)
    tk.Label(top, text="用户名").pack(pady=5);
    e1 = tk.Entry(top);
    e1.pack()
    tk.Label(top, text="密码").pack(pady=5);
    e2 = tk.Entry(top, show="*");
    e2.pack()
    tk.Button(top, text="确定", command=save).pack(pady=10)
    top.wait_window()


def delete_account():
    try:
        os.remove(CFG); log.write("本地账号已删除")
    except:
        log.write("配置文件不存在")
    write_account()


# ---------- 后台心跳 ----------
running = False


def heartbeat():
    global running
    if not content1: log.write("未找到账号，请先录入"); return
    running = True
    url_chk = ""  # 网络状态检查URL
    url_login = ""  # 登录认证URL
    while running:
        try:
            if debug == True:
                set_status("网络连接正常（debug）", "lightgreen")
            else:
                if url_chk and url_login:
                    # 这里可以添加实际的网络检查和登录逻辑
                    # 由于是离线模式，这里仅做示例
                    set_status("网络连接正常", "lightgreen")
                else:
                    set_status("网络配置未设置", "orange")
            set_online("离线模式", "orange")
            set_ver("版本：未知", "lightgreen")

        except Exception as e:
            set_status("离线模式", "orange")
        time.sleep(1)


def start_auth():
    if not content1: log.write("未录入账号"); return
    threading.Thread(target=heartbeat, daemon=True).start()
    log.write("后台认证已启动")


def stop_auth():
    global running
    running = False
    log.write("后台认证已停止")


# ---------- UI 刷新 ----------
def set_status(text, color):
    lbl_status["text"] = text
    lbl_status["bg"] = color


def set_online(text, color):
    lbl_online["text"] = text
    lbl_online["bg"] = color


def set_ver(text, color):
    lbl_ver["text"] = text
    lbl_ver["bg"] = color


# ---------- 主界面 ----------
root = tk.Tk()
root.title("网络认证助手(离线)")
root.geometry("700x500")

# 顶部状态条
status_frame = tk.Frame(root)
status_frame.pack(fill="x", padx=5, pady=5)

lbl_status = tk.Label(status_frame, text="等待认证", bg="lightblue", font=("微软雅黑", 12))
lbl_status.pack(side="left", fill="x", expand=True)

lbl_online = tk.Label(status_frame, text="在线：--", bg="lightblue", font=("微软雅黑", 12))
lbl_online.pack(side="left", padx=10)

lbl_usr = tk.Label(status_frame, text="用户信息：--", bg="lightblue", font=("微软雅黑", 12))
lbl_usr.pack(side="left", padx=10)

# 日志区
log_box = scrolledtext.ScrolledText(root, height=12, state='normal')
log_box.pack(fill="both", expand=True, padx=5, pady=5)
log = LogBox(log_box)

# 底部信息
lbl_ver = tk.Label(root, text="版本：未知", bg="lightgreen", font=("微软雅黑", 11))
lbl_ver.pack(fill="x", padx=5, pady=2)

lbl_elua = tk.Label(root,
                    text="本程序用于网络自动认证\n本程序仅供个人学习和参考，请勿用做其他用途",
                    bg="lightblue", font=("微软雅黑", 11))
lbl_elua.pack(fill="x", padx=5, pady=2)

# 按钮
btn_frame = tk.Frame(root)
btn_frame.pack(pady=5)
tk.Button(btn_frame, text="开始认证", bg="green", command=start_auth, width=12).grid(row=0, column=0, padx=5)
tk.Button(btn_frame, text="停止登录", bg="red", command=stop_auth, width=12).grid(row=0, column=1, padx=5)
tk.Button(btn_frame, text="重新录入", command=write_account, width=12).grid(row=0, column=2, padx=5)
tk.Button(btn_frame, text="删除账号", command=delete_account, width=12).grid(row=0, column=3, padx=5)
tk.Button(btn_frame, text="快速反馈", command=lambda: messagebox.showinfo("提示", "离线模式下无法提交反馈"),
          width=12).grid(row=0, column=4, padx=5)
tk.Button(btn_frame, text="退出", command=root.destroy, width=12).grid(row=0, column=5, padx=5)

# 初始化
if not load_account():
    write_account()
else:
    log.write("账号已加载，点击【开始认证】启动后台检测")

root.mainloop()
