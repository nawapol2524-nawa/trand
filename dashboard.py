import http.server
import socketserver
import os
import sys
import time
import threading
import json
import urllib.parse
import subprocess
import socket
import signal
from datetime import datetime, timedelta

PORT = 9848
CONSOLE_LOG_FILE = "console_log.txt"
STATUS_LOG_FILE = "status_log.txt"

def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def read_last_lines(filepath, num_lines=180, buffer_size=128 * 1024):
    """
    อ่าน N บรรทัดสุดท้ายจากไฟล์อย่างปลอดภัย รวดเร็วระดับ O(1)
    ไม่โหลดทั้งไฟล์เข้า RAM รองรับไฟล์ขนาดใหญ่หลายร้อย MB ปลอดภัยต่อ Race Condition
    """
    try:
        if not os.path.exists(filepath):
            return ""
        size = os.path.getsize(filepath)
        if size == 0:
            return ""

        with open(filepath, "rb") as f:
            if size <= buffer_size:
                data = f.read()
            else:
                f.seek(size - buffer_size)
                data = f.read()
                # ถ้า seek กลางไฟล์ ให้ตัดบรรทัดแรกที่อาจไม่สมบูรณ์ทิ้ง
                first_nl = data.find(b"\n")
                if first_nl != -1:
                    data = data[first_nl + 1:]

            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines(keepends=True)
            if len(lines) > num_lines:
                lines = lines[-num_lines:]
            return "".join(lines)
    except Exception:
        return ""

def get_console_text(lines=180):
    """อ่านข้อความล่าสุดจาก console_log.txt หรือ status_log.txt อย่างปลอดภัย 100%"""
    # 1. พยายามอ่านจาก console_log.txt ก่อน
    content = read_last_lines(CONSOLE_LOG_FILE, num_lines=lines)

    # 2. ถ้า console_log.txt ยังว่างหรือไม่มี ให้สลับไปอ่าน status_log.txt
    if not content.strip():
        content = read_last_lines(STATUS_LOG_FILE, num_lines=lines)

    # 3. ถ้ายังว่างทั้งคู่ ให้แสดงสถานะที่ชัดเจน
    if not content.strip():
        return "⏳ กำลังรอสัญญาณ Console Log จากระบบ Supervisor..."

    return content

