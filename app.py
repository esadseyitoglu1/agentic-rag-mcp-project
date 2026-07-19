"""
app.py - Streamlit Web Arayüzü
================================
KAVRAM: Streamlit nedir?
Normal Flask/Django gibi web framework değil.
Python kodunu direkt web sayfasına çeviriyor.
Veri bilimciler ve AI geliştiriciler için ideal.
Komut: streamlit run app.py
"""

import asyncio
import os
import glob
from dotenv import load_dotenv

load_dotenv(override=True)

import sys
if 'agent' in sys.modules:
    del sys.modules['agent']
if 'mcp_react_agent' in sys.modules:
    del sys.modules['mcp_react_agent']

# Ajan modülünü en üstte import ediyoruz ki Streamlit değişiklikleri takip edebilsin
from mcp_react_agent import ask_agent_streamlit

import streamlit as st
from rag_engine import get_index_stats

# ============================================================
# SAYFA AYARLARI
# ============================================================
st.set_page_config(
    page_title="🎮 Indie RAG Bot | Hiyel Studios",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# ÖZEL CSS - Premium Görünüm
# ============================================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    * { font-family: 'Inter', sans-serif; }
    
    .stApp {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
        min-height: 100vh;
    }
    
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow: 0 20px 60px rgba(102, 126, 234, 0.4);
    }
    
    .main-header h1 {
        color: white;
        font-size: 2.5rem;
        font-weight: 700;
        margin: 0;
        text-shadow: 0 2px 10px rgba(0,0,0,0.3);
    }
    
    .main-header p {
        color: rgba(255,255,255,0.85);
        font-size: 1.1rem;
        margin-top: 0.5rem;
    }
    
    .answer-box {
        background: linear-gradient(135deg, rgba(102, 126, 234, 0.15), rgba(118, 75, 162, 0.15));
        border: 1px solid rgba(102, 126, 234, 0.4);
        border-radius: 16px;
        padding: 1.5rem;
        margin: 1rem 0;
        backdrop-filter: blur(10px);
    }
    
    .source-card {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 1rem;
        margin: 0.5rem 0;
        border-left: 3px solid #667eea;
    }
    
    .source-card .source-name {
        color: #a78bfa;
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 0.3rem;
    }
    
    .stat-badge {
        background: rgba(102, 126, 234, 0.2);
        border: 1px solid rgba(102, 126, 234, 0.4);
        border-radius: 8px;
        padding: 0.5rem 1rem;
        color: #a78bfa;
        font-weight: 600;
    }
    
    .rule-box {
        background: rgba(34, 197, 94, 0.1);
        border: 1px solid rgba(34, 197, 94, 0.3);
        border-radius: 12px;
        padding: 1rem;
        margin: 1rem 0;
    }
    
    .stButton > button {
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.7rem 2rem;
        font-weight: 600;
        font-size: 1rem;
        width: 100%;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(102, 126, 234, 0.6);
    }
    
    div[data-testid="stTextInput"] input {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(102, 126, 234, 0.4);
        border-radius: 10px;
        color: white;
    }
    
    .chat-user {
        background: rgba(102, 126, 234, 0.2);
        border-radius: 16px 16px 4px 16px;
        padding: 1rem 1.5rem;
        margin: 0.5rem 0;
        margin-left: 20%;
        color: white;
    }
    
    .chat-bot {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 16px 16px 16px 4px;
        padding: 1rem 1.5rem;
        margin: 0.5rem 0;
        margin-right: 20%;
        color: rgba(255,255,255,0.9);
    }
    
    .hallucination-warning {
        background: rgba(239, 68, 68, 0.1);
        border: 1px solid rgba(239, 68, 68, 0.3);
        border-radius: 12px;
        padding: 0.8rem 1rem;
        color: #fca5a5;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# SESSION STATE - Sohbet geçmişi için
# ============================================================
if "messages" not in st.session_state:
    st.session_state.messages = []


# ============================================================
# SIDEBAR - Ayarlar ve Kontroller
# ============================================================
with st.sidebar:
    st.markdown("## ⚙️ Ayarlar")


    
    # İndeks Durumu
    st.markdown("### 📊 İndeks Durumu")
    stats = get_index_stats()
    
    if stats["status"] == "hazır":
        st.markdown(f"""
        <div class="stat-badge">
            ✅ İndeks Hazır<br>
            📄 {stats['chunk_count']} parça yüklü
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning("⚠️ İndeks henüz oluşturulmadı!")
    
    st.markdown("---")
    

    
    # Kritik Kural Kutusu
    st.markdown("### 📜 Kritik Kural")
    st.markdown("""
    <div class="rule-box">
        <strong>✅ Sıfır Hallüsinasyon</strong><br>
        Bot yalnızca yüklü belgelerden yanıt üretir. 
        Belgede yoksa: <em>"Belgelerde bu konuda bilgi bulamadım"</em> der.
    </div>
    """, unsafe_allow_html=True)
    
    # Yüklü Belgeler
    st.markdown("### 📁 Yüklü Belgeler")
    docs = glob.glob("docs/*.txt") + glob.glob("docs/*.pdf")
    for doc in docs:
        st.markdown(f"📄 `{os.path.basename(doc)}`")

    if not docs:
        st.warning("docs/ klasörü boş!")

    # Sohbeti Temizle
    st.markdown("---")
    if st.button("🗑️ Sohbeti Temizle", key="clear_chat"):
        st.session_state["agent_history"] = []
        st.session_state["pending_action"] = None
        st.rerun()

    # Örnek Sorular — tıklanınca aşağıdaki görev kutusuna yazılır
    st.markdown("### 💡 Örnek Sorular")
    example_questions = [
        "Patron savaşında oyun neden donuyor?",
        "Checkpoint sorunu çözüldü mü?",
        "Oyuncuların en çok şikayet ettiği hatalar neler?",
        "v1.3'te neler gelecek?",
        "Ses sorunu nasıl düzeltilir?",
        "FPS düşük, ne yapmalıyım?",
    ]
    for q in example_questions:
        if st.button(f"❓ {q[:40]}...", key=f"ex_{q[:20]}"):
            st.session_state["agent_command_input"] = q
            st.rerun()


# ============================================================
# ANA İÇERİK ALANI
# ============================================================

# Başlık
st.markdown("""
<div class="main-header">
    <h1>🎮 Indie RAG Bot</h1>
    <p>Hiyel Studios | Oyuncu Geri Bildirim Analiz Sistemi</p>
    <p style="font-size: 0.9rem; opacity: 0.7;">
        Yama notları • Steam yorumları • Discord mesajları • SSS belgelerini analiz eder
    </p>
</div>
""", unsafe_allow_html=True)

# ============================================================
# SİSTEM ÖZETİ — Sunumda hocaya göstermek için: teknolojiler + özellikler
# ============================================================
col_tech, col_feat = st.columns(2)

with col_tech:
    st.markdown("### 🛠️ Kullanılan Teknolojiler")
    st.markdown("""
    <div class="rule-box">

    - **RAG:** ChromaDB (vektör DB) + `intfloat/multilingual-e5-base` (embedding)
    - **LLM:** Google Gemini (`gemini-flash-latest`)
    - **Ajan Çatısı:** LangGraph (`create_react_agent`, `StateGraph`)
    - **MCP:** Model Context Protocol — FastMCP sunucu, stdio/JSON-RPC
    - **Web Arama:** DuckDuckGo (`ddgs`)
    - **Dış Entegrasyon:** Trello API
    - **Belge Formatları:** `.txt` + `.pdf` (`pypdf`)
    - **Arayüz:** Streamlit

    </div>
    """, unsafe_allow_html=True)

with col_feat:
    st.markdown("### ✅ Kullanılan Özellikler")
    st.markdown("""
    <div class="rule-box">

    - ✅ **2+ Tool (web dahil):** rag_search, web_search, bug_priority_scorer,
      community_mood_radar, create_trello_card + MCP tool'ları
    - ✅ **Kendi yazdığımız tool:** bug_priority_scorer, community_mood_radar
      (LLM/API yok, saf Python algoritma)
    - ✅ **Follow-up:** konuşma geçmişi bağlam olarak modele veriliyor
    - ✅ **Chat UI:** `st.chat_message` tabanlı sohbet arayüzü
    - ✅ **Guardrail:** max iterasyon limiti, kritik eylem onayı, loglama
    - ✅ **Thinking:** Thought → Action → Observation izi şeffaf gösteriliyor
    - ✅ **MCP:** gerçek protokol, otomatik tool keşfi (elle tanım yok)

    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# Nasıl Çalışır - Kısa Açıklama
with st.expander("🎓 Bu otonom sistem nasıl çalışıyor? (RAG + Ajan + MCP)"):
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        **1️⃣ RAG (Bilgi Tabanı)**
        
        Steam yorumları, yama notları, Discord mesajları ve SSS dosyaları vektörlere (sayısal koordinatlara) çevrilip veritabanına kaydedildi. 
        Ajanımız, soruları cevaplamadan önce bu lokal belleğe danışır (Sıfır Hallüsinasyon kuralı).
        """)
    
    with col2:
        st.markdown("""
        **2️⃣ LangGraph Ajanı & Araçlar**
        
        Sistem sadece metin üreten bir "Chatbot" değildir. İçinde **Groq (Llama 3 70B)** barındıran Otonom bir Kalite Kontrol Yöneticisidir. 
        Topluluk Ruh Hali Radarı, Web Arama, RAG Arama ve Öncelik Skorlayıcı gibi kendi geliştirdiğimiz lokal araçlara (Tools) sahiptir.
        """)
    
    with col3:
        st.markdown("""
        **3️⃣ Gerçek MCP Entegrasyonu**
        
        Ajanımız *Model Context Protocol (stdio/JSON-RPC)* kullanarak kendi lokal sınırlarının dışına çıkar.
        Kritik bir hata tespit ettiğinde, inisiyatif alarak harici Trello MCP sunucusuna bağlanır ve şirketin veri tabanına doğrudan Bug Kartı açar.
        """)

st.markdown("---")






# ============================================================
# AJAN — Birleşik Görev Arayüzü (Klasik ReAct + Gerçek MCP)
# ============================================================
st.markdown("---")
st.markdown("## 🤖 Otonom Ajan (Gerçek MCP)")

allow_trello_action = st.checkbox(
    "⚠️ Ajanın inisiyatif alıp otomatik Trello kartı açmasına izin ver",
    value=True,
    key="mcp_allow_trello"
)

# Ajan Session State Yönetimi
if "agent_history" not in st.session_state:
    st.session_state["agent_history"] = []

# Geçmiş mesajları göster
for msg in st.session_state["agent_history"]:
    with st.chat_message(msg["role"]):
        badge = "🔌 "
        st.markdown(f"{badge}{msg['content']}" if msg["role"] == "assistant" else msg["content"])

        if msg.get("trace"):
            with st.expander("🧠 Düşünme Süreci (Trace)", expanded=False):
                for step in msg["trace"]:
                    if step["type"] == "thought":
                        st.markdown(f"🤔 **Düşünce:** {step['content']}")
                    elif step["type"] == "action":
                        st.markdown(f"🛠️ **Araç Kullanımı:** `{step['content']}`")
                    elif step["type"] == "observation":
                        obs_text = step["content"]
                        if len(obs_text) > 1000:
                            st.markdown(f"👁️ **Gözlem:** _{obs_text[:1000]}..._ (kısaltıldı)")
                        else:
                            st.markdown(f"👁️ **Gözlem:** \n{obs_text}")

# Tek görev girişi
col_input, col_btn = st.columns([5, 1])
with col_input:
    agent_prompt = st.text_input(
        "Ajana Görev Ver",
        placeholder="Örn: 'Patron savaşındaki donma bugını değerlendir'",
        key="agent_command_input",
        label_visibility="collapsed"
    )
with col_btn:
    run_agent_btn = st.button("🚀 Gönder", key="run_agent_submit", use_container_width=True)

if run_agent_btn and agent_prompt:
    prompt = agent_prompt
    st.session_state["agent_history"].append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    groq_key = os.environ.get("GROQ_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not groq_key and not gemini_key:
        st.error("Lütfen .env dosyasına GEMINI_API_KEY (veya GROQ_API_KEY) girin.")
        st.stop()

    with st.chat_message("assistant"):
        with st.spinner("🔌 Otonom Ajan Düşünüyor..."):
            try:
                mcp_answer, mcp_tools, mcp_trace = asyncio.run(
                    ask_agent_streamlit(prompt, allow_trello=allow_trello_action, groq_key=groq_key, history=st.session_state["agent_history"][:-1])
                )
            except Exception as e:
                mcp_answer, mcp_tools, mcp_trace = f"MCP Hatası: {e}", [], []

        content = mcp_answer
        if mcp_tools:
            content = f"_Kullanılabilir Otonom Araçlar: {', '.join(mcp_tools)}_\n\n{mcp_answer}"
        if not allow_trello_action:
            content += "\n\n_(Trello izni kapalı olduğu için eyleme geçilemedi.)_"

        st.markdown(content)
        st.session_state["agent_history"].append({
            "role": "assistant", "content": content, "trace": mcp_trace, "mode": "mcp"
        })

    st.rerun()


# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: rgba(255,255,255,0.4); font-size: 0.8rem; padding: 1rem 0;">
    🎮 Hiyel Studios Indie RAG Bot |
    RAG: intfloat/multilingual-e5-base | LLM: Groq (Llama-3.3-70B) |
    DB: ChromaDB (Lokal) | Protokol: Gerçek MCP (stdio/JSON-RPC) + Trello API |
    Otonom QA Yöneticisi Aktif ✅
</div>
""", unsafe_allow_html=True)
