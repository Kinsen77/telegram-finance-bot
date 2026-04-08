import logging
import sqlite3
import datetime
import pytz
import os
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# ตั้งค่า Timezone ไทย
BKK_TZ = pytz.timezone('Asia/Bangkok')

# ตั้งค่า Logging เพื่อดู Error
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- 1. จัดการฐานข้อมูล ---
def init_db():
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  chat_id INTEGER, 
                  amount REAL, 
                  note TEXT, 
                  date TEXT)''')
    conn.commit()
    conn.close()

def save_transaction(chat_id, amount, note):
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    now = datetime.datetime.now(BKK_TZ).strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO transactions (chat_id, amount, note, date) VALUES (?, ?, ?, ?)", 
              (chat_id, amount, note, now))
    conn.commit()
    conn.close()

# --- 2. ฟังก์ชันคำนวณเงิน ---
def get_summary(chat_id, start_date, end_date):
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    c.execute("""SELECT amount FROM transactions 
                 WHERE chat_id = ? AND date BETWEEN ? AND ?""", 
              (chat_id, start_date, end_date))
    rows = c.fetchall()
    conn.close()
    
    income = sum(r[0] for r in rows if r[0] > 0)
    expense = sum(r[0] for r in rows if r[0] < 0)
    return income, abs(expense)

# --- 3. คำสั่งต่างๆ (Command Handlers) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "สวัสดีครับ! บอทบันทึกรายรับรายจ่ายกลุ่มพร้อมใช้งานแล้ว\n\n"
        "วิธีใช้งาน:\n"
        "➕ ใส่เลขบวก เช่น +500 ขายของ\n"
        "➖ ใส่เลขลบ หรือเลขเฉยๆ เช่น -100 ค่าข้าว หรือ 100 ค่ากาแฟ\n\n"
        "คำสั่งอื่นๆ:\n"
        "/today - ดูสรุปวันนี้\n"
        "/month - ดูสรุปเดือนนี้\n"
        "/reset - ล้างข้อมูลทั้งหมด"
    )
    await update.message.reply_text(welcome_text)

async def today_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    today_str = datetime.datetime.now(BKK_TZ).strftime('%Y-%m-%d')
    income, expense = get_summary(chat_id, today_str + " 00:00:00", today_str + " 23:59:59")
    
    text = f"📊 สรุปยอดวันนี้\n➕ รายรับ: {income:,.2f}\n➖ รายจ่าย: {expense:,.2f}\n💰 คงเหลือ: {income-expense:,.2f}"
    await update.message.reply_text(text)

async def month_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    now = datetime.datetime.now(BKK_TZ)
    
    # ดึงค่า Parameter (เช่น /month -1)
    offset = 0
    if context.args:
        try:
            offset = int(context.args[0])
        except ValueError:
            pass # ถ้าใส่เป็น YYYY-MM ต้องจัดการเพิ่ม (ในที่นี้ขอทำแบบง่ายก่อน)

    # คำนวณช่วงวันที่ (ตัดรอบวันที่ 5-6)
    target_month = now.month + offset
    target_year = now.year
    while target_month < 1:
        target_month += 12
        target_year -= 1
        
    start_date = f"{target_year}-{target_month:02d}-06 00:00:00"
    # วันสิ้นสุดคือวันที่ 5 ของเดือนถัดไป
    end_month = target_month + 1
    end_year = target_year
    if end_month > 12:
        end_month = 1
        end_year += 1
    end_date = f"{end_year}-{end_month:02d}-05 23:59:59"

    income, expense = get_summary(chat_id, start_date, end_date)
    text = f"📅 รอบเดือน: {target_year}-{target_month:02d}\n(6 ของเดือนนี้ - 5 ของเดือนหน้า)\n\n➕ รับ: {income:,.2f}\n➖ จ่าย: {expense:,.2f}\n💰 สุทธิ: {income-expense:,.2f}"
    await update.message.reply_text(text)

async def reset_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ระบบยืนยันแบบง่าย: ต้องพิมพ์ /reset confirm
    if not context.args or context.args[0] != "confirm":
        await update.message.reply_text("⚠️ แน่ใจนะ? ข้อมูลจะหายหมด! พิมพ์ `/reset confirm` เพื่อยืนยัน")
        return
    
    chat_id = update.effective_chat.id
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ ลบข้อมูลของกลุ่มนี้เรียบร้อยแล้ว")

# --- 4. ตัวอ่านข้อความอัตโนมัติ (Message Handler) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    
    # ใช้ Regex ค้นหาตัวเลข
    match = re.match(r'^([\+\-]?)\s*(\d+(\.\d+)?)', text)
    if match:
        sign = match.group(1)
        amount = float(match.group(2))
        note = text[match.end():].strip() or "ไม่ได้ระบุ"
        
        # ถ้าไม่มีเครื่องหมาย หรือเป็น - ให้เป็นรายจ่าย (ติดลบ)
        if sign == "+":
            final_amount = amount
        else:
            final_amount = -amount
            
        save_transaction(chat_id, final_amount, note)
        status = "✅ บันทึกรายรับ" if final_amount > 0 else "❌ บันทึกรายจ่าย"
        await update.message.reply_text(f"{status}: {abs(final_amount):,.2f}\nโน้ต: {note}")

# --- 5. เริ่มต้นบอท ---
if __name__ == '__main__':
    init_db()
    TOKEN = os.getenv("BOT_TOKEN") # ดึง Token จาก Environment Variable
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today_summary))
    app.add_handler(CommandHandler("month", month_summary))
    app.add_handler(CommandHandler("reset", reset_data))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Bot is running...")
    app.run_polling()
