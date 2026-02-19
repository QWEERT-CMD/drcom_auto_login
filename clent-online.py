import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog
import threading
import time
import random
import requests
import json
import os
import base64
from requests.exceptions import Timeout, RequestException

last_ad_update = 0
AD_REFRESH_INTERVAL = 10

# 配置文件
VERSION_FN = 'version.yml'


def _version(path):
    return open(path, encoding='utf-8').read().strip()


# 服务器配置
SER_IP = ""
VER = ""
CFG = "comfig.yml"
debug = False


# ---------- 快速反馈功能 ----------
def quick_feedback():
    """快速反馈（简单对话框）"""
    feedback = simpledialog.askstring("快速反馈",
                                      "请输入您的反馈意见：\n（简短描述遇到的问题或建议）",
                                      parent=root)
    if feedback and feedback.strip():
        content = feedback.strip()
        if len(content) < 3:
            messagebox.showwarning("警告", "反馈内容太短，请至少输入3个字符")
            return

        def do_quick_submit():
            try:
                if SER_IP:
                    response = requests.post(
                        f"http://{SER_IP}:80/feedback",
                        data={"feedback": content},
                        timeout=10
                    )
                    if response.status_code == 200:
                        root.after(0, lambda: messagebox.showinfo("成功", "快速反馈已提交！"))
                        root.after(0, lambda: log.write("快速反馈已提交"))
                    else:
                        root.after(0, lambda: messagebox.showerror("失败", "提交失败，请稍后重试"))
                else:
                    root.after(0, lambda: messagebox.showinfo("提示", "反馈功能未配置"))
            except Exception as e:
                root.after(0, lambda: messagebox.showerror("错误", f"网络错误: {str(e)}"))

        threading.Thread(target=do_quick_submit, daemon=True).start()


try:
    new_ver = ""
    if SER_IP:
        new_ver = requests.get(f"http://{SER_IP}:80/update", timeout=5).text.strip()


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
        url_chk = ""
        url_login = ""
        while running:
            try:
                if debug == True:
                    set_status("网络连接正常（debug）", "lightgreen")
                    ip = "127.0.0.1"
                else:
                    if url_chk and url_login:
                        r = requests.get(url_chk, timeout=5)
                        data = json.loads(r.text[r.text.index("(") + 1: r.text.rindex(")")])
                        result, ip = data.get("result"), data.get("v46ip", "")
                        if result == 1:
                            set_status("网络连接正常", "lightgreen")

                        else:
                            set_status("已掉线，正在重连", "orange")
                            requests.get(url_login, timeout=5)
                    else:
                        set_status("网络配置未设置", "orange")
                        ip = ""
                # 在线人数
                if SER_IP and ip:
                    try:
                        hb = requests.get(f"http://{SER_IP}:80/heartbeat",
                                          params={"ip": ip, "user": content1[0], "pwd": content1[1], "pt": "pc"}, timeout=5)
                        if hb.text.split('%')[1] <= "5":
                            set_online(f"当前账号共在线 {hb.text.split('%')[1]} 人", "lightgreen")
                        else:
                            set_online(f"当前账号共在线 {hb.text.split('%')[1]} 人", "red")
                    except Exception:
                        set_online("无法获取在线人数", "orange")
                else:
                    set_online("无法获取在线人数", "orange")

                # 广告
                global last_ad_update
                now = time.time()
                if now - last_ad_update >= AD_REFRESH_INTERVAL:
                    try:
                        if SER_IP:
                            gg = requests.get(f"http://{SER_IP}:80/gg", timeout=5).text.strip().split('|')
                            set_ad(f"{random.choice(gg)}")
                            last_ad_update = now
                    except Exception:
                        pass
                # 版本

                if SER_IP:
                    if new_ver == VER:
                        set_ver(f"版本：{VER}", "lightgreen")
                    else:
                        set_ver(f"版本：{VER},最新：{new_ver}", "red")
                else:
                    set_ver("版本：未知", "lightgreen")

            except Exception as e:
                set_status("请求异常", "red");
                log.write(str(e))
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


    def set_ad(text):
        lbl_ad["text"] = text


    def set_ver(text, color):
        lbl_ver["text"] = text
        lbl_ver["bg"] = color


    # ---------- 主界面 ----------
    root = tk.Tk()
    root.title("网络认证助手")
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
    lbl_ad = tk.Label(root, text="--", bg="lightblue", font=("微软雅黑", 11))
    lbl_ad.pack(fill="x", padx=5, pady=2)

    lbl_gx = tk.Label(root, text="",
                      bg="lightgreen", font=("微软雅黑", 11))
    lbl_gx.pack(fill="x", padx=5, pady=2)

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
    tk.Button(btn_frame, text="快速反馈", command=quick_feedback, width=12).grid(row=0, column=4, padx=5)
    tk.Button(btn_frame, text="退出", command=root.destroy, width=12).grid(row=0, column=5, padx=5)

    # 初始化
    if not load_account():
        write_account()
    else:
        log.write("账号已加载，点击【开始认证】启动后台检测")
    root.mainloop()
except:
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
        url_chk = ""
        url_login = ""
        while running:
            try:
                if debug == True:
                    set_status("网络连接正常（debug）", "lightgreen")
                    ip = "127.0.0.1"
                else:
                    if url_chk and url_login:
                        r = requests.get(url_chk, timeout=5)
                        data = json.loads(r.text[r.text.index("(") + 1: r.text.rindex(")")])
                        result, ip = data.get("result"), data.get("v46ip", "")
                        if result == 1:
                            set_status("网络连接正常", "lightgreen")

                        else:
                            set_status("已掉线，正在重连", "orange")
                            requests.get(url_login, timeout=5)
                    else:
                        set_status("网络配置未设置", "orange")
                        ip = ""
                set_online("无法获取在线人数", "orange")
                # 在线人数

                # 广告
                global last_ad_update
                now = time.time()
                if now - last_ad_update >= AD_REFRESH_INTERVAL:
                    pass
                # 版本

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


    def set_ad(text):
        lbl_ad["text"] = text


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
    lbl_ad = tk.Label(root, text="--", bg="lightblue", font=("微软雅黑", 11))
    lbl_ad.pack(fill="x", padx=5, pady=2)
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
