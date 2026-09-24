#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kimi Code 计量台 — 零依赖单文件仪表盘。python dashboard.py 后访问 http://127.0.0.1:8398"""

import glob
import json
import os
import re
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8398
ROOTS = [
    os.path.expanduser(r"~\.kimi-code\sessions"),
    os.path.expanduser(r"~\AppData\Roaming\kimi-desktop\daimon-share\daimon\runtime\kimi-code\home\sessions"),
]
TOKEN_FILE = os.path.expanduser(r"~\.kimi-code\server.token")
INSTANCES_DIR = os.path.expanduser(r"~\.kimi-code\server\instances")
TIMEOUT = 3
DAIMON_CFG = os.path.expandvars(r"%APPDATA%\kimi-desktop\daimon-share\daimon\config.json")
LEVELDB_DIR = os.path.expandvars(r"%APPDATA%\kimi-desktop\Local Storage\leveldb")
CLOUD_URL = ("https://www.kimi.com/apiv2/"
             "kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats")
JWT_RE = re.compile(rb"access_token[\x00-\x20]*.{0,10}?(eyJ[A-Za-z0-9_\-\.]{100,})")
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_cache.json")
USAGE_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_cache.json")
LOGO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kimi-logo.png")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUD_TIMEOUT = 12
USAGE_LOCK = threading.Lock()

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Kimi Code 计量台</title>
<style>
/* EVA UI skill tokens — references/tokens.md 原值 */
:root{
  --bg:#100706; --panel:rgba(29,11,8,0.9); --scope:#1b1010;
  --line:#6f2e1f; --linew:#9b4b31;
  --text:#ffd9bf; --muted:#cf8d68; --alert:#ff8e2b;
  --command:#ff7a1a; --warning:#ff9f43; --critical:#ff4d38; --locked:#ffd166;
  --hair:rgba(255,158,0,0.25);
}
*{box-sizing:border-box; margin:0; padding:0; border-radius:0!important;}
body{background:var(--bg); color:var(--text);
  font-family:"Arial Narrow","Roboto Condensed","Microsoft YaHei",sans-serif; font-size:13px; line-height:1.55;}
.num{font-family:Consolas,monospace;}
.shell{width:min(1440px, calc(100% - 24px)); margin:0 auto; padding:12px 0 28px;}
/* ScreenFrame + 扫描线纹理 */
.frame{position:relative; border:1px solid var(--line); background:var(--panel);}
.frame::before,.frame::after{content:""; position:absolute; width:18px; height:18px; z-index:3;
  border-top:2px solid rgba(255,122,26,0.65); border-left:2px solid rgba(255,122,26,0.65);}
.frame::before{top:8px; left:8px;} .frame::after{right:8px; bottom:8px; transform:rotate(180deg);}
.dots{background-image:radial-gradient(rgba(255,159,67,0.09) 1px, transparent 1.4px); background-size:10px 10px;}
.scan{background-image:repeating-linear-gradient(0deg, rgba(255,159,67,0.028) 0 1px, transparent 1px 3px);}
.pad{padding:14px 16px; position:relative;}
.panel{animation:reveal .25s steps(2) both;}
@keyframes reveal{from{opacity:0;} to{opacity:1;}}
/* 头部机器人：dome + 眼睛 sprite 合成（双眼共用同一动画节拍） */
.logo-wrap{position:relative; width:64px; height:64px; flex:none;}
.logo-dome{width:64px; height:64px; display:block;}
.eye-g{position:absolute; animation:eyeglance 7s steps(1) infinite;}
.logo-eye{display:block; width:100%; animation:eyeblink 5s steps(1) infinite; transform-origin:center;}
@keyframes eyeglance{0%,70%{transform:translate(0,0);} 74%,86%{transform:translate(2px,-1px);} 90%,100%{transform:translate(0,0);}}
@keyframes eyeblink{0%,88%{transform:scaleY(1);} 91%{transform:scaleY(0.12);} 94%,100%{transform:scaleY(1);}}
/* EVA-01 全身剪影：左侧栏 A.T. FIELD 模块下方，充填至栏底 + 能量扫描带 */
.evafig{flex:1; min-height:60px; display:flex; align-items:flex-end; justify-content:center; margin-top:10px; overflow:hidden; position:relative;}
.evafig img{max-width:150px; width:100%; max-height:100%; object-fit:contain; opacity:0.2; pointer-events:none; animation:evaglow 8s linear infinite;}
/* 扫描带：60px 渐变剖面（透明->橙辉->亮芯->淡出），微斜，辉光；3.6s 匀速下扫后停顿，8s 循环 */
.evascan{position:absolute; left:-10%; right:-10%; height:60px; top:-70px;
  background:linear-gradient(180deg,
    rgba(255,122,26,0) 0%,
    rgba(255,122,26,0.08) 30%,
    rgba(255,158,76,0.18) 46%,
    rgba(255,222,170,0.34) 50%,
    rgba(255,158,76,0.18) 54%,
    rgba(255,122,26,0.08) 70%,
    rgba(255,122,26,0) 100%);
  filter:drop-shadow(0 0 10px rgba(255,122,26,0.18));
  box-shadow:0 0 26px rgba(255,122,26,0.08);
  animation:evasweep 8s linear infinite;}
@keyframes evasweep{
  0%{top:-70px;}
  45%{top:100%;}
  100%{top:100%;}
}
/* 扫过时机体增亮（同一 8s 周期，窗口与下扫同步） */
@keyframes evaglow{
  0%{opacity:0.20; filter:brightness(1);}
  10%{opacity:0.26; filter:brightness(1.12);}
  22%{opacity:0.31; filter:brightness(1.35);}
  34%{opacity:0.26; filter:brightness(1.12);}
  44%,100%{opacity:0.20; filter:brightness(1);}
}
@media (max-width:1080px){.evafig{display:none;}}
/* 当前值闪烁：液位计当前格 + 24H 当前小时 tick */
@keyframes curblink{0%,100%{opacity:1;} 50%{opacity:0.25;}}
.lvlbar i.cur{animation:curblink 1s steps(2) infinite;}
.tickcol i.cur{animation:curblink 1s steps(2) infinite;}
/* StripeBand 16px 节拍 */
.hz{height:10px; margin:14px 0;
  background:repeating-linear-gradient(-60deg, rgba(255,122,26,0.9) 0 6px, rgba(255,122,26,0.12) 6px 10px, transparent 10px 16px);}
/* 顶部指挥横幅 */
.banner{display:flex; align-items:center; justify-content:space-between; gap:18px; padding:6px 4px 12px;}
.b-left{display:flex; align-items:center; gap:14px; min-width:0;}
.b-mid{text-align:center;}
.b-right{text-align:right;}
.eyebrow{color:var(--muted); text-transform:uppercase; letter-spacing:0.12em; font-size:0.72rem; font-family:"Bahnschrift",Consolas,monospace;}
.head h1{margin:4px 0 2px; color:var(--command); font-size:clamp(1.6rem,3vw,2.2rem); line-height:1.1; letter-spacing:4px; font-weight:700;
  font-family:"SourceHanSerifSC EvaJian","Yu Mincho","YuMincho","MS Mincho",serif; text-transform:uppercase;}
.mincho{font-family:"SourceHanSerifSC EvaJian","Yu Mincho","YuMincho","MS Mincho",serif; font-weight:700; font-size:24px; letter-spacing:10px; color:var(--text);}
.head .sub{font-family:"Bahnschrift",Consolas,monospace; font-size:10px; letter-spacing:2px; color:var(--muted); text-transform:uppercase; margin-top:4px;}
.head .who{font-family:"Bahnschrift",Consolas,monospace; font-size:12px; color:var(--text); letter-spacing:1px; margin-top:4px;}
.clock{font-size:20px; letter-spacing:2px; color:var(--alert);}
.cur{color:var(--command); animation:blink 1s steps(1) infinite;}
@keyframes blink{50%{opacity:0;}}
.cls{display:flex; justify-content:space-between; font-family:"Bahnschrift",Consolas,monospace; font-size:10px; letter-spacing:2px;
  color:var(--muted); margin:2px 0 12px; text-transform:uppercase;}
/* StatusIndicator chips */
.chip{font-family:"Bahnschrift",Consolas,monospace; font-size:10px; letter-spacing:2px; padding:1px 8px;
  border:1px solid var(--command); color:var(--command); white-space:nowrap;}
.chip.warn{border-color:var(--warning); color:var(--warning);}
.chip.crit{border-color:var(--critical); color:var(--critical);}
.chip.lock{border-color:var(--locked); color:var(--locked);}
/* 布局：侧轨 + 主区双列网格 */
.layout{display:grid; grid-template-columns:190px 1fr; gap:14px; align-items:stretch;}
.main{min-width:0;}
.grid2{display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px;}
.grid2>section{display:flex; min-width:0;}
.grid2>section>.frame{flex:1;}
@media (max-width:1080px){ .layout{grid-template-columns:1fr;} .grid2{grid-template-columns:1fr;} }
/* 面板头：DataLabel + REF + 坐标 + chip 同一基线 */
.phead{display:flex; align-items:baseline; gap:10px; border-bottom:1px solid var(--line); padding-bottom:6px; margin-bottom:10px;}
.phead h2{border:0; padding:0; margin:0;}
.ref{margin-left:auto; font-family:"Bahnschrift",Consolas,monospace; font-size:9px; letter-spacing:2px; color:var(--muted);}
.coord{font-family:"Bahnschrift",Consolas,monospace; font-size:9px; letter-spacing:2px; color:var(--muted);}
h2{font-size:12px; letter-spacing:0.12em; font-weight:bold; color:var(--muted); text-transform:uppercase;
  border-left:3px solid var(--command); padding-left:8px;}
