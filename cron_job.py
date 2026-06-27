import feedparser
import urllib.parse
import google.generativeai as genai
import pandas as pd
import time
import json
import os
from datetime import datetime, timedelta

# 1. 準備と環境変数の取得（GitHubのアクションからキーを受け取る）
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("エラー: GEMINI_API_KEY が設定されていません。")
    exit(1)
genai.configure(api_key=api_key)

# 2. Excelファイルから企業リストを読み込み
file_path = "法人企業一覧.xlsx"
if not os.path.exists(file_path):
    print("エラー: 法人企業一覧.xlsx が見つかりません。")
    exit(1)

df_excel = pd.read_excel(file_path, header=None)
companies = df_excel[0].iloc[1:].dropna().astype(str).tolist()
companies = sorted(list(set([c.strip() for c in companies if c.strip()])))

# 3. ニュース収集関数
def fetch_google_news(company, max_results=5):
    articles = []
    search_name = company.split("（")[0].split("(")[0].strip()
    encoded_query = urllib.parse.quote(f'"{search_name}"')
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ja&gl=JP&ceid=JP:ja"
    
    feed = feedparser.parse(url)
    for entry in feed.entries[:max_results]:
        articles.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "company": company,
            "title": entry.title,
            "link": entry.link,
            "score": 0,
            "comment": ""
        })
    return articles

# 4. AI評価関数
def batch_evaluate_articles(articles_batch):
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    articles_data = [{"id": i, "company": a["company"], "title": a["title"]} for i, a in enumerate(articles_batch)]
    
    prompt = f"""
    以下の記事リストを読み、ルネサンスのBtoB担当（法人営業）の視点から、パートナーシップ深耕や健康経営提案における「重要度スコア（0-100）」と「一行コメント（日本語）」を返してください。
    
    {json.dumps(articles_data, ensure_ascii=False)}
    
    必ず以下のJSONフォーマットのみを返してください。
    [
        {{"id": 0, "score": 90, "comment": "コメント"}},
        ...
    ]
    """
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
        print(f"AI評価中にエラー: {e}")
    return articles_batch

# 5. メイン処理の実行
print("ニュースの収集を開始します...")
all_articles = []
for comp in companies:
    all_articles.extend(fetch_google_news(comp))

if all_articles:
    print(f"合計 {len(all_articles)} 件の記事をAI分析中...")
    analyzed_list = []
    batch_size = 5
    for i in range(0, len(all_articles), batch_size):
        batch = all_articles[i:i+batch_size]
        analyzed_list.extend(batch_evaluate_articles(batch))
        if i + batch_size < len(all_articles):
            time.sleep(7)
    
    # 既存の蓄積データ（archive.csv）があれば合体、なければ新規作成
    archive_file = "archive.csv"
    df_new = pd.DataFrame(analyzed_list)
    
    if os.path.exists(archive_file):
        df_old = pd.read_csv(archive_file)
        df_total = pd.concat([df_old, df_new], ignore_index=True)
        # 重複するURLの記事は排除
        df_total = df_total.drop_duplicates(subset=["link"], keep="first")
    else:
        df_total = df_new
        
    df_total.to_csv(archive_file, index=False)
    print("データの蓄積が完了しました。")
else:
    print("収集されたニュースがありませんでした。")
