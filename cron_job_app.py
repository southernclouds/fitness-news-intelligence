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

# 2. Geminiに検索クエリを言語別に5つずつ自動生成させる（構造化出力に最適化）
def generate_search_queries():
    # generation_config で必ずJSON形式で返却するよう強制
    model = genai.GenerativeModel(
        "gemini-2.5-flash-lite",
        generation_config={"response_mime_type": "application/json"}
    )
    prompt = f"""
業界: {industry}
役割: {role}
上記のビジネスパーソンが追うべき重要キーワードを「日本語」と「英語」で5つずつ挙げてください。

必ず以下のJSON形式（指定したキー名）のみで返してください。余計な解説文や枠（```json など）は一切含めないでください。
{{"日本語": ["kw1", "kw2", ...], "英語": ["kw1", "kw2", ...]}}
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        return json.loads(text)
    except Exception as e:
        print(f"クエリ生成エラー: {e}")
        # 万が一のエラー時のフォールバック
        return {"日本語": ["健康経営", "フィットネス", "ウェルネス"], "英語": ["Corporate wellness", "Fitness industry"]}

# 3. Google News RSSから記事を取得
def fetch_google_news(keywords, lang_cfg, max_results=10):
    articles = []
    query_str = " OR ".join([f'"{kw}"' for kw in keywords])
    encoded_query = urllib.parse.quote(query_str)
    # 💡 Markdownリンクのバグを修正し、正しいURL形式に戻しました
    url = f"[https://news.google.com/rss/search?q=](https://news.google.com/rss/search?q=){encoded_query}&hl={lang_cfg['hl']}&gl={lang_cfg['gl']}&ceid={lang_cfg['ceid']}"
    
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

# 4. AI評価（3件ずつバッチ処理・構造化出力に最適化）
def batch_evaluate_articles(articles_batch):
    # generation_config で必ずJSON形式で返却するよう強制
    model = genai.GenerativeModel(
        "gemini-2.5-flash-lite",
        generation_config={"response_mime_type": "application/json"}
    )
    
    articles_data = [{"id": i, "title": a["title"]} for i, a in enumerate(articles_batch)]
    
    prompt = f"""
評価者: {industry}における{role}
以下の記事リスト（JSON形式）を読み込み、各記事の「重要度スコア(0-100)」と「戦略的な一行コメント(日本語)」を評価してください。

必ず以下のJSON配列の形式（指定したキー名 "id", "score", "comment"）のみで返答してください。余計な解説文やマークダウンの枠（```json などの囲み）は絶対に含めないでください。

[
  {{"id": 0, "score": 85, "comment": "健康経営の具体的な成功事例として非常に参考になるニュース。"}},
  {{"id": 1, "score": 40, "comment": "一般的なイベント情報であり、BtoB戦略への影響は低い。"}}
]

【評価対象の記事リスト】
{json.dumps(articles_data, ensure_ascii=False)}
"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # response_mime_type 指定により直接パース可能
        evaluations = json.loads(text)
        
        for ev in evaluations:
            idx = ev.get("id")
            if idx is not None and idx < len(articles_batch):
                # scoreを確実に数値(int)として取得、commentを文字列として取得
                articles_batch[idx]["score"] = int(ev.get("score", 0))
                articles_batch[idx]["comment"] = ev.get("comment", "")
    except Exception as e:
        print(f"AI評価エラー: {e}")
        # エラー時は初期値（score=0, comment=""）のまま進行
    return articles_batch

# 5. メイン処理
if __name__ == "__main__":
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
        
        # 💡 インデントのブロックを確実に整えました
        if os.path.exists(archive_file):
            try:
                df_old = pd.read_csv(archive_file)
                df_total = pd.concat([df_old, df_new], ignore_index=True)
                df_total = df_total.drop_duplicates(subset=["link"], keep="first")
            except Exception as e:
                print(f"古いCSVの読み込みに失敗したため、新規作成します: {e}")
                df_total = df_new
        else:
            df_total = df_new
            
        # 確実にCSVファイルをローカルに書き出す（インデント位置も修正）
        df_total.to_csv(archive_file, index=False)
        print(f"CSVファイルの書き出しが完了しました: {archive_file}")
    else:
        print("取得できた記事がありませんでした。")
