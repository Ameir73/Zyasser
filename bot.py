import asyncio
import aiohttp
from aiohttp import web
import re
import logging
import traceback
import sys
import os
import random
import yt_dlp
import pytgcalls
from supabase import create_client, Client
from pyrogram import Client as PyroClient, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, Update  # ✅ تم التعديل هنا لقراءة النظام الجديد
from pytgcalls.exceptions import NoActiveGroupCall

# ==========================================
# ⚙️ [ إعدادات البوت الأساسية (من بيئة التشغيل) ]
# ==========================================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

if not os.path.exists("downloads"):
    os.makedirs("downloads")

# ==========================================
# 🤖 [ تهيئة العملاء (Clients) ]
# ==========================================
app = PyroClient("MusicBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
assistant = None
call_py = pytgcalls.PyTgCalls(assistant)

# ==========================================
# 📢 [ كلاس إرسال الأخطاء للتليجرام ]
# ==========================================
class TelegramLoggerHandler(logging.Handler):
    def __init__(self, bot_client, chat_id):
        super().__init__()
        self.bot_client = bot_client
        self.chat_id = chat_id

    def emit(self, record):
        log_entry = self.format(record)
        if record.levelno >= logging.ERROR:
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self.send_log(log_entry))
            except RuntimeError:
                pass

    async def send_log(self, message):
        try:
            msg = f"⚠️ **تنبيـه خطأ في النظام:**\n`{message[:3500]}`"
            await self.bot_client.send_message(self.chat_id, msg)
        except Exception:
            pass

# ==========================================
# 🗄️ [ نظام إدارة قاعدة البيانات ]
# ==========================================
async def request_supabase(endpoint: str, method: str = "GET", payload: dict = None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    
    async with aiohttp.ClientSession() as session:
        if method == "GET":
            async with session.get(url, headers=headers) as response:
                return await response.json()
        elif method == "POST":
            headers["Prefer"] = "resolution=merge-duplicates"
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status in [200, 201, 204]:
                    return True
                return False

async def save_assistant(session_string: str):
    data = {"id": 1, "session_string": session_string}
    return await request_supabase("assistants", method="POST", payload=data)

async def get_assistant():
    data = await request_supabase("assistants?id=eq.1&select=*")
    return data[0].get("session_string") if isinstance(data, list) and data else None

async def is_chat_admin(chat_id: int, user_id: int) -> bool:
    data = await request_supabase(f"chat_admins?chat_id=eq.{chat_id}&user_id=eq.{user_id}&select=*")
    return isinstance(data, list) and len(data) > 0
    
# ==========================================
# 🎵 [ نظام قائمة الانتظار (Queue) الذكي ]
# ==========================================
chat_queues = {}

def add_to_queue(chat_id: int, title: str, audio_path: str, requested_by: int):
    if chat_id not in chat_queues:
        chat_queues[chat_id] = []
    chat_queues[chat_id].append({"title": title, "path": audio_path, "requested_by": requested_by})
    return len(chat_queues[chat_id])

def pop_next_in_queue(chat_id: int):
    if chat_id in chat_queues and len(chat_queues[chat_id]) > 0:
        return chat_queues[chat_id].pop(0)
    return None

def clear_queue(chat_id: int):
    if chat_id in chat_queues:
        chat_queues[chat_id] = []

# ==========================================
# 📥 [ محرك التحميل ]
# ==========================================
def fetch_from_soundcloud(target, is_search=False):
    outtmpl = 'downloads/%(id)s.%(ext)s'
    ydl_opts = {'format': 'm4a/bestaudio/best', 'outtmpl': outtmpl, 'quiet': True, 'no_warnings': True}
    query = f"scsearch1:{target}" if is_search else target

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=True)
        audio_data = info['entries'][0] if 'entries' in info and len(info['entries']) > 0 else info
        audio_file = ydl.prepare_filename(audio_data)
        clean_title = audio_data.get('title', 'مقطع صوتي').split("http")[0].split("☆")[0].strip()
        return audio_file, clean_title

