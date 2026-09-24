# -*- coding: utf-8 -*-
"""Kimi Code 计量单 — 票据/仪表视觉

- 会计票据：纸面方角、发丝线、双线总计（缓存命中率）
- 三条额度用 20 刻度游标尺：5 小时 / 本周 / 本月，已用 + 剩余 + 重置时间
- 额度主源：Kimi Code CLI 本地服务 /api/v1/oauth/usage（server.token，不过期）
- 月度额度为云端接口尽力补充（桌面端在线才有）；缓存命中率来自 wire.jsonl
- 点击盖红章、章影随手；刷新时数字从 0 重新"打印"；悬停刻度浮起
- 左键拖拽，右键菜单，每 30 分钟自动刷新
"""
import glob
import json
import math
import os
import re
import threading
import time
import urllib.request

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk

# ── 数据获取 ───────────────────────────────────────────────

LEVELDB_DIR = os.path.expandvars(r"%APPDATA%\kimi-desktop\Local Storage\leveldb")
DAIMON_CFG = os.path.expandvars(r"%APPDATA%\kimi-desktop\daimon-share\daimon\config.json")
API_URL = ("https://www.kimi.com/apiv2/"
           "kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats")
JWT_RE = re.compile(rb"access_token[\x00-\x20]*.{0,10}?(eyJ[A-Za-z0-9_\-\.]{100,})")

POLL_SECONDS = 30 * 60
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "kimi_widget.json")


def read_tokens():
    candidates = []
    try:
        cfg = json.load(open(DAIMON_CFG, encoding="utf-8"))

        def walk(o):
            if isinstance(o, str) and o.startswith("eyJ"):
                candidates.append(o)
            elif isinstance(o, dict):
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(cfg)
    except Exception:
        pass
    ldb = []
    for path in glob.glob(os.path.join(LEVELDB_DIR, "*.log")) + \
            glob.glob(os.path.join(LEVELDB_DIR, "*.ldb")):
        try:
            with open(path, "rb") as f:
                for m in JWT_RE.finditer(f.read()):
                    ldb.append((os.path.getmtime(path), m.group(1).decode()))
        except OSError:
            continue
    ldb.sort(key=lambda c: c[0], reverse=True)
    candidates.extend(t for _, t in ldb)
    return candidates