h2 .en{color:var(--muted); font-weight:normal; font-size:11px; letter-spacing:0.12em; margin-left:8px; font-family:"Bahnschrift",Consolas,monospace;}
/* 侧轨 */
.side{padding:12px; font-family:"Bahnschrift",Consolas,monospace; display:flex; flex-direction:column;}
/* 垂直液位计（worst quota） */
.lvl{display:flex; justify-content:space-between; height:132px; margin-bottom:4px;}
.lvlbar{flex:none; width:14px; display:flex; flex-direction:column-reverse; gap:1px;}
.lvlbar i{flex:1; border:1px solid var(--line); display:block;}
.lvlbar i.on{background:var(--command); border-color:var(--command);}
.lvlbar.warn i.on{background:var(--warning); border-color:var(--warning);}
.lvlbar.crit i.on{background:var(--critical); border-color:var(--critical);}
.lvlscale{position:relative; flex:1; margin-left:8px; font-family:Consolas,monospace; font-size:9px; color:var(--muted);}
.lvlscale span{position:absolute; right:0;}
/* 迷你遥测列 */
.mini2{display:flex; gap:12px; margin-bottom:2px;}
.mini2 .st{flex-wrap:wrap;}
.mini2 .st b{width:100%; text-align:left;}
.col{flex:1; min-width:0;}
.tickcol{display:flex; flex-direction:column-reverse; gap:1px; height:88px; margin-bottom:2px;}
.tickcol i{flex:1; border:1px solid var(--line); display:block;}
.tickcol i.on{background:var(--command); border-color:var(--command);}
.mlabel{font-size:9px; letter-spacing:2px; color:var(--muted); font-family:Consolas,monospace;}
.railend{margin-top:auto; padding-top:12px;}
.ptitle{color:var(--muted); text-transform:uppercase; letter-spacing:0.12em; font-size:0.72rem; margin:10px 0 6px;
  border-left:2px solid var(--command); padding-left:6px; display:flex; justify-content:space-between;}
.ptitle:first-child{margin-top:0;}
.chev{height:84px; border:1px solid var(--line); margin-bottom:4px;
  background:repeating-linear-gradient(135deg, transparent 0 8px, rgba(255,159,67,0.5) 8px 12px, transparent 12px 22px);}
.m .m{display:block;}
.modes span{display:block; border:1px solid var(--line); color:var(--muted); font-size:10px; letter-spacing:2px; padding:2px 8px; margin-bottom:4px;
  animation:modeact 9s steps(1) infinite;}
.modes span:nth-child(1){animation-delay:0s;}
.modes span:nth-child(2){animation-delay:-3s;}
.modes span:nth-child(3){animation-delay:-6s;}
@keyframes modeact{
  0%,33.3%{background:rgba(255,122,26,0.14); color:var(--command); border-color:var(--command); box-shadow:inset 3px 0 0 var(--command);}
  33.4%,100%{background:transparent; color:var(--muted); border-color:var(--line); box-shadow:none;}
}
.st{display:flex; justify-content:space-between; font-size:10px; letter-spacing:1px; color:var(--muted); padding:2px 0;
  border-bottom:1px solid rgba(111,46,31,0.5);}
.st b{color:var(--text); font-weight:normal; font-family:Consolas,monospace;}
.tickfield{height:26px; border:1px solid var(--line); margin-top:8px; position:relative;
  background:repeating-linear-gradient(90deg, rgba(255,209,102,0.35) 0 1px, transparent 1px 8px),
             repeating-linear-gradient(0deg, rgba(255,159,67,0.12) 0 1px, transparent 1px 8px);}
.tickfield svg{position:absolute; inset:0; width:100%; height:100%; display:block;}
/* 通用 */
.label{color:var(--muted); font-size:12px; letter-spacing:0.08em;}
.mini{font-family:"Bahnschrift",Consolas,monospace; font-size:10px; letter-spacing:1px; color:var(--muted); text-transform:uppercase; margin-top:10px;}
.row{display:flex; justify-content:space-between; align-items:baseline; padding:4px 0;}
.row .v{font-family:Consolas,monospace; text-align:right; perspective:120px;}
/* 翻牌：值变化时逐字 split-flap（steps 机器节拍，宽度用 Consolas 保持稳定） */
.flap{display:inline-block; position:relative; white-space:pre;}
.flap .fo{display:inline-block; animation:flapout .45s steps(4) both;}
.flap .fn{position:absolute; left:0; top:0; animation:flapin .45s steps(4) both;}
@keyframes flapout{from{transform:rotateX(0deg); opacity:1;} to{transform:rotateX(-90deg); opacity:0;}}
@keyframes flapin{from{transform:rotateX(90deg); opacity:0;} to{transform:rotateX(0deg); opacity:1;}}
/* 总计 */
.total .cap{font-size:12px; color:var(--muted); letter-spacing:3px;}
.total .big{font-family:Consolas,monospace; font-size:52px; line-height:1.15; text-align:right; color:var(--alert);}
.total .big small{font-size:18px; color:var(--muted);}
.total .sub{display:flex; justify-content:space-between; font-size:12px; color:var(--muted); margin-top:2px; border-top:1px solid var(--line); padding-top:6px;}
/* 额度行：threshold band + ThresholdBar */
.quota .qname{width:150px;}
.quota .qname .magi{display:block; font-family:"Bahnschrift",Consolas,monospace; font-size:9px; letter-spacing:2px; color:var(--muted);}
.quota .pct{width:90px; padding:1px 6px; background:rgba(255,122,26,0.10);}
.quota .pct.warn{background:rgba(255,159,67,0.16); color:var(--warning);}
.quota .pct.bad{background:rgba(255,77,56,0.18); color:var(--critical);}
.quota .reset{color:var(--muted); font-size:12px;}
.qsub{display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin:-2px 0 2px;}
.qsub .reset{flex:1; min-width:0;}
.cd{flex:none; min-width:86px; text-align:right; white-space:nowrap; font-family:Consolas,monospace; color:var(--command); font-weight:normal;}
.cd.crit{color:var(--critical);}
/* 剩余时间细轨：斜纹向左流动 = 排空感（无缝循环） */
@keyframes flow{from{background-position:0 0;} to{background-position:-11.31px 0;}}
.tltrack{height:4px; margin-top:3px; background:rgba(111,46,31,0.55); position:relative; overflow:hidden;}
.tlfill{height:100%; width:0%; animation:flow 1.1s linear infinite;
  background:repeating-linear-gradient(-45deg, rgba(255,122,26,0.6) 0 4px, rgba(255,122,26,0.28) 4px 8px);}
.tltrack.warn .tlfill{background:repeating-linear-gradient(-45deg, rgba(255,159,67,0.62) 0 4px, rgba(255,159,67,0.3) 4px 8px);}
.tltrack.crit .tlfill{background:repeating-linear-gradient(-45deg, rgba(255,77,56,0.65) 0 4px, rgba(255,77,56,0.32) 4px 8px);}
/* ThresholdBar：用量为主角 —— 高格实色 + 槽框 + 慢扫描条 */
@keyframes cellin{from{opacity:0;} to{opacity:1;}}
@keyframes scanx{from{left:-16px;} to{left:100%;}}
.tickruler{display:flex; gap:2px; margin:0;}
.tickruler i{width:8px; height:14px; background:transparent; border:1px solid var(--line); display:block;}
.tickruler i.on{background:var(--command); border-color:var(--command);}
.tickruler.warn i.on{background:var(--warning); border-color:var(--warning);}
.tickruler.bad i.on{background:var(--critical); border-color:var(--critical);}
.tickruler.anim i.on{animation:cellin .15s steps(1) both;}
.rulerbox{border:1px solid var(--line); padding:3px; margin:6px 0 8px; position:relative; overflow:hidden;}
.rulerbox::after{content:""; position:absolute; top:0; bottom:0; width:14px; left:-16px; pointer-events:none;
  background:rgba(255,209,102,0.12); animation:scanx 5s linear infinite;}
/* 柱图 */
@keyframes rise{from{transform:scaleY(0);} to{transform:scaleY(1);}}
@keyframes pulselive{0%,100%{opacity:1;} 50%{opacity:0.4;}}
.bars.anim .b{transform-origin:bottom; animation:rise .18s steps(3) both;}
.bars .b.live{animation:pulselive 2s steps(2) infinite;}
.bars.anim .b.live{animation:rise .18s steps(3) both, pulselive 2s steps(2) infinite;}
/* 柱图 */
hr.hair{border:0; border-top:1px solid var(--line); margin:14px 0;}
.bars{display:flex; align-items:flex-end; gap:0; height:120px; margin-top:18px; border-bottom:1px solid var(--line);}
.bars .b{flex:1; background:var(--command); margin:0 1px; min-height:1px;}
.bars .b:hover{background:var(--warning);}
.xaxis{display:flex; justify-content:space-between; font-family:Consolas,monospace; font-size:11px; color:var(--muted); margin-top:4px;}
/* TelemetryTable */
table.lst{width:100%; border-collapse:collapse; font-size:12px;}
td,th{padding:4px 0; border-bottom:1px solid var(--line); text-align:left; vertical-align:baseline;}
td.r,th.r{text-align:right; font-family:Consolas,monospace;}
th{color:var(--muted); font-weight:normal; font-size:11px; letter-spacing:0.12em; text-transform:uppercase;}
/* NERV 标牌 */
.tagrow{display:flex; justify-content:space-between; align-items:flex-end; gap:14px;}
.tag{width:320px; flex:none;}
.tag .tb-head{background:var(--command); color:var(--bg); font-family:"Bahnschrift",Consolas,monospace; letter-spacing:3px; font-weight:bold;
  font-size:11px; padding:4px 12px; text-transform:uppercase;}
