import streamlit as st
import feedparser
import urllib.parse
import google.generativeai as genai
import pandas as pd
import plotly.express as px
import time
import json
import re
from datetime import datetime, timedelta

# -----------------------------------------------------------------------------
# 1. ページ設定とセッション状態の初期化
# -----------------------------------------------------------------------------
st.set_page_config(page_title="ニュース・インテリジェンス・ダッシュボード", layout="wide")

if "analyzed_articles" not in st.session_state:
    st.session_state["analyzed_articles"] = None
if "insight_cache" not in st.session_state:
    st.session_state["insight_cache"] = {}

# -----------------------------------------------------------------------------
# 2. サイドバー（ユーザー入力エリア）
# -----------------------------------------------------------------------------
st.sidebar.header("分析条件設定")

default_industry = "フィットネス業界・健康経営・BtoBウェルネス"
default_role = "健康経営ソリューション部門・部長（マネジメント）"

industry_input = st.sidebar.text_input("事業・業界", value=default_industry)
role_input = st.sidebar.text_input("部門・役割", value=default_role)

dynamic_title = f"【{industry_input}】×【{role_input}】 ニュース・インテリジェンス"

hours_lookback = st.sidebar.slider("対象期間 (過去X時間)", min_value=6, max_value=72, value=24, step=6)

language_options = {
    "日本語": {"hl": "ja", "gl": "JP", "ceid": "JP:ja"},
    "英語": {"hl": "en", "gl": "US", "ceid": "US:en"},
    "フランス語": {"hl": "fr", "gl": "FR", "ceid": "FR:fr"},
    "スペイン語": {"hl": "es", "gl": "ES", "ceid": "ES:es"}
}
selected_languages = st.sidebar.multiselect(
    "取得言語", 
    options=list(language_options.keys()), 
    default=["日本語", "英語"]
)

additional_keywords_raw = st.sidebar.text_area("追加キーワード (改行区切り、任意)", value="")

analyze_button = st.sidebar.button("ニュースを取得して分析")

# -----------------------------------------------------------------------------
# 3. メインエリアの構成
# -----------------------------------------------------------------------------
st.title(dynamic_title)

tab_list, tab_dist, tab_deep = st.tabs(["分析結果一覧", "重要度の分布", "個別記事の深掘り"])

# Gemini APIのセットアップ
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except Exception as e:
    st.error("Gemini APIキーの取得に失敗しました。StreamlitのSecrets設定を確認してください。")

# -----------------------------------------------------------------------------
# 4. バックエンド処理関数群
# -----------------------------------------------------------------------------
def generate_search_queries(industry, role, languages):
    """Gemini APIを使用して、業界と役割に適した検索クエリを言語ごとに生成する"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
    lang_str = ", ".join(languages)
    prompt = f"""
    【前提条件】
    業界: {industry}
    役割: {role}
    
    上記のビジネスパーソンがビジネスチャンスや脅威、社会的トレンドを察知するために、Google Newsで検索すべき重要なキーワードを、指定された各言語（{lang_str}）で5つずつ挙げてください。
    
    【出力フォーマット】
    必ず以下のJSONフォーマットのみを返してください。余計な解説文は一切含めないでください。
    {{
        "言語名1": ["キーワード1", "キーワード2", "キーワード3", "キーワード4", "キーワード5"],
        "言語名2": ["キーワード1", "キーワード2", "キーワード3", "キーワード4", "キーワード5"]
    }}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        # Markdownのコードブロックをクリア
        if text.startswith("```json"):
            text = text.split("```json")[1].split("```")[0].strip()
        elif text.startswith("```"):
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"クエリ生成中にエラーが発生しました: {str(e)}")
        return {lang: [industry] for lang in languages}

def fetch_google_news(keywords, lang_cfg, max_results=10):
    """Google News RSSから記事を取得する"""
    articles = []
    # キーワードをORで結合してクエリを作成
    query_str = " OR ".join([f'"{kw}"' for kw in keywords])
    encoded_query = urllib.parse.quote(query_str)
    
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl={lang_cfg['hl']}&gl={lang_cfg['gl']}&ceid={lang_cfg['ceid']}"
    
    feed = feedparser.parse(url)
    for entry in feed.entries[:max_results]:
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", "")
        })
    return articles

