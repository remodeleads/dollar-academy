# DA Sales Calls — שלב 1: שינוי שם אוטומטי + העלאה ל‑Drive

אחרי כל זום מכירה (שמתוזמן ב‑Google Calendar), התהליך הזה:
1. מזהה הקלטת זום מקומית שהסתיימה,
2. קורא את שעת ההתחלה ומתאים אותה לאירוע ביומן,
3. משנה את שם הווידאו (+האודיו) ל**כותרת האירוע** (+ תאריך),
4. מעלה ל**תיקיית Drive ספציפית** (עם אימות גודל+md5),
5. מוחק את העותק המקומי אחרי שההעלאה אושרה.

**חיבור אחד לגוגל מכסה את שני התפקידים:** יומן (קריאה בלבד) + Drive (העלאה).
הכל רץ מקומית על המק; אפשר לבטל גישה בכל רגע ב‑[myaccount.google.com/permissions](https://myaccount.google.com/permissions).

> שלב 2 (בהמשך): תמלול + סיכום שיחה מובנה + דף לקוח עם לינק לחיץ. לא נכלל כאן.

---

## הכנה חד‑פעמית

### 1. הרשאת Google (חיבור אחד לשניהם)
ב‑[Google Cloud Console](https://console.cloud.google.com):
- צור פרויקט (למשל `DA Sales Calls`).
- **APIs & Services → Library** → הפעל **Google Calendar API** וגם **Google Drive API**.
- **OAuth consent screen** → User type **External** → מלא שם + מייל → **PUBLISH APP** (מצב "In production", אחרת ההרשאה פגה כל 7 ימים).
- **Credentials → Create Credentials → OAuth client ID → Application type: Desktop app → Download JSON.**
- שמור את הקובץ כאן בשם **`credentials.json`**.

### 2. תיקיית היעד ב‑Drive
פתח את התיקייה ב‑Drive בדפדפן. ה‑URL: `https://drive.google.com/drive/folders/XXXXXXXX`
— העתק את `XXXXXXXX` ל‑`DRIVE_FOLDER_ID` ב‑`config.json`.

### 3. התקנה והתחברות
```bash
cd "~/DollarAcademy/projects/DA Sales Calls"
./install.sh                          # יוצר venv ומתקין תלויות
.venv/bin/python authorize.py         # חיבור אחד: יומן(קריאה) + Drive(העלאה) — נפתח דפדפן
# ואז ערוך config.json → הדבק DRIVE_FOLDER_ID
```

### 4. בדיקה יבשה (לא נוגעת בכלום)
```bash
.venv/bin/python pipeline.py --dry-run --scan
```
מדפיס לאיזה אירוע כל הקלטה תותאם ואיזה שם תקבל. כשמרוצים — הרצה אמיתית:
```bash
.venv/bin/python pipeline.py --scan
```

### 5. מעבר ל‑`/Users/Shared/ZoomRecordings` + ריצה 24/7
ב‑Zoom: **Settings → Recording → Local Recording → "Store my recordings at" → Change**
בחר `/Users/Shared/ZoomRecordings` (מיקום מקומי לא‑מוגן; מונע בעיות Full Disk Access ל‑LaunchAgent).
ואז עדכן ב‑`config.json`: `"WATCH_DIR": "/Users/Shared/ZoomRecordings"` והפעל:
```bash
./load-agent.sh              # מתקין LaunchAgent שרץ תמיד
tail -f logs/pipeline.log    # מעקב
```

---

## הגדרות (`config.json`)
| שדה | ערך | משמעות |
|---|---|---|
| `WATCH_DIR` | `~/Documents/Zoom` | היכן Zoom שומר הקלטות (החלף ל‑`/Users/Shared/ZoomRecordings` בשלב 5) |
| `CALENDAR_ID` | `primary` | היומן של אירועי המכירה |
| `RULES` | רשימה | ניתוב: כל כלל `{name, keyword, drive_folder_id}`. הכלל הראשון שהמילה שלו מופיעה בכותרת האירוע **או** בשם פגישת הזום — קובע לאיזו תיקייה להעלות. כלל עם `drive_folder_id` ריק = כבוי. |
| `APPEND_DATE` | `true` | להוסיף ` YYYY-MM-DD` לשם (מונע דריסה כשחוזרים על אותו נושא/לקוח) |
| `UPLOAD_AUDIO` | `true` | להעלות גם את קובץ האודיו (m4a) |
| `DELETE_AFTER_UPLOAD` | `true` | למחוק מקומית אחרי אימות ההעלאה |
| `MATCH_TOLERANCE_MIN` | `20` | דקות סטייה מותרות בין תחילת ההקלטה לאירוע |

## פקודות שימושיות
```bash
.venv/bin/python pipeline.py --once "PATH/to/folder"   # תיקייה אחת
.venv/bin/python pipeline.py --reset-state             # לשכוח מה עובד/דולג (לבדיקה חוזרת)
```
