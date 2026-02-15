#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
from aiohttp import web
from urllib.parse import parse_qs
import json
import time
import subprocess as sp
import re
import os
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import psutil
import aiofiles
from io import BytesIO
from collections import Counter
from cachetools import TTLCache
import csv
import tempfile

# ------------------ 配置 ------------------
CONFIG_FILE = 'count.yml'   #记录使用过客户端的ip
LOG_FILE    = 'user_count_log.json'   #记录没小时在线人数，用于统计
FEEDBACK_FILE='feedback.txt'  #记录用户的反馈内容
SPEED_LOG_FILE='speedlog.csv'   #小时测速记录
SPEED_ENDPOINT = ''      #测速服务器
CACHE_TTL   = 300
response_cache = TTLCache(maxsize=100, ttl=CACHE_TTL)
clients = {}
web_port=80          #web服务端口
if not os.path.exists(CONFIG_FILE):
    open(CONFIG_FILE, 'w').close()
    open(LOG_FILE, 'w').close()
    open(FEEDBACK_FILE, 'w').close()
    open(SPEED_LOG_FILE, 'w').close()

# ------------------ 工具 ------------------
async def add_client_id(ip, filename=CONFIG_FILE):
    try:
        if not os.path.exists(filename):
            async with aiofiles.open(filename, 'w') as f: await f.write('')
        async with aiofiles.open(filename, 'r', encoding='utf-8') as f:
            exist = f.read().strip().split(',')
        if ip in exist: return
        async with aiofiles.open(filename, 'a', encoding='utf-8') as f:
            await f.write(f"{ip},")
    except Exception as e:
        print(f"添加客户端ID错误: {e}")

async def save_feedback(ip, feedback_text):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out = f"[{ts}] IP: {ip}\n反馈内容: {feedback_text}\n{'-'*50}\n"
        async with aiofiles.open(FEEDBACK_FILE, 'a', encoding='utf-8') as f:
            await f.write(out)
        return True
    except Exception as e:
        print(f"保存反馈错误: {e}")
        return False

def count_keys_with_specific_user(nested_dict, specific_user):
    return [v.get('user') for v in nested_dict.values()].count(specific_user)

def sig_bar(dbm: int) -> str:
    if dbm >= -50: return "▂▄▆█"
    if dbm >= -60: return "▂▄▆ "
    if dbm >= -70: return "▂▄  "
    return "▂   "

async def sys_status():
    with open("/proc/stat") as f: cpu1 = f.readline()
    idle1 = sum(int(x) for x in cpu1.split()[4:8])
    total1 = sum(int(x) for x in cpu1.split()[1:])
    await asyncio.sleep(1)
    with open("/proc/stat") as f: cpu2 = f.readline()
    idle2 = sum(int(x) for x in cpu2.split()[4:8])
    total2 = sum(int(x) for x in cpu2.split()[1:])
    cpu_usage = 100 * (1 - (idle2 - idle1) / (total2 - total1))
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"): mem["total"] = int(line.split()[1]) // 1024
            elif line.startswith("MemAvailable:"): mem["avail"] = int(line.split()[1]) // 1024
    mem["used"] = mem["total"] - mem["avail"]
    load = os.getloadavg()[0]
    uptime = int(sp.check_output("awk '{print int($1)}' /proc/uptime", shell=True).decode().strip() or 0)
    uptime_h = uptime // 3600; uptime_m = (uptime % 3600) // 60
    return f"CPU:{cpu_usage:4.1f}%  内存:{mem['used']}/{mem['total']}MB  负载:{load:.2f}  运行:{uptime_h}h{uptime_m}m"

def html_snapshot(text):
    import html
    return html.escape(text).replace("\n", "<br>\n")