table.titleblock{width:100%; border-collapse:collapse; font-size:12px;}
table.titleblock td{border-top:1px solid var(--line); padding:4px 12px; text-align:left;}
table.titleblock td.tb-label{color:var(--muted); font-size:11px; letter-spacing:2px;}
/* 表盘：A.T. FIELD scope */
.scope-frame{position:relative; width:360px; max-width:100%; margin:0 auto; padding:10px 0;}
.bk{position:absolute; width:18px; height:18px; border-top:2px solid rgba(255,122,26,0.65); border-left:2px solid rgba(255,122,26,0.65);}
.bk.tl{top:0; left:0;} .bk.tr{top:0; right:0; transform:rotate(90deg);}
.bk.bl{bottom:0; left:0; transform:rotate(-90deg);} .bk.br{bottom:0; right:0; transform:rotate(180deg);}
/* 面板准星（鼠标 X/Y 轴交线） */
.crosshair{position:absolute; display:none; pointer-events:none; z-index:5;
  background:rgba(255,158,76,0.35);}
.ch-v{top:0; bottom:0; width:1px;}
.ch-h{left:0; right:0; height:1px;}
.ch-dot{position:absolute; display:none; width:7px; height:7px; z-index:5; pointer-events:none;
  border:1px solid var(--command); transform:translate(-50%,-50%);}
.ch-dot::after{content:''; position:absolute; inset:2px; background:var(--command);}
/* 缓存写马赛克块：对齐数字高度 */
.mosaic{font-size:1em; line-height:1; display:inline-block; transform:scaleY(0.7);}
.hitline{margin-top:16px; position:relative;}
.dialtip{display:none; position:absolute; z-index:2; pointer-events:none; white-space:nowrap;
  background:var(--scope); border:1px solid var(--line); color:var(--text);
  font-family:Consolas,monospace; font-size:11px; padding:2px 8px;}
.hitline .hovermark{fill:var(--text);}
.hitline svg{width:360px; max-width:100%; height:300px; display:block; margin:0 auto;}
.hitline text{font-family:Consolas,monospace; font-size:10px; fill:var(--muted);}
.hitline .ax{stroke:var(--hair); stroke-width:1; fill:none;}
.hitline .rail-min{stroke:var(--linew); stroke-width:1;}
.hitline .ring95{stroke:var(--command); stroke-width:1; stroke-dasharray:3,3; fill:none;}
.hitline .rim{stroke:var(--linew); stroke-width:1.6; fill:none;}
.hitline .rimdash{stroke:var(--linew); stroke-width:1; stroke-dasharray:3,3; fill:none; opacity:0.55;}
.hitline .fill{fill:var(--command); stroke:none;}
.hitline .ln{stroke:var(--command); stroke-width:2; fill:none;}
.hitline .low{stroke:var(--critical); stroke-width:3; fill:none; animation:lowblink 1s steps(2) infinite;}
.hitline .lowdot{stroke:var(--critical); stroke-width:1.5; fill:none; animation:lowblink 1s steps(2) infinite;}
@keyframes lowblink{0%,100%{opacity:1;} 50%{opacity:0;}}
.hitline .dot{fill:var(--text);}
.hitline .sweep{stroke:rgba(255,122,26,0.30); stroke-width:1;}
.warn{color:var(--warning);} .bad{color:var(--critical);}
</style>
</head>
<body>
<main class="shell">
<div class="frame dots scan page" style="padding:16px;">

<div class="frame dots" style="padding:12px 16px;">
<header class="banner head" style="padding:0 0 8px;">
  <div class="b-left">
    <div class="logo-wrap">
      <img class="logo-dome" src="/kimi-logo-dome.png" alt="Kimi">
      <span class="eye-g" style="left:39.5%; top:42.9%; width:13.8%;"><img class="logo-eye" src="/kimi-logo-eye-l.png" alt=""></span>
      <span class="eye-g" style="left:63.3%; top:40.1%; width:12.5%;"><img class="logo-eye" src="/kimi-logo-eye-r.png" alt=""></span>
    </div>
    <div>
      <div class="eyebrow">NERV · CENTRAL DOGMA · CENTRAL COMMAND</div>
      <h1>KIMI CODE 计量台<span class="cur">▮</span></h1>
      <div class="who" id="who" style="display:none"></div>
    </div>
  </div>
  <div class="b-mid">
    <div class="mincho">「作戦監視」</div>
    <div class="sub">USAGE MONITORING SYSTEM · TOKYO-3</div>
  </div>
  <div class="b-right">
    <div class="clock num" id="clock">---- -- -- --:--:--</div>
    <div class="mini" id="uptime">UP --:--:--</div>
  </div>
</header>
<div class="cls" style="margin:0;"><span>CLASSIFICATION: INTERNAL · MAGI-2 CLEARANCE</span><span>REF K2-0923-00 · BOOT <b class="num" id="boot">--</b></span></div>
</div>
<div class="hz" style="margin:14px 0;"></div>

