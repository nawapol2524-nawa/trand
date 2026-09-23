# RAILWAY_DEPLOYMENT.md
# STATUS: READY TO DEPLOY
# Updated: 2026-09-23

---

## ขั้นตอน Deploy บน Railway.app

### ⚠️ Railway Free Tier ข้อจำกัด

| ข้อ | รายละเอียด |
|-----|-----------|
| Credit | \$5 ฟรี ใช้หมดแล้วหยุด (ไม่ใช่ฟรีตลอด) |
| RAM | 512MB (เพียงพอสำหรับ demo) |
| CPU | Shared (ไม่แน่นอน) |
| Sleep | ไม่ sleep อัตโนมัติ แต่หยุดเมื่อ credit หมด |
| Port 5035 outbound | ✅ รองรับ (เป็น outbound connection) |
| 24/7 Hobby Plan | \$5/เดือน = ~500 ชั่วโมง (ไม่พอ 24/7) |
| **สรุป** | **ใช้ทดสอบ DEMO เท่านั้น — ไม่เหมาะ Production** |

---

## Step 1: สร้าง Railway Account

1. ไปที่ https://railway.app
2. Sign up ด้วย GitHub account (เดียวกับ nawapole2524-nawa)
3. ยืนยัน email

---

## Step 2: สร้าง Project จาก GitHub Repo

1. คลิก **New Project**
2. เลือก **Deploy from GitHub repo**
3. เลือก repo: `nawapole2524-nawa/trand`
4. Railway จะตรวจจับ `Dockerfile` อัตโนมัติ

---

## Step 3: ตั้งค่า Environment Variables

ใน Railway Dashboard → Variables → Raw Editor วาง:

```env
# SAFETY
TRADING_MODE=DEMO
LIVE_TRADING_ENABLED=false

# cTrader
CTRADER_CLIENT_ID=41116_fh8xCpgr7UEs72rCbwFRQTx0TLzPPOPXUTaR63Jq9We9hBNTss
CTRADER_CLIENT_SECRET=lmT7pTQKlmqOh6onMbiv8TjBZ3rzOZTbmuV73uKgAAZROSxfYm
CTRADER_ACCOUNT_ID=2565611
CTRADER_HOST=demo.ctraderapi.com
CTRADER_PORT=5035

# ใส่ Access Token หลังรัน get_ctrader_token.py
CTRADER_ACCESS_TOKEN=YOUR_TOKEN_HERE

# Deriv API
DERIV_API_TOKEN=YOUR_DERIV_API_TOKEN_HERE
DERIV_APP_ID=YOUR_APP_ID_HERE

# Logging
LOG_LEVEL=INFO
```

> **⛔ ห้ามใส่ TRADING_MODE=LIVE ใน Railway จนกว่าจะ verify ครบทุกอย่าง**

---

## Step 4: Deploy

Railway จะ build อัตโนมัติเมื่อ push ไป GitHub
ดู logs ใน Railway Dashboard → Deployments → View Logs

---

## Step 5: ตรวจสอบ TCP Port 5035

เพิ่ม step นี้ใน Railway console (ถ้ามี shell access):

```bash
python3 -c "
import socket
s = socket.create_connection(('demo.ctraderapi.com', 5035), timeout=10)
s.close()
print('PASS: port 5035 reachable from Railway')
"
```

---

## Step 6: Monitor Logs

Railway Dashboard → Service → Logs

สิ่งที่ต้องเห็น:
```json
{"event":"BOT_STARTING","trading_mode":"DEMO"}
{"event":"BROKER_GATE","status":"BLOCKED","reason":"Phase 0 broker verification not yet complete"}
{"event":"BOT_RUNNING","mode":"PAPER","status":"SCAFFOLD"}
```

Note: ยังอยู่ใน SCAFFOLD — strategies ยังไม่ได้ต่อ broker

---

## Workflow หลัง Deploy

```
Railway deploy (PAPER mode)    ← ตอนนี้
        ↓
ตรวจสอบ TCP port 5035 จาก Railway
        ↓
รัน get_ctrader_token.py → ได้ Access Token
        ↓
Phase 6: Broker implementation
        ↓
ย้าย Production → Oracle Cloud (ฟรีตลอด)
```

---

## ถ้า Railway Credit หมด

ย้ายไป Oracle Cloud Always Free:
- https://cloud.oracle.com/free
- VM.Standard.A1.Flex — 4 OCPU, 24GB RAM — ฟรีตลอดชีพ
- Region: ap-singapore-1 (ใกล้ไทย)