# ------------------ Wi-Fi 扫描 ------------------
scan_lock = asyncio.Lock()
async def scan_only():
    async with scan_lock:
        cache_key = "wifi_scan"
        if cache_key in response_cache: return response_cache[cache_key]
        iface = "wlan0"
        if not iface: return "未找到无线接口"
        try:
            proc = await asyncio.create_subprocess_shell(
                f"sudo iw dev {iface} scan passive",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if stderr and "passive" in stderr.decode():
                proc = await asyncio.create_subprocess_shell(
                    f"sudo iw dev {iface} scan",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if stderr:
                result = f"扫描失败: {stderr.decode()}"
                response_cache[cache_key] = result; return result
            raw = stdout.decode()
            if not raw:
                result = "扫描失败"
                response_cache[cache_key] = result; return result
            aps = []; block = {}
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("BSS "):
                    if block: aps.append(block)
                    block = {"bssid": line.split()[1].rstrip(":")}
                if "SSID:" in line and not line.startswith("Supported"):
                    block["ssid"] = line.split(":", 1)[1].strip()
                if "signal:" in line:
                    block["sig"] = int(float(re.search(r"signal:\s*([-0-9.]+)", line).group(1)))
                if "DS Parameter set: channel " in line:
                    block["chan"] = int(line.split()[-1])
            if block: aps.append(block)
            out = ["=" * 60, await sys_status(), "=" * 60,
                   f"周边 Wi-Fi 数量：{len(aps)}",
                   "信号  SSID                      信道  BSSID"]
            out.append("-" * 65)
            for ap in aps:
                dbm = ap.get("sig", -999)
                out.append(f"{sig_bar(dbm)}  "
                           f"{ap.get('ssid', 'Hidden'):<25}  "
                           f"{ap.get('chan', ''):>4}  "
                           f"{ap.get('bssid', '')}")
            result = "\n".join(out)
            response_cache[cache_key] = result; return result
        except asyncio.TimeoutError:
            result = "扫描超时"
            response_cache[cache_key] = result; return result
        except Exception as e:
            result = f"扫描失败: {str(e)}"
            response_cache[cache_key] = result; return result

# ------------------ 后台任务 ------------------
async def cleanup_clients():
    while True:
        try:
            current_time = time.time()
            expired = [cid for cid, data in clients.items() if current_time - data['timestamp'] > 20]
            for cid in expired: del clients[cid]
            await asyncio.sleep(10)
        except Exception as e:
            print(f"清理客户端错误: {e}")
            await asyncio.sleep(10)

async def save_user_count():
    while True:
        try:
            now = datetime.now()
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            await asyncio.sleep((next_hour - now).total_seconds())
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            user_count = len(clients)
            data = {"timestamp": current_time, "user_count": user_count}
            async with aiofiles.open(LOG_FILE, "a", encoding='utf-8') as f:
                await f.write(json.dumps(data, ensure_ascii=False) + "\n")
            for k in list(response_cache.keys()):
                if 'plot' in str(k) or 'pie' in str(k): del response_cache[k]
        except Exception as e:
            print(f"保存用户数量错误: {e}")
            await asyncio.sleep(60)

# ------------------ 画图 ------------------
async def generate_line_plot():
    cache_key = "line_plot"
    if cache_key in response_cache: return response_cache[cache_key]
    try:
        async with aiofiles.open(LOG_FILE, "r", encoding="utf-8") as f:
            raw = await f.read()
        objs = [json.loads(l) for l in raw.strip().splitlines() if l.strip()]
        ts = [datetime.strptime(o['timestamp'], '%Y-%m-%d %H:%M:%S') for o in objs]
        us = [o['user_count'] for o in objs]
        plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        plt.figure(figsize=(10, 5))
        plt.plot(ts, us, marker='o', linestyle='-', color='b', label='用户数量')
        plt.title('user/time'); plt.xlabel('time'); plt.ylabel('user')
        plt.legend(); plt.grid(True); plt.tight_layout()
        buf = BytesIO(); plt.savefig(buf, format='png', dpi=80); plt.close()
        img = buf.getvalue(); buf.close()
        response_cache[cache_key] = img; return img
    except Exception as e:
        plt.figure(figsize=(10, 5)); plt.text(0.5, 0.5, 'none', ha='center'); plt.axis('off')
        buf = BytesIO(); plt.savefig(buf, format='png'); plt.close(); img = buf.getvalue(); buf.close(); return img

async def generate_user_pie():
    cache_key = "user_pie"
    if cache_key in response_cache: return response_cache[cache_key]
    try:
        cnt = Counter(data['user'] for data in clients.values() if data.get('user'))
        plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        if not cnt:
            plt.figure(figsize=(4, 4)); plt.text(0.5, 0.5, 'None', ha='center'); plt.axis('off')
        else:
            labels, sizes = zip(*cnt.items())
            plt.figure(figsize=(5, 5)); plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, shadow=True); plt.title('user'); plt.axis('equal')
        buf = BytesIO(); plt.savefig(buf, format='png', dpi=80); plt.close(); img = buf.getvalue(); buf.close()
        response_cache[cache_key] = img; return img
    except Exception as e:
        plt.figure(figsize=(4, 4)); plt.text(0.5, 0.5, '生成错误', ha='center'); plt.axis('off')
        buf = BytesIO(); plt.savefig(buf, format='png'); plt.close(); img = buf.getvalue(); buf.close(); return img

# ------------------ 速度监控 ------------------

async def speed_test():
    cache_key = "speed_test_result"
    if cache_key in response_cache: return response_cache[cache_key]
    try:
        srv = [{"id": 1, "name": "self", "server": SPEED_ENDPOINT,
                "dlURL": "backend/garbage.php", "ulURL": "backend/empty.php",
                "pingURL": "backend/empty.php", "getIpURL": "backend/getIP.php"}]
        proc = await asyncio.create_subprocess_exec(
            './librespeed-cli', '--local-json', '-', '--csv',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate(input=json.dumps(srv).encode())
        if proc.returncode != 0:
            result = f"测速失败: {stderr.decode()[:100]}"
            response_cache[cache_key] = result; return result
        parts = stdout.decode().strip().split(',')
        ts = parts[0].split('+')[0] if '+' in parts[0] else parts[0] if parts else datetime.now().isoformat()+'Z'
        ping = float(parts[4]) if len(parts)>4 and parts[4] else 0.0
        down = float(parts[5]) if len(parts)>5 and parts[5] else 0.0
        up   = float(parts[6]) if len(parts)>6 and parts[6] else 0.0
        await save_speed_log(ts, ping, down, up)
        result = {'timestamp': ts, 'ping_ms': ping, 'download_Mbps': down, 'upload_Mbps': up}
        response_cache[cache_key] = result; return result
    except Exception as e:
        result = f"测速异常: {str(e)}"
        response_cache[cache_key] = result; return result

async def save_speed_log(ts, ping, down, up):
    try:
        exists = os.path.exists(SPEED_LOG_FILE)
        with open(SPEED_LOG_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            if not exists: writer.writerow(['timestamp', 'ping_ms', 'download_Mbps', 'upload_Mbps'])
            writer.writerow([ts, ping, down, up])
    except Exception as e:
        print(f"[速度日志] 保存错误: {e}")

async def generate_speed_chart():
    cache_key = "speed_chart"
    if cache_key in response_cache: return response_cache[cache_key]
    if not os.path.exists(SPEED_LOG_FILE):
        plt.figure(figsize=(10, 4)); plt.text(0.5, 0.5, '暂无速度数据', ha='center'); plt.axis('off')
        buf = BytesIO(); plt.savefig(buf, format='png', dpi=80); plt.close(); img = buf.getvalue(); buf.close(); return img
    try:
        times, pings, downs, ups = [], [], [], []
        cutoff = datetime.now() - timedelta(hours=12)          # 仅保留近 12 小时
        with open(SPEED_LOG_FILE, 'r') as f:
            reader = csv.reader(f); next(reader, None)
            for row in reader:
                if len(row) >= 4:
                    try:
                        dt = datetime.fromisoformat(row[0].replace('Z', ''))
                        if dt >= cutoff:
                            times.append(dt); pings.append(float(row[1])); downs.append(float(row[2])); ups.append(float(row[3]))
                    except:
                        continue
        if len(times) < 2:
            plt.figure(figsize=(10, 4)); plt.text(0.5, 0.5, '数据不足，请等待更多测试', ha='center'); plt.axis('off')
            buf = BytesIO(); plt.savefig(buf, format='png', dpi=80); plt.close(); img = buf.getvalue(); buf.close(); return img
        plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']; plt.rcParams['axes.unicode_minus'] = False
        fig, ax = plt.subplots(figsize=(10, 4))
        if downs: ax.plot(times, downs, label='download (Mbps)', color='#2E8B57', linewidth=1.5)
        if ups:   ax.plot(times, ups,   label='upload (Mbps)',   color='#1F77B4', linewidth=1.5)
        if pings: ax.plot(times, pings, label='ping (ms)',       color='#FF6F00', linewidth=1.2, alpha=0.8)
        ax.set_ylabel('speed / ping'); ax.set_xlabel('time (UTC)'); ax.grid(True, alpha=0.2); ax.legend(loc='upper left', fontsize=9)
        from matplotlib.dates import DateFormatter; ax.xaxis.set_major_formatter(DateFormatter('%H:%M')); plt.xticks(rotation=30, fontsize=8); plt.tight_layout()
        temp_fd, temp_path = tempfile.mkstemp(suffix='.png'); os.close(temp_fd); plt.savefig(temp_path, dpi=80, bbox_inches='tight'); plt.close(fig)
        with open(temp_path, 'rb') as f: img = f.read(); os.remove(temp_path); response_cache[cache_key] = img; return img
    except Exception as e:
        print(f"[速度图表] 生成错误: {e}")
        plt.figure(figsize=(10, 4)); plt.text(0.5, 0.5, '图表生成失败', ha='center'); plt.axis('off')
        buf = BytesIO(); plt.savefig(buf, format='png'); plt.close(); img = buf.getvalue(); buf.close(); return img

async def speed_monitor_task():
    while True:
        try:
            await asyncio.sleep(3600)           # 整点测速
            print(f"[速度监控] 定时测试开始 ({datetime.now().strftime('%H:%M:%S')})")
            result = await speed_test()
            if isinstance(result, dict):
                print(f"[速度监控] 完成 - Ping: {result['ping_ms']:.1f}ms, Down: {result['download_Mbps']:.2f}Mbps, Up: {result['upload_Mbps']:.2f}Mbps")
                if "speed_chart" in response_cache: del response_cache["speed_chart"]
            else:
                print(f"[速度监控] 失败: {result}")
        except Exception as e:
            print(f"[速度监控] 任务错误: {e}")
            await asyncio.sleep(300)

# ------------------ 路由 ------------------
def get_pt_by_ip(data: dict, ip: str) -> str:
    return data.get(ip, {}).get('pt') or '未知'

async def handle(request):
    path = request.path
    query_params = parse_qs(request.query_string)
    client_ip = request.transport.get_extra_info('peername')[0]
    print(f"\033[94m[请求] {client_ip} - {path}\033[0m")
    try:
        # ---- 前端轮询接口 ----
        if path == '/api/status':
            active_clients = await get_active_clients()
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            speed_result = await speed_test()
            async with aiofiles.open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                content = await f.read()
            total_devices = max(0, len(content.split(',')) - 1)
            return web.Response(text=json.dumps({
                'total_devices': total_devices,
                'online': len(active_clients),
                'cpu': round(cpu, 1),
                'mem_used': mem.used // 1024 // 1024,
                'mem_total': mem.total // 1024 // 1024,
                'ping_ms':  speed_result.get('ping_ms')   if isinstance(speed_result, dict) else None,
                'down_mbps':speed_result.get('download_Mbps') if isinstance(speed_result, dict) else None,
                'up_mbps':  speed_result.get('upload_Mbps')   if isinstance(speed_result, dict) else None,
                'users': [{'ip':ip, 'pt':data.get('pt') or '未知'} for ip,data in active_clients.items()]
            }, ensure_ascii=False), content_type='application/json')

        if path == '/':
            active_clients = await get_active_clients()
            async with aiofiles.open(CONFIG_FILE, "r", encoding='utf-8') as fi:
                content = await fi.read()
                total_devices = max(0, len(content.split(",")) - 1)
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            used, total = mem.used // 1024 // 1024, mem.total // 1024 // 1024
            speed_result = await speed_test()
            # 修复：为速度数值添加 id 属性，使前端JS可以更新
            speed_info = f"""
                <div class="stat-card"><div class="stat-number" id="ping-ms">{speed_result.get('ping_ms','--')}ms</div><div class="stat-label">网络延迟</div></div>
                <div class="stat-card"><div class="stat-number" id="down-mbps">{speed_result.get('download_Mbps','--')}</div><div class="stat-label">下载速度(Mbps)</div></div>
                <div class="stat-card"><div class="stat-number" id="up-mbps">{speed_result.get('upload_Mbps','--')}</div><div class="stat-label">上传速度(Mbps)</div></div>
            """ if isinstance(speed_result, dict) else """
                <div class="stat-card"><div class="stat-number" id="ping-ms">--</div><div class="stat-label">网络延迟</div></div>
                <div class="stat-card"><div class="stat-number" id="down-mbps">--</div><div class="stat-label">下载速度(Mbps)</div></div>
                <div class="stat-card"><div class="stat-number" id="up-mbps">--</div><div class="stat-label">上传速度(Mbps)</div></div>
            """
            import subprocess
            def run_neofetch():
                try:
                    return subprocess.run(["neofetch", "--color_blocks", "off", "--stdout"],
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          text=True, check=False).stdout
                except FileNotFoundError:
                    return "neofetch 未安装"
            neofetch_text = run_neofetch()
            neofetch_html = (
                '<div class="neofetch-card" style="background:rgba(255,255,255,.08);border-radius:15px;padding:20px;margin:20px 30px;box-shadow:0 8px 32px rgba(0,0,0,.2);backdrop-filter:blur(5px);border:1px solid rgba(255,255,255,.1);">'
                '<div class="neofetch-title" style="font-size:1.4em;color:#e0f7fa;margin-bottom:15px;font-weight:500;text-align:center;">🖥️ 本机系统信息（neofetch）</div>'
                "<pre style='white-space:pre-wrap;font-size:12px;color:#e0f7fa;'>" +
                neofetch_text.replace("<", "&lt;").replace(">", "&gt;") + "</pre></div>"
            )
            mouse_trail_html = ""  # 原星光轨迹代码太长，此处省略，保持与原文件一致即可
            # 关键修复：用 r""" 包裹整段 HTML/JS，避免 Python 解析 JS 关键字
            response_html = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>设备监控系统</title>
<style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{
        font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",sans-serif,"Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol","Noto Color Emoji";
        background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);
        min-height:100vh;padding:20px;color:#e0f7fa;
    }
    .container{
        max-width:1200px;margin:0 auto;background:rgba(255,255,255,.08);backdrop-filter:blur(12px);
        border-radius:20px;border:1px solid rgba(255,255,255,.18);box-shadow:0 20px 40px rgba(0,0,0,.3);overflow:hidden;
    }
    .header{
        background:linear-gradient(135deg,rgba(16,141,199,.8),rgba(0,200,200,.6));color:#fff;padding:40px 30px;text-align:center;position:relative;border-bottom:1px solid rgba(255,255,255,.2);
    }
    .header::before{
        content:"";position:absolute;top:0;left:0;right:0;bottom:0;background:url('data:image/svg+xml,%3Csvg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 100 100\"%3E%3Ccircle cx=\"20\" cy=\"20\" r=\"2\" fill=\"rgba(255,255,255,.1)\"/%3E%3Ccircle cx=\"80\" cy=\"40\" r=\"1.5\" fill=\"rgba(255,255,255,.1)\"/%3E%3Ccircle cx=\"40\" cy=\"80\" r=\"1\" fill=\"rgba(255,255,255,.1)\"/%3E%3C/svg%3E');animation:float 20s infinite linear;
    }
    @keyframes float{0%{transform:translateY(0)}100%{transform:translateY(-100px)}}
    .header h1{font-size:2.5em;margin-bottom:10px;position:relative;z-index:1;text-shadow:0 2px 4px rgba(0,0,0,.2)}
    .header h2{font-size:1.2em;opacity:.9;margin:10px 0;position:relative;z-index:1;font-weight:300}
    .stats-container{
        display:flex;justify-content:space-around;padding:30px;background:rgba(255,255,255,.05);flex-wrap:wrap;gap:20px;border-bottom:1px solid rgba(255,255,255,.1);
    }
    .stat-card{
        background:rgba(255,255,255,.1);padding:25px;border-radius:15px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.2);transition:all .3s ease;min-width:200px;flex:1;backdrop-filter:blur(5px);border:1px solid rgba(255,255,255,.15);
    }
    .stat-card:hover{transform:translateY(-5px);box-shadow:0 12px 40px rgba(0,0,0,.3);background:rgba(255,255,255,.15)}
    .stat-number{font-size:2.5em;font-weight:700;color:#4fc3f7;margin-bottom:10px;text-shadow:0 0 10px rgba(79,195,247,.5)}
    .stat-number1{font-size:1.6em;font-weight:700;color:#4fc3f7;margin-bottom:10px;text-shadow:0 0 10px rgba(79,195,247,.5)}
    .stat-label{color:#b3e5fc;font-size:1.1em;font-weight:500}
    .stat-label1{color:#b3e5fc;font-size:0.9em;font-weight:500}
    .users-section{padding:30px}
    .section-title{font-size:1.8em;color:#e0f7fa;margin-bottom:25px;text-align:center;position:relative;font-weight:300}
    .section-title::after{
        content:"";position:absolute;bottom:-10px;left:50%;transform:translateX(-50%);width:60px;height:2px;background:linear-gradient(90deg,transparent,#4fc3f7,transparent);
    }
    .users-grid{
        display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px;margin-bottom:40px;
    }
    .user-card{
        background:rgba(255,255,255,.08);border-radius:15px;padding:20px;box-shadow:0 8px 32px rgba(0,0,0,.2);transition:all .3s ease;border-left:4px solid #4fc3f7;position:relative;overflow:hidden;backdrop-filter:blur(5px);border:1px solid rgba(255,255,255,.1);
    }
    .user-card:hover{transform:translateY(-5px);box-shadow:0 15px 40px rgba(0,0,0,.3);background:rgba(255,255,255,.12)}
    .user-ip{font-size:1.2em;font-weight:600;color:#e0f7fa;margin-bottom:10px}
    .user-status{
        display:inline-block;padding:5px 12px;border-radius:20px;font-size:.9em;font-weight:500;background:rgba(0,200,83,.2);color:#00c853;border:1px solid rgba(0,200,83,.3);
    }
    .user-status.offline{background:rgba(244,67,54,.2);color:#f44336;border:1px solid rgba(244,67,54,.3)}
    .charts-container{
        display:flex;flex-wrap:wrap;gap:30px;justify-content:center;padding:30px;background:rgba(255,255,255,.05);border-top:1px solid rgba(255,255,255,.1);
    }
    .chart-wrapper{
        background:rgba(255,255,255,.08);border-radius:15px;padding:20px;box-shadow:0 8px 32px rgba(0,0,0,.2);text-align:center;transition:all .3s ease;backdrop-filter:blur(5px);border:1px solid rgba(255,255,255,.1);
    }
    .chart-wrapper:hover{transform:translateY(-5px);box-shadow:0 15px 40px rgba(0,0,0,.3);background:rgba(255,255,255,.12)}
    .chart-wrapper img{max-width:100%;height:auto;border-radius:10px}
    .chart-title{font-size:1.3em;color:#e0f7fa;margin-bottom:15px;font-weight:500}
    .feedback-section{
        padding:30px;background:rgba(255,255,255,.05);border-top:1px solid rgba(255,255,255,.1);
    }
    .feedback-form{
        max-width:600px;margin:0 auto;background:rgba(255,255,255,.08);padding:25px;border-radius:15px;box-shadow:0 8px 32px rgba(0,0,0,.2);backdrop-filter:blur(5px);border:1px solid rgba(255,255,255,.1);
    }
    .feedback-title{font-size:1.5em;color:#e0f7fa;margin-bottom:20px;text-align:center}
    .form-group{margin-bottom:20px}
    .form-label{display:block;color:#b3e5fc;margin-bottom:8px;font-weight:500}
    .form-textarea{
        width:100%;min-height:120px;padding:12px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:8px;color:#e0f7fa;font-size:14px;resize:vertical;transition:all .3s ease;
    }
    .form-textarea:focus{outline:none;border-color:#4fc3f7;box-shadow:0 0 0 2px rgba(79,195,247,.2);background:rgba(255,255,255,.15)}
    .form-submit{
        background:linear-gradient(135deg,#4fc3f7,#29b6f6);color:white;border:none;padding:12px 30px;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;transition:all .3s ease;width:100%;
    }
    .form-submit:hover{transform:translateY(-2px);box-shadow:0 5px 15px rgba(41,182,246,.4)}
    .form-submit:active{transform:translateY(0)}
    .success-message{
        background:rgba(76,175,80,.2);border:1px solid rgba(76,175,80,.3);color:#4caf50;padding:12px;border-radius:8px;text-align:center;margin-top:15px;
    }
    @media (max-width:768px){
        .header h1{font-size:2em}
        .stats-container{flex-direction:column;align-items:center}
        .users-grid{grid-template-columns:1fr}
        .charts-container{flex-direction:column;align-items:center}
    }
    .fade-in{animation:fadeIn .8s ease-in}@keyframes fadeIn{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
</style>
</head>
<body>
<div class="container fade-in">
    <div class="header">
        <h1>🖥️ 设备监控系统</h1>
        <h2>实时在线用户管理面板</h2>
       
    </div>

    <div class="stats-container" id="stats-container">
        <div class="feedback-form">
            <h3 class="feedback-title">最新版本下载</h3>
            <a href="下载链接" style="display:inline-block; text-align:center;
          width:120px; line-height:36px; background:#4fc3f7; color:#fff;
          text-decoration:none; border-radius:4px;" target="_blank">电脑版下载<br></a>
            <a href="下载链接 " style="display:inline-block; text-align:center;
          width:120px; line-height:36px; background:#4fc3f7; color:#fff;
          text-decoration:none; border-radius:4px;" target="_blank">手机版下载</a>
            <div id="message" style="display:none;"></div>
        </div>
        <div class="stat-card pulse">
            <div class="stat-number" id="total-devices">""" + str(total_devices) + r"""</div>
            <div class="stat-label">总设备数</div>
            <div class="stat-label1">共有""" + str(total_devices) + r"""台设备使用过改程序</div>
        </div>
        <div class="stat-card">
            <div class="stat-number" id="online-count">""" + str(len(active_clients)) + r"""</div>
            <div class="stat-label">当前在线</div>
        </div>
        <div class="stat-card">
            <div class="stat-number1" id="cpu-mem">CPU:""" + f"{cpu:.1f}" + r"""%<br>内存:""" + f"{used}/{total}" + r"""MB</div>
            <div class="stat-label1">资源占用</div>
        </div>
        """ + speed_info + r"""
    </div>

    <div class="users-section">
        <h2 class="section-title">👥 活跃用户列表</h2>
        <div class="users-grid" id="users-grid">
            """ + ''.join(f'<div class="user-card fade-in"><div class="user-ip">📍 {client}</div><span class="user-status online">🟢 {get_pt_by_ip(clients, client)}</span></div>' for client, data in active_clients.items()) + r"""
        </div>
    </div>

    <div class="charts-container">
        <div class="chart-wrapper">
            <h3 class="chart-title">📊 用户在线趋势</h3>
            <img src="/line_plot.png?t=""" + str(int(time.time())) + r"""\" alt="用户在线趋势图" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAwIiBoZWlnaHQ9IjMwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNDAwIiBoZWlnaHQ9IjMwMCIgZmlsbD0iI2Y4ZjlmYSIvPjx0ZXh0IHg9IjIwMCIgeT0iMTUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjE2IiBmaWxsPSIjNjY2Ij7nkIblrZDlpJblsYLoioI8L3RleHQ+PC9zdmc+'">
        </div>
        <div class="chart-wrapper">
            <h3 class="chart-title">🥧 用户账号使用情况图</h3>
            <img src="/user_pie.png?t=""" + str(int(time.time())) + r"""\" alt="用户账号使用情况图" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAwIiBoZWlnaHQ9IjMwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNDAwIiBoZWlnaHQ9IjMwMCIgZmlsbD0iI2Y4ZjlmYSIvPjx0ZXh0IHg9IjIwMCIgeT0iMTUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjE2IiBmaWxsPSIjNjY2Ij7nkIblrZDlpJblsYLoioI8L3RleHQ+PC9zdmc+'">
        </div>
        <div class="chart-wrapper">
            <h3 class="chart-title">🚀 12小时速度监控</h3>
            <img src="/speed_chart.png?t=""" + str(int(time.time())) + r"""\" alt="网络速度图表" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAwIiBoZWlnaHQ9IjMwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNDAwIiBoZWlnaHQ9IjMwMCIgZmlsbD0iI2Y4ZjlmYSIvPjx0ZXh0IHg9IjIwMCIgeT0iMTUwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBkeT0iLjNlbSIgZm9udC1mYW1pbHk9IkFyaWFsIiBmb250LXNpemU9IjE2IiBmaWxsPSIjNjY2Ij7nkIblrZDlpJblsYLoioI8L3RleHQ+PC9zdmc+'">
            <div style="margin-top:10px;">
                <button onclick="window.location.href='/'" style="background:#4CAF50;color:white;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;">刷新图表</button>
            </div>
        </div>
    </div>

    <div class="feedback-section">
        <div class="feedback-form">
            <h3 class="feedback-title">💬 意见反馈</h3>
            <form id="feedbackForm" action="/feedback" method="post">
                <div class="form-group">
                    <label class="form-label" for="feedback">您的宝贵意见：</label>
                    <textarea class="form-textarea" id="feedback" name="feedback" placeholder="请输入您的反馈意见、建议或遇到的问题..." required></textarea>
                </div>
                <button type="submit" class="form-submit">提交反馈</button>
            </form>
            <div id="message" style="display:none;"></div>
        </div>
    </div>
    """ + neofetch_html + r"""
</div>
<canvas id="mouse-trail" style="position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:9999"></canvas>
""" + mouse_trail_html + r"""
<script>
document.getElementById('feedbackForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    const submitButton = form.querySelector('button[type="submit"]');
    const messageDiv = document.getElementById('message');
    submitButton.disabled = true;
    submitButton.textContent = '提交中...';
    try {
        const response = await fetch('/feedback', { method: 'POST', body: formData });
        if (response.ok) {
            messageDiv.innerHTML = '<div class="success-message">✅ 感谢您的反馈！我们已收到您的意见。</div>';
            messageDiv.style.display = 'block';
            form.reset();
            setTimeout(() => { messageDiv.style.display = 'none'; }, 3000);
        } else {
            throw new Error('提交失败');
        }
    } catch (error) {
        messageDiv.innerHTML = '<div style="background:rgba(244,67,54,.2);border:1px solid rgba(244,67,54,.3);color:#f44336;padding:12px;border-radius:8px;text-align:center;">❌ 提交失败，请稍后重试</div>';
        messageDiv.style.display = 'block';
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = '提交反馈';
    }
});
setInterval(async () => {
    try {
        const r = await fetch('/api/status');
        const d = await r.json();
        document.getElementById('total-devices').textContent        = d.total_devices;
        document.getElementById('online-count').textContent         = d.online;
        document.getElementById('cpu-mem').innerHTML                = `CPU:${d.cpu}%<br>内存:${d.mem_used}/${d.mem_total}MB`;
        document.getElementById('ping-ms').textContent              = d.ping_ms == null ? '--' : d.ping_ms.toFixed(1)+'ms';
        document.getElementById('down-mbps').textContent            = d.down_mbps == null ? '--' : d.down_mbps.toFixed(1);
        document.getElementById('up-mbps').textContent              = d.up_mbps == null ? '--' : d.up_mbps.toFixed(1);
        const grid = document.getElementById('users-grid');
        grid.innerHTML = d.users.map(u => `
          <div class="user-card fade-in">
            <div class="user-ip">📍 ${u.ip}</div>
            <span class="user-status online">🟢 ${u.pt}</span>
          </div>`).join('');
    } catch(e){}
}, 5000);
setInterval(() => {
    ['line_plot','user_pie','speed_chart'].forEach(n=>{
        const img = document.querySelector(`img[alt*="${n.replace('_','')}"]`);
        if(img) img.src = `/${n}.png?t=${Date.now()}`;
    });
}, 60000);
</script>
</body>
</html>"""
            return web.Response(text=response_html, content_type='text/html')

        elif path == '/line_plot.png':
            img = await generate_line_plot(); return web.Response(body=img, content_type='image/png')
        elif path == '/user_pie.png':
            img = await generate_user_pie(); return web.Response(body=img, content_type='image/png')
        elif path == '/speed_chart.png':
            img = await generate_speed_chart(); return web.Response(body=img, content_type='image/png')
        elif path == '/speedtest_now':
            # 取消手动测速，仅保留整点测速
            return web.Response(text=json.dumps({'status': 'info', 'message': '测速已关闭，仅保留整点自动测速'}), content_type='application/json')
        elif path == '/server':
            snapshot = await scan_only(); return web.Response(text=html_snapshot(snapshot), content_type='text/html')
        elif path == '/gg':
            return web.Response(text="我是小贴士", content_type='text/html')      #小贴士内容
        elif path == '/rs':
            active_clients = await get_active_clients()
            return web.Response(text= str(len(active_clients)) , content_type='text/html')
        elif path == '/admin/admin':
            items = list(clients.items()); req = "\n".join(f"<ul> {ip}: {data} </ul>" for ip, data in items)
            return web.Response(text=f"<html><head><title>用户列表(ip)(管理员)</title></head><body><h1>用户列表(ip)</h1>{req}</body></html>", content_type='text/html')
        elif path == '/heartbeat':
            client_id = query_params.get('ip', ['unknown'])[0]
            clients[client_id] = {'timestamp': time.time(), 'user': query_params.get('user', [''])[0], 'pwd': query_params.get('pwd', [''])[0], 'pt': query_params.get('pt', [''])[0]}
            await add_client_id(client_id)
            for k in list(response_cache.keys()):
                if 'pie' in str(k) or 'homepage' in str(k): del response_cache[k]
            return web.Response(text=f"<html><head><title>Heartbeat</title></head><body><h1>Heartbeat Received</h1><p>ip: {client_id}</p><p>user: {clients[client_id]['user']}</p><p>pwd: {clients[client_id]['pwd']}</p><p>%%{count_keys_with_specific_user(clients, clients[client_id]['user'])}%%</p></body></html>", content_type='text/html')
        elif path == '/clients':
            active_clients = await get_active_clients()
            return web.Response(text=f"<html><head><title>用户列表(ip)</title></head><body><h1>用户列表(ip)</h1><ul>{''.join(f'<li>{ip}</li>' for ip in active_clients)}</ul></body></html>", content_type='text/html')
        elif path == '/feedback' and request.method == 'POST':
            try:
                data = await request.post()
                feedback_text = data.get('feedback', '').strip()
                if feedback_text:
                    await save_feedback(client_ip, feedback_text)
                    return web.Response(text=json.dumps({'status': 'success', 'message': '反馈已提交'}), content_type='application/json')
                return web.Response(text=json.dumps({'status': 'error', 'message': '反馈内容不能为空'}), content_type='application/json', status=400)
            except Exception as e:
                print(f"处理反馈错误: {e}")
                return web.Response(text=json.dumps({'status': 'error', 'message': '服务器错误'}), content_type='application/json', status=500)
        else:
            return web.Response(text=f"<html><head><title>404 Not Found</title></head><body><h1>404 Not Found</h1><p>The requested path {path} was not found.</p></body></html>", content_type='text/html', status=404)
    except Exception as e:
        print(f"处理请求错误 {path}: {e}")
        return web.Response(text=f"<h1>500 Internal Server Error</h1><p>{str(e)}</p>", content_type='text/html', status=500)

async def get_active_clients():
    current_time = time.time()
    return {ip: data for ip, data in clients.items() if current_time - data['timestamp'] < 60}

async def start_server():
    app = web.Application()
    app.router.add_get('/{tail:.*}', handle)
    app.router.add_post('/{tail:.*}', handle)
    asyncio.create_task(cleanup_clients())
    asyncio.create_task(save_user_count())
    asyncio.create_task(speed_monitor_task())
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', web_port)
    await site.start()
    print(f"服务器已启动 {web_port}端口")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['figure.max_open_warning'] = 0
    plt.switch_backend('Agg')
    if not os.path.exists('./librespeed-cli'):
        print("[警告] librespeed-cli 不存在，速度监控功能将不可用")
        print("请下载ARM64版本: https://github.com/librespeed/speedtest-cli/releases ")
    else:
        os.chmod('./librespeed-cli', 0o755)
    asyncio.run(start_server())