<div class="layout">
  <aside class="frame dots side">
    <div class="ptitle">SIDE RAIL<span>A-01</span></div>
    <div class="chev"></div>
    <div class="ptitle">MODE</div>
    <div class="modes"><span>MONITOR</span><span>RECORD</span><span>SYNC</span></div>
    <div class="ptitle">STATE</div>
    <div class="states">
      <div class="st"><span>MAGILINK</span><b class="num" id="rail1">--</b></div>
      <div class="st"><span>Q-WORST</span><b class="num" id="rail2">--</b></div>
      <div class="st"><span>TURNS</span><b class="num" id="rail3">--</b></div>
      <div class="st"><span>FEED</span><b class="num">WIRE.JSONL</b></div>
    </div>
    <div class="tickfield">
      <svg id="ecg" viewBox="0 0 120 22" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <filter id="ecgglow" x="-20%" y="-60%" width="140%" height="220%">
            <feGaussianBlur stdDeviation="1.0" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <!-- 隐藏轨迹：3 个波峰（周期 40），y 约束在网格内（0..16.5/22），不显示 -->
          <path id="ecgpath" fill="none" d="M0,14 H8 l1,-2 l1,2 H16 l1.5,2.5 l2,-16.5 l2,16.5 l1.5,-2.5 H40 H48 l1,-2 l1,2 H56 l1.5,2.5 l2,-16.5 l2,16.5 l1.5,-2.5 H80 H88 l1,-2 l1,2 H96 l1.5,2.5 l2,-16.5 l2,16.5 l1.5,-2.5 H120"/>
          <linearGradient id="ecgtg" gradientUnits="userSpaceOnUse" x1="-45" y1="0" x2="0" y2="0">
            <stop offset="0" stop-color="#ff9e4d" stop-opacity="0.15"/>
            <stop offset="1" stop-color="#ff9e4d" stop-opacity="0.65"/>
          </linearGradient>
        </defs>
        <path id="ecgtrail" fill="none" stroke="url(#ecgtg)" stroke-width="2" stroke-linecap="round"/>
        <circle id="ecglead" r="1.1" fill="#ff7a1a" filter="url(#ecgglow)"/>
      </svg>
    </div>
    <div class="ptitle">SEG</div>
    <div class="mini" style="margin-top:0;">T-08 · T-16 · T-20<br>CAL OK · GRID SYNC</div>
    <div class="ptitle">A.T. FIELD<span>A-02</span></div>
    <div class="st"><span>MIN-RATE</span><b class="num" id="f1">--</b></div>
    <div class="st"><span>FIELD</span><b class="num" id="f2">--</b></div>
    <div class="mlabel" style="margin-top:4px;">FIELD <b class="num" id="f3" style="color:var(--text); font-weight:normal;">--</b> · SYNC OK</div>
    <div class="evafig"><img src="/kimi-eva01-full.png" alt="EVA-01"><div class="evascan"></div></div>
    <div class="ptitle">LEVEL METER<span>A-03</span></div>
    <div class="lvl">
      <div class="lvlbar" id="lvlbar"></div>
      <div class="lvlscale"><span style="top:-2px;">100</span><span style="top:13%;">85</span><span style="top:38%;">60</span><span style="bottom:-2px;">0</span></div>
    </div>
    <div class="st"><span>LVL Q-WORST</span><b class="num" id="lvlv">--</b></div>
    <div class="ptitle">ACTIVITY<span>A-04</span></div>
    <div class="mini2">
      <div class="col" style="flex:none;">
        <div class="tickcol" id="act24"></div>
        <div class="mlabel">24H</div>
      </div>
      <div class="col">
        <div class="st"><span>T-TURN</span><b class="num" id="rt1">--</b></div>
        <div class="st"><span>D30-TURN</span><b class="num" id="rt2">--</b></div>
        <div class="st"><span>CACHE R/W</span><b class="num" id="rt3">--</b></div>
      </div>
    </div>
    <div class="railend">
      <div class="chev"></div>
      <div class="mini" style="margin-top:8px;">REF K2-0923-A1 · RAIL END<br>GRID E-00 · N-14</div>
    </div>
  </aside>

  <div class="main">
    <div class="grid2">
      <section class="quota">
        <div class="frame dots pad panel" style="animation-delay:.05s;">
          <div class="phead"><h2>MAGI SYSTEM · 额度<span class="en">quota</span></h2><span class="ref">REF K2-0923-01</span><span class="coord">E-04 · N-12</span><span class="chip" id="chipq">--</span></div>
          <div class="row">
            <span class="qname">5 小时<span class="magi">MELCHIOR</span></span>
            <span class="v pct" id="q5p">--</span>
          </div>
          <div class="rulerbox">
            <div class="tickruler" id="q5t"></div>
            <div class="tltrack" id="tl5"><div class="tlfill"></div></div>
          </div>
          <div class="qsub"><span class="reset" id="q5r">重置 --</span><b class="cd num" id="cd5">--</b></div>
          <div class="row">
            <span class="qname">7 天<span class="magi">BALTHASAR</span></span>
            <span class="v pct" id="q7p">--</span>
          </div>
          <div class="rulerbox">
            <div class="tickruler" id="q7t"></div>
            <div class="tltrack" id="tl7"><div class="tlfill"></div></div>
          </div>
          <div class="qsub"><span class="reset" id="q7r">重置 --</span><b class="cd num" id="cd7">--</b></div>
          <div class="row">
            <span class="qname">本月<span class="magi">CASPER</span></span>
            <span class="v pct" id="qmp">--</span>
          </div>
          <div class="rulerbox">
            <div class="tickruler" id="qmt"></div>
            <div class="tltrack" id="tlm"><div class="tlfill"></div></div>
          </div>
          <div class="qsub"><span class="reset" id="qmr"></span><b class="cd num" id="cdm">--</b></div>
          <div class="label" id="qleft"></div>
          <div class="mini">THRESH <span style="color:var(--critical);">■</span>≥85 CRIT · <span style="color:var(--warning);">■</span>≥60 WARN · RULER=用量 · TRACK=剩余 · CYCLE 5H/7D/30D</div>
        </div>
      </section>

      <section>
        <div class="frame dots pad panel" style="animation-delay:.1s;">
          <div class="phead"><h2>今日<span class="en">today</span></h2><span class="ref">REF K2-0923-02</span><span class="coord">E-04 · N-08</span></div>
          <div class="row"><span class="label">输入 tokens</span><span class="v num" id="tin">--</span></div>
          <div class="row"><span class="label">输出 tokens</span><span class="v num" id="tout">--</span></div>
          <div class="row"><span class="label">缓存读 / 写</span><span class="v num" id="tcache">--</span></div>
          <div class="row"><span class="label">轮数</span><span class="v num" id="tturns">--</span></div>
          <div class="row"><span class="label">今日命中率</span><span class="v num" id="thit">--</span></div>
          <hr class="hair">
          <div class="bars today" id="tbars"></div>
          <div class="xaxis"><span>0 时</span><span>6</span><span>12</span><span>18</span><span>23 时</span></div>
          <div class="mini">BUCKET HOURLY · TZ LOCAL · UNIT TOKENS</div>
        </div>
      </section>
    </div>

    <section class="total">
      <div class="frame dots pad panel" style="animation-delay:.15s;">
        <div class="phead"><h2>A.T. FIELD · 缓存命中率<span class="en">hit-rate</span></h2><span class="ref">REF K2-0923-03</span><span class="coord">E-06 · N-10</span><span class="chip" id="chiph">--</span></div>
        <div class="row"><span class="cap">总 计 · 缓存命中率（全量）</span><span class="big num"><span id="hit">--</span><small> %</small></span></div>
        <div class="sub"><span>缓存命中 / 全部输入</span><span class="num" id="hitsub">--</span></div>
        <div class="hitline">
          <div class="scope-frame">
            <i class="bk tl"></i><i class="bk tr"></i><i class="bk bl"></i><i class="bk br"></i>
            <svg id="hsvg" viewBox="0 0 360 300"></svg>
          </div>
          <div class="xaxis"><span id="hstart">--</span><span>近 60 分钟 · 每分钟命中率</span><span id="hend">--</span></div>
        </div>
        <div class="mini">SAMPLING 60S · BUCKET 1MIN · NULL=NO DATA · BASELINE 95% · RAIL CAL-1%</div>
      </div>
    </section>

    <div class="hz"></div>
    <div class="grid2">
      <section>
        <div class="frame dots pad panel" style="animation-delay:.2s;">
          <div class="phead"><h2>近 30 天<span class="en">daily</span></h2><span class="ref">REF K2-0923-04</span><span class="coord">E-02 · N-06</span></div>
          <div class="bars days" id="dbars"></div>
          <div class="xaxis" id="daxis"><span>--</span><span>--</span></div>
          <div class="mini">WINDOW 30D · HOVER=HIT% · UNIT TOKENS</div>
        </div>
      </section>

      <section>
        <div class="frame dots pad panel" style="animation-delay:.25s;">
          <div class="phead"><h2>工作区排行<span class="en">top 8 · 30d</span></h2><span class="ref">REF K2-0923-05</span><span class="coord">E-02 · N-04</span></div>
          <table class="lst">
            <thead><tr><th>#</th><th>工作区</th><th class="r">tokens</th><th class="r">轮数</th><th class="r">命中率</th></tr></thead>
            <tbody id="ws"></tbody>
          </table>
          <div class="mini">RANK BY TOKENS · WINDOW 30D · SRC WIRE.JSONL</div>
        </div>
      </section>
    </div>

    <div class="hz"></div>
    <div class="tagrow">
      <div class="mini" style="margin-top:0;max-width:400px;">SRC WIRE.JSONL ×23 · CACHE USAGE_CACHE.JSON · QUOTA CACHE DASHBOARD_CACHE.JSON · POLL 60S · RECOMPUTE FULL</div>
      <div class="frame dots tag">
        <div class="tb-head">NERV · USAGE TERMINAL</div>
        <table class="titleblock">
          <tbody>
            <tr><td class="tb-label">签名</td><td class="num" id="sig">--</td></tr>
            <tr><td class="tb-label">图号</td><td class="num" id="no">No.----</td></tr>
            <tr><td class="tb-label">日期</td><td class="num" id="now">--</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>

</div>
</main>
<script>
function fmt(n){return (n==null||isNaN(n))?'--':n.toLocaleString('en-US');}
function pct(x,d){return x==null?'--':(x*100).toFixed(d==null?1:d)+'%';}
function cls(r){return r>=0.85?'bad':(r>=0.6?'warn':'');}
function ruler(el,r,anim){
  el.className='tickruler '+cls(r)+(anim?' anim':'');
  el.innerHTML='';
  var on=Math.round(r*20);
  for(var i=0;i<20;i++){var s=document.createElement('i');
    if(i<on){ s.className='on'; s.style.animationDelay=(i*30)+'ms'; }
    el.appendChild(s);}
}
function bar(max){return function(v){var d=document.createElement('div'); d.className='b';
  d.style.height=(max>0?Math.max(1,Math.round(v/max*120)):1)+'px'; return d;};}

/* 翻牌：值变了才动，逐字 split-flap；首载不动。force=true 时对当前值自翻（机场板刷新） */
var FLAPSTAGGER=70;   // 逐字错峰（ms）；翻牌时长在 CSS .flap .fo/.fn 里（唯一来源）
function escCh(c){ return c===' '?'&nbsp;':(c==='<'?'&lt;':(c==='>'?'&gt;':(c==='&'?'&amp;':c))); }
function setFlap(el,txt,force){
  if(!el) return;
  var old=el._fv;
  el._fv=txt;
  if(old==null){ el.textContent=txt; return; }
  if(old===txt && !force) return;
  if(old!==txt) el._flapChangedAt=Date.now();
  var len=Math.max(old.length,txt.length);
  var po=old.padStart(len,' '), pn=txt.padStart(len,' ');
  var html='', st=0;
  for(var i=0;i<len;i++){
    if(!force && po[i]===pn[i]){ html+=escCh(pn[i]); }
    else{
      html+='<span class="flap"><span class="fo" style="animation-delay:'+st+'ms">'+escCh(po[i])+
            '</span><span class="fn" style="animation-delay:'+st+'ms">'+escCh(pn[i])+'</span></span>';
      st+=FLAPSTAGGER;
    }
  }
  el.innerHTML=html.replaceAll('▓','<span class="mosaic">▓</span>');
}
/* 30s 强制翻牌节拍：8 组按固定次序错峰 1.5s，近 2s 内真变过的组跳过 */
var FLAPG=['q5p','q7p','qmp','tin','tout','tcache','tturns','thit'];
var FLAPCYCLE=30000, FLAPSTAG=1500;
function flapSchedule(){
  var now=Date.now();
  var cyc=Math.floor(now/FLAPCYCLE);
  for(var i=0;i<FLAPG.length;i++){
    var el=document.getElementById(FLAPG[i]);
    if(!el || el._fv==null || el._flapCyc===cyc) continue;
    if(now < cyc*FLAPCYCLE + i*FLAPSTAG) continue;
    el._flapCyc=cyc;
    if(now-(el._flapChangedAt||0) < 2000) continue;
    setFlap(el, el._fv, true);
  }
}

