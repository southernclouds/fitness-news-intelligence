import feedparser
import urllib.parse
import google.generativeai as genai
import pandas as pd
import time
import json
import os
from datetime import datetime, timedelta

# 1. 環境変数の取得
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("エラー: GEMINI_API_KEY が設定されていません。")
    exit(1)
genai.configure(api_key=api_key)

industry = "フィットネス業界・健康経営・BtoBウェルネス"
role = "健康経営ソリューション部門・部長（マネジメント）"

# 2. Geminiに検索クエリを言語別に5つずつ自動生成させる
def generate_search_queries():
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    prompt = f"業界: {industry}\n役割: {role}\n上記のビジネスパーソンが追うべき重要キーワードを「日本語」と「英語」で5つずつ挙げてください。必ず指定のJSON形式でのみ返してください。\n{{\"日本語\": [\"kw1\", ...], \"英語\": [\"kw1\", ...]}}"
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text.split("```json")[1].split("```")[0].strip()
        elif text.startswith("```"):
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        print(f"クエリ生成エラー: {e}")
        return {"日本語": ["健康経営", "フィットネス", "ウェルネス"], "英語": ["Corporate wellness", "Fitness industry"]}

# 3. Google News RSSから記事を取得
def fetch_google_news(keywords, lang_cfg, max_results=10):
    articles = []
    query_str = " OR ".join([f'"{kw}"' for kw in keywords])
    encoded_query = urllib.parse.quote(query_str)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl={lang_cfg['hl']}&gl={lang_cfg['gl']}&ceid={lang_cfg['ceid']}"
    
    feed = feedparser.parse(url)
    for entry in feed.entries[:max_results]:
        articles.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", ""),
            "score": 0,
            "comment": ""
        })
    return articles

# 4. AI評価（5件ずつバッチ処理）
def batch_evaluate_articles(articles_batch):
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    articles_data = [{"id": i, "title": a["title"]} for i, a in enumerate(articles_batch)]
    prompt = f"評価者: {industry}における{role}\n以下の記事リストの「重要度スコア(0-100)」と「一行コメント(日本語)」をJSONで返してください。\n{json.dumps(articles_data, ensure_ascii=False)}"
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text.split("```json")[1].split("```")[0].strip()
        elif text.startswith("```"):
            text = text.split("```")[1].split("```")[0].strip()
        evaluations = json.loads(text)
        for ev in evaluations:
            idx = ev.get("id")
            if idx is not None and idx < len(articles_batch):
                articles_batch[idx]["score"] = int(ev.get("score", 0))
                articles_batch[idx]["comment"] = ev.get("comment", "")
    except Exception as e:
        print(f"AI評価エラー: {e}")
    return articles_batch

# 5. メイン処理
print("トレンドキーワードの生成中...")
queries = generate_search_queries()

language_options = {
    "日本語": {"hl": "ja", "gl": "JP", "ceid": "JP:ja"},
    "英語": {"hl": "en", "gl": "US", "ceid": "US:en"}
}

all_articles = []
for lang in ["日本語", "英語"]:
    if lang in queries:
        fetched = fetch_google_news(queries[lang], language_options[lang], max_results=15)
        for f in fetched:
            f["language"] = lang
        all_articles.extend(fetched)

if all_articles:
    print(f"合計 {len(all_articles)} 件の記事をAI分析中...")
    analyzed_list = []
    batch_size = 3
    for i in range(0, len(all_articles), batch_size):
        batch = all_articles[i:i+batch_size]
        analyzed_list.extend(batch_evaluate_articles(batch))
        if i + batch_size < len(all_articles):
            time.sleep(10)
            
    archive_file = "archive_app.csv"
    df_new = pd.DataFrame(analyzed_list)
    
    if os.path.exists(archive_file):
        df_old = pd.read_csv(archive_file)
        df_total = pd.concat([df_old, df_new], ignore_index=True)
        df_total = df_total.drop_duplicates(subset=["link"], keep="first")
    else:
        df_total = df_new
        
    df_total.to_csv(archive_file, index=False)
    print("トレンドニュースの蓄積が完了しました。")