def batch_evaluate_articles(articles_batch, industry, role):
    """Gemini APIを使用して、記事を5件ずつバッチで重要度評価・コメント生成する"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
    articles_data = [{"id": i, "title": a["title"]} for i, a in enumerate(articles_batch)]
    
    prompt = f"""
    【文脈】
    評価者: {industry}における{role}
    
    以下の記事リスト（タイトル）を読み、あなたのビジネス（戦略策定、市場トレンド把握、組織変革、新サービス開発など）における「重要度スコア（0から100の数値）」と、その理由を説明する「一行コメント（日本語）」を返してください。
    
    記事リスト:
    {json.dumps(articles_data, ensure_ascii=False)}
    
    【出力フォーマット】
    必ず以下のJSONフォーマットのみを返してください。解説文は含めないでください。
    [
        {{"id": 0, "score": 85, "comment": "BtoB健康経営の推進における新しい標準化の動きを示す記事であり、競合戦略上重要。"}},
        {{"id": 1, "score": 40, "comment": "一般的なフィットネスの話題であり、BtoBビジネスへの直接の影響は限定的。"}},
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
        # 元の記事データとマージ
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
    st.session_state["analyzed_articles"] = None
    st.session_state["insight_cache"] = {}
    
    all_fetched_articles = []
    
    with st.status("ニュースの取得とAI分析を実行中...", expanded=True) as status:
        st.write("1. 業界と役割に応じた検索クエリを自動生成しています...")
        generated_queries = generate_search_queries(industry_input, role_input, selected_languages)
        
        # ユーザー指定の追加キーワードの処理
        additional_kws = [k.strip() for k in additional_keywords_raw.split("\n") if k.strip()]
        
        st.write("2. Google News RSSから最新の記事を収集しています...")
        for lang in selected_languages:
            kws = generated_queries.get(lang, []) + additional_kws
            cfg = language_options[lang]
            fetched = fetch_google_news(kws, cfg, max_results=10)
            for f in fetched:
                f["language"] = lang
            all_fetched_articles.extend(fetched)
            
        if not all_fetched_articles:
            st.error("記事を取得できませんでした。キーワードや言語設定を変更してください。")
            status.update(label="処理失敗", state="error")
        else:
            st.write(f"3. 合計 {len(all_fetched_articles)} 件の記事をAI（gemini-2.5-flash-lite）で分析中（5件ずつバッチ処理）...")
            
            analyzed_list = []
            batch_size = 5
            total_articles = len(all_fetched_articles)
            
            progress_bar = st.progress(0.0)
            
            for i in range(0, total_articles, batch_size):
                batch = all_fetched_articles[i:i+batch_size]
                evaluated_batch = batch_evaluate_articles(batch, industry_input, role_input)
                analyzed_list.extend(evaluated_batch)
                
                # 進捗更新
                progress_percent = min((i + batch_size) / total_articles, 1.0)
                progress_bar.progress(progress_percent)
                
                # APIレートリミット（Utilities.sleep相当）への配慮
                if i + batch_size < total_articles:
                    time.sleep(7)
            
            df = pd.DataFrame(analyzed_list)
            # 必要な列の確保と整形
            if "score" not in df.columns:
                df["score"] = 0
            if "comment" not in df.columns:
                df["comment"] = ""
                
            df = df.sort_values(by="score", ascending=False).reset_index(drop=True)
            df = df[["title", "language", "score", "comment", "link"]]
            
            st.session_state["analyzed_articles"] = df
            status.update(label="分析が完了しました", state="complete")

# -----------------------------------------------------------------------------
# 6. 各タブの描画処理
# -----------------------------------------------------------------------------
df_result = st.session_state["analyzed_articles"]

with tab_list:
    st.subheader("AIスコアリングによる重要ニュース一覧")
    if df_result is not None:
        st.dataframe(
            df_result,
            column_config={
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
        st.info("サイドバーのボタンを押して分析を開始してください。")

with tab_dist:
    st.subheader("分析データの可視化")
    if df_result is not None:
        col1, col2 = st.columns(2)
        with col1:
            st.write("全体的な重要度スコアの分布")
            fig_hist = px.histogram(df_result, x="score", nbins=10, labels={"score": "重要度スコア", "count": "記事数"})
            st.plotly_chart(fig_hist, use_container_width=True)
        with col2:
            st.write("言語別の重要度スコア分布")
            fig_box = px.box(df_result, x="language", y="score", labels={"language": "言語", "score": "重要度スコア"})
            st.plotly_chart(fig_box, use_container_width=True)
    else:
        st.info("サイドバーのボタンを押して分析を開始してください。")

with tab_deep:
    st.subheader("注目記事の深掘り・戦略的示唆の抽出")
    if df_result is not None:
        selected_title = st.selectbox("詳細を分析する記事を選択してください", options=df_result["title"].tolist())
        
        if selected_title:
            # キャッシュチェック
            if selected_title in st.session_state["insight_cache"]:
                st.markdown(st.session_state["insight_cache"][selected_title])
            else:
                with st.spinner("AIが戦略的示唆を生成中..."):
                    model = genai.GenerativeModel("gemini-2.5-flash-lite")
                    deep_prompt = f"""
                    【文脈】
                    対象業界: {industry_input}
                    対象役割: {role_input}
                    
                    【記事タイトル】
                    {selected_title}
                    
                    上記の記事タイトルをもとに、これが【対象業界】の【対象役割】に与える「戦略的示唆（ビジネス上の意味合いや次に取るべき行動へのヒント）」を3点、それぞれ2文程度で具体的に提示してください。
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