/* 重置倒计时：时间戳存这里，render 时刷新，1s ticker 只读（不与 60s 轮询争抢） */
var CD={q5:null,q7:null,qm:null};
/* 动画重触发守卫：值没变就不重播（steps 机器节拍） */
var ANIM={};
function animKey(n,k){ if(ANIM[n]===k) return false; ANIM[n]=k; return true; }
function cdFmt(ms){
  if(ms==null) return '--';
  if(ms<0) ms=0;
  var s=Math.floor(ms/1000);
  var d=Math.floor(s/86400); s%=86400;
  var h=Math.floor(s/3600), m=Math.floor(s%3600/60), ss=s%60;
  return 'T-'+(d>0? d+'天 ':'')+p2(h)+':'+p2(m)+':'+p2(ss);
}
function tickCd(){
  var now=Date.now();
  var e5=document.getElementById('cd5'), e7=document.getElementById('cd7'), em=document.getElementById('cdm');
  if(e5){
    if(CD.q5==null){ e5.textContent='--'; e5.className='cd num'; }
    else{ var m5=CD.q5-now; e5.textContent=cdFmt(m5); e5.className='cd num'+((m5>=0&&m5<600000)?' crit':''); }
  }
  if(e7){
    if(CD.q7==null){ e7.textContent='--'; e7.className='cd num'; }
    else{ e7.textContent=cdFmt(CD.q7-now); e7.className='cd num'; }
  }
  if(em){
    if(CD.qm==null){ em.textContent='--'; em.className='cd num'; }
    else{ em.textContent=cdFmt(CD.qm-now); em.className='cd num'; }
  }
  // 时间细轨：与倒计时同一节拍排空（用量槽内的 4px 弱化单线）
  tlTick('tl5',CD.q5==null?null:CD.q5-now,5*3600*1000);
  tlTick('tl7',CD.q7==null?null:CD.q7-now,7*86400*1000);
  tlTick('tlm',CD.qm==null?null:CD.qm-now,30*86400*1000);
}
function tlTick(id,ms,cyc){
  var tr=document.getElementById(id); if(!tr) return;
  var f=tr.children[0];
  if(!f){ f=document.createElement('div'); f.className='tlfill'; tr.appendChild(f); }
  if(ms==null){ f.style.width='0%'; tr.className='tltrack'; return; }
  var r=ms/cyc; if(r<0) r=0; if(r>1) r=1;
  f.style.width=(r*100).toFixed(2)+'%';
  tr.className='tltrack '+(r>0.5?'':(r>=0.2?'warn':'crit'));
}

