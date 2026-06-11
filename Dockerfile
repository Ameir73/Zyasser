# استخدام نسخة بايثون خفيفة ومستقرة ونظام حديث (Bookworm)
FROM python:3.10-slim-bookworm

# تحديث النظام وتثبيت أداة ffmpeg الضرورية للصوت
RUN apt-get update && apt-get install -y ffmpeg

# تحديد مسار العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المكتبات وتثبيتها
COPY requirements.txt .

# 🔥 [التعديل هنا] تحديث أداة pip أولاً لتجنب أخطاء تعارض المكتبات
RUN pip install --no-cache-dir --upgrade pip

# تثبيت المكتبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع إلى السيرفر
COPY . .

# أمر تشغيل البوت الرسمي
CMD ["python", "bot.py"]