# ==========================================
# ▶️ [ المحرك الأساسي: أمر التشغيل ]
# ==========================================
@app.on_message(filters.command(["play", "تشغيل"]) & filters.group)
async def play_command(client, message: Message):
    if not call_py:
        return await message.reply_text("⚠️ البوت قيد الصيانة: محرك الصوت غير متصل (يرجى إرسال جلسة المساعد للمطور).")

    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if len(message.command) < 2:
        return await message.reply_text("⚠️ يرجى كتابة اسم المقطع أو الرابط.\nمثال: `/play زامل مع الله`")
        
    query = message.text.split(" ", 1)[1].strip()
    is_link = re.match(r'https?://(www\.|m\.)?soundcloud\.com/.+', query)
    
    status_msg = await message.reply_text("⏳ جاري البحث والتحميل...")
    
    try:
        loop = asyncio.get_event_loop()
        audio_path, title = await loop.run_in_executor(None, fetch_from_soundcloud, query, not is_link)
        
        queue_len = add_to_queue(chat_id, title, audio_path, user_id)
        
        if queue_len == 1:
            next_song = pop_next_in_queue(chat_id)
            try:
                # 1️⃣ تعديل الموضع الأول
                await call_py.play(chat_id, MediaStream(next_song['path']))
                await status_msg.edit_text(f"▶️ **تم بدء التشغيل:**\n🎵 `{next_song['title']}`")
            except NoActiveGroupCall:
                await status_msg.edit_text("❌ عذراً، يجب على أحد المشرفين فتح المحادثة الصوتية (Voice Chat) أولاً.")
            except Exception as e:
                await status_msg.edit_text(f"❌ حدث خطأ أثناء الاتصال بالمحادثة الصوتية:\n`{e}`")
        else:
            await status_msg.edit_text(f"✅ **تمت الإضافة لقائمة الانتظار:**\n🎵 `{title}`\nرقمها في الطابور: `{queue_len}`")
            
    except Exception as e:
        await status_msg.edit_text(f"❌ فشل التحميل:\n`{e}`")

async def on_stream_end_handler(client, update: Update):
    chat_id = update.chat_id
    next_song = pop_next_in_queue(chat_id)
    
    if next_song:
        # 2️⃣ تعديل الموضع الثاني
        await call_py.play(chat_id, MediaStream(next_song['path']))
        await app.send_message(chat_id, f"▶️ **جاري تشغيل المقطع التالي:**\n🎵 `{next_song['title']}`")
    else:
        await call_py.leave_group_call(chat_id)
        await app.send_message(chat_id, "✅ انتهت القائمة، تم مغادرة المحادثة الصوتية.")

# ==========================================
# ⏯️ [ أوامر التحكم (تخطي، إيقاف، إنهاء) ]
# ==========================================
@app.on_message(filters.command(["skip", "تخطي"]) & filters.group)
async def skip_track(client, message: Message):
    chat_id = message.chat.id
    if message.from_user.id != OWNER_ID and not await is_chat_admin(chat_id, message.from_user.id):
        return await message.reply_text("⚠️ هذا الأمر للمشرفين فقط.")

    next_song = pop_next_in_queue(chat_id)
    if next_song:
        # 3️⃣ تعديل الموضع الثالث
        await call_py.play(chat_id, MediaStream(next_song['path']))
        await message.reply_text(f"⏭️ **تم التخطي!**\n🎵 المقطع الحالي: `{next_song['title']}`")
    else:
        await call_py.leave_group_call(chat_id)
        await message.reply_text("⏭️ تم التخطي. لا يوجد مقاطع أخرى، غادرت المحادثة.")

@app.on_message(filters.command(["stop", "انهاء"]) & filters.group)
async def stop_track(client, message: Message):
    chat_id = message.chat.id
    if message.from_user.id != OWNER_ID and not await is_chat_admin(chat_id, message.from_user.id):
        return await message.reply_text("⚠️ هذا الأمر للمشرفين فقط.")
        
    clear_queue(chat_id)
    await call_py.leave_group_call(chat_id)
    await message.reply_text("⏹️ **تم إنهاء التشغيل وتفريغ القائمة.**")

@app.on_message(filters.command(["pause", "ايقاف"]) & filters.group)
async def pause_track(client, message: Message):
    chat_id = message.chat.id
    await call_py.pause_stream(chat_id)
    await message.reply_text("⏸️ **تم إيقاف التشغيل مؤقتاً.**")

@app.on_message(filters.command(["resume", "استئناف"]) & filters.group)
async def resume_track(client, message: Message):
    chat_id = message.chat.id
    await call_py.resume_stream(chat_id)
    await message.reply_text("▶️ **تم استئناف التشغيل.**")

# ==========================================
# 👨‍💻 [ لوحة المطور وحفظ الجلسة ]
# ==========================================
waiting_for_session = []

@app.on_message(filters.command(["مطور", "panel"]) & filters.private)
async def developer_panel(client, message: Message):
    if message.from_user.id != OWNER_ID:
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة/تحديث حساب مساعد", callback_data="add_assistant")],
        [InlineKeyboardButton("🔄 إعادة تشغيل السورس", callback_data="restart_bot")]
    ])
    await message.reply_text("**👨‍💻 لوحة تحكم المطور:**", reply_markup=keyboard)

@app.on_callback_query(filters.regex("^add_assistant$"))
async def ask_for_session(client, callback_query):
    if callback_query.from_user.id != OWNER_ID: return
    if OWNER_ID not in waiting_for_session:
        waiting_for_session.append(OWNER_ID)
    await callback_query.message.edit_text(
        "**📥 أرسل كود الجلسة (String Session) الآن:**",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء ❌", callback_data="cancel_session")]])
    )

