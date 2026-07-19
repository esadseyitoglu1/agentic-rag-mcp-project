"""
trello_mcp_server.py - Kendi MCP Sunucumuz (FastMCP)
========================================================

KAVRAM: Bu dosya çalıştırıldığında gerçek bir "MCP server" olur.
Client (agent), bizimle stdio (standart giriş/çıkış) üzerinden JSON-RPC
protokolüyle konuşup hangi tool'ların var olduğunu SORAR — client
tarafında hiçbir tool listesi veya açıklaması elle yazılmaz, otomatik keşfedilir.

@mcp.tool() dekoratörünün altındaki her fonksiyonda:
- Docstring  → tool açıklaması olur (LLM bunu okuyup ne zaman çağıracağına karar verir)
- Type hint  → parametre şeması olur

Fark: mcp_agent.py'deki create_trello_card() sadece Python içinden import
edilip çağrılabilir. Buradaki create_bug_card() ise HERHANGİ bir MCP-uyumlu
istemci tarafından (bizim ajanımız, Claude Desktop, başka bir framework...)
otomatik keşfedilip çağrılabilir — MCP'nin standardizasyon vaadi tam olarak bu.
"""

import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp_agent import create_trello_card as _create_trello_card
from rag_engine import query_rag

load_dotenv(override=True)

mcp = FastMCP("HiyelStudiosTrelloServer")


@mcp.tool()
def create_bug_card(title: str, description: str, priority: str = "ORTA") -> str:
    """
    Hiyel Studios'un Trello bug tracker panosuna yeni bir bug kartı açar.

    Args:
        title: Bug'ın kısa başlığı (örn. "Patron savaşında donma").
        description: Bug'ın detaylı açıklaması.
        priority: "KRİTİK", "ORTA" veya "DÜŞÜK" — kartın rengini ve sırasını belirler.
    """
    api_key = os.environ.get("TRELLO_API_KEY", "")
    token = os.environ.get("TRELLO_TOKEN", "")
    
    if priority == "KRİTİK":
        list_id = os.environ.get("TRELLO_LIST_ID_KRITIK", "")
    elif priority == "ORTA":
        list_id = os.environ.get("TRELLO_LIST_ID_ORTA", "")
    else:
        list_id = os.environ.get("TRELLO_LIST_ID_DUSUK", "")

    if not all([api_key, token, list_id]):
        return "HATA: TRELLO_API_KEY / TRELLO_TOKEN / veya ilgili liste ID .env dosyasında eksik."

    bug_info = {"bug_adi": title, "aciklama": description, "oncelik": priority, "etki": ""}
    cluster = {"severity": priority, "count": 1, "sources": ["mcp_agent"], "members": [description]}

    try:
        card_url, _ = _create_trello_card(api_key, token, list_id, bug_info, cluster)
        return f"Trello kartı oluşturuldu: {card_url}"
    except Exception as e:
        return f"Trello hatası: {e}"


@mcp.tool()
def score_bug_priority(bug_description: str) -> str:
    """
    Bir bug açıklamasını 0-100 arası öncelik skoruna çevirir.
    Kritiklik (crash/donma/veri kaybı), belgelerdeki yaygınlık ve etkilenen
    bölüme göre KRİTİK/ORTA/DÜŞÜK önceliği hesaplar. Trello'ya kart açmadan
    ÖNCE bu aracı çağırıp doğru "priority" değerini belirlemek gerekir.
    """
    bug_lower = bug_description.lower()
    score = 0
    reasoning = []

    crash_keywords = ["crash", "çökü", "kapanıyor", "açılmıyor", "hata", "error", "exception"]
    freeze_keywords = ["donuyor", "freeze", "takılı", "kilitlendi", "hang"]
    data_loss_keywords = ["kayıt", "save", "progress", "ilerleme", "sıfırlandı"]
    visual_keywords = ["grafik", "görsel", "titriyor", "fps", "visual", "texture"]

    if any(k in bug_lower for k in crash_keywords):
        score += 40; reasoning.append("Oyunu tamamen çökertiyor (+40)")
    elif any(k in bug_lower for k in data_loss_keywords):
        score += 35; reasoning.append("Kayıt/ilerleme kaybı (+35)")
    elif any(k in bug_lower for k in freeze_keywords):
        score += 30; reasoning.append("Oyunu donduruyor (+30)")
    elif any(k in bug_lower for k in visual_keywords):
        score += 10; reasoning.append("Görsel/performans sorunu (+10)")
    else:
        score += 5; reasoning.append("Genel sorun (+5)")

    try:
        chunks, _ = query_rag(bug_description, n_results=5)
        hit_count = len(chunks) if chunks else 0
        freq_score = min(hit_count * 6, 30)
        score += freq_score
        reasoning.append(f"Belgede {hit_count} ilgili kayıt bulundu (+{freq_score})")
    except Exception:
        reasoning.append("Yaygınlık hesaplanamadı (+0)")

    boss_keywords = ["patron", "boss", "son bölüm", "final", "bölüm 5", "bölüm 4"]
    mid_keywords = ["bölüm 3", "bölüm 2", "kristal", "tapınak"]
    early_keywords = ["bölüm 1", "başlangıç", "giriş", "tutorial"]

    if any(k in bug_lower for k in boss_keywords):
        score += 20; reasoning.append("Patron/son bölüm etkileniyor (+20)")
    elif any(k in bug_lower for k in mid_keywords):
        score += 12; reasoning.append("Orta bölümler etkileniyor (+12)")
    elif any(k in bug_lower for k in early_keywords):
        score += 5; reasoning.append("Erken bölüm etkileniyor (+5)")
    else:
        score += 8; reasoning.append("Bölüm belirsiz (+8)")

    if score >= 70:
        priority = "KRİTİK"
    elif score >= 40:
        priority = "ORTA"
    else:
        priority = "DÜŞÜK"

    return (
        f"SKOR: {score}/100 | ÖNCELİK: {priority}\n" +
        "\n".join(f"- {r}" for r in reasoning)
    )


if __name__ == "__main__":
    mcp.run()  # stdio transport (varsayılan) — client bizi bir alt-process olarak başlatır
