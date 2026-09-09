import http.server
import socketserver
import os
import time
import re
import json
import urllib.parse
import subprocess

PORT = 9848

def get_binance_pnl():
    net_usdt = 0.0
    if os.path.exists("trade_log.txt"):
        with open("trade_log.txt", "r", encoding="utf-8") as f:
            for line in f:
                if "[TP SUCCESS" in line and "กำไรสุทธิ:" in line:
                    match = re.search(r'กำไรสุทธิ:\s*\+\$([0-9.]+)', line)
                    if match:
                        net_usdt += float(match.group(1))
                elif "[SL SUCCESS" in line and "ขาดทุนสุทธิ:" in line:
                    match = re.search(r'ขาดทุนสุทธิ:\s*-\$([0-9.]+)', line)
                    if match:
                        net_usdt -= float(match.group(1))
    return net_usdt

def get_forex_pnl():
    if os.path.exists("agent_memory_deriv.json"):
        try:
            with open("agent_memory_deriv.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("net_profit_usd", 0.0)
        except:
            pass
    return 0.0

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
            
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        
        # Read Binance
        binance_text = "ยังไม่มีข้อมูล Binance..."
        if os.path.exists("status_log.txt"):
            with open("status_log.txt", "r", encoding="utf-8") as f:
                binance_text = "".join(f.readlines()[-15:])
                
        # Read Forex
        forex_text = "ยังไม่มีข้อมูล Forex..."
        if os.path.exists("status_log_deriv.txt"):
            with open("status_log_deriv.txt", "r", encoding="utf-8") as f:
                forex_text = "".join(f.readlines()[-15:])
                
        binance_pnl_usdt = get_binance_pnl()
        binance_pnl_thb = binance_pnl_usdt * 34.0
        binance_color = "#00ff00" if binance_pnl_usdt >= 0 else "#ff4444"
        binance_sign = "+" if binance_pnl_usdt >= 0 else ""
        
        forex_pnl_usd = get_forex_pnl()
        forex_pnl_thb = forex_pnl_usd * 34.0
        forex_color = "#00ff00" if forex_pnl_usd >= 0 else "#ff4444"
        forex_sign = "+" if forex_pnl_usd >= 0 else ""
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>AG 2.0 Dual-Engine Dashboard</title>
            <style>
                body {{ background-color: #0d1117; color: #c9d1d9; font-family: 'Courier New', Courier, monospace; padding: 20px; line-height: 1.5; }}
                h1 {{ color: #58a6ff; text-align: center; border-bottom: 1px solid #30363d; padding-bottom: 15px; text-transform: uppercase; letter-spacing: 2px; }}
                .container {{ max-width: 1000px; margin: 0 auto; }}
                .box {{ border: 1px solid #30363d; background: #161b22; padding: 20px; margin-bottom: 25px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); position: relative; }}
                h2 {{ margin-top: 0; font-size: 1.2em; border-bottom: 1px dashed #30363d; padding-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }}
                .binance-title {{ color: #f3ba2f; }}
                .forex-title {{ color: #ff4444; }}
                .terminal-title {{ color: #00ff00; }}
                .pnl-badge {{ font-size: 0.9em; padding: 5px 10px; border-radius: 5px; background: rgba(255,255,255,0.1); }}
                pre {{ white-space: pre-wrap; word-wrap: break-word; font-size: 0.95em; margin-top: 15px; background: #0d1117; padding: 15px; border-radius: 5px; }}
                .footer {{ color: #8b949e; text-align: center; font-size: 0.85em; margin-top: 30px; }}
                input[type="text"] {{ flex: 1; padding: 12px; background: #0d1117; color: #00ff00; border: 1px solid #30363d; border-radius: 5px; font-family: monospace; font-size: 1em; outline: none; }}
                input[type="text"]:focus {{ border-color: #58a6ff; }}
                button {{ padding: 12px 24px; background: #238636; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; transition: 0.2s; }}
                button:hover {{ background: #2ea043; }}
            </style>
            <script>
                // Auto-refresh the page every 5 seconds, but stop if user is typing in the command box
                let refreshInterval = setInterval(function() {{
                    window.location.reload();
                }}, 5000);

                function stopRefresh() {{
                    clearInterval(refreshInterval);
                }}
            </script>
        </head>
        <body>
            <div class="container">
                <h1>🚀 AG 2.0 Live Dashboard</h1>
                
                <div class="box">
                    <h2 class="terminal-title">💻 Web Terminal (สั่งงาน Wispbyte)</h2>
                    <form method="POST" action="/run" style="display: flex; gap: 10px; margin-top: 15px;">
                        <input type="text" name="cmd" placeholder="พิมพ์คำสั่ง Linux เช่น ls, cat, pip install... (กดแล้วจะหยุดรีเฟรชออโต้)" onfocus="stopRefresh()" autocomplete="off">
                        <button type="submit">Run Command</button>
                    </form>
                    <p style="color: #8b949e; font-size: 0.8em; margin-top: 10px;">⚠️ คำเตือน: นี่คือ Terminal ของจริงที่เชื่อมกับเซิร์ฟเวอร์ โปรดระวังการสั่งคำสั่งที่อาจทำลายระบบ</p>
                </div>
                
                <div class="box">
                    <h2 class="binance-title">
                        <span>🪙 Binance Spot Engine (~200 THB)</span>
                        <span class="pnl-badge" style="color: {binance_color};">
                            PnL: {binance_sign}{binance_pnl_usdt:.4f} USDT ({binance_sign}{binance_pnl_thb:.2f} ฿)
                        </span>
                    </h2>
                    <pre>{binance_text}</pre>
                </div>
                
                <div class="box">
                    <h2 class="forex-title">
                        <span>📈 Deriv Forex Engine (100 THB)</span>
                        <span class="pnl-badge" style="color: {forex_color};">
                            PnL: {forex_sign}{forex_pnl_usd:.4f} USD ({forex_sign}{forex_pnl_thb:.2f} ฿)
                        </span>
                    </h2>
                    <pre>{forex_text}</pre>
                </div>
                
                <div class="footer">
                    <p>อัปเดตอัตโนมัติทุก 5 วินาที | ดึงข้อมูลล่าสุดเมื่อ: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        if self.path == "/run":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(post_data)
            cmd = params.get('cmd', [''])[0]
            
            output = "ไม่มีคำสั่งถูกทำงาน"
            if cmd:
                try:
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
                    output = result.stdout
                    if result.stderr:
                        output += "\n[Error/Warnings]:\n" + result.stderr
                except subprocess.TimeoutExpired:
                    output = "⏳ หมดเวลา (Timeout 15 วินาที) คำสั่งใช้เวลานานเกินไป"
                except Exception as e:
                    output = f"❌ เกิดข้อผิดพลาด: {str(e)}"
                    
            if not output.strip():
                output = "(คำสั่งทำงานสำเร็จ แต่ไม่มีข้อความส่งกลับมา)"

            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>Terminal Output</title>
                <style>
                    body {{ background-color: #0d1117; color: #00ff00; font-family: 'Courier New', Courier, monospace; padding: 20px; }}
                    h2 {{ color: #58a6ff; }}
                    pre {{ background: #161b22; padding: 20px; border: 1px solid #30363d; border-radius: 5px; white-space: pre-wrap; word-wrap: break-word; font-size: 1.1em; }}
                    button {{ padding: 12px 24px; background: #238636; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 1.1em; margin-top: 20px; }}
                    button:hover {{ background: #2ea043; }}
                </style>
            </head>
            <body>
                <h2>$ {cmd}</h2>
                <pre>{output}</pre>
                <button onclick="window.location.href='/'">🔙 กลับไปหน้า Dashboard</button>
            </body>
            </html>
            """
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def run_server():
    print(f"🚀 เริ่มรัน Web Dashboard ที่พอร์ต {PORT}...")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), DashboardHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    run_server()