@app.on_message(filters.private & filters.text)
async def receive_session_string(client, message: Message):
    if message.from_user.id == OWNER_ID and OWNER_ID in waiting_for_session:
        session_text = message.text.strip()
        status_msg = await message.reply_text("⏳ جاري الحفظ...")
        try:
            await save_assistant(session_text)
            waiting_for_session.remove(OWNER_ID)
            await status_msg.edit_text("✅ **تم حفظ الجلسة!**\nيرجى ضغط زر (إعادة تشغيل السورس) من لوحة المطور لتفعيلها.")
        except Exception as e:
            await status_msg.edit_text(f"❌ خطأ:\n`{e}`")
        message.stop_propagation()

@app.on_callback_query(filters.regex("^restart_bot$"))
async def restart_bot_callback(client, callback_query):
    if callback_query.from_user.id != OWNER_ID: return
    await callback_query.message.edit_text("🔄 جاري إعادة تشغيل السيرفر...")
    os.execl(sys.executable, sys.executable, *sys.argv)

@app.on_callback_query(filters.regex("^cancel_session$"))
async def cancel_session_add(client, callback_query):
    if OWNER_ID in waiting_for_session: waiting_for_session.remove(OWNER_ID)
    await callback_query.message.edit_text("تم الإلغاء ✅")

# ==========================================
# ⚡ [ نظام الإنعاش الأبدي: 24/7 (النبض الذاتي) ]
# ==========================================
async def handle_ping(request):
    """استجابة سريعة لإخبار السيرفر أن النظام مستيقظ"""
    return web.Response(
        text="Music Bot is Alive & Vigilant ⚡", 
        headers={"Connection": "keep-alive"}
    )

async def self_resuscitation():
    """النبض الذاتي: البوت يوقظ نفسه لمنع النوم (Anti-Idle)"""
    render_url = os.getenv("RENDER_EXTERNAL_URL") 
    if not render_url:
        logging.warning("⚠️ RENDER_EXTERNAL_URL غير متوفر، النبض الذاتي لن يعمل. (أضف رابط راندر في المتغيرات)")
        return

    while True:
        try:
            rand_ping = f"{render_url}?v={random.randint(1, 99999)}"
            async with aiohttp.ClientSession() as session:
                async with session.get(rand_ping, timeout=10) as response:
                    logging.info(f"💉 [نبضة حية لسيرفر الويب]: {response.status}")
        except Exception as e:
            logging.error(f"⚠️ [فشل النبض]: {e}")
        
        await asyncio.sleep(240) # كل 4 دقائق

async def watch_dog(task_func, *args):
    """مراقب دائم: يعيد تشغيل أي وظيفة خلفية تنهار"""
    while True:
        try:
            logging.info(f"🛡️ تشغيل محرك: {task_func.__name__}")
            await task_func(*args)
        except Exception as e:
            logging.error(f"🚨 انهيار في {task_func.__name__}: {e}")
            logging.info("♻️ إعادة التشغيل التلقائي الآن...")
            await asyncio.sleep(10)

# ==========================================
# 🚀 [ محرك الإقلاع الرئيسي (Main Startup) ]
# ==========================================
async def start_bot_core():
    """تشغيل عميل التليجرام ومحرك الصوت"""
    global assistant, call_py
    logging.info("⏳ جاري تشغيل البوت والاتصال بقاعدة البيانات...")
    await app.start()
    
    session = await get_assistant()
    if session:
        try:
            logging.info("⏳ جاري تشغيل الحساب المساعد وربطه بمحرك الصوت...")
            assistant = PyroClient("Assistant_Memory", session_string=session, api_id=API_ID, api_hash=API_HASH, in_memory=True)
            await assistant.start()
            
            call_py = PyTgCalls(assistant)
            
            @call_py.on_stream_end()
            async def handle_stream_end(client, update: Update):
                await on_stream_end_handler(client, update)
                
            await call_py.start()
            logging.info("✅ محرك الصوت (PyTgCalls) جاهز للعمل!")
        except Exception as e:
            logging.error(f"❌ فشل تسجيل دخول الحساب المساعد: {e}")
    else:
        logging.warning("⚠️ لم يتم العثور على جلسة مساعدة! يرجى إرسال /مطور للبوت وإضافتها.")
        
    logging.info("✅ السورس يعمل الآن بكفاءة عالية!")
    await idle() # إبقاء البوت متصلاً

async def main_startup():
    # 1. إعداد نظام اللوج المطور (سيرسل الأخطاء لحساب المطور مباشرة)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        headers=[
            logging.StreamHandler(),
            TelegramLoggerHandler(app, OWNER_ID) 
        ]
    )

    # 2. إعداد سيرفر الويب (الذي يمنع Render من إيقاف السكربت)
    web_app = web.Application()
    web_app.router.add_get('/', handle_ping)
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"🌐 سيرفر الويب (Anti-Idle) يعمل على البورت {port}")

    # 3. تشغيل النبض الذاتي في الخلفية
    asyncio.create_task(watch_dog(self_resuscitation))

    # 4. تشغيل البوت ومحرك PyTgCalls
    await start_bot_core()

if __name__ == "__main__":
    asyncio.run(main_startup())
