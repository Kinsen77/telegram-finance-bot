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

# --- 2. ฟังก์ชันคำนวณช่วงเวลา (รอบวันที่ 6 ถึง 5) ---
def get_current_cycle_range():
    now = datetime.datetime.now(BKK_TZ)
    if now.day >= 6:
        start_date = now.replace(day=6, hour=0, minute=0, second=0).strftime('%Y-%m-%d %H:%M:%S')
        next_month = now.month + 1 if now.month < 12 else 1
        next_year = now.year if now.month < 12 else now.year + 1
        end_date = now.replace(year=next_year, month=next_month, day=5, hour=23, minute=59, second=59).strftime('%Y-%m-%d %H:%M:%S')
    else:
        prev_month = now.month - 1 if now.month > 1 else 12
        prev_year = now.year if now.month > 1 else now.year - 1
        start_date = now.replace(year=prev_year, month=prev_month, day=6, hour=0, minute=0, second=0).strftime('%Y-%m-%d %H:%M:%S')
        end_date = now.replace(day=5, hour=23, minute=59, second=59).strftime('%Y-%m-%d %H:%M:%S')
    return start_date, end_date

def get_summary(chat_id, start_date, end_date):
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    c.execute("SELECT amount FROM transactions WHERE chat_id = ? AND date BETWEEN ? AND ?", (chat_id, start_date, end_date))
    rows = c.fetchall()
    conn.close()
    income = sum(r[0] for r in rows if r[0] > 0)
    expense = sum(r[0] for r in rows if r[0] < 0)
    return income, abs(expense)

# --- 3. คำสั่งต่างๆ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_command(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **วิธีใช้งานบอทบันทึกรายรับ-รายจ่ายกลุ่ม**\n"
        "สมาชิกทุกคนใช้ 'กระเป๋าเดียวกัน' ข้อมูลรวมกันทั้งกลุ่ม\n\n"
        "💰 **วิธีบันทึก (ต้องมีเครื่องหมายนำหน้าเท่านั้น):**\n"
        "• **รายรับ:** พิมพ์ `+` ตามด้วยเลข เช่น `+100 ค่าขนม` \n"
        "• **รายจ่าย:** พิมพ์ `-` ตามด้วยเลข เช่น `-50 ค่ากาแฟ` \n"
        "*(หมายเหตุ: ถ้าพิมพ์ตัวเลขเฉยๆ บอทจะไม่บันทึกให้ครับ)* \n\n"
        "📊 **คำสั่งดูยอด:**\n"
        "/today - ดูสรุปของวันนี้\n"
        "/month - ดูสรุปยอดรอบเดือนปัจจุบัน (6 ถึง 5)\n"
        "/help - แสดงวิธีใช้งานนี้\n\n"
        "⚠️ **การลบข้อมูล:**\n"
        "/reset confirm - ลบเฉพาะข้อมูลใน 'รอบเดือนปัจจุบัน'\n\n"
        "💡 **ตัวอย่าง:**\n"
        "👉 `+500` -> บันทึกรับ 500\n"
        "👉 `-120 ค่าข้าว` -> บันทึกจ่าย 120\n"
        "--------------------------"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def today_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    today_str = datetime.datetime.now(BKK_TZ).strftime('%Y-%m-%d')
    income, expense = get_summary(chat_id, today_str + " 00:00:00", today_str + " 23:59:59")
    await update.message.reply_text(f"📊 **สรุปวันนี้**\n➕ รับ: {income:,.2f}\n➖ จ่าย: {expense:,.2f}\n💰 คงเหลือวันนี้: {income-expense:,.2f}", parse_mode='Markdown')

async def month_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    start_d, end_d = get_current_cycle_range()
    income, expense = get_summary(chat_id, start_d, end_d)
    await update.message.reply_text(f"📅 **สรุปรอบเดือนปัจจุบัน**\n({start_d[:10]} ถึง {end_d[:10]})\n\n➕ รับรวม: {income:,.2f}\n➖ จ่ายรวม: {expense:,.2f}\n💰 คงเหลือสุทธิ: {income-expense:,.2f}", parse_mode='Markdown')

async def reset_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] != "confirm":
        await update.message.reply_text("⚠️ **ยืนยันการลบ?**\nลบเฉพาะข้อมูล **'รอบเดือนปัจจุบัน'**\nพิมพ์ `/reset confirm` เพื่อยืนยัน")
        return
    
    chat_id = update.effective_chat.id
    start_d, end_d = get_current_cycle_range()
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE chat_id = ? AND date BETWEEN ? AND ?", (chat_id, start_d, end_d))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ ลบข้อมูลรอบเดือนปัจจุบันเรียบร้อยแล้ว")

# --- 4. ตัวอ่านข้อความ (ปรับปรุง Regex ให้รับเฉพาะ + และ - เท่านั้น) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    # Regex: บังคับต้องเริ่มด้วย + หรือ - ตามด้วยตัวเลข
    match = re.match(r'^([\+\-])\s*(\d+(\.\d+)?)', text)
    
    if match:
        sign = match.group(1)
        amount = float(match.group(2))
        note = text[match.end():].strip() or "ไม่ระบุรายการ"
        final_amount = amount if sign == "+" else -amount
        
        save_transaction(chat_id, final_amount, note)
        
        start_d, end_d = get_current_cycle_range()
        income, expense = get_summary(chat_id, start_d, end_d)
        
        icon = "✅ รับ" if final_amount > 0 else "❌ จ่าย"
        response = (
            f"{icon}: {abs(final_amount):,.2f} ({note})\n"
            f"--------------------------\n"
            f"💰 **เงินคงเหลือเดือนนี้: {income-expense:,.2f}**"
        )
        await update.message.reply_text(response, parse_mode='Markdown')

# --- 5. เริ่มบอท ---
if __name__ == '__main__':
    init_db()
    TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("today", today_summary))
    app.add_handler(CommandHandler("month", month_summary))
    app.add_handler(CommandHandler("reset", reset_data))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    app.run_polling()
