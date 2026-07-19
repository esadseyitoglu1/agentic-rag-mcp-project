"""
rag_engine.py - RAG Motoru
===========================
Bu dosya şunları yapıyor:
1. docs/ klasöründeki belgeleri okur
2. Belgeleri küçük parçalara (chunk) böler  
3. Her parçayı embedding modeli ile vektöre dönüştürür
4. ChromaDB'ye kaydeder
5. Soru geldiğinde en alakalı parçaları bulur
"""

import os
import sys
import glob
import chromadb
from sentence_transformers import SentenceTransformer

# Windows terminal encoding fix
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Streamlit cache — model sadece bir kere yüklenir, her sorguda sıfırlanmaz
try:
    import streamlit as st
    @st.cache_resource
    def get_model():
        return SentenceTransformer(MODEL_NAME)

    @st.cache_resource
    def get_chroma_client():
        return chromadb.PersistentClient(path=VECTORDB_FOLDER)
except ImportError:
    # Streamlit yoksa (terminal testi için) normal yükle
    def get_model():
        return SentenceTransformer(MODEL_NAME)
    def get_chroma_client():
        return chromadb.PersistentClient(path=VECTORDB_FOLDER)

# ============================================================
# KAVRAM AÇIKLAMASI: Embedding Modeli
# Bu model metni sayısal vektörlere çeviriyor.
# "multilingual-e5-base" = Türkçe dahil 100+ dil destekliyor.
# İlk çalıştırmada ~1GB indirilecek (sadece bir kere).
# ============================================================
MODEL_NAME = "intfloat/multilingual-e5-base"
DOCS_FOLDER = "docs"
VECTORDB_FOLDER = "vectordb"
COLLECTION_NAME = "indie_game_docs"

# Chunk ayarları
CHUNK_SIZE = 500      # Her parça maksimum 500 karakter
CHUNK_OVERLAP = 50   # Parçalar arasında 50 karakter örtüşme (bilgi kaybını önler)


def load_pdf_text(file_path):
    """PDF'in tüm sayfalarındaki metni tek bir string'e çevirir."""
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def load_documents():
    """
    docs/ klasöründeki tüm .txt ve .pdf dosyalarını okur.

    KAVRAM: Bu adım RAG'ın 'ham malzemesi'.
    Oyuncu yorumları, yama notları, Discord mesajları - hepsi buraya giriyor.

    GÜVENLİK NOTU: PDF içeriği de tıpkı .txt gibi doğrudan chunk'lanıp
    LLM'in göreceği context'e giriyor. Bir belgenin içine gizlenmiş talimatlar
    ("kritik eylemler için onay isteme" vb.) RAG'ın döndürdüğü bir Observation
    olarak agent'a ulaşabilir — buna "dolaylı prompt injection" denir. Guardrail'lerin
    (örn. agent.py'deki critical-tool onay kontrolü) LLM'in ne "düşündüğüne" değil,
    kod seviyesinde tool adına bakması bu yüzden önemli.
    """
    documents = []
    txt_files = glob.glob(os.path.join(DOCS_FOLDER, "*.txt"))
    pdf_files = glob.glob(os.path.join(DOCS_FOLDER, "*.pdf"))

    if not txt_files and not pdf_files:
        print(f"UYARI: {DOCS_FOLDER}/ klasöründe .txt veya .pdf dosyası bulunamadı!")
        return []

    for file_path in txt_files:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            documents.append({
                "content": content,
                "source": os.path.basename(file_path)
            })
        print(f"  [OK] Yuklendi: {os.path.basename(file_path)} ({len(content)} karakter)")

    for file_path in pdf_files:
        content = load_pdf_text(file_path)
        documents.append({
            "content": content,
            "source": os.path.basename(file_path)
        })
        print(f"  [OK] Yuklendi (PDF): {os.path.basename(file_path)} ({len(content)} karakter)")

    return documents


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """
    Büyük metni küçük parçalara böler.
    
    KAVRAM: Chunking (Parçalama)
    Neden parçalıyoruz?
    - Embedding modelleri çok uzun metni bir seferde işleyemiyor
    - Küçük parçalar = daha hassas eşleştirme
    - Overlap = parçalar arasında bilgi kopukluğu olmasın
    
    Örnek (chunk_size=10, overlap=3):
    Metin: "ABCDEFGHIJ"
    Parça 1: "ABCDEFGHIJ"  (0-10)
    Parça 2: "HIJKLM..."   (7-17) ← 3 karakter örtüşüyor
    """
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        
        if chunk.strip():  # Boş parçaları atlıyoruz
            chunks.append(chunk)
        
        start = end - overlap  # Overlap uygula
    
    return chunks


