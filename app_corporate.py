import streamlit as st
import feedparser
import urllib.parse
import google.generativeai as genai
import pandas as pd
import plotly.express as px
import time
import json
import os
from datetime import datetime, timedelta

# -----------------------------------------------------------------------------
# 1. ページ設定とデータ読み込み
# -----------------------------------------------------------------------------
st.set_page_config(page_title="契約法人 ニュース・インテリジェンス", layout="wide")

if "analyzed_articles" not in st.session_state:
    st.session_state["analyzed_articles"] = None
if "insight_cache" not in st.session_state:
    st.session_state["insight_cache"] = {}

# Excelファイルから企業・団体リストを取得する関数
@st.cache_data
def load_company_list():
    file_path = "法人企業一覧.xlsx"
    if os.path.exists(file_path):
        try:
            # 1列目を企業・団体名として読み込む（ヘッダーがない前提でheader=None）
            df = pd.read_excel(file_path, header=None)
            # 空白を除外してリスト化
            companies = df[0].dropna().astype(str).tolist()
            # 必要に応じて「（健康保険組合）」などの不要な後ろの文字をトリミングする処理を入れると精度が上がります
            return sorted(list(set(companies)))
        except Exception as e:
            return [f"ファイル読み込みエラー: {str(e)}"]
    else:
        return ["法人企業一覧.xlsx が見つかりません"]

company_options = load_company_list()

# -----------------------------------------------------------------------------
# 2. サイドバー（ユーザー入力エリア）
# -----------------------------------------------------------------------------
st.sidebar.header("分析条件設定")

# 企業選択
selected_companies = st.sidebar.multiselect(
    "分析対象の法人・団体",
    options=company_options,
    default=company_options[:5] if len(company_options) >= 5 else company_options
)

hours_lookback = st.sidebar.slider("対象期間 (過去X時間)", min_value=6, max_value=72, value=24, step=6)

language_options = {
    "日本語": {"hl": "ja", "gl": "JP", "ceid": "JP:ja"},
    "英語": {"hl": "en", "gl": "US", "ceid": "US:en"}
}
selected_languages = st.sidebar.multiselect(
    "取得言語", 
    options=list(language_options.keys()), 
    default=["日本語"]
)

additional_keywords_raw = st.sidebar.text_area("追加キーワード (例: 健康経営, 福利厚生)", value="健康経営")

analyze_button = st.sidebar.button("契約法人のニュースを取得して分析")

# タイトルの動的設定
dynamic_title = "🏢 契約法人・団体 ニュース・インテリジェンス・ダッシュボード"

# Gemini APIのセットアップ
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except Exception as e:
    st.error("Gemini APIキーの取得に失敗しました。StreamlitのSecrets設定を確認してください。")

# -----------------------------------------------------------------------------
# 3. メインエリアの構成
# -----------------------------------------------------------------------------
st.title(dynamic_title)

tab_list, tab_dist, tab_deep = st.tabs(["分析結果一覧", "重要度の分布", "個別記事の深掘り"])

# -----------------------------------------------------------------------------
# 4. バックエンド処理関数群
# -----------------------------------------------------------------------------
def fetch_google_news(company, additional_kws, lang_cfg, max_results=5):
    """企業名と追加キーワードを組み合わせてGoogle News RSSから記事を取得する"""
    articles = []
    
    # クエリ例: "住友生命保険" AND ("健康経営" OR "福利厚生")
    if additional_kws:
        kw_or_str = " OR ".join([f'"{kw}"' for kw in additional_kws])
        query_str = f'"{company}" AND ({kw_or_str})'
    else:
        query_str = f'"{company}"'
        
    encoded_query = urllib.parse.quote(query_str)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl={lang_cfg['hl']}&gl={lang_cfg['gl']}&ceid={lang_cfg['ceid']}"
    
    feed = feedparser.parse(url)
    for entry in feed.entries[:max_results]:
        articles.append({
            "company": company,
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", "")
        })
    return articles

