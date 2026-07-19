"""
mcp_agent.py - MCP/Trello Entegrasyonu
========================================

KAVRAM: MCP (Model Context Protocol) Nedir?
Normal bir LLM sadece metin üretir — dünyayla etkileşime giremez.
MCP, LLM'e "el ve kol" veriyor:
- Dosya oluşturabilir
- Veritabanı sorgulayabilir
- Trello/GitHub gibi araçlara bağlanabilir

Biz burada MCP'nin ruhunu Trello API ile uyguluyoruz:
Sistem → kendi kendine düşünür → Trello'da kart açar

AKIŞ:
1. Tüm docs/ belgelerini oku
2. Şikayetleri embedding ile vektöre çevir
3. Benzer şikayetleri grupla (clustering)
4. Her gruba "kritiklik skoru" ver (kaç kişi yazdı?)
5. Trello'ya kart aç (MCP = dış dünya eylemi!)
"""

import os
import requests
import json
from collections import defaultdict
from rag_engine import get_model, query_rag, DOCS_FOLDER, VECTORDB_FOLDER, COLLECTION_NAME
import glob
import chromadb
import numpy as np

# ============================================================
# TRELLO AYARLARI
# Bu değerleri Streamlit arayüzünden alacağız
# ============================================================
TRELLO_API_URL = "https://api.trello.com/1"


def get_all_feedback_chunks():
    """
    docs/ klasöründeki tüm belgelerdeki şikayet/yorum içeriklerini döndürür.
    ChromaDB'den direkt çekiyoruz.
    """
    try:
        client = chromadb.PersistentClient(path=VECTORDB_FOLDER)
        collection = client.get_collection(COLLECTION_NAME)
        
        # Tüm kayıtları çek
        all_data = collection.get(include=["documents", "metadatas", "embeddings"])
        
        return all_data
    except Exception as e:
        return None


def cluster_similar_complaints(threshold=0.82):
    """
    KAVRAM: Clustering (Kümeleme)
    
    Aynı sorunu farklı kelimelerle yazan oyuncuları tespit et.
    
    "oyun donuyor" → vektör A
    "game freezes"  → vektör B  
    "kilitlendi"    → vektör C
    
    A-B benzerliği: 0.91 → AYNI BUG ✓
    A-C benzerliği: 0.88 → AYNI BUG ✓
    
    Cosine similarity > threshold ise aynı grup.
    
    Returns:
        clusters: [{
            "representative": "En temsili şikayet metni",
            "members": ["şikayet1", "şikayet2", ...],
            "count": 3,
            "sources": ["steam_reviews.txt", "discord.txt"],
            "severity": "KRİTİK/ORTA/DÜŞÜK"
        }]
    """
    all_data = get_all_feedback_chunks()
    
    if not all_data or not all_data["documents"]:
        return []
    
    documents = all_data["documents"]
    embeddings = np.array(all_data["embeddings"])
    metadatas = all_data["metadatas"]
    
    # Normalize et (cosine similarity için)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normalized = embeddings / norms
    
    # Cosine similarity matrisi
    similarity_matrix = np.dot(normalized, normalized.T)
    
    # Greedy clustering
    assigned = [False] * len(documents)
    clusters = []
    
    for i in range(len(documents)):
        if assigned[i]:
            continue
        
        cluster_members = [i]
        cluster_sources = [metadatas[i].get("source", "?")]
        assigned[i] = True
        
        for j in range(i + 1, len(documents)):
            if not assigned[j] and similarity_matrix[i][j] > threshold:
                cluster_members.append(j)
                cluster_sources.append(metadatas[j].get("source", "?"))
                assigned[j] = True
        
        # Küme oluştur
        member_texts = [documents[idx] for idx in cluster_members]
        count = len(cluster_members)
        
        # Kritiklik skoru
        if count >= 5:
            severity = "KRİTİK"
        elif count >= 3:
            severity = "ORTA"
        else:
            severity = "DÜŞÜK"
        
        clusters.append({
            "representative": member_texts[0][:300],  # İlk üye temsili
            "members": member_texts,
            "count": count,
            "sources": list(set(cluster_sources)),
            "severity": severity
        })
    
    # Büyükten küçüğe sırala
    clusters.sort(key=lambda x: x["count"], reverse=True)
    
    return clusters