def build_index():
    """
    Tüm belgeleri indeksler: okur → parçalar → vektöre çevirir → kaydeder.
    
    Bu fonksiyon yavaş ama sadece bir kere çalıştırılır.
    Sonraki sorgularda ChromaDB'den direkt çekiyoruz.
    """
    print("\n" + "="*50)
    print("RAG İNDEKSLEME BAŞLIYOR")
    print("="*50)
    
    # Adım 1: Belgeleri yükle
    print("\n[1/4] Belgeler yükleniyor...")
    documents = load_documents()
    
    if not documents:
        return False
    
    # Adım 2: ChromaDB bağlantısı
    # KAVRAM: ChromaDB, vektörleri diskte saklayan yerel veritabanı
    # vectordb/ klasörüne kaydediyor, internet gerekmez
    print(f"\n[2/4] ChromaDB başlatılıyor ({VECTORDB_FOLDER}/)...")
    client = chromadb.PersistentClient(path=VECTORDB_FOLDER)
    
    # Eski koleksiyonu temizle (yeniden indeksleme için)
    try:
        client.delete_collection(COLLECTION_NAME)
        print("  Eski indeks temizlendi.")
    except Exception:
        pass
    
    collection = client.create_collection(name=COLLECTION_NAME)
    
    # Adım 3: Embedding modeli yükle (cache'den gelir, ilk seferden sonra anında)
    print(f"\n[3/4] Embedding modeli yukleniyor: {MODEL_NAME}")
    print("  (Ilk seferde ~1GB indiriliyor, bu normal...)")
    model = get_model()
    print("  [OK] Model hazir!")
    
    # Adım 4: Belgeleri parçala ve vektöre çevir
    print("\n[4/4] Belgeler işleniyor ve vektöre dönüştürülüyor...")
    
    all_chunks = []
    all_ids = []
    all_metadatas = []
    
    for doc in documents:
        chunks = chunk_text(doc["content"])
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc['source']}_chunk_{i}"
            all_chunks.append(chunk)
            all_ids.append(chunk_id)
            all_metadatas.append({"source": doc["source"], "chunk_index": i})
        
        print(f"  [OK] {doc['source']}: {len(chunks)} parca olusturuldu")
    
    # KAVRAM: Embedding = metni sayısal koordinata çevirme
    # Bu satır tüm parçaları aynı anda vektöre çeviriyor
    print(f"\n  Toplam {len(all_chunks)} parça vektöre dönüştürülüyor...")
    
    # multilingual-e5 için "query: " veya "passage: " prefix gerekiyor
    # Belgeler için "passage: " prefix kullanıyoruz
    prefixed_chunks = [f"passage: {chunk}" for chunk in all_chunks]
    embeddings = model.encode(prefixed_chunks, show_progress_bar=True)
    
    # ChromaDB'ye kaydet
    collection.add(
        documents=all_chunks,
        embeddings=embeddings.tolist(),
        ids=all_ids,
        metadatas=all_metadatas
    )
    
    print(f"\n[TAMAM] INDEKSLEME TAMAMLANDI!")
    print(f"   Toplam {len(all_chunks)} parca ChromaDB'ye kaydedildi.")
    return True


def query_rag(question, n_results=4):
    """
    Kullanıcının sorusuna en alakalı belge parçalarını bulur.
    
    KAVRAM: Retrieval (Geri Çekme)
    1. Soru → embedding → vektör
    2. Bu vektörü ChromaDB'deki vektörlerle karşılaştır
    3. En yakın (cosine similarity) N parçayı getir
    
    KAVRAM: Cosine Similarity (Kosinüs Benzerliği)
    İki vektörün arasındaki açıyı ölçer.
    Açı küçük = vektörler birbirine yakın = anlamsal olarak benzer
    """
    # ChromaDB baglantisi (cache'den — anında)
    client = get_chroma_client()
    
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        return None, "Hata: Once indeks olusturmaniz gerekiyor! Sol panelden 'Indeksi Olustur' butonuna basin."
    
    # Embedding modeli (cache'den — anında, yeniden yuklenmez)
    model = get_model()
    
    # Soruyu vektöre çevir (soru için "query: " prefix)
    query_embedding = model.encode(f"query: {question}")
    
    # En yakın N parçayı bul
    results = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=n_results
    )
    
    if not results["documents"][0]:
        return [], "Belgeler bulunamadı."
    
    # Sonuçları düzenli formata çevir
    retrieved_chunks = []
    for i, (doc, metadata) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
        retrieved_chunks.append({
            "content": doc,
            "source": metadata["source"],
            "relevance_rank": i + 1
        })
    
    return retrieved_chunks, None


def get_index_stats():
    """Mevcut indeks hakkında bilgi döndürür."""
    try:
        client = chromadb.PersistentClient(path=VECTORDB_FOLDER)
        collection = client.get_collection(COLLECTION_NAME)
        count = collection.count()
        return {"status": "hazır", "chunk_count": count}
    except Exception:
        return {"status": "yok", "chunk_count": 0}
