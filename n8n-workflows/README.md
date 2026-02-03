# n8n PDF to JSON Workflow

Workflow לחילוץ נתונים פיננסיים מקבצי PDF והמרתם ל-JSON מובנה, כולל ניתוח הזדמנויות וסיכונים עבור כלים כמו base44.

## מבנה הפרויקט

```
n8n-workflows/
├── pdf-to-json-workflow.json    # קובץ ה-workflow של n8n
├── schemas/
│   └── output-schema.json       # JSON Schema לפורמט הפלט
├── templates/
│   └── analysis-template.html   # תבנית HTML לניתוח AI
└── README.md                    # תיעוד זה
```

## התקנה

### דרישות מוקדמות

1. **n8n** מותקן ופועל (גרסה 1.0 ומעלה)
2. **OpenAI API Key** (או ספק LLM אחר)
3. גישה לקבצי PDF לעיבוד

### שלבי התקנה

1. פתח את n8n בדפדפן
2. לחץ על "Import" בתפריט הראשי
3. העלה את הקובץ `pdf-to-json-workflow.json`
4. הגדר את ה-credentials:
   - OpenAI API Key (או ספק LLM אחר)
   - HTTP Request credentials אם נדרש

## שימוש

### הפעלה ידנית

1. פתח את ה-workflow ב-n8n
2. לחץ על "Execute Workflow"
3. ספק URL ל-PDF או העלה קובץ
4. הפלט יכלול:
   - JSON מובנה עם כל הנתונים
   - HTML לניתוח הזדמנויות וסיכונים

### הפעלה דרך Webhook

ניתן להחליף את ה-Manual Trigger ב-Webhook Trigger לאוטומציה:

```bash
curl -X POST "https://your-n8n-instance/webhook/pdf-to-json" \
  -H "Content-Type: application/json" \
  -d '{"pdf_url": "https://example.com/report.pdf"}'
```

## מבנה הפלט

### JSON Structure

```json
{
  "schema_version": "1.0.0",
  "data_type": "financial_fund_analysis",
  "_meta": {
    "created_at": "2026-02-03T12:00:00.000Z",
    "source": "n8n-pdf-extractor",
    "format": "base44-compatible"
  },
  "fields": {
    "fund_name": "שם הקרן",
    "fund_type": "gemel",
    "return_ytd": 8.5,
    "management_fee": 0.5,
    "risks_count": 3,
    "opportunities_count": 2
  },
  "collections": {
    "risks": [...],
    "opportunities": [...],
    "assets": {...}
  },
  "full_data": {...},
  "analysis_html": "<html>...</html>"
}
```

### קטגוריות סיכונים

| קטגוריה | תיאור |
|---------|--------|
| `market` | סיכוני שוק |
| `credit` | סיכוני אשראי |
| `liquidity` | סיכוני נזילות |
| `operational` | סיכונים תפעוליים |
| `regulatory` | סיכונים רגולטוריים |
| `currency` | סיכוני מטבע |
| `interest_rate` | סיכוני ריבית |
| `concentration` | סיכוני ריכוזיות |

### קטגוריות הזדמנויות

| קטגוריה | תיאור |
|---------|--------|
| `growth` | הזדמנויות צמיחה |
| `value` | הזדמנויות ערך |
| `income` | הזדמנויות הכנסה |
| `diversification` | הזדמנויות פיזור |
| `cost_reduction` | הזדמנויות להפחתת עלויות |
| `market_timing` | הזדמנויות תזמון שוק |

### רמות חומרה

- `critical` - קריטי
- `high` - גבוה
- `medium` - בינוני
- `low` - נמוך

## אינטגרציה עם base44

הפלט מותאם לעבודה עם base44:

1. **fields** - שדות שטוחים לגישה מהירה
2. **collections** - מערכים ואובייקטים מקוננים
3. **_meta** - מטאדטה לניהול ומעקב

### דוגמה לשימוש ב-base44

```javascript
// קריאת הנתונים
const data = await base44.getData("financial_fund_analysis");

// גישה לשדות
const fundName = data.fields.fund_name;
const risks = data.collections.risks;

// סינון סיכונים גבוהים
const highRisks = risks.filter(r => r.severity === "high");
```

## ניתוח AI עם ה-HTML

ה-HTML שנוצר מכיל:

1. **סיכום ויזואלי** - כרטיסיות עם מדדים מרכזיים
2. **רשימת סיכונים** - עם רמת חומרה והמלצות
3. **רשימת הזדמנויות** - עם פוטנציאל השפעה
4. **נתונים גולמיים** - JSON מעוצב
5. **הנחיות ל-LLM** - prompt מובנה לניתוח

### שימוש עם מודל שפה

```python
# דוגמה עם OpenAI
import openai

# קריאת ה-HTML
with open("analysis.html", "r") as f:
    html_content = f.read()

response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=[
        {
            "role": "system",
            "content": "אתה מנתח פיננסי מומחה בקרנות פנסיה וגמל ישראליות."
        },
        {
            "role": "user",
            "content": f"נתח את המסמך הבא ותן תובנות:\n\n{html_content}"
        }
    ]
)
```

## התאמה אישית

### שינוי ספק LLM

ניתן להחליף את node ה-OpenAI בספק אחר:
- Anthropic Claude
- Google Gemini
- Azure OpenAI
- Local LLM (Ollama)

### הוספת שדות

1. ערוך את ה-prompt ב-"LLM - Extract Structured Data"
2. עדכן את הקוד ב-"Structure JSON Output"
3. עדכן את ה-schema ב-`output-schema.json`

### שינוי עיצוב HTML

ערוך את הקובץ `templates/analysis-template.html` או את הקוד ב-node "Generate Analysis HTML".

## Troubleshooting

### בעיות נפוצות

| בעיה | פתרון |
|------|--------|
| PDF לא נקרא | ודא שה-PDF לא מוגן בסיסמה |
| LLM לא מחזיר JSON תקין | הגדל את `maxTokens` או פשט את ה-prompt |
| שגיאת timeout | הגדל את ה-timeout ב-HTTP Request |
| חסרים נתונים | בדוק את איכות ה-PDF ושפת המסמך |

### Logs

בדוק את הלוגים ב-n8n:
```bash
n8n logs --tail 100
```

## רישיון

MIT License

## תמיכה

לשאלות ובעיות: https://github.com/anthropics/claude-code/issues