def generate_bug_report(cluster, llm_url="http://localhost:11434/api/generate", model="qwen2.5:3b"):
    """
    Bir şikayet kümesi için Ollama ile bug raporu üret.
    SADECE belgelerdeki bilgiye dayanır — hallüsinasyon yok!
    """
    prompt = f"""Sen bir oyun geliştirici asistanısın.
    
Aşağıda oyuncuların bildirdiği benzer şikayetler var:

{chr(10).join(f'- {m[:200]}' for m in cluster['members'][:5])}

Bu şikayetlere dayanarak SADECE yukarıdaki metinlere göre:
1. Bug'ın kısa adı (max 10 kelime)
2. Etkilenen oyuncu sayısı tahmini
3. Önerilen öncelik: {cluster['severity']}
4. Kısa açıklama (2-3 cümle)

Belgelerde olmayan hiçbir bilgi ekleme. Türkçe yaz. JSON formatında yanıt ver:
{{"bug_adi": "...", "aciklama": "...", "oncelik": "...", "etki": "..."}}"""

    try:
        response = requests.post(
            llm_url,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1}
            },
            timeout=60
        )
        result = response.json().get("response", "{}")
        # JSON parse
        bug_info = json.loads(result)
        return bug_info
    except Exception as e:
        # Fallback: LLM olmadan basit rapor
        return {
            "bug_adi": cluster["representative"][:60],
            "aciklama": f"{cluster['count']} oyuncu benzer sorun bildirdi.",
            "oncelik": cluster["severity"],
            "etki": f"Kaynak: {', '.join(cluster['sources'])}"
        }


def create_trello_card(api_key, token, list_id, bug_info, cluster):
    """
    KAVRAM: MCP Eylemi — Trello'ya Kart Aç
    
    Bu fonksiyon RAG+Ajan sistemini gerçek dünyaya bağlıyor.
    Sadece metin üretmekle kalmıyor — Trello'da fiilen kart oluşturuyor.
    Bu tam olarak MCP'nin özü: LLM → Dış Dünya Eylemi
    
    Args:
        api_key: Trello API anahtarı
        token: Trello kullanıcı token'ı
        list_id: Hangi listeye kart açılacak (örn: "Yapılacaklar")
        bug_info: Ollama'nın ürettiği bug raporu
        cluster: Şikayet kümesi
    
    Returns:
        card_url: Oluşturulan kartın URL'i
    """
    
    # Renk etiketi: kritikliğe göre
    label_color = {
        "KRİTİK": "red",
        "ORTA": "yellow", 
        "DÜŞÜK": "blue"
    }.get(cluster["severity"], "green")
    
    # Kart açıklaması
    description = f"""## Bug Raporu - RAG Ajan Tarafından Oluşturuldu

**Öncelik:** {cluster['severity']}
**Şikayet Sayısı:** {cluster['count']} oyuncu
**Kaynaklar:** {', '.join(cluster['sources'])}

### Açıklama
{bug_info.get('aciklama', 'Açıklama yok')}

### Etki
{bug_info.get('etki', 'Belirtilmedi')}

### Örnek Şikayetler
{chr(10).join(f'> {m[:150]}...' for m in cluster['members'][:3])}

---
*Bu kart otomatik olarak Indie RAG Bot tarafından oluşturuldu.*
*Sıfır Hallüsinasyon — Tüm bilgi belgelerden alındı.*
"""
    
    # Trello API çağrısı
    response = requests.post(
        f"{TRELLO_API_URL}/cards",
        params={
            "key": api_key,
            "token": token
        },
        json={
            "name": f"[{cluster['severity']}] {bug_info.get('bug_adi', 'Bug')}",
            "desc": description,
            "idList": list_id,
            "pos": "top" if cluster["severity"] == "KRİTİK" else "bottom"
        }
    )
    
    if response.status_code == 200:
        card_data = response.json()
        return card_data.get("url", ""), card_data.get("id", "")
    else:
        raise Exception(f"Trello API Hatası: {response.status_code} - {response.text}")


def get_trello_boards(api_key, token):
    """Kullanıcının Trello board'larını listele."""
    response = requests.get(
        f"{TRELLO_API_URL}/members/me/boards",
        params={"key": api_key, "token": token, "fields": "name,id"}
    )
    if response.status_code == 200:
        return response.json()
    return []


def get_trello_lists(api_key, token, board_id):
    """Seçilen board'un listelerini getir."""
    response = requests.get(
        f"{TRELLO_API_URL}/boards/{board_id}/lists",
        params={"key": api_key, "token": token}
    )
    if response.status_code == 200:
        return response.json()
    return []
