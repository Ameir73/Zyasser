# 1. إجبار الدوكر على استخدام معمارية x86_64 القياسية لتجاوز مشكلة توافق tgcalls
FROM --platform=linux/amd64 python:3.11-slim-bookworm

# 2. تحديث النظام وتثبيت أداة ffmpeg الضرورية وأدوات التجميع
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 3. تحديد مسار العمل
WORKDIR /app

# 4. نسخ ملف المكتبات
COPY requirements.txt .

# 5. تحديث pip وتثبيت setuptools و wheel (مهم جداً للتعامل مع الحزم المعقدة
RUN pip install --no-cache-dir pyrogram pytgcalls yt-dlp supabase
# 6. تثبيت المكتبات (الآن سيجد pip النسخة المتوافقة ويثبتها بسلاسة)
RUN pip install --no-cache-dir -r requirements.txt

# 7. نسخ باقي ملفات المشروع
COPY . .

# 8. أمر تشغيل البوت
CMD ["python", "bot.py"]
