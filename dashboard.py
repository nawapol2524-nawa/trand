import http.server
import socketserver
import os
import time
import json
import urllib.parse
import subprocess
from datetime import datetime, timedelta

PORT = 9848
CONSOLE_LOG_FILE = "console_log.txt"
STATUS_LOG_FILE = "status_log.txt"

def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def get_console_text(lines=180):
    """อ่านข้อความล่าสุดจาก console_log.txt หรือ status_log.txt"""
    target = CONSOLE_LOG_FILE if os.path.exists(CONSOLE_LOG_FILE) else STATUS_LOG_FILE
    if not os.path.exists(target):
        return "⏳ กำลังรอสัญญาณ Console Log จากระบบ Supervisor..."
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except Exception as e:
        return f"⚠️ ไม่สามารถอ่าน Log ได้: {e}"

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
        :root {
            --bg-color: #0d1117;
            --panel-bg: #161b22;
            --terminal-bg: #010409;
            --border-color: #30363d;
            --text-primary: #58a6ff;
            --text-terminal: #39ff14;
            --text-dim: #8b949e;
            --accent-green: #238636;
            --accent-green-hover: #2ea043;
            --accent-blue: #1f6feb;
            --danger: #f85149;
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

        .pulse-dot {
            width: 8px;
            height: 8px;
            background-color: #3fb950;
            border-radius: 50%;
            animation: pulse 1.8s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.9); opacity: 0.7; }
            50% { transform: scale(1.3); opacity: 1; box-shadow: 0 0 8px #3fb950; }
            100% { transform: scale(0.9); opacity: 0.7; }
        }

        /* Controls Bar */
        .controls-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 6px 14px;
            background: #090d13;
            border-left: 1px solid var(--border-color);
            border-right: 1px solid var(--border-color);
            border-bottom: 1px solid #21262d;
            font-size: 0.8em;
            color: var(--text-dim);
        }

        .controls-bar label {
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            user-select: none;
        }

        /* Live Console Screen */
        .console-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 480px;
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
            font-family: 'SF Mono', 'Cascadia Code', Menlo, Monaco, Consolas, 'Courier New', monospace;
            font-size: 0.9em;
            line-height: 1.45;
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
            background: #010409;
        }
        pre#consoleOutput::-webkit-scrollbar-thumb {
            background: #30363d;
            border-radius: 4px;
        }
        pre#consoleOutput::-webkit-scrollbar-thumb:hover {
            background: #58a6ff;
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
            color: var(--text-terminal);
            font-family: monospace;
            font-size: 1.15em;
            font-weight: bold;
            padding-left: 4px;
        }

        input#cmdInput {
            flex: 1;
            padding: 10px 14px;
            background: #010409;
            color: #ffffff;
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
            background: var(--accent-green);
            color: #ffffff;
        }

        .btn-run:hover {
            background: var(--accent-green-hover);
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
            <span style="color: #30363d;">|</span>
            <span style="color: #8b949e; font-size: 0.85em;">Wispbyte Live Stream</span>
        </div>
        <div class="header-status">
            <span class="badge badge-live">
                <span class="pulse-dot"></span>
                <span>STREAMING</span>
            </span>
            <span style="color: var(--text-dim); font-size: 0.8em;" id="lastSyncTime">Sync: ...</span>
        </div>
    </header>

    <div class="controls-bar">
        <div>
            <span>📍 Auto-poll ทุก 2 วินาที (Zero Page Reload 100%)</span>
        </div>
        <div style="display: flex; gap: 16px;">
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
            <span class="prompt-symbol">$</span>
            <input type="text" id="cmdInput" placeholder="พิมพ์คำสั่ง Linux เช่น ls -la, ps aux, git status (กด Enter เพื่อรัน)..." autocomplete="off" spellcheck="false">
            <button type="submit" class="btn btn-run" id="btnRun">Execute</button>
            <button type="button" class="btn btn-clear" onclick="clearConsole()">Clear Screen</button>
        </form>
        <div class="cmd-status" id="cmdStatus">
            <span>พร้อมรับคำสั่ง (สามารถกดลูกศร ↑ / ↓ เพื่อดูประวัติคำสั่งได้)</span>
        </div>
    </div>

    <script>
        const consoleEl = document.getElementById('consoleOutput');
        const cmdInput = document.getElementById('cmdInput');
        const cmdStatus = document.getElementById('cmdStatus');
        const chkAutoScroll = document.getElementById('chkAutoScroll');
        const lastSyncTimeEl = document.getElementById('lastSyncTime');
        const btnRun = document.getElementById('btnRun');

        let isFirstLoad = true;
        let isUserScrolling = false;
        let cmdHistory = [];
        let historyIndex = -1;

        // ตรวจจับการเลื่อน Scroll เพื่อปิด Auto-Scroll ชั่วคราวหากผู้ใช้เลื่อนขึ้นไปอ่านข้อความเก่า
        consoleEl.addEventListener('scroll', () => {
            const isNearBottom = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 60;
            if (!isNearBottom && chkAutoScroll.checked) {
                // ผู้ใช้กำลังเลื่อนดูข้อความข้างบน
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

        // ฟังก์ชันดึง Console Log แบบ AJAX Real-time ทุก 2 วินาที (ไร้การ Reload หน้าเว็บ)
        async function fetchConsoleLogs() {
            try {
                const res = await fetch('/api/console?t=' + Date.now());
                if (res.ok) {
                    const text = await res.text();
                    
                    // ป้องกันการกระตุกถ้าข้อความเหมือนเดิม
                    if (consoleEl.textContent !== text) {
                        consoleEl.textContent = text;
                        
                        // เลื่อนลงล่างสุดเฉพาะเมื่อเปิด Auto-Scroll และผู้ใช้ไม่ได้เลื่อนอ่านข้อความเก่า
                        if (isFirstLoad || (chkAutoScroll.checked && !isUserScrolling)) {
                            consoleEl.scrollTop = consoleEl.scrollHeight;
                            isFirstLoad = false;
                        }
                    }

                    const now = new Date();
                    lastSyncTimeEl.textContent = 'Sync: ' + now.toLocaleTimeString('th-TH');
                }
            } catch (err) {
                console.error('Fetch log error:', err);
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

            // บันทึกประวัติคำสั่ง
            cmdHistory.push(cmd);
            historyIndex = cmdHistory.length;

            cmdStatus.className = 'cmd-status running';
            cmdStatus.textContent = '⏳ กำลังส่งและรันคำสั่ง: ' + cmd + '...';
            btnRun.disabled = true;

            // แสดงคำสั่งบน Console ทันทีเพื่อความรู้สึกแบบ Real Terminal
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
                cmdStatus.className = 'cmd-status error';
                cmdStatus.textContent = '❌ ไม่สามารถส่งคำสั่งได้: ' + err.message;
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
    def do_GET(self):
        # 1. API: ส่งคืนข้อความ Console สดล่าสุด
        if self.path.startswith("/api/console"):
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            log_content = get_console_text(lines=180)
            self.wfile.write(log_content.encode("utf-8"))
            return

        # 2. Web Page: หน้าจอเดี่ยว Pure Live Terminal
        if self.path == "/" or self.path.startswith("/?"):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        # API: รับคำสั่งจากหน้าเว็บไป Execute บนเซิร์ฟเวอร์แบบ AJAX In-Page
        if self.path == "/api/run" or self.path == "/run":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length).decode('utf-8')
                
                cmd = ""
                # รองรับทั้ง JSON payload และ x-www-form-urlencoded
                try:
                    data = json.loads(post_data)
                    cmd = data.get('cmd', '').strip()
                except Exception:
                    params = urllib.parse.parse_qs(post_data)
                    cmd = params.get('cmd', [''])[0].strip()

                if not cmd:
                    self._send_json({"status": "error", "error": "ไม่มีคำสั่งถูกส่งมา"}, 400)
                    return

                # ดำเนินการรันคำสั่งบน Linux Server
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

                # บันทึกคำสั่งและผลลัพธ์ลง console_log.txt อัตโนมัติ เพื่อให้ซิงค์ขึ้น GDrive
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
        self.send_response(status)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        # ปิด Access log ซ้ำซ้อนเพื่อไม่ให้รกหน้าจอและกิน CPU
        pass

def run_server():
    print(f"🚀 เริ่มต้นระบบ AG 2.0 Live Quant Terminal Server ที่พอร์ต {PORT}...")
    print(f"🌐 ใช้งานผ่าน URL: http://0.0.0.0:{PORT}")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), QuantTerminalHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n🛑 หยุดการทำงานของ Terminal Server เรียบร้อย")

if __name__ == "__main__":
    run_server()