def append_to_console_log(text):
    """บันทึกคำสั่งและผลลัพธ์ลง console_log.txt เพื่อให้ซิงค์ขึ้น Google Drive และแสดงสด"""
    try:
        with open(CONSOLE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass

HTML_PAGE = """<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AG 2.0 Live Quant Terminal</title>
    <style>
        /* Base / PowerShell Dark Theme (ขาว-ดำ / Charcoal) - ค่าเริ่มต้น */
        :root {
            --bg-color: #0c0c0c;
            --panel-bg: #161b22;
            --terminal-bg: #0d1117;
            --border-color: #30363d;
            --text-primary: #58a6ff;
            --text-terminal: #f0f6fc; /* ขาวสว่าง คมชัด ไม่แสบตา */
            --prompt-symbol-color: #58a6ff;
            --text-dim: #8b949e;
            --accent-btn: #238636;
            --accent-btn-hover: #2ea043;
            --input-bg: #010409;
            --input-text: #ffffff;
            --danger: #f85149;
        }

        /* ธีม: PowerShell Classic (น้ำเงินเข้ม-ขาว แบบ Windows PowerShell) */
        body.theme-powershell-blue {
            --bg-color: #011638;
            --panel-bg: #011e4d;
            --terminal-bg: #012456; /* น้ำเงินเข้มเอกลักษณ์ของ PowerShell */
            --border-color: #1a3c74;
            --text-primary: #90caf9;
            --text-terminal: #ffffff; /* ขาวบริสุทธิ์ */
            --prompt-symbol-color: #e5c07b;
            --text-dim: #90a4ae;
            --accent-btn: #0969da;
            --accent-btn-hover: #1f6feb;
            --input-bg: #011a3d;
            --input-text: #ffffff;
        }

        /* ธีม: Pure Black & White (ดำสนิท-ขาว เรียบหรู) */
        body.theme-true-black {
            --bg-color: #000000;
            --panel-bg: #111111;
            --terminal-bg: #000000;
            --border-color: #262626;
            --text-primary: #ffffff;
            --text-terminal: #ffffff;
            --prompt-symbol-color: #ffffff;
            --text-dim: #777777;
            --accent-btn: #2b2b2b;
            --accent-btn-hover: #444444;
            --input-bg: #0a0a0a;
            --input-text: #ffffff;
        }

        /* ธีม: Matrix Green (เขียวเดิม สำหรับคนที่ชอบ) */
        body.theme-matrix {
            --bg-color: #0d1117;
            --panel-bg: #161b22;
            --terminal-bg: #010409;
            --border-color: #30363d;
            --text-primary: #58a6ff;
            --text-terminal: #39ff14;
            --prompt-symbol-color: #39ff14;
            --text-dim: #8b949e;
            --accent-btn: #238636;
            --accent-btn-hover: #2ea043;
            --input-bg: #010409;
            --input-text: #ffffff;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-color);
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 12px;
            transition: background-color 0.2s;
        }

        /* Top Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 16px;
            background: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px 8px 0 0;
        }

        .header-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 700;
            font-size: 1.05em;
            letter-spacing: 0.5px;
            color: var(--text-primary);
            font-family: 'SF Mono', Monaco, Consolas, 'Courier New', monospace;
        }

        .header-status {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.85em;
        }

        .badge {
            padding: 3px 8px;
            border-radius: 12px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        .badge-live {
            background: rgba(46, 160, 67, 0.2);
            color: #3fb950;
            border: 1px solid rgba(46, 160, 67, 0.4);
        }

        .badge-warning {
            background: rgba(227, 179, 65, 0.2);
            color: #e3b341;
            border: 1px solid rgba(227, 179, 65, 0.4);
        }

        .badge-error {
            background: rgba(248, 81, 73, 0.2);
            color: #f85149;
            border: 1px solid rgba(248, 81, 73, 0.4);
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            background-color: #3fb950;
            border-radius: 50%;
            animation: pulse 1.8s infinite;
        }

        .pulse-dot.warning {
            background-color: #e3b341;
            animation: pulse-warn 1.4s infinite;
        }

        .pulse-dot.error {
            background-color: #f85149;
            animation: none;
            box-shadow: 0 0 6px #f85149;
        }

        @keyframes pulse {
            0% { transform: scale(0.9); opacity: 0.7; }
            50% { transform: scale(1.3); opacity: 1; box-shadow: 0 0 8px #3fb950; }
            100% { transform: scale(0.9); opacity: 0.7; }
        }

        @keyframes pulse-warn {
            0% { transform: scale(0.9); opacity: 0.7; }
            50% { transform: scale(1.3); opacity: 1; box-shadow: 0 0 8px #e3b341; }
            100% { transform: scale(0.9); opacity: 0.7; }
        }

        /* Controls Bar */
        .controls-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 7px 14px;
            background: var(--panel-bg);
            border-left: 1px solid var(--border-color);
            border-right: 1px solid var(--border-color);
            border-bottom: 1px solid var(--border-color);
            font-size: 0.82em;
            color: var(--text-dim);
            flex-wrap: wrap;
            gap: 8px;
        }

        .controls-bar label {
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            user-select: none;
        }

        .theme-selector {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .theme-selector select {
            background: var(--input-bg);
            color: var(--text-terminal);
            border: 1px solid var(--border-color);
            border-radius: 5px;
            padding: 3px 8px;
            font-size: 0.9em;
            font-family: inherit;
            cursor: pointer;
            outline: none;
        }

        /* Live Console Screen */
        .console-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 520px;
            background: var(--terminal-bg);
            border-left: 1px solid var(--border-color);
            border-right: 1px solid var(--border-color);
            position: relative;
        }

        pre#consoleOutput {
            flex: 1;
            padding: 16px;
            color: var(--text-terminal);
            background: var(--terminal-bg);
            font-family: 'SF Mono', 'Cascadia Code', Consolas, 'Courier New', Menlo, Monaco, monospace;
            font-size: 0.9em;
            line-height: 1.48;
            white-space: pre-wrap;
            word-break: break-all;
            overflow-y: auto;
            max-height: calc(100vh - 180px);
        }

        /* Custom Scrollbar */
        pre#consoleOutput::-webkit-scrollbar {
            width: 8px;
        }
        pre#consoleOutput::-webkit-scrollbar-track {
            background: var(--terminal-bg);
        }
        pre#consoleOutput::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 4px;
        }
        pre#consoleOutput::-webkit-scrollbar-thumb:hover {
            background: var(--text-primary);
        }

        /* Command Input Section */
        .command-wrapper {
            background: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 0 0 8px 8px;
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        form#cmdForm {
            display: flex;
            align-items: center;
            gap: 8px;
            width: 100%;
        }

        .prompt-symbol {
            color: var(--prompt-symbol-color);
            font-family: 'SF Mono', Monaco, Consolas, monospace;
            font-size: 1.05em;
            font-weight: bold;
            padding-left: 4px;
            white-space: nowrap;
        }

        input#cmdInput {
            flex: 1;
            padding: 10px 14px;
            background: var(--input-bg);
            color: var(--input-text);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            font-family: 'SF Mono', Monaco, Consolas, monospace;
            font-size: 0.95em;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        input#cmdInput:focus {
            border-color: var(--text-primary);
            box-shadow: 0 0 6px rgba(88, 166, 255, 0.3);
        }

        .btn {
            padding: 10px 18px;
            font-size: 0.9em;
            font-weight: 600;
            border-radius: 6px;
            border: none;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .btn-run {
            background: var(--accent-btn);
            color: #ffffff;
        }

        .btn-run:hover {
            opacity: 0.9;
        }

        .btn-clear {
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid var(--border-color);
        }

        .btn-clear:hover {
            background: #30363d;
            color: #ffffff;
        }

        .cmd-status {
            font-size: 0.8em;
            color: var(--text-dim);
            padding-left: 6px;
            min-height: 18px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .cmd-status.running {
            color: #e3b341;
        }

        .cmd-status.success {
            color: #3fb950;
        }

        .cmd-status.error {
            color: var(--danger);
        }
    </style>
</head>
<body>
    <header>
        <div class="header-title">
            <span>⚡ AG 2.0 QUANT TERMINAL</span>
            <span style="color: var(--border-color);">|</span>
            <span style="color: var(--text-dim); font-size: 0.85em;">Wispbyte Live Stream</span>
        </div>
        <div class="header-status">
            <span class="badge badge-live" id="streamBadge">
                <span class="pulse-dot" id="pulseDot"></span>
                <span id="badgeText">STREAMING</span>
            </span>
            <span style="color: var(--text-dim); font-size: 0.8em;" id="lastSyncTime">Sync: ...</span>
        </div>
    </header>

    <div class="controls-bar">
        <div class="theme-selector">
            <span>🎨 ธีมสี:</span>
            <select id="themeSelect" onchange="applyTheme(this.value)">
                <option value="powershell-dark">⚪ PowerShell Dark (ขาว-ดำ / Charcoal)</option>
                <option value="powershell-blue">🔷 PowerShell Classic (น้ำเงินเข้ม-ขาว)</option>
                <option value="true-black">⬛ Pure Black & White (ดำสนิท-ขาวโอโม)</option>
                <option value="matrix">🟢 Matrix Green (เขียวเดิม)</option>
            </select>
        </div>
        <div style="display: flex; gap: 16px; align-items: center;">
            <label>
                <input type="checkbox" id="chkAutoScroll" checked>
                <span>Auto-Scroll ด้านล่างสุด</span>
            </label>
            <button class="btn btn-clear" style="padding: 2px 8px; font-size: 0.8em;" onclick="manualScrollBottom()">⬇️ ล่างสุด</button>
        </div>
    </div>

    <div class="console-container">
        <pre id="consoleOutput">กำลังโหลดข้อมูล Console Log ล่าสุด...</pre>
    </div>

    <div class="command-wrapper">
        <form id="cmdForm" onsubmit="handleCommandSubmit(event)">
            <span class="prompt-symbol" id="promptText">PS &gt;</span>
            <input type="text" id="cmdInput" placeholder="พิมพ์คำสั่ง เช่น restart, help, git pull, ps aux (กด Enter เพื่อรัน)..." autocomplete="off" spellcheck="false">
            <button type="submit" class="btn btn-run" id="btnRun">Execute</button>
            <button type="button" class="btn btn-clear" onclick="clearConsole()">Clear Screen</button>
        </form>
        <div class="cmd-status" id="cmdStatus">
            <span>พร้อมรับคำสั่ง (พิมพ์ <b>restart</b> เพื่อรีสตาร์ทบอททั้งหมด, พิมพ์ <b>help</b> เพื่อดูคำสั่งทั้งหมด)</span>
        </div>
    </div>

    <script>
        const consoleEl = document.getElementById('consoleOutput');
        const cmdInput = document.getElementById('cmdInput');
        const cmdStatus = document.getElementById('cmdStatus');
        const chkAutoScroll = document.getElementById('chkAutoScroll');
        const lastSyncTimeEl = document.getElementById('lastSyncTime');
        const btnRun = document.getElementById('btnRun');
        const themeSelect = document.getElementById('themeSelect');
        const promptText = document.getElementById('promptText');
        const streamBadge = document.getElementById('streamBadge');
        const pulseDot = document.getElementById('pulseDot');
        const badgeText = document.getElementById('badgeText');

        let isFirstLoad = true;
        let isUserScrolling = false;
        let cmdHistory = [];
        let historyIndex = -1;
        let consecutiveErrors = 0;

        function updateStreamStatus(state, msg) {
            if (state === 'live') {
                consecutiveErrors = 0;
                if (streamBadge) streamBadge.className = 'badge badge-live';
                if (pulseDot) pulseDot.className = 'pulse-dot';
                if (badgeText) badgeText.textContent = 'STREAMING';
                if (lastSyncTimeEl) lastSyncTimeEl.textContent = 'Sync: ' + msg;
            } else if (state === 'reconnecting') {
                consecutiveErrors++;
                if (consecutiveErrors >= 3) {
                    if (streamBadge) streamBadge.className = 'badge badge-error';
                    if (pulseDot) pulseDot.className = 'pulse-dot error';
                    if (badgeText) badgeText.textContent = 'OFFLINE';
                } else {
                    if (streamBadge) streamBadge.className = 'badge badge-warning';
                    if (pulseDot) pulseDot.className = 'pulse-dot warning';
                    if (badgeText) badgeText.textContent = 'RECONNECTING';
                }
                if (lastSyncTimeEl) lastSyncTimeEl.textContent = 'Sync: ' + msg;
            }
        }

        // จัดการเปลี่ยนและบันทึก Theme ลง LocalStorage
        function applyTheme(theme) {
            document.body.className = '';
            if (theme === 'powershell-blue') {
                document.body.classList.add('theme-powershell-blue');
                promptText.textContent = 'PS C:\\> ';
            } else if (theme === 'true-black') {
                document.body.classList.add('theme-true-black');
                promptText.textContent = '$ ';
            } else if (theme === 'matrix') {
                document.body.classList.add('theme-matrix');
                promptText.textContent = '$ ';
            } else {
                // powershell-dark (ขาว-ดำ / Charcoal)
                promptText.textContent = 'PS > ';
            }
            themeSelect.value = theme;
            localStorage.setItem('ag_terminal_theme', theme);
        }

        // โหลดธีมที่เคยเลือกไว้ (เริ่มต้นที่ powershell-dark ขาว-ดำ)
        const savedTheme = localStorage.getItem('ag_terminal_theme') || 'powershell-dark';
        applyTheme(savedTheme);

        // ตรวจจับการเลื่อน Scroll เพื่อปิด Auto-Scroll ชั่วคราวหากผู้ใช้เลื่อนขึ้นไปอ่านข้อความเก่า
        consoleEl.addEventListener('scroll', () => {
            const isNearBottom = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 60;
            if (!isNearBottom && chkAutoScroll.checked) {
                isUserScrolling = true;
            } else if (isNearBottom) {
                isUserScrolling = false;
            }
        });

        function manualScrollBottom() {
            chkAutoScroll.checked = true;
            isUserScrolling = false;
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }

        let isFetching = false;
        // ฟังก์ชันดึง Console Log แบบ AJAX Real-time ทุก 2 วินาที (ไร้การ Reload หน้าเว็บ)
        async function fetchConsoleLogs() {
            if (isFetching) return;
            isFetching = true;
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 4000);
                const res = await fetch('/api/console?t=' + Date.now(), { signal: controller.signal });
                clearTimeout(timeoutId);
                if (res.ok) {
                    const text = await res.text();
                    
                    if (text && text.trim().length > 0) {
                        if (consoleEl.textContent !== text) {
                            consoleEl.textContent = text;
                            
                            if (isFirstLoad || (chkAutoScroll.checked && !isUserScrolling)) {
                                consoleEl.scrollTop = consoleEl.scrollHeight;
                                isFirstLoad = false;
                            }
                        }
                    } else if (isFirstLoad) {
                        consoleEl.textContent = "⏳ กำลังรอสัญญาณ Console Log จากระบบ Supervisor...";
                    }

                    const now = new Date();
                    updateStreamStatus('live', now.toLocaleTimeString('th-TH'));
                } else {
                    updateStreamStatus('reconnecting', 'HTTP ' + res.status);
                }
            } catch (err) {
                const errLabel = err.name === 'AbortError' ? 'Timeout' : 'Reconnecting...';
                updateStreamStatus('reconnecting', errLabel);
            } finally {
                isFetching = false;
            }
        }

        // เริ่มต้นลูปสตรีมสด
        fetchConsoleLogs();
        setInterval(fetchConsoleLogs, 2000);

        // จัดการส่งคำสั่งผ่าน AJAX
        async function handleCommandSubmit(e) {
            e.preventDefault();
            const cmd = cmdInput.value.trim();
            if (!cmd) return;

            cmdHistory.push(cmd);
            historyIndex = cmdHistory.length;

            cmdStatus.className = 'cmd-status running';
            cmdStatus.textContent = '⏳ กำลังส่งและรันคำสั่ง: ' + cmd + '...';
            btnRun.disabled = true;

            consoleEl.textContent += `\\n[WEB-TERMINAL] $ ${cmd}\\n`;
            if (chkAutoScroll.checked) consoleEl.scrollTop = consoleEl.scrollHeight;

            try {
                const res = await fetch('/api/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cmd: cmd })
                });

                const data = await res.json();
                if (data.status === 'success') {
                    cmdStatus.className = 'cmd-status success';
                    cmdStatus.textContent = '✅ คำสั่งทำงานสำเร็จ (' + new Date().toLocaleTimeString('th-TH') + ')';
                    if (data.output) {
                        consoleEl.textContent += data.output + '\\n';
                        if (chkAutoScroll.checked) consoleEl.scrollTop = consoleEl.scrollHeight;
                    }
                } else {
                    cmdStatus.className = 'cmd-status error';
                    cmdStatus.textContent = '❌ ผิดพลาด: ' + (data.error || 'Unknown error');
                }
            } catch (err) {
                const isRestart = cmd.toLowerCase().startsWith('restart') || cmd.toLowerCase() === 'reboot';
                if (isRestart) {
                    cmdStatus.className = 'cmd-status success';
                    cmdStatus.textContent = '🔄 กำลังรีสตาร์ทระบบและดึงโค้ดล่าสุด... สตรีมสดจะกลับมาใน 3-5 วินาที';
                    consoleEl.textContent += '\\n[WEB-TERMINAL] 🔄 ส่งสัญญาณรีสตาร์ทระบบสำเร็จ กำลังเชื่อมต่อใหม่อัตโนมัติ...\\n';
                } else {
                    cmdStatus.className = 'cmd-status error';
                    cmdStatus.textContent = '❌ ไม่สามารถส่งคำสั่งได้: ' + err.message;
                }
            } finally {
                btnRun.disabled = false;
                cmdInput.value = '';
                cmdInput.focus();
            }
        }

        // จัดการปุ่มลูกศรขึ้น-ลงเพื่อดูประวัติคำสั่ง (Command History Navigation)
        cmdInput.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowUp') {
                if (cmdHistory.length > 0 && historyIndex > 0) {
                    historyIndex--;
                    cmdInput.value = cmdHistory[historyIndex];
                }
                e.preventDefault();
            } else if (e.key === 'ArrowDown') {
                if (historyIndex < cmdHistory.length - 1) {
                    historyIndex++;
                    cmdInput.value = cmdHistory[historyIndex];
                } else {
                    historyIndex = cmdHistory.length;
                    cmdInput.value = '';
                }
                e.preventDefault();
            }
        });

        function clearConsole() {
            consoleEl.textContent = '--- Screen Cleared (Waiting next log stream) ---\\n';
        }
    </script>
</body>
</html>
"""

class QuantTerminalHandler(http.server.BaseHTTPRequestHandler):
    timeout = 10  # ป้องกัน Socket ค้างไม่เกิน 10 วินาที
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self):
        try:
            self.close_connection = True
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass

    def do_GET(self):
        self.close_connection = True
        try:
            # 1. API: ส่งคืนข้อความ Console สดล่าสุด
            if self.path.startswith("/api/console"):
                log_content = get_console_text(lines=180)
                encoded = log_content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)
                try:
                    self.wfile.flush()
                except Exception:
                    pass
                return

            # 2. Web Page: หน้าจอเดี่ยว Pure Live Terminal
            if self.path == "/" or self.path.startswith("/?"):
                encoded = HTML_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)
                try:
                    self.wfile.flush()
                except Exception:
                    pass
                return

            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass

    def do_POST(self):
        # API: รับคำสั่งจากหน้าเว็บไป Execute บนเซิร์ฟเวอร์แบบ AJAX In-Page
        if self.path == "/api/run" or self.path == "/run":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length).decode('utf-8')
                
                cmd = ""
                try:
                    data = json.loads(post_data)
                    cmd = data.get('cmd', '').strip()
                except Exception:
                    params = urllib.parse.parse_qs(post_data)
                    cmd = params.get('cmd', [''])[0].strip()

                if not cmd:
                    self._send_json({"status": "error", "error": "ไม่มีคำสั่งถูกส่งมา"}, 400)
                    return

                cmd_lower = cmd.lower().strip()

                # ⚡ คำสั่งพิเศษ: Restart ระบบทั้งหมด (main.py + Binance + Deriv)
                if cmd_lower in ("restart", "restart bot", "restart all", "/restart", "reboot"):
                    git_msg = ""
                    try:
                        git_res = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, timeout=10)
                        if git_res.stdout.strip():
                            git_msg = f"\n[GIT] {git_res.stdout.strip()}"
                    except Exception as ge:
                        git_msg = f"\n[GIT NOTE] {ge}"

                    def schedule_restart_flag():
                        time.sleep(0.8)
                        try:
                            with open("restart.flag", "w", encoding="utf-8") as f:
                                f.write(f"restart requested at {get_thai_time()}")
                        except Exception:
                            pass

                    threading.Thread(target=schedule_restart_flag, daemon=True).start()

                    output = (
                        "🔄 [COMMAND RESTART ACCEPTED]\n"
                        f"ได้รับคำสั่งรีสตาร์ทระบบเรียบร้อยแล้ว!{git_msg}\n"
                        "⏳ กำลังส่งสัญญาณให้ Supervisor ปิด Workers และ Re-execute main.py ตัวใหม่ทันที...\n"
                        "📡 หน้าจอ Console จะกลับมาสตรีมสดอัตโนมัติใน 3-5 วินาที ไร้การหลุดจากคอนเทนเนอร์"
                    )
                    append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-RESTART] $ {cmd}\n{output}\n")
                    self._send_json({
                        "status": "success",
                        "cmd": cmd,
                        "output": output,
                        "elapsed_sec": 0.5
                    })
                    try:
                        self.wfile.flush()
                    except Exception:
                        pass
                    return

                # ⚡ คำสั่งพิเศษ: สั่งรัน AI Retraining ใน Background
                elif cmd_lower in ("train", "retrain", "train ai", "ai train"):
                    def run_bg_train():
                        try:
                            append_to_console_log(f"\n[{get_thai_time()}] [AI-TRAIN] 🧠 เริ่มต้นกระบวนการ Offline Retraining ใน Background (Brad Goh SMC + Grid Search)...\n")
                            proc = subprocess.Popen(
                                [sys.executable, "-u", "train_offline.py"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                                bufsize=1
                            )
                            for line in iter(proc.stdout.readline, ''):
                                if not line:
                                    break
                                append_to_console_log(line.rstrip())
                            proc.stdout.close()
                            proc.wait()
                            append_to_console_log(f"\n[{get_thai_time()}] [AI-TRAIN] 🎯 การฝึกโมเดล AI RL เสร็จสมบูรณ์ (Exit Code: {proc.returncode})\n")
                        except Exception as e:
                            append_to_console_log(f"\n[{get_thai_time()}] [AI-TRAIN ERROR] ❌ {e}\n")

                    threading.Thread(target=run_bg_train, daemon=True).start()

                    output = (
                        "🧠 [AI RETRAINING INITIATED]\n"
                        "คำสั่งฝึกฝนโมเดล AI RL ถูกส่งไปยัง Background Process เรียบร้อยแล้ว!\n"
                        "⚡ กำลังเริ่มรัน train_offline.py (Brad Goh SMC + 64 Grid Search Combinations)...\n"
                        "📡 ท่านสามารถติดตาม Log ความคืบหน้าได้สดๆ บนหน้าจอ Console นี้แบบ Real-Time\n"
                        "🎯 ผลลัพธ์ที่ดีที่สุดจะถูกอัปเดตลง agent_memory_multi.json โดยอัตโนมัติ"
                    )
                    append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-TRAIN] $ {cmd}\n{output}\n")
                    self._send_json({
                        "status": "success",
                        "cmd": cmd,
                        "output": output,
                        "elapsed_sec": 0.1
                    })
                    return

                # ⚡ คำสั่งพิเศษ: รีสตาร์ทเฉพาะ Binance
                elif cmd_lower in ("restart binance", "restart btc", "restart crypto"):
                    subprocess.run(["pkill", "-f", "main_binance.py"])
                    output = "🔄 กำลังสั่งรีสตาร์ทเฉพาะ Binance Spot Engine... (Supervisor จะเปิดขึ้นมาใหม่ใน 2 วินาที)"
                    append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-RESTART] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.2})
                    return

                # ⚡ คำสั่งพิเศษ: รีสตาร์ทเฉพาะ Deriv (Forex / Synthetic)
                elif cmd_lower in ("restart deriv", "restart forex", "restart synthetic"):
                    subprocess.run(["pkill", "-f", "main_forex.py"])
                    subprocess.run(["pkill", "-f", "main_deriv_synthetic.py"])
                    output = "🔄 กำลังสั่งรีสตาร์ท Deriv Engine... (Supervisor จะเปิดขึ้นมาใหม่ตามโหมดวันทำการใน 2 วินาที)"
                    append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-RESTART] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.2})
                    return

                # ⚡ คำสั่งพิเศษ: Help เมนูแนะนำคำสั่ง
                elif cmd_lower in ("help", "/help", "?"):
                    help_text = (
                        "📖 [AVAILABLE BOT COMMANDS]\n"
                        "  • restart          : ดึงโค้ดล่าสุดจาก GitHub และรีสตาร์ทระบบทั้งหมด (main.py + Binance + Deriv)\n"
                        "  • restart binance  : รีสตาร์ทเฉพาะ Binance Spot Engine\n"
                        "  • restart deriv    : รีสตาร์ทเฉพาะ Deriv Engine (Forex/Synthetic ตามวันทำการ)\n"
                        "  • train / retrain  : สั่งรัน AI Retraining (train_offline.py) ใน Background ทันที\n"
                        "  • git pull         : ดึงโค้ดอัปเดตจาก GitHub ทันที\n"
                        "  • git status       : เช็คสถานะไฟล์และ Git Commit ล่าสุด\n"
                        "  • ls -la           : ดูรายชื่อไฟล์ทั้งหมดในโฟลเดอร์\n"
                        "  • ps aux           : ดูโปรเซสและ PID ที่กำลังรันอยู่ทั้งหมดบน Linux\n"
                        "  • (และคำสั่ง Linux ทั่วไปสามารถพิมพ์สั่งได้ตามปกติ)"
                    )
                    self._send_json({"status": "success", "cmd": cmd, "output": help_text, "elapsed_sec": 0.01})
                    return

                # ดำเนินการรันคำสั่งบน Linux Server ปกติ
                start_time = time.time()
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=20
                )
                elapsed = time.time() - start_time

                output = result.stdout
                if result.stderr:
                    output += ("\n" if output else "") + "[STDERR]: " + result.stderr

                if not output.strip():
                    output = "(คำสั่งทำงานสำเร็จ รหัส Exit Code: 0)"

                formatted_log = (
                    f"\n[{get_thai_time()}] [WEB-TERMINAL-EXEC] $ {cmd} (ใช้เวลา {elapsed:.2f}s)\n"
                    f"{output.strip()}\n"
                )
                append_to_console_log(formatted_log)

                self._send_json({
                    "status": "success",
                    "cmd": cmd,
                    "output": output.strip(),
                    "elapsed_sec": round(elapsed, 2)
                })

            except subprocess.TimeoutExpired:
                err_msg = "⏳ หมดเวลา (Timeout 20 วินาที): คำสั่งใช้เวลานานเกินไป"
                append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-TIMEOUT] $ {cmd}\n")
                self._send_json({"status": "error", "error": err_msg}, 408)
            except Exception as e:
                self._send_json({"status": "error", "error": str(e)}, 500)
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, data, status=200):
        try:
            self.close_connection = True
            encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
            try:
                self.wfile.flush()
            except Exception:
                pass
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass

    def log_message(self, format, *args):
        pass

class RobustThreadingHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
        super().server_bind()

    def handle_error(self, request, client_address):
        # ละเว้น BrokenPipeError / ConnectionResetError ที่เกิดจาก client ตัดการเชื่อมต่อทั่วไป
        exc_type, exc_val, _ = sys.exc_info()
        if exc_type in (BrokenPipeError, ConnectionResetError, socket.timeout):
            return
        super().handle_error(request, client_address)

_shutdown_event = threading.Event()

def signal_handler(signum, frame):
    print(f"\n🛑 ได้รับสัญญาณ ({signum}) กำลังปิด Terminal Server อย่างปลอดภัย...")
    _shutdown_event.set()

def run_server():
    print(f"🚀 เริ่มต้นระบบ AG 2.0 Live Quant Terminal Server ที่พอร์ต {PORT}...")
    print(f"🌐 ใช้งานผ่าน URL: http://0.0.0.0:{PORT}")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    httpd = None
    for attempt in range(1, 11):
        try:
            httpd = RobustThreadingHTTPServer(("0.0.0.0", PORT), QuantTerminalHandler)
            break
        except OSError as e:
            if attempt == 10:
                print(f"❌ ไม่สามารถเปิดพอร์ต {PORT} ได้หลังพยายาม 10 ครั้ง: {e}")
                sys.exit(1)
            print(f"⏳ พอร์ต {PORT} กำลังรอเคลียร์ (ความพยายาม {attempt}/10)...")
            time.sleep(1)

    srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    srv_thread.start()

    while not _shutdown_event.is_set():
        _shutdown_event.wait(0.5)

    print("🛑 กำลังหยุดการทำงานของ HTTP Server...")
    httpd.shutdown()
    httpd.server_close()
    print("👋 ปิด Terminal Server เรียบร้อยสมบูรณ์")

if __name__ == "__main__":
    run_server()