def fetch_cloud():
    """云端订阅接口原始响应（JWT 短命，仅作月度额度的补充来源）"""
    tokens = read_tokens()
    if not tokens:
        raise RuntimeError("未找到 Kimi 登录令牌")
    last_err = None
    for tok in tokens:
        try:
            req = urllib.request.Request(
                API_URL, data=b"{}",
                headers={"Authorization": f"Bearer {tok}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as e:
            last_err = e
    else:
        raise last_err or RuntimeError("所有候选令牌均无效")
    return data


def _local_server():
    """读 Kimi Code CLI 本地服务地址和凭据（server.token + 最新实例）"""
    home = os.path.expanduser(r"~\.kimi-code")
    token = open(os.path.join(home, "server.token")).read().strip()
    inst_dir = os.path.join(home, "server", "instances")
    best = None
    for fn in os.listdir(inst_dir):
        try:
            inst = json.load(open(os.path.join(inst_dir, fn),
                                  encoding="utf-8"))
            if best is None or inst.get("heartbeat_at", 0) > \
                    best.get("heartbeat_at", 0):
                best = inst
        except Exception:
            continue
    if not best:
        raise RuntimeError("无 CLI 服务实例")
    return best["host"], best["port"], token


def fetch_local_quota():
    """CLI 本地服务：5h / 7d 额度（主数据源，凭据不过期）"""
    host, port, token = _local_server()
    req = urllib.request.Request(
        f"http://{host}:{port}/api/v1/oauth/usage",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    usages = (data.get("data") or {}).get("quota", {}).get("usages") or {}
    rl5 = usages.get("limit5h") or {}
    rl7 = usages.get("limit7d") or {}
    return {
        "code5h_ratio": (float(rl5["usedRatio"])
                         if rl5.get("usedRatio") is not None else None),
        "code5h_reset": rl5.get("resetAt") or "",
        "code7d_ratio": float(rl7.get("usedRatio") or 0),
        "code7d_reset": rl7.get("resetAt") or "",
    }


def fetch_cloud_monthly():
    """云端接口：仅月度额度（需桌面端在线刷新令牌，失败则月度留空）"""
    try:
        data = fetch_cloud()
    except Exception:
        return {"used": None, "expire": ""}
    bal = data.get("subscriptionBalance") or {}
    return {"used": float(bal["amountUsedRatio"])
            if bal.get("amountUsedRatio") is not None else None,
            "expire": bal.get("expireTime") or ""}


def fetch_quota():
    q = fetch_local_quota()
    q.update(fetch_local_user())
    q.update(fetch_cloud_monthly())
    return q


def fetch_local_user():
    """CLI 本地服务：会员级别 / 昵称（与额度同凭据，稳定）"""
    try:
        host, port, token = _local_server()
        req = urllib.request.Request(
            f"http://{host}:{port}/api/v1/oauth/userinfo",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        u = (data.get("data") or {}).get("userInfo") or {}
        return {"level": u.get("userLevelName") or "",
                "nickname": u.get("nickname") or ""}
    except Exception:
        return {"level": "", "nickname": ""}


SESSIONS_GLOBS = [
    os.path.expandvars(
        r"%APPDATA%\kimi-desktop\daimon-share\daimon\runtime"
        r"\kimi-code\home\sessions\*\*\agents\main\wire.jsonl"),
    os.path.expanduser(
        r"~\.kimi-code\sessions\*\*\agents\main\wire.jsonl"),
]


def _find_usage(o):
    if isinstance(o, dict):
        u = o.get("usage")
        if isinstance(u, dict) and ("inputCacheRead" in u or "inputOther" in u):
            return u
        for v in o.values():
            r = _find_usage(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find_usage(v)
            if r:
                return r
    return None


def cache_hit_rate(hours=24):
    now = time.time()
    cr = cc = other = 0
    for pat in SESSIONS_GLOBS:
        for fp in glob.glob(pat):
            try:
                if now - os.path.getmtime(fp) > hours * 3600:
                    continue
                with open(fp, "rb") as f:
                    for ln in f:
                        if b'"usage"' not in ln:
                            continue
                        try:
                            u = _find_usage(json.loads(ln))
                        except ValueError:
                            continue
                        if u:
                            cr += int(u.get("inputCacheRead") or 0)
                            cc += int(u.get("inputCacheCreation") or 0)
                            other += int(u.get("inputOther") or 0)
            except OSError:
                continue
    total = cr + cc + other
    return cr / total if total > 0 else None


# ── 视觉常量（票据） ───────────────────────────────────────

MAGIC = "#ff00ff"          # 透明镂空（阴影区）
PAPER = "#fcfbf8"          # 纸面（冷白）
INK = "#22252b"            # 墨色
HAIR = "#d9d6cd"           # 发丝线
FAINT = "#8d887a"          # 弱墨
RED = "#b3402a"            # 朱砂（紧张 / 印章）
AMBER = "#a97b16"          # 账房琥珀（注意）

W, H = 312, 400
PX, PY = 2, 2              # 纸面左上角（右侧下方留给投影）
FONT_NUM = "Consolas"
FONT_CN = "Microsoft YaHei UI"
FONT_PRINT = "SimSun"
TICKS = 20                 # 每条额度的刻度数


def state_color(ratio):
    if ratio >= 0.85:
        return RED
    if ratio >= 0.6:
        return AMBER
    return INK


def fmt_time(iso):
    if not iso:
        return "--"
    try:
        dt = time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
        ts = time.mktime(dt) - time.timezone
        lt = time.localtime(ts)
        now = time.localtime()
        hm = time.strftime("%H:%M", lt)
        if lt.tm_yday == now.tm_yday and lt.tm_year == now.tm_year:
            return f"今天 {hm}"
        return f"{lt.tm_mon}月{lt.tm_mday}日 {hm}"
    except Exception:
        return "--"


def blend(c1, c2, t):
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t)
                                   for i in range(3))


class Widget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Kimi Code 计量单")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=MAGIC)
        self.root.attributes("-transparentcolor", MAGIC)

        self.data = None
        self.error = None
        self.cache_rate = None
        self.last_fetch = 0.0
        self._fetching = False
        self._drag = None
        # 动画状态：缓动显示值 / 悬停 / 印章 / 光标
        self._disp = {"rate": 0.0, "m5": 0.0, "m7": 0.0, "mmo": 0.0}
        self._target = dict(self._disp)
        self._hover_e = 0.0
        self._hover_t = 0.0
        self.mouse = None
        self.stamps = []
        self._tick_job = None

        self.cv = tk.Canvas(self.root, width=W, height=H,
                            bg=MAGIC, highlightthickness=0)
        self.cv.pack()
        x, y = self._load_pos()
        self.root.geometry(f"{W}x{H}+{x}+{y}")

        self.menu = tk.Menu(self.root, tearoff=0, bg=PAPER, fg=INK,
                            activebackground=HAIR, activeforeground=INK)
        self.menu.add_command(label="立即刷新", command=self.refresh)
        self.menu.add_command(label="退出", command=self.root.destroy)

        self.cv.bind("<ButtonPress-1>", self._drag_start)
        self.cv.bind("<B1-Motion>", self._drag_move)
        self.cv.bind("<Button-3>",
                     lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        self.cv.bind("<Enter>", lambda e: self._hover_to(1.0))
        self.cv.bind("<Leave>", self._on_leave)
        self.cv.bind("<Motion>", self._on_motion)

        self._draw()

    def _hover_to(self, t):
        self._hover_t = t
        self._ensure_tick()

    def _on_leave(self, e):
        self.mouse = None
        self._hover_to(0.0)

    def _on_motion(self, e):
        self.mouse = (e.x, e.y)
        if self._hover_e > 0.02:
            self._ensure_tick()

    # ── 动画引擎：一个 30ms 节拍器，驱动缓动/悬停/印章/刷新提示 ──
    def _ensure_tick(self):
        if self._tick_job is None:
            self._tick_job = self.root.after(30, self._tick)

    def _tick(self):
        self._tick_job = None
        active = False
        for k in self._disp:
            diff = self._target[k] - self._disp[k]
            if abs(diff) > 0.0008:
                self._disp[k] += diff * 0.16
                active = True
            else:
                self._disp[k] = self._target[k]
        diff = self._hover_t - self._hover_e
        if abs(diff) > 0.02:
            self._hover_e += diff * 0.25
            active = True
        else:
            self._hover_e = self._hover_t
        now = time.time()
        self.stamps = [s for s in self.stamps if now - s[2] < 0.8]
        if self.stamps or self._fetching:
            active = True
        self._draw()
        if active:
            self._ensure_tick()

    # ── 绘制 ──
    def _draw(self):
        cv = self.cv
        cv.delete("all")
        hv = self._hover_e
        paper = blend(PAPER, "#ffffff", 0.6 * hv)
        frame = blend(HAIR, INK, 0.55 * hv)
        cv.create_rectangle(PX, PY, W - 4, H - 4, fill=paper, outline="")
        cv.create_rectangle(PX + 6, PY + 6, W - 10, H - 10,
                            outline=frame, width=1)

        T = cv.create_text

        # 票头：字号 + 编号（负号字号 = 像素，免疫 DPI 缩放）
        T(22, 32, text="Kimi Code 计量单", anchor="w",
          fill=INK, font=(FONT_PRINT, -17, "bold"))
        d0 = self.data or {}
        head_right = d0.get("level") or time.strftime("No.%m%d")
        if d0.get("level") and d0.get("nickname"):
            head_right = f"{d0['nickname']} · {d0['level']}"
        T(W - 24, 32, text=head_right, anchor="e",
          fill=INK if d0.get("level") else FAINT,
          font=(FONT_CN, -11, "bold"))
        self._double_rule(cv, 50)

        # 总计行：缓存命中率（双线夹住 = 会计的"最终合计"）
        if self._fetching:
            pulse = (math.sin(time.time() * 6) + 1) / 2
            right = ("打印中…", blend(FAINT, RED, pulse))
        elif self.cache_rate is not None:
            right = (f"{self._disp['rate'] * 100:.1f} %", INK)
        else:
            right = ("--", FAINT)
        T(22, 82, text="缓存命中率 · 24h", anchor="w",
          fill=FAINT, font=(FONT_CN, -11))
        T(W - 24, 76, text=right[0], anchor="e",
          fill=right[1], font=(FONT_NUM, -24, "bold"))
        self._double_rule(cv, 100)

        # 三条额度：账目行 + 刻度尺
        d = self.data or {}
        self._draw_item(cv, 124, "5小时频限", "m5",
                        d.get("code5h_ratio"), d.get("code5h_reset"),
                        allow_idle=True)
        self._draw_item(cv, 204, "本周额度", "m7",
                        d.get("code7d_ratio"), d.get("code7d_reset"))
        self._draw_item(cv, 284, "本月额度", "mmo",
                        d.get("used"), d.get("expire"))

        # 票脚：虚线撕口 + 更新时间（有错误时整行让位给错误信息）
        fy = H - 40
        for x in range(22, W - 24, 9):
            cv.create_line(x, fy, x + 4, fy, fill=HAIR)
        if self.error and not self.data:
            T(22, H - 20, text=self.error[:34], anchor="w",
              fill=RED, font=(FONT_CN, -11))
        else:
            T(22, H - 20, text="每30分钟自动更新", anchor="w",
              fill=FAINT, font=(FONT_CN, -11))
            ts = time.strftime("%H:%M", time.localtime(self.last_fetch)) \
                if self.last_fetch else "--:--"
            T(W - 24, H - 20, text=f"更新 {ts}", anchor="e",
              fill=FAINT, font=(FONT_NUM, -11))

        # 章影：悬停时一枚淡章随手移动；点击盖实，0.8s 淡去
        if hv > 0.5 and self.mouse:
            mx, my = self.mouse
            ghost = blend(RED, paper, 0.82)
            cv.create_oval(mx - 14, my - 14, mx + 14, my + 14,
                           outline=ghost, width=1)
            cv.create_text(mx, my, text="验", fill=ghost,
                           font=(FONT_PRINT, -11, "bold"))
        now = time.time()
        for sx, sy, t0 in self.stamps:
            age = (now - t0) / 0.8
            r = 18
            col = blend(RED, paper, age * 0.85)
            cv.create_oval(sx - r, sy - r, sx + r, sy + r,
                           outline=col, width=2)
            cv.create_text(sx, sy, text="验", fill=col,
                           font=(FONT_PRINT, -13, "bold"))

    def _double_rule(self, cv, y):
        cv.create_line(22, y, W - 24, y, fill=INK)
        cv.create_line(22, y + 3, W - 24, y + 3, fill=INK)

    def _draw_item(self, cv, y, name, key, ratio, reset, allow_idle=False):
        idle = allow_idle and self.data is not None and ratio is None
        r = self._disp[key]
        color = state_color(r) if self.data and ratio is not None else FAINT

        cv.create_text(22, y, text=name, anchor="w",
                       fill=INK, font=(FONT_CN, -14, "bold"))
        cv.create_text(W - 24, y, text=f"重置 {fmt_time(reset)}", anchor="e",
                       fill=FAINT, font=(FONT_CN, -11))

        if idle:
            used_txt, left_txt = "空闲", "剩 100%"
        elif self.data and ratio is not None:
            used_txt = f"已用 {r * 100:5.1f}%"
            left_txt = f"剩 {(1 - r) * 100:5.1f}%"
        else:
            used_txt = left_txt = "--"
        cv.create_text(22, y + 20, text=used_txt, anchor="w",
                       fill=FAINT, font=(FONT_NUM, -11))
        cv.create_text(W - 24, y + 20, text=left_txt, anchor="e",
                       fill=color, font=(FONT_NUM, -13, "bold"))

        # 刻度尺：20 格游标，已用格着状态色；光标掠过时近处刻度受浮起
        x1, x2, ty = 22, W - 24, y + 40
        step = (x2 - x1) / TICKS
        filled = round(r * TICKS) if self.data and not idle else 0
        mx = self.mouse[0] if (self._hover_e > 0.5 and self.mouse) else None
        for i in range(TICKS):
            tx = x1 + i * step
            lift = 0.0
            if mx is not None and abs(tx - mx) < 40:
                lift = (1 - abs(tx - mx) / 40) * 3 * self._hover_e
            cv.create_rectangle(tx, ty - lift, tx + step - 3, ty + 9 - lift,
                                fill=color if i < filled else HAIR,
                                outline="")

    # ── 拖拽与位置记忆 ──
    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())
        self.stamps.append((e.x, e.y, time.time()))
        self.stamps = self.stamps[-4:]
        self._ensure_tick()

    def _drag_move(self, e):
        if self._drag:
            self.root.geometry(
                f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")
            self._save_pos()

    def _load_cfg(self):
        try:
            return json.load(open(CONFIG_PATH, encoding="utf-8"))
        except Exception:
            return {}

    def _load_pos(self):
        cfg = self._load_cfg()
        try:
            return int(cfg["x"]), int(cfg["y"])
        except Exception:
            return self.root.winfo_screenwidth() - W - 40, 40

    def _save_pos(self):
        cfg = self._load_cfg()
        cfg["x"], cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        try:
            json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"))
        except OSError:
            pass

    # ── 刷新 ──
    def refresh(self):
        if self._fetching:
            return
        self._fetching = True
        # 显示值归零：数据到位后重新"打印"，刷新反馈肉眼可见
        for k in self._disp:
            self._disp[k] = 0.0
        self._ensure_tick()

        def work():
            try:
                self.data = fetch_quota()
                self.error = None
                self.cache_rate = cache_hit_rate()
            except Exception as e:
                self.error = str(e)
            self.last_fetch = time.time()
            self._fetching = False
            self.root.after(0, self._apply_data)

        threading.Thread(target=work, daemon=True).start()

    def _apply_data(self):
        """数据到位：写入缓动目标，启动打印动画"""
        d = self.data or {}
        if self.cache_rate is not None:
            self._target["rate"] = self.cache_rate
        for key, raw in (("m5", d.get("code5h_ratio")),
                         ("m7", d.get("code7d_ratio")),
                         ("mmo", d.get("used"))):
            if raw is not None:
                self._target[key] = max(0.0, min(1.0, raw))
            elif self.data is not None:
                self._target[key] = 0.0
        self._draw()
        self._ensure_tick()

    def schedule(self):
        self.refresh()
        # 失败或月度缺失时 2 分钟重试（桌面端上线后可尽快补回），正常 30 分钟
        wait = 120 if (self.data is None
                       or self.data.get("used") is None) else POLL_SECONDS
        self.root.after(wait * 1000, self.schedule)


if __name__ == "__main__":
    app = Widget()
    app.root.after(200, app.refresh)
    app.root.after(2000, app.schedule)
    app.root.mainloop()