def batch_evaluate_articles(articles_batch):
    """Gemini APIを使用して、記事を5件ずつバッチで重要度評価する"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
    articles_data = [{"id": i, "company": a["company"], "title": a["title"]} for i, a in enumerate(articles_batch)]
    
    prompt = f"""
    【文脈】
    あなたはフィットネス・健康推進サービスのBtoB担当（法人営業・コンサルタント）です。
    提携先や契約法人に関するニュースをチェックしています。
    
    以下の記事リストを読み、パートナーシップの維持・深耕、あるいは新規提案（健康経営、福利厚生サービスの拡充など）の観点から、「重要度スコア（0から100の数値）」と、その理由を説明する「一行コメント（日本語）」を返してください。
    
    記事リスト:
    {json.dumps(articles_data, ensure_ascii=False)}
    
    【出力フォーマット】
    必ず以下のJSONフォーマットのみを返してください。解説文は含めないでください。
    [
        {{"id": 0, "score": 90, "comment": "対象企業の健康経営方針に直結する人事ニュースであり、早期のコンタクトが推奨される。"}},
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
        return articles_batch
    except Exception as e:
        for a in articles_batch:
            a["score"] = 0
            a["comment"] = f"評価エラー: {str(e)}"
        return articles_batch

# -----------------------------------------------------------------------------
# 5. ボタン押下時の実行処理
# -----------------------------------------------------------------------------
if analyze_button:
    if not selected_companies:
        st.warning("分析対象の法人を1つ以上選択してください。")
    else:
        st.session_state["analyzed_articles"] = None
        st.session_state["insight_cache"] = {}
        
        all_fetched_articles = []
        additional_kws = [k.strip() for k in additional_keywords_raw.split("\n") if k.strip()]
        
        with st.status("契約法人のニュースを取得・分析中...", expanded=True) as status:
            st.write("1. 選択された企業の最新ニュースをGoogle Newsから収集しています...")
            
            for company in selected_companies:
                # 団体名に含まれる健康保険組合などの文字を簡易的にトリミングして検索ヒット率を上げる調整
                search_name = company.split("（")[0].split("(")[0]
                
                for lang in selected_languages:
                    cfg = language_options[lang]
                    fetched = fetch_google_news(search_name, additional_kws, cfg, max_results=5)
                    for f in fetched:
                        f["language"] = lang
                    all_fetched_articles.extend(fetched)
            
            if not all_fetched_articles:
                st.error("該当する最新ニュースが見つかりませんでした。対象企業を増やすか、追加キーワードを減らしてみてください。")
                status.update(label="処理失敗", state="error")
            else:
                st.write(f"2. 合計 {len(all_fetched_articles)} 件の記事をAIで分析中（5件ずつバッチ処理）...")
                
                analyzed_list = []
                batch_size = 5
                total_articles = len(all_fetched_articles)
                
                progress_bar = st.progress(0.0)
                
                for i in range(0, total_articles, batch_size):
                    batch = all_fetched_articles[i:i+batch_size]
                    evaluated_batch = batch_evaluate_articles(batch)
                    analyzed_list.extend(evaluated_batch)
                    
                    progress_percent = min((i + batch_size) / total_articles, 1.0)
                    progress_bar.progress(progress_percent)
                    
                    if i + batch_size < total_articles:
                        time.sleep(7)
                
                df = pd.DataFrame(analyzed_list)
                if "score" not in df.columns:
                    df["score"] = 0
                if "comment" not in df.columns:
                    df["comment"] = ""
                    
                df = df.sort_values(by="score", ascending=False).reset_index(drop=True)
                df = df[["company", "title", "language", "score", "comment", "link"]]
                
                st.session_state["analyzed_articles"] = df
                status.update(label="分析が完了しました", state="complete")

# -----------------------------------------------------------------------------
# 6. 各タブの描画処理
# -----------------------------------------------------------------------------
df_result = st.session_state["analyzed_articles"]

with tab_list:
    st.subheader("法人別・重要ニュース一覧")
    if df_result is not None:
        st.dataframe(
            df_result,
            column_config={
                "company": st.column_config.TextColumn("対象法人・団体", width="medium"),
                "title": st.column_config.TextColumn("タイトル", width="large"),
                "language": st.column_config.TextColumn("言語", width="small"),
                "score": st.column_config.NumberColumn("重要度スコア", format="%d"),
                "comment": st.column_config.TextColumn("AI一行コメント", width="large"),
                "link": st.column_config.LinkColumn("元記事リンク", display_text="開く")
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("サイドバーのボタンを押してニュース取得を開始してください。")

with tab_dist:
    st.subheader("分析データの可視化")
    if df_result is not None:
        col1, col2 = st.columns(2)
        with col1:
            st.write("全体的な重要度スコアの分布")
            fig_hist = px.histogram(df_result, x="score", nbins=10, labels={"score": "重要度スコア", "count": "記事数"})
            st.plotly_chart(fig_hist, use_container_width=True)
        with col2:
            st.write("法人別のスコア分布")
            fig_box = px.box(df_result, x="company", y="score", labels={"company": "法人・団体", "score": "重要度スコア"})
            st.plotly_chart(fig_box, use_container_width=True)
    else:
        st.info("サイドバーのボタンを押して分析を開始してください。")

with tab_deep:
    st.subheader("個別記事からの提案アプローチ示唆")
    if df_result is not None:
        selected_title = st.selectbox("詳細を分析する記事を選択してください", options=df_result["title"].tolist())
        
        if selected_title:
            if selected_title in st.session_state["insight_cache"]:
                st.markdown(st.session_state["insight_cache"][selected_title])
            else:
                with st.spinner("AIが戦略的示唆を生成中..."):
                    # 選択された記事の企業名を取得
                    target_comp = df_result[df_result["title"] == selected_title]["company"].values[0]
                    
                    model = genai.GenerativeModel("gemini-2.5-flash-lite")
                    deep_prompt = f"""
                    【文脈】
                    対象企業: {target_comp}
                    記事タイトル: {selected_title}
                    
                    このニュースを踏まえ、ルネサンスの法人営業・健康コンサルタントとして、この企業（または健康保険組合）に対してどのようなアクションやアプローチ、あるいは健康経営サービスの提案を行うべきか、戦略的示唆を3点、それぞれ2文程度で具体的に提示してください。
                    """
                    try:
                        response = model.generate_content(deep_prompt)
                        insight_text = response.text
                        st.session_state["insight_cache"][selected_title] = insight_text
                        st.markdown(insight_text)
                    except Exception as e:
                        st.error(f"示唆の生成中にエラーが発生しました: {str(e)}")
    else:
        st.info("サイドバーのボタンを押して分析を開始してください。")
