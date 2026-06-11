# استخدام نسخة بايثون خفيفة
FROM python:3.10-slim-buster

# تحديث النظام وتثبيت أداة ffmpeg الضرورية للصوت
RUN apt-get update && apt-get install -y ffmpeg

# تحديد مسار العمل
WORKDIR /app

# نسخ ملف المكتبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع (مثل ملف زوامل.py)
COPY . .

# أمر تشغيل البوت
CMD ["python", "bot.py"]