import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import os

st.set_page_config(page_title="業界ニュース・アーカイブ", layout="wide")

if "insight_cache" not in st.session_state:
    st.session_state["insight_cache"] = {}

st.title("【フィットネス業界・健康経営・BtoBウェルネス】 ニュース・インテリジェンス（毎朝7時自動更新）")

archive_file = "archive_app.csv"

if os.path.exists(archive_file):
    df = pd.read_csv(archive_file)
    available_dates = sorted(df["date"].dropna().unique().tolist(), reverse=True)
    
    st.sidebar.header("表示条件設定")
    selected_date = st.sidebar.selectbox("表示する日付", options=available_dates)
    
    df_filtered = df[df["date"] == selected_date]
    
    selected_lang = st.sidebar.multiselect("言語で絞り込み", options=["日本語", "英語"], default=["日本語", "英語"])
    df_filtered = df_filtered[df_filtered["language"].isin(selected_lang)]
    
    df_display = df_filtered.sort_values(by="score", ascending=False).reset_index(drop=True)
    
    tab_list, tab_dist, tab_deep = st.tabs(["分析結果一覧", "重要度の分布", "個別記事の深掘り"])
    
    with tab_list:
        st.subheader(f"{selected_date} の重要ニュース一覧")
        st.dataframe(
            df_display[["title", "language", "score", "comment", "link"]],
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
        
    with tab_dist:
        st.subheader("スコアの分布状況")
        col1, col2 = st.columns(2)
        with col1:
            fig_hist = px.histogram(df_display, x="score", nbins=10, labels={"score": "重要度スコア"})
            st.plotly_chart(fig_hist, use_container_width=True)
        with col2:
            fig_box = px.box(df_display, x="language", y="score", labels={"language": "言語", "score": "スコア"})
            st.plotly_chart(fig_box, use_container_width=True)
            
    with tab_deep:
        st.subheader("注目記事が与える戦略的示唆")
        selected_title = st.selectbox("詳細を分析する記事を選択してください", options=df_display["title"].tolist())
        
        if selected_title:
            if selected_title in st.session_state["insight_cache"]:
                st.markdown(st.session_state["insight_cache"][selected_title])
            else:
                with st.spinner("AIが戦略的示唆を生成中..."):
                    try:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        model = genai.GenerativeModel("gemini-2.5-flash-lite")
                        
                        deep_prompt = f"対象業界: フィットネス業界・健康経営・BtoBウェルネス\n対象役割: マネジメント層\n記事: {selected_title}\n\nこのニュースを踏まえ、今後与える影響や戦略的示唆を3点、それぞれ2文程度で提示してください。"
                        response = model.generate_content(deep_prompt)
                        insight_text = response.text
                        st.session_state["insight_cache"][selected_title] = insight_text
                        st.markdown(insight_text)
                    except Exception as e:
                        st.error(f"Gemini APIの設定を確認してください: {e}")
else:
    st.info("まだ自動蓄積データ（archive_app.csv）が作成されていません。手動テストを実行するか、明日の朝までお待ちください。")
