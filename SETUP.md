# 🚀 Dollar Academy Sales Pipeline - Setup Guide

## סטטוס: כמעט מוכן!

המערכת בנויה וקרובה לפעולה. צריך להשלים 5 צעדים קטנים:

---

## **1️⃣ Google API Setup**

### A. Create Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create new project: "Dollar Academy Sales"
3. Enable APIs:
   - Google Calendar API
   - Google Drive API

### B. Create OAuth Credentials
1. Console → Credentials
2. Create "Desktop Application" OAuth client
3. Download JSON → save as `credentials.json` בתיקייה הזו

### C. Run Authorization
```bash
cd /Users/shmuelmordechay/DollarAcademy/projects/DA\ Sales\ Calls
source .venv/bin/activate
python authorize.py
```
⚠️ Browser יפתח - approve the permissions
✅ `token.json` יווצר

---

## **2️⃣ API Keys**

### Anthropic API Key (Claude)
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```
[Get key here](https://console.anthropic.com/account/keys)

### OpenAI API Key (Whisper)
```bash
export OPENAI_API_KEY="sk-..."
```
[Get key here](https://platform.openai.com/account/api-keys)

---

## **3️⃣ Install Dependencies**

```bash
cd /Users/shmuelmordechay/DollarAcademy/projects/DA\ Sales\ Calls
source .venv/bin/activate
pip install -r requirements.txt
```

---

## **4️⃣ Configure Zoom Recording Directory**

ודא שהזום שומר הקלטות בתיקייה:
```
/Users/Shared/ZoomRecordings
```

אם הקלטות בתיקייה אחרת, עדוף את `config.json`:
```json
{
  "WATCH_DIR": "/path/to/your/zoom/recordings",
  ...
}
```

---

## **5️⃣ Start the Pipeline**

### Terminal 1 - Form Server (מטפל בטפסים)
```bash
cd /Users/shmuelmordechay/DollarAcademy/projects/DA\ Sales\ Calls
source .venv/bin/activate
python form_server.py
```
✅ Server יתחיל on `http://localhost:8765`

### Terminal 2 - Pipeline Watch (מוצא קלטות והעלאות)
```bash
cd /Users/shmuelmordechay/DollarAcademy/projects/DA\ Sales\ Calls
source .venv/bin/activate
python pipeline.py --watch
```
✅ Pipeline יתחיל בpoll mode (כל 30 שניות)

---

## **✅ Testing**

### בדוק שהכל עובד:

1. **תן קלטה לתיקיית Zoom:**
   ```bash
   cp /tmp/test_video.mp4 /Users/Shared/ZoomRecordings/
   ```

2. **Pipeline צריך:**
   - ✅ למצוא את הקלטה
   - ✅ לשנות שם בעברית עם התאריך
   - ✅ להעלות לGoogle Drive
   - ✅ לפתוח Form בדפדפן

3. **מלא את הטופס:**
   - בחר סוג (sales/team/other)
   - בחר סטטוס (נסלק/פתוח)
   - שמור

4. **בדוק Drive:**
   - ✅ Recording עלה לתיקייה הנכונה
   - ✅ Summary נוצר
   - ✅ state.json עודכן

---

## **🐚 Daemon Setup (Optional - להריץ בעקבית)**

### Create LaunchAgent (macOS)

**File:** `~/Library/LaunchAgents/com.dollaracademy.dasales.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dollaracademy.dasales</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>
        source /Users/shmuelmordechay/DollarAcademy/projects/DA\ Sales\ Calls/.venv/bin/activate
        cd /Users/shmuelmordechay/DollarAcademy/projects/DA\ Sales\ Calls
        export ANTHROPIC_API_KEY="your-key"
        export OPENAI_API_KEY="your-key"
        python pipeline.py --watch
        </string>
    </array>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <true/>
    
    <key>StandardOutPath</key>
    <string>/tmp/dasales.log</string>
    
    <key>StandardErrorPath</key>
    <string>/tmp/dasales.err</string>
</dict>
</plist>
```

**Load it:**
```bash
launchctl load ~/Library/LaunchAgents/com.dollaracademy.dasales.plist
```

**Check status:**
```bash
launchctl list | grep dasales
```

---

## **📊 File Structure**

```
DA Sales Calls/
├── pipeline.py              ← Main orchestrator
├── call_analyzer.py         ← Transcription + Claude analysis
├── form_server.py           ← Form submission handler
├── outcome_form.html        ← Beautiful form UI
├── config.json              ← Configuration (Drive folder IDs)
├── authorize.py             ← One-time Google auth
├── token.json               ← Google auth token (auto-generated)
├── credentials.json         ← Google OAuth (you provide)
├── requirements.txt         ← Python dependencies
├── state.json               ← Running state (auto-generated)
└── logs/
    └── pipeline.log         ← Activity log
```

---

## **🔧 Troubleshooting**

### Pipeline not finding recordings
- ✅ Check `config.json` → `WATCH_DIR` is correct
- ✅ Zoom is saving to that folder (check Zoom settings)

### Form not opening
- ✅ form_server.py is running on localhost:8765
- ✅ Check logs: `tail -f logs/pipeline.log`

### Google Drive upload fails
- ✅ Run `authorize.py` again
- ✅ Check folder IDs in `config.json`

### Transcription fails
- ✅ Check `OPENAI_API_KEY` is set
- ✅ Check audio file format (should be .m4a)

---

## **📝 Next Steps**

After setup works:
1. [ ] Create additional branches (onboarding, marketing, etc.)
2. [ ] Create dashboard to view all sales metrics
3. [ ] Add Slack notifications
4. [ ] Set up weekly reports

---

**Questions?** Check `pipeline.py` logs or GitHub issues.