function render(d){
  function sect(name,fn){ try{ fn(); }catch(e){ console.error('section '+name+' failed:', e); } }
  var t=d.today||{};
  sect('head',function(){
  document.getElementById('no').textContent='No.'+d.generatedNo;
  document.getElementById('now').textContent=d.generatedAt;
  var who=document.getElementById('who'), u=d.user||{};
  var name=(u.nickname&&u.level)?(u.nickname+' · '+u.level):(u.nickname||u.level||'');
  if(name){ who.textContent=name; who.style.display=''; }
  else{ who.textContent=''; who.style.display='none'; }
  document.getElementById('sig').textContent=name||'--';
  });
  sect('total',function(){
  document.getElementById('hit').textContent = t.hitRate==null?'--':(t.hitRate*100).toFixed(1);
  document.getElementById('hitsub').textContent =
    (t.hitRate==null?'--':fmt(t.cacheRead))+' / '+fmt((t.cacheRead||0)+(t.cacheCreate||0)+(t.input||0));
  });
  sect('hitline',function(){
  var svg=document.getElementById('hsvg');
  var s=d.hitSeries||[];
  var cx=150, cy=150, r1=104, r0=Math.round(r1*0.35);
  var ns='http://www.w3.org/2000/svg';
  function mk(tag,attrs){var e=document.createElementNS(ns,tag); for(var k in attrs){e.setAttribute(k,attrs[k]);} svg.appendChild(e); return e;}
  function pt(i,r){var a=(-90+i*6)*Math.PI/180; return {x:cx+r*Math.cos(a), y:cy+r*Math.sin(a)};}
  var i, x;
  // 固定参照系：内圈 r0=95%、外圈 r1=100%；低于 95% 的分钟按真实值向内潜
  function R(g){var r=r0+(g-0.95)/0.05*(r1-r0); return Math.max(6, Math.min(r1, r));}
  function P(i,g){return pt(i,R(g));}
  svg.innerHTML='';
  // 径向渐变：填色在折线附近可见，至内圈 r0 衰减为透明（消除扇形向心直边）
  var defs=mk('defs',{});
  var grad=document.createElementNS(ns,'radialGradient');
  grad.setAttribute('id','hgrad');
  grad.setAttribute('gradientUnits','userSpaceOnUse');
  grad.setAttribute('cx',cx); grad.setAttribute('cy',cy); grad.setAttribute('r',r1);
  [['0','0'],[''+(r0/r1),'0'],['0.8','0.16'],['1','0.20']].forEach(function(sp){
    var st=document.createElementNS(ns,'stop');
    st.setAttribute('offset',sp[0]);
    st.setAttribute('stop-color','#ff7a1a');
    st.setAttribute('stop-opacity',sp[1]);
    grad.appendChild(st);
  });
  defs.appendChild(grad);
  // 参考环：95% 虚线内圈（基线）
  mk('circle',{cx:cx,cy:cy,r:r0,'class':'ring95'});
  // 右侧纵向比例尺（直径规）：内圈直径端点=95%、外圈直径端点=100%
  var sbx=cx+r1+60;
  mk('line',{'class':'ax',x1:sbx.toFixed(1),y1:(cy-r1).toFixed(1),x2:sbx.toFixed(1),y2:(cy+r1).toFixed(1)});
  var rails=[[0.95,'95%'],[1.0,'100%']];
  for(var ri=0;ri<rails.length;ri++){
    var rG=R(rails[ri][0]);
    var ty=(cy-rG).toFixed(1), by=(cy+rG).toFixed(1);
    mk('line',{'class':'ax',x1:sbx.toFixed(1),y1:ty,x2:(sbx+6).toFixed(1),y2:ty});
    mk('line',{'class':'ax',x1:sbx.toFixed(1),y1:by,x2:(sbx+6).toFixed(1),y2:by});
    var st=mk('text',{x:(sbx+10).toFixed(1),y:(cy-rG+3).toFixed(1)}); st.textContent=rails[ri][1];
    var sb=mk('text',{x:(sbx+10).toFixed(1),y:(cy+rG+3).toFixed(1)}); sb.textContent=rails[ri][1];
  }
  // 细分校准刻度（每 1%，3px 短tick）
  for(var v1=96; v1<100; v1++){
    var r1p=R(v1/100);
    var my1=(cy-r1p).toFixed(1), my2=(cy+r1p).toFixed(1);
    mk('line',{'class':'rail-min',x1:sbx.toFixed(1),y1:my1,x2:(sbx+3).toFixed(1),y2:my1});
    mk('line',{'class':'rail-min',x1:sbx.toFixed(1),y1:my2,x2:(sbx+3).toFixed(1),y2:my2});
  }
  // 外缘：整圈虚线（数据顶点折线即实线，见下方 polyline）
  mk('circle',{cx:cx,cy:cy,r:r1,'class':'rimdash'});
  // 分钟弧线：null 断弧；连续段加闭合面积填充（沿内圈 r0 闭合）
  var run=[], runStart=0, lastpt=null;
  function flush(){
    if(run.length>1){
      var d='M '+run[0].p;
      for(var j=1;j<run.length;j++){ d+=' L '+run[j].p; }
      var pe=pt(runStart+run.length-1,r0), pb=pt(runStart,r0);
      var large=((run.length-1)*6>180)?1:0;
      d+=' L '+pe.x.toFixed(1)+','+pe.y.toFixed(1);
      d+=' A '+r0+','+r0+' 0 '+large+' 0 '+pb.x.toFixed(1)+','+pb.y.toFixed(1);
      d+=' Z';
      mk('path',{d:d,fill:'url(#hgrad)',stroke:'none'});
      mk('polyline',{'class':'ln',points:run.map(function(p){return p.p;}).join(' ')});
      // 折线位于 95% 内圈里的部分：红色闪烁（按弦与圆的精确交点截断）
      for(var j=0;j<run.length-1;j++){
        var a=run[j], b=run[j+1];
        var ax=a.p.split(','), bx=b.p.split(',');
        var x1=+ax[0], y1=+ax[1], x2=+bx[0], y2=+bx[1];
        var ra=Math.hypot(x1-cx,y1-cy), rb=Math.hypot(x2-cx,y2-cy);
        if(ra>=r0 && rb>=r0) continue;
        var ex=x2, ey=y2, sx=x1, sy=y1;
        // 精确交点：|a+t(b-a)-c|^2 = r0^2 的小根
        function crossT(){
          var dx=x2-x1, dy=y2-y1, fx=x1-cx, fy=y1-cy;
          var A=dx*dx+dy*dy, B=2*(dx*fx+dy*fy), C=fx*fx+fy*fy-r0*r0;
          var disc=B*B-4*A*C;
          if(disc<=0) return null;
          var sq=Math.sqrt(disc);
          var t1=(-B-sq)/(2*A), t2=(-B+sq)/(2*A);
          if(t1>=0&&t1<=1) return t1;
          if(t2>=0&&t2<=1) return t2;
          return null;
        }
        var tc=crossT();
        if(ra<r0 && rb>=r0){ // a 在内、b 在外：截到交点
          if(tc==null) continue;
          ex=x1+(x2-x1)*tc; ey=y1+(y2-y1)*tc;
        } else if(ra>=r0 && rb<r0){ // b 在内、a 在外：从交点起
          if(tc==null) continue;
          sx=x1+(x2-x1)*tc; sy=y1+(y2-y1)*tc;
        }
        mk('line',{x1:sx.toFixed(1),y1:sy.toFixed(1),x2:ex.toFixed(1),y2:ey.toFixed(1),'class':'low'});
      }
    }
    else if(run.length===1){
      var p=run[0].p.split(','); mk('circle',{'class':'dot',cx:p[0],cy:p[1],r:2});
      if(run[0].g<0.95){ mk('circle',{'class':'lowdot',cx:p[0],cy:p[1],r:3.5}); }
    }
    run=[];
  }
  for(i=0;i<s.length;i++){
    x=s[i];
    if(x.rate==null){ flush(); continue; }
    if(run.length===0){ runStart=i; }
    lastpt=P(i,x.rate);
    run.push({p:lastpt.x.toFixed(1)+','+lastpt.y.toFixed(1), g:x.rate});
  }
  flush();
  if(lastpt){ mk('circle',{'class':'dot',cx:lastpt.x.toFixed(1),cy:lastpt.y.toFixed(1),r:2.5}); }
  // 扫描线（SMIL 旋转，motion.md 批准的 scan sweep）
  var sw=mk('line',{'class':'sweep',x1:cx,y1:cy,x2:cx,y2:(cy-r1+6).toFixed(1)});
  var at=document.createElementNS(ns,'animateTransform');
  at.setAttribute('attributeName','transform');
  at.setAttribute('type','rotate');
  at.setAttribute('from','0 '+cx+' '+cy);
  at.setAttribute('to','360 '+cx+' '+cy);
  at.setAttribute('dur','12s');
  at.setAttribute('repeatCount','indefinite');
  sw.appendChild(at);
  // 表盘方位标签
  var tl=[['现在',cx,cy-r1-8,'middle'],['-15分',cx+r1+10,cy+3,'start'],
          ['-30分',cx,cy+r1+18,'middle'],['-45分',cx-r1-10,cy+3,'end']];
  for(i=0;i<4;i++){ var e=mk('text',{x:tl[i][1],y:tl[i][2],'text-anchor':tl[i][3]}); e.textContent=tl[i][0]; }
  // 悬停读数：角度→分钟，跟随光标的读数 + 表盘标记
  var tip=document.getElementById('dialtip');
  if(tip){ tip.style.display='none'; }
  var mark=null;
  svg.onmousemove=function(e){
    if(!s.length) return;
    var host=svg.parentNode; if(!host) return;
    var rb=svg.getBoundingClientRect();
    var mx=(e.clientX-rb.left)*360/rb.width, my=(e.clientY-rb.top)*300/rb.height;
    var deg=Math.atan2(my-cy, mx-cx)*180/Math.PI;
    var mi=Math.round((deg+90)/6); mi=((mi%60)+60)%60;
    var it=s[mi]; if(!it) return;
    if(!tip){
      tip=document.createElement('div'); tip.id='dialtip'; tip.className='dialtip';
      host.appendChild(tip);
    }
    tip.textContent=it.t+' · '+(it.rate==null?'无数据':(it.rate*100).toFixed(1)+'%');
    var hr=host.getBoundingClientRect();
    tip.style.left=(e.clientX-hr.left+14)+'px';
    tip.style.top=(e.clientY-hr.top-12)+'px';
    tip.style.display='block';
    if(!mark){
      mark=document.createElementNS(ns,'circle');
      mark.setAttribute('class','hovermark'); mark.setAttribute('r',3);
      svg.appendChild(mark);
    }
    var q=(it.rate==null)?P(mi,Math.max(lo,Math.min(hi,0.95))):P(mi,it.rate);
    mark.setAttribute('cx',q.x.toFixed(1));
    mark.setAttribute('cy',q.y.toFixed(1));
  };
  svg.onmouseleave=function(){
    if(mark&&mark.parentNode){ mark.parentNode.removeChild(mark); }
    mark=null;
    if(tip){ tip.style.display='none'; }
  };
  document.getElementById('hstart').textContent=s.length?s[0].t:'--';
  document.getElementById('hend').textContent=s.length?s[s.length-1].t:'--';
  });
  sect('today',function(){
  setFlap(document.getElementById('tin'),fmt(t.input));
  setFlap(document.getElementById('tout'),fmt(t.output));
  setFlap(document.getElementById('tcache'),fmt(t.cacheRead)+' / ▓▓▓');
  document.getElementById('tcache').title='Kimi 不上报缓存创建量，写侧以马赛克占位';
  setFlap(document.getElementById('tturns'),fmt(t.turns));
  setFlap(document.getElementById('thit'),pct(t.hitRate));
  // 命中率高是好事，不套额度的高低警戒色
  var ch=document.getElementById('chiph');
  if(ch){
    ch.textContent='AT-FIELD '+(t.hitRate==null?'--':(t.hitRate*100).toFixed(1)+'%');
    ch.className='chip '+(t.hitRate==null?'':(t.hitRate>=0.95?'':(t.hitRate>=0.85?'warn':'crit')));
  }
  });
  sect('hourly',function(){
  var tb=document.getElementById('tbars'); tb.innerHTML='';
  var h=d.hourly||[];
  var tmax=Math.max.apply(null,h.concat([1]));
  var anim=animKey('hourly',h.join(','));
  tb.className='bars today'+(anim?' anim':'');
  var lastnz=-1;
  h.forEach(function(v,i){ if(v>0) lastnz=i; });
  h.forEach(function(v,i){
    var b=bar(tmax)(v);
    b.title=v.toLocaleString('en-US')+' tokens';
    b.style.animationDelay=(i*15)+'ms';
    if(i===lastnz&&lastnz>=0) b.className='b live';
    tb.appendChild(b);
  });
  });
  sect('days',function(){
  var db=document.getElementById('dbars'); db.innerHTML='';
  var days=d.days||[];
  var dmax=Math.max.apply(null,days.map(function(x){return x.tokens;}).concat([1]));
  var anim=animKey('daily',days.map(function(x){return x.tokens;}).join(','));
  db.className='bars days'+(anim?' anim':'');
  days.forEach(function(x,i){
    var b=bar(dmax)(x.tokens);
    b.title=x.date+' · '+x.tokens.toLocaleString('en-US')+' tokens · 命中率 '+(x.hitRate==null?'--':(x.hitRate*100).toFixed(1)+'%')+' · '+x.turns+' 轮';
    b.style.animationDelay=(i*15)+'ms';
    if(i===days.length-1&&days.length) b.className='b live';
    db.appendChild(b);
  });
  var ax=document.getElementById('daxis');
  if(ax.children.length>=2&&days.length){
    ax.children[0].textContent=days[0].date.slice(5);
    ax.children[1].textContent=days[days.length-1].date.slice(5);
  }
  });
  sect('quota',function(){
  var q=d.quota;
  if(q&&q.ok){
    CD.q5=Date.parse(q.limit5h.resetAt)||null;
    CD.q7=Date.parse(q.limit7d.resetAt)||null;
    setFlap(document.getElementById('q5p'),'已用 '+pct(q.limit5h.usedRatio,1));
    document.getElementById('q5p').className='v pct '+cls(q.limit5h.usedRatio);
    setFlap(document.getElementById('q7p'),'已用 '+pct(q.limit7d.usedRatio,1));
    document.getElementById('q7p').className='v pct '+cls(q.limit7d.usedRatio);
    document.getElementById('q5r').textContent='剩 '+pct(1-q.limit5h.usedRatio,1)+' · 重置 '+q.limit5h.resetLocal;
    document.getElementById('q7r').textContent='剩 '+pct(1-q.limit7d.usedRatio,1)+' · 重置 '+q.limit7d.resetLocal;
    ruler(document.getElementById('q5t'),q.limit5h.usedRatio,animKey('r5',''+q.limit5h.usedRatio));
    ruler(document.getElementById('q7t'),q.limit7d.usedRatio,animKey('r7',''+q.limit7d.usedRatio));
    document.getElementById('qleft').textContent='';
  }else{
    CD.q5=null; CD.q7=null;
    setFlap(document.getElementById('q5p'),'不可用');
    setFlap(document.getElementById('q7p'),'不可用');
    document.getElementById('q5r').textContent=''; document.getElementById('q7r').textContent='';
    ruler(document.getElementById('q5t'),0); ruler(document.getElementById('q7t'),0);
    document.getElementById('qleft').textContent='额度接口暂不可用';
  }
  var worst=Math.max(q&&q.ok?q.limit5h.usedRatio:0, q&&q.ok?q.limit7d.usedRatio:0, (d.monthly&&d.monthly.used!=null)?d.monthly.used:0);
  var cq=document.getElementById('chipq');
  if(cq){
    cq.textContent='MAGI '+(worst*100).toFixed(1)+'%';
    cq.className='chip '+(worst>=0.85?'crit':(worst>=0.6?'warn':''));
  }
  });
  sect('monthly',function(){
  var m=d.monthly||{used:null};
  CD.qm=(m.used!=null&&m.expire)?(Date.parse(m.expire)||null):null;
  var qmp=document.getElementById('qmp'), qmr=document.getElementById('qmr');
  if(m.used!=null){
    setFlap(qmp,'已用 '+pct(m.used,1));
    qmp.className='v pct '+cls(m.used);
    qmr.textContent='剩 '+pct(1-m.used,1)
      +(m.expireLocal?' · 到期 '+m.expireLocal:'')
      +(m.cached?' · 更新于 '+(m.fetchedAt||'--'):'');
    ruler(document.getElementById('qmt'),m.used,animKey('rm',''+m.used));
  }else{
    setFlap(qmp,'--');
    qmp.className='v pct';
    qmr.textContent='';
    ruler(document.getElementById('qmt'),0,false);
  }
  });
  sect('rail',function(){
  var worst=Math.max(d.quota&&d.quota.ok?d.quota.limit5h.usedRatio:0, d.quota&&d.quota.ok?d.quota.limit7d.usedRatio:0, (d.monthly&&d.monthly.used!=null)?d.monthly.used:0);
  var r1=document.getElementById('rail1');
  if(r1) r1.textContent=(d.quota&&d.quota.ok)?'LINK OK':'DOWN';
  var r2=document.getElementById('rail2');
  if(r2) r2.textContent=(worst*100).toFixed(1)+'%';
  var r3=document.getElementById('rail3');
  if(r3) r3.textContent=fmt(d.turns);
  // ECG 心率：近 10 分钟活跃分钟数 -> BPM(40..140)，写入 window._ecgBpm 供彗星驱动
  var hs=d.hitSeries||[];
  var act=0;
  for(var q=Math.max(0,hs.length-10); q<hs.length; q++){ if(hs[q]&&hs[q].rate!=null) act++; }
  window._ecgBpm=Math.min(140, 40+act*10);
  // ECG 彗星：亮核 + 连续余晖（rAF 驱动；一圈 480/BPM 秒）
  (function(){
    if(window._ecgComet) return; window._ecgComet=true;
    var wave=document.getElementById('ecgpath');
    var lead=document.getElementById('ecglead');
    var trail=document.getElementById('ecgtrail');
    var tg=document.getElementById('ecgtg');
    if(!wave||!lead||!trail||!tg) return;
    var L=wave.getTotalLength(), pts=[], last=0, t0=performance.now();
    function frame(now){
      var bpm=window._ecgBpm||90;
      var dur=480/bpm*1000;
      var dist=((now-t0)%dur)/dur*L;
      if(dist<last){ pts=[]; }          // 折返清零：消除右端到左端的连线
      last=dist;
      var p=wave.getPointAtLength(dist);
      lead.setAttribute('cx',p.x.toFixed(1)); lead.setAttribute('cy',p.y.toFixed(1));
      pts.push(p);                       // 全程留痕：扫过即"打印"，形成心电波形
      var dd='M'+pts[0].x.toFixed(1)+','+pts[0].y.toFixed(1);
      for(var i=1;i<pts.length;i++){ dd+=' L'+pts[i].x.toFixed(1)+','+pts[i].y.toFixed(1); }
      trail.setAttribute('d',dd);
      tg.setAttribute('x1',pts[0].x.toFixed(1));
      tg.setAttribute('x2',p.x.toFixed(1));
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  })();
  // LEVEL METER：worst quota 垂直液位计（24 段）；最顶满格 = 当前水位，闪烁
  var lb=document.getElementById('lvlbar');
  if(lb){
    lb.className='lvlbar '+(worst>=0.85?'crit':(worst>=0.6?'warn':''));
    lb.innerHTML='';
    var on=Math.round(worst*24);
    for(var i=0;i<24;i++){var sg=document.createElement('i'); if(i<on) sg.className=(i===on-1)?'on cur':'on'; lb.appendChild(sg);}
  }
  var lv=document.getElementById('lvlv');
  if(lv) lv.textContent=(worst*100).toFixed(1)+'%';
  // ACTIVITY：今日 24 小时活跃 tick 列 + 计数对；当前小时 tick 闪烁
  var ac=document.getElementById('act24');
  if(ac){
    ac.innerHTML='';
    var H=d.hourly||[];
    var curH=new Date().getHours();
    for(var j=0;j<24;j++){var tk=document.createElement('i'); if(H[j]>0) tk.className='on'; if(j===curH) tk.className=(tk.className?tk.className+' ':'')+'cur'; ac.appendChild(tk);}
  }
  var td=d.today||{};
  var t1=document.getElementById('rt1'); if(t1) t1.textContent=fmt(td.turns);
  var turns30=0;
  (d.days||[]).forEach(function(x){ turns30+=x.turns; });
  var t2=document.getElementById('rt2'); if(t2) t2.textContent=fmt(turns30);
  var t3=document.getElementById('rt3'); if(t3){t3.innerHTML=fmt(td.cacheRead)+'/<span class="mosaic">▓▓▓</span>'; t3.title='Kimi 不上报缓存创建量，写侧以马赛克占位';}
  // A.T. FIELD 迷你状态：当前分钟命中率 + 今日 FIELD 状态字
  var hs=d.hitSeries||[], lastm=null;
  for(var k=hs.length-1;k>=0;k--){ if(hs[k].rate!=null){ lastm=hs[k]; break; } }
  var f1=document.getElementById('f1');
  if(f1) f1.textContent=lastm?((lastm.rate*100).toFixed(1)+'%'):'--';
  var f2=document.getElementById('f2');
  if(f2) f2.textContent=pct(td.hitRate);
  var f3=document.getElementById('f3');
  if(f3) f3.textContent=(td.hitRate==null?'--':(td.hitRate>=0.95?'STABLE':(td.hitRate>=0.85?'WATCH':'DEGRADED')));
  });
  sect('workspaces',function(){
  var wb=document.getElementById('ws'); wb.innerHTML='';
  var ws=d.workspaces||[];
  ws.forEach(function(w,i){
    var tr=document.createElement('tr');
    var h=(w.hitRate==null?'--':(w.hitRate*100).toFixed(1)+'%');
    tr.innerHTML='<td class="num">'+(i+1)+'</td><td>'+w.name+'</td><td class="r">'+fmt(w.tokens)+'</td><td class="r">'+fmt(w.turns)+'</td><td class="r">'+h+'</td>';
    wb.appendChild(tr);
  });
  if(ws.length===0){var tr=document.createElement('tr'); tr.innerHTML='<td colspan="5" class="label">近 30 天无记录</td>'; wb.appendChild(tr);}
  });
}

function load(){
  fetch('/api/data').then(function(r){return r.json();}).then(render).catch(function(e){console.error(e);});
}
load();
setInterval(load,60000);
/* A.T. FIELD 面板准星：鼠标处 X/Y 轴交线 */
(function(){
  var sec=document.querySelector('section.total .frame');
  if(!sec) return;
  if(getComputedStyle(sec).position==='static') sec.style.position='relative';
  var v=document.createElement('i'), h=document.createElement('i'), d=document.createElement('i');
  v.className='crosshair ch-v'; h.className='crosshair ch-h'; d.className='ch-dot';
  sec.appendChild(v); sec.appendChild(h); sec.appendChild(d);
  sec.addEventListener('mousemove',function(e){
    var r=sec.getBoundingClientRect();
    var x=e.clientX-r.left, y=e.clientY-r.top;
    v.style.left=x+'px'; h.style.top=y+'px';
    d.style.left=x+'px'; d.style.top=y+'px';
    v.style.display=h.style.display=d.style.display='block';
  });
  sec.addEventListener('mouseleave',function(){
    v.style.display=h.style.display=d.style.display='none';
  });
})();
/* 指挥时钟 + 运行时长 + BOOT 戳（机器刷新读数） */
function p2(n){return (n<10?'0':'')+n;}
var T0=Date.now();
function tickClock(){
  var d=new Date();
  var c=document.getElementById('clock');
  if(c) c.textContent=d.getFullYear()+'-'+p2(d.getMonth()+1)+'-'+p2(d.getDate())+' '+p2(d.getHours())+':'+p2(d.getMinutes())+':'+p2(d.getSeconds());
  var u=document.getElementById('uptime');
  if(u){var s=Math.floor((Date.now()-T0)/1000); u.textContent='UP '+p2(Math.floor(s/3600))+':'+p2(Math.floor(s/60)%60)+':'+p2(s%60);}
}
setInterval(tickClock,1000); tickClock();
setInterval(tickCd,1000); tickCd();
setInterval(flapSchedule,1000);
var bt=document.getElementById('boot');
if(bt) bt.textContent=new Date().toTimeString().slice(0,8);
</script>
</body>
</html>"""


def local_dt():
    return datetime.now().astimezone()


def empty_usage_cache():
    return {"files": {}, "tot": {"read": 0, "create": 0, "other": 0, "turns": 0},
            "days": {}, "wss": {}, "minutes": {}}


def load_usage_cache():
    try:
        with open(USAGE_CACHE_FILE, "r", encoding="utf-8") as f:
            c = json.load(f)
        for k, default in empty_usage_cache().items():
            if not isinstance(c.get(k), type(default)):
                c[k] = default
        return c
    except Exception:
        return empty_usage_cache()


def save_usage_cache(cache):
    tmp = USAGE_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, USAGE_CACHE_FILE)


def prune_usage_cache(cache, now, today_key):
    day_cut = (now - timedelta(days=35)).strftime("%Y-%m-%d")
    min_cut = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    cache["days"] = {k: v for k, v in cache["days"].items() if k >= day_cut}
    for k, v in cache["days"].items():
        if k != today_key:
            v.pop("hourly", None)
    wss = {}
    for ws, dates in cache["wss"].items():
        keep = {k: v for k, v in dates.items() if k >= day_cut}
        if keep:
            wss[ws] = keep
    cache["wss"] = wss
    cache["minutes"] = {k: v for k, v in cache["minutes"].items() if k >= min_cut}
    cache["files"] = {p: i for p, i in cache["files"].items() if os.path.exists(p)}


def fold_event(cache, ws, dt, u, today_key):
    """把一条 usage 记录折进缓存聚合（tot 全量 / days 按天 / wss 按工作区按天 / minutes 按分钟）"""
    inp = int(u.get("inputOther") or 0)
    cr = int(u.get("inputCacheRead") or 0)
    cc = int(u.get("inputCacheCreation") or 0)
    out = int(u.get("output") or 0)
    total = inp + cr + cc + out
    tot = cache["tot"]
    tot["read"] += cr
    tot["create"] += cc
    tot["other"] += inp
    tot["turns"] += 1

    dkey = dt.strftime("%Y-%m-%d")
    d = cache["days"].setdefault(dkey, {"input": 0, "output": 0, "cacheRead": 0,
                                        "cacheCreate": 0, "turns": 0, "hourly": [0] * 24})
    d["input"] += inp
    d["output"] += out
    d["cacheRead"] += cr
    d["cacheCreate"] += cc
    d["turns"] += 1
    if dkey == today_key:
        d["hourly"][dt.hour] += total

    w = cache["wss"].setdefault(ws, {}).setdefault(
        dkey, {"tokens": 0, "read": 0, "create": 0, "other": 0, "turns": 0})
    w["tokens"] += total
    w["read"] += cr
    w["create"] += cc
    w["other"] += inp
    w["turns"] += 1

    mk = dt.strftime("%Y-%m-%d %H:%M")
    b = cache["minutes"].setdefault(mk, [0, 0, 0])
    b[0] += cr
    b[1] += cc
    b[2] += inp


def scan_session_files(cache, today_key):
    """增量扫描所有 wire.jsonl：offset+mtime 未变则只读尾部，否则整读"""
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, "*", "*", "agents", "*", "wire.jsonl")):
            parts = path.split(os.sep)
            ws = parts[len(parts) - 5]
            try:
                st = os.stat(path)
            except OSError:
                cache["files"].pop(path, None)
                continue
            info = cache["files"].get(path)
            # 追加型日志：size >= offset 即只读尾部新字节（mtime 每次追加都会变，
            # 不能作为整读判据，否则历史事件会被重复计入）；size < offset 视为截断/轮换，整读重计
            start = 0
            if info and st.st_size >= info.get("offset", 0) > 0:
                start = info["offset"]
            try:
                with open(path, "rb") as f:
                    f.seek(start)
                    for raw in f:
                        if b'"usage"' not in raw:
                            continue
                        try:
                            obj = json.loads(raw)
                        except Exception:
                            continue
                        usage = obj.get("usage")
                        ts = obj.get("time")
                        if usage is None:
                            msg = obj.get("message")
                            if isinstance(msg, dict):
                                usage = (msg.get("meta") or {}).get("usage")
                                ts = obj.get("time") or msg.get("time")
                        if not isinstance(usage, dict):
                            continue
                        try:
                            ts = int(ts)
                            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone()
                        except (TypeError, ValueError, OverflowError, OSError):
                            continue
                        fold_event(cache, ws, dt, usage, today_key)
                    offset = f.tell()
                cache["files"][path] = {"offset": offset, "mtime": st.st_mtime}
            except OSError:
                continue


def local_server():
    """最新 CLI 本地服务实例 (host, port, token)；失败返回 None"""
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            token = f.read().strip()
        best, best_hb = None, -1
        for p in glob.glob(os.path.join(INSTANCES_DIR, "*.json")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    inst = json.load(f)
                if inst.get("heartbeat_at", 0) > best_hb:
                    best, best_hb = inst, inst["heartbeat_at"]
            except Exception:
                continue
        if best and token:
            return best["host"], best["port"], token
    except Exception:
        pass
    return None


def api_get(path, srv):
    url = "http://%s:%s%s" % (srv[0], srv[1], path)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + srv[2]})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_quota():
    try:
        srv = local_server()
        if not srv:
            return {"ok": False}
        data = api_get("/api/v1/oauth/usage", srv)
        usages = data["data"]["quota"]["usages"]

        def conv(u):
            iso = u.get("resetAt")
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
                local = dt.strftime("%m-%d %H:%M")
            except Exception:
                local = iso or "--"
            return {"usedRatio": float(u.get("usedRatio", 0)), "resetAt": iso, "resetLocal": local}

        return {"ok": True, "limit5h": conv(usages["limit5h"]), "limit7d": conv(usages["limit7d"])}
    except Exception:
        return {"ok": False}


def fetch_userinfo():
    """会员级别 / 昵称（CLI 本地服务，凭据稳定）；失败返回空串"""
    try:
        srv = local_server()
        if not srv:
            return {"nickname": "", "level": ""}
        u = (api_get("/api/v1/oauth/userinfo", srv).get("data") or {}).get("userInfo") or {}
        return {"nickname": u.get("nickname") or "", "level": u.get("userLevelName") or ""}
    except Exception:
        return {"nickname": "", "level": ""}


def iso_local(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return ""


def read_tokens():
    """候选云端 JWT：daimon config.json 全量扫描 + leveldb 日志正则"""
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


def fetch_monthly():
    """云端月度额度。云端 JWT 仅 ~14 分钟且随桌面端刷新，常失败：
    成功写 dashboard_cache.json；失败回退缓存（标注更新时间）；再无则 used=None。"""
    for tok in read_tokens()[:3]:
        try:
            req = urllib.request.Request(
                CLOUD_URL, data=b"{}",
                headers={"Authorization": "Bearer " + tok,
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=CLOUD_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            bal = data.get("subscriptionBalance") or {}
            if bal.get("amountUsedRatio") is None:
                raise ValueError("no amountUsedRatio")
            result = {"used": float(bal["amountUsedRatio"]),
                      "expire": bal.get("expireTime") or "",
                      "expireLocal": iso_local(bal.get("expireTime") or ""),
                      "cached": False, "fetchedAt": local_dt().strftime("%H:%M")}
            try:
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"used": result["used"],
                               "expire": bal.get("expireTime") or "",
                               "fetched_at": time.time()}, f)
            except OSError:
                pass
            return result
        except Exception:
            continue
    try:
        c = json.load(open(CACHE_FILE, encoding="utf-8"))
        if c.get("used") is not None:
            return {"used": float(c["used"]),
                    "expire": c.get("expire") or "",
                    "expireLocal": iso_local(c.get("expire") or ""),
                    "cached": True,
                    "fetchedAt": datetime.fromtimestamp(c.get("fetched_at", 0)).strftime("%H:%M")}
    except Exception:
        pass
    return {"used": None, "expire": "", "expireLocal": "", "cached": False, "fetchedAt": ""}


def compute():
    now = local_dt()
    today_key = now.strftime("%Y-%m-%d")
    day0 = (now - timedelta(days=29)).strftime("%Y-%m-%d")

    def hit(read, create, other):
        denom = read + create + other
        return (read / denom) if denom else None

    with USAGE_LOCK:
        cache = load_usage_cache()
        scan_session_files(cache, today_key)
        prune_usage_cache(cache, now, today_key)
        save_usage_cache(cache)

        tot = cache["tot"]
        days = cache["days"]
        minutes = cache["minutes"]

        td = days.get(today_key, {"input": 0, "output": 0, "cacheRead": 0,
                                  "cacheCreate": 0, "turns": 0})
        today = {"input": td["input"], "output": td["output"],
                 "cacheRead": td["cacheRead"], "cacheCreate": td["cacheCreate"],
                 "turns": td["turns"]}
        today["hitRate"] = hit(today["cacheRead"], today["cacheCreate"], today["input"])
        hourly = td.get("hourly") or [0] * 24

        base_minute = now.replace(second=0, microsecond=0)
        window_start = base_minute - timedelta(minutes=59)
        hit_series = []
        for i in range(60):
            mk = window_start + timedelta(minutes=i)
            b = minutes.get(mk.strftime("%Y-%m-%d %H:%M"))
            denom = (b[0] + b[1] + b[2]) if b else 0
            hit_series.append({"t": mk.strftime("%H:%M"),
                               "rate": (b[0] / denom) if denom else None})

        day_list = []
        for i in range(30):
            dkey = (now - timedelta(days=29 - i)).strftime("%Y-%m-%d")
            d = days.get(dkey)
            day_list.append({
                "date": dkey,
                "tokens": (d["input"] + d["output"] + d["cacheRead"] + d["cacheCreate"]) if d else 0,
                "turns": d["turns"] if d else 0,
                "hitRate": hit(d["cacheRead"], d["cacheCreate"], d["input"]) if d else None,
            })

        ws_acc = {}
        for ws, dates in cache["wss"].items():
            acc = {"tokens": 0, "read": 0, "create": 0, "other": 0, "turns": 0}
            for dkey, v in dates.items():
                if dkey < day0:
                    continue
                for k in acc:
                    acc[k] += v[k]
            ws_acc[ws] = acc
        ws_rank = sorted(ws_acc.items(), key=lambda kv: kv[1]["tokens"], reverse=True)[:8]
        workspaces = [{
            "name": name,
            "tokens": v["tokens"],
            "turns": v["turns"],
            "hitRate": hit(v["read"], v["create"], v["other"]),
        } for name, v in ws_rank]

        hit_all = hit(tot["read"], tot["create"], tot["other"])

    return {
        "generatedAt": now.strftime("%Y-%m-%d %H:%M:%S"),
        "generatedNo": now.strftime("%m%d"),
        "hitRate": hit_all,
        "hitSeries": hit_series,
        "turns": tot["turns"],
        "today": today,
        "hourly": hourly,
        "days": day_list,
        "workspaces": workspaces,
        "quota": fetch_quota(),
        "user": fetch_userinfo(),
        "monthly": fetch_monthly(),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/api/data":
            body = json.dumps(compute(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        elif self.path == "/logo.png":
            try:
                with open(LOGO_FILE, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
            except OSError:
                body = b"not found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
        elif self.path.startswith("/kimi-") and self.path.endswith(".png"):
            try:
                with open(os.path.join(APP_DIR, os.path.basename(self.path)), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
            except OSError:
                body = b"not found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
        else:
            self.send_response(404)
            body = b"not found"
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # 已有实例在跑：只打开页面，不抢端口
        if "--no-open" not in sys.argv:
            webbrowser.open("http://127.0.0.1:%d" % PORT)
        return
    print("Kimi Code 计量台  http://127.0.0.1:%d" % PORT)
    if "--no-open" not in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open("http://127.0.0.1:%d" % PORT)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
