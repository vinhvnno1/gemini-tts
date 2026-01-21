# Text-to-Speech với Gemini AI

Web app chuyển văn bản thành giọng nói sử dụng Gemini 2.0 Flash Native Audio.

## Deploy miễn phí

### Render.com (Khuyên dùng)

1. Tạo tài khoản tại https://render.com
2. Connect GitHub repository
3. Tạo "New Web Service"
4. Cấu hình:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python tts_server.py`
   - **Environment Variable:** `GEMINI_API_KEY=your_key`

### Railway.app

1. Tạo tài khoản tại https://railway.app
2. "New Project" → "Deploy from GitHub"
3. Thêm environment variable `GEMINI_API_KEY`
4. Railway sẽ tự động detect Python và deploy

## Chạy local

```bash
export GEMINI_API_KEY=your_key
python3 tts_server.py
```

Mở http://localhost:3000
# gemini-tts
# gemini-tts
# gemini-tts
