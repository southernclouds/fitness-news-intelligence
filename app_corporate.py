import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import os

st.set_page_config(page_title="契約法人 ニュース・アーカイブ", layout="wide")

if "insight_cache" not in st.session_state:
    st.session_state["insight_cache"] = {}

st.title("🏢 契約法人・団体 ニュース・インテリジェンス（毎朝7時自動更新）")

archive_file = "archive.csv"

# データの読み込み
if os.path.exists(archive_file):
    df = pd.read_csv(archive_file)
    
    # 日付リストを取得（新しい順）
    available_dates = sorted(df["date"].dropna().unique().tolist(), reverse=True)
    
    # サイドバーで日付と企業を選択
    st.sidebar.header("表示条件設定")
    selected_date = st.sidebar.selectbox("表示する日付", options=available_dates)
    
    # 選択された日付で絞り込み
    df_filtered = df[df["date"] == selected_date]
    
    # さらに企業で絞り込みたい場合
    all_companies = ["すべて"] + sorted(df_filtered["company"].unique().tolist())
    selected_company = st.sidebar.selectbox("法人・団体で絞り込み", options=all_companies)
    
    if selected_company != "すべて":
        df_filtered = df_filtered[df_filtered["company"] == selected_company]
        
    df_display = df_filtered.sort_values(by="score", ascending=False).reset_index(drop=True)
    
    # タブの描画
    tab_list, tab_dist, tab_deep = st.tabs(["分析結果一覧", "重要度の分布", "個別記事の深掘り"])
    
    with tab_list:
        st.subheader(f"{selected_date} の重要ニュース一覧")
        st.dataframe(
            df_display[["company", "title", "score", "comment", "link"]],
            column_config={
                "company": st.column_config.TextColumn("対象法人・団体", width="medium"),
                "title": st.column_config.TextColumn("タイトル", width="large"),
                "score": st.column_config.NumberColumn("重要度スコア", format="%d"),
                "comment": st.column_config.TextColumn("AI一行コメント", width="large"),
                "link": st.column_config.LinkColumn("元記事リンク", display_text="開く")
            },
            hide_index=True,
            use_container_width=True
        )
        
    with tab_dist:
        st.subheader("スコアの分布状況")
        col1, col2 = st.columns(2)
        with col1:
            fig_hist = px.histogram(df_display, x="score", nbins=10, labels={"score": "重要度スコア"})
            st.plotly_chart(fig_hist, use_container_width=True)
        with col2:
            fig_box = px.box(df_display, x="company", y="score", labels={"company": "法人", "score": "スコア"})
            st.plotly_chart(fig_box, use_container_width=True)
            
    with tab_deep:
        st.subheader("個別記事からの提案アプローチ示唆")
        selected_title = st.selectbox("詳細を分析する記事を選択してください", options=df_display["title"].tolist())
        
        if selected_title:
            if selected_title in st.session_state["insight_cache"]:
                st.markdown(st.session_state["insight_cache"][selected_title])
            else:
                with st.spinner("AIが戦略的示唆を生成中..."):
                    # 閲覧用にGeminiを呼び出す設定
                    try:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        model = genai.GenerativeModel("gemini-2.5-flash-lite")
                        target_comp = df_display[df_display["title"] == selected_title]["company"].values[0]
                        
                        deep_prompt = f"対象企業: {target_comp}\n記事: {selected_title}\n\nこのニュースを踏まえ、ルネサンスの法人営業としてどのような健康経営サービスの提案を行うべきか、戦略的示唆を3点、それぞれ2文程度で具体的に提示してください。"
                        response = model.generate_content(deep_prompt)
                        insight_text = response.text
                        st.session_state["insight_cache"][selected_title] = insight_text
                        st.markdown(insight_text)
                    except Exception as e:
                        st.error(f"Gemini APIの設定を確認してください: {e}")
                        
else:
    st.info("まだ自動蓄積データ（archive.csv）が作成されていません。明日の朝7時以降に自動的に作成されます。")
