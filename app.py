import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import os

st.set_page_config(page_title="業界ニュース・インテリジェンス", layout="wide")

if "insight_cache" not in st.session_state:
    st.session_state["insight_cache"] = {}

# サイドバーでの事業本部切り替え
st.sidebar.header("事業本部・視点の選択")
business_segment = st.sidebar.radio(
    "インテリジェンス領域",
    options=["ヘルスケア事業本部 (BtoB・健康経営)", "スポーツクラブ事業本部 (BtoC・店舗ビジネス)"]
)

# 選択されたセグメントに応じて読み込むファイルを切り替え
if "ヘルスケア事業本部" in business_segment:
    archive_file = "archive_app.csv"
    title_prefix = "【ヘルスケア事業（BtoB・健康経営）】"
    context_prompt = "対象業界: フィットネス業界における健康経営ソリューション、BtoBウェルネスビジネス\n対象役割: ヘルスケア事業本部 マネジメント層"
else:
    archive_file = "archive_app_btc.csv"
    title_prefix = "【スポーツクラブ事業（BtoC・店舗ビジネス）】"
    context_prompt = "対象業界: フィットネス業界における総合スポーツクラブ、24時間ジム、BtoC店舗ビジネス\n対象役割: スポーツクラブ事業本部 マネジメント層（組織 inertia の打破、環境適応を目指す視点）"

st.title(f"{title_prefix} ニュース・インテリジェンス（毎朝7時自動更新）")

if os.path.exists(archive_file):
    df = pd.read_csv(archive_file)
    available_dates = sorted(df["date"].dropna().unique().tolist(), reverse=True)
    
    st.sidebar.markdown("---")
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
            cache_key = f"{business_segment}_{selected_title}"
            if cache_key in st.session_state["insight_cache"]:
                st.markdown(st.session_state["insight_cache"][cache_key])
            else:
                with st.spinner("AIが戦略的示唆を生成中..."):
                    try:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        model = genai.GenerativeModel("gemini-2.5-flash-lite")
                        
                        deep_prompt = f"{context_prompt}\n記事: {selected_title}\n\nこのニュースを踏まえ、今後のBtoC市場における競争優位の確立や新業態のヒント、マネジメントとして取るべき戦略的示唆を3点、それぞれ2文程度で提示してください。"
                        response = model.generate_content(deep_prompt)
                        insight_text = response.text
                        st.session_state["insight_cache"][cache_key] = insight_text
                        st.markdown(insight_text)
                    except Exception as e:
                        st.error(f"Gemini APIの設定を確認してください: {e}")
else:
    st.info(f"まだ選択された事業本部の自動蓄積データ（{archive_file}）が作成されていません。GitHub Actionsから手動テストを実行するか、明日の朝までお待ちください。")
