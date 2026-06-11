# استخدام نسخة بايثون خفيفة ومستقرة
FROM python:3.10-slim-bookworm

# تثبيت أداة ffmpeg الضرورية فقط للصوت
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# تحديد مسار العمل
WORKDIR /app

# نسخ ملف المكتبات وتحديث pip
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip

# تثبيت المكتبات (الآن سيتم التثبيت بثوانٍ)
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# أمر تشغيل البوت
CMD ["python", "bot.py"]
