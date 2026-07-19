"""
agent_graph.py - LangGraph "Düşünen Ajan"
===========================================

KAVRAM: Neden LangGraph?
Normal RAG akışı sabittir: Soru -> Belge Ara -> Cevapla.
Ama belgede cevap yoksa ne olacak? Bot "bulamadım" der ve orada biter.

LangGraph ile akışı bir GRAPH (durum makinesi) olarak kuruyoruz:

    Soru -> [RAG Düğümü] -> Belgede yeterli bilgi var mı?
                              ├─ Evet -> [Sonuçlandır] (bitir)
                              └─ Hayır -> [Web Arama Düğümü] -> [Sonuçlandır] (bitir)

KAVRAM: Conditional Edge (Koşullu Kenar)
Bu, ajanın "karar verme" yeteneği kazandığı yerdir. Sabit bir sıra değil,
bir fonksiyonun (should_search_web) döndürdüğü değere göre iki farklı
yoldan birine dallanıyoruz. Bu "Ajan = Beyin" fikrinin somut hali.
"""

import json
import requests
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, START, END
from ddgs import DDGS
from rag_engine import query_rag

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"


class AgentState(TypedDict):
    question: str
    rag_answer: Optional[str]
    rag_sources: List[dict]
    rag_found: bool
    used_web: bool
    web_answer: Optional[str]
    web_sources: List[str]
    final_answer: str
    trace: List[str]  # Öğretici: ajanın attığı adımların kaydı (UI'da gösterilecek)


def _call_ollama(prompt: str, timeout: int = 120) -> str:
    """Ollama'ya prompt gönderir, düz metin yanıt döner."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=timeout,
        )
        return response.json().get("response", "").strip()
    except Exception as e:
        return f"Ollama Hatasi: {e}"


def _call_ollama_json(prompt: str, timeout: int = 120) -> dict:
    """
    Ollama'ya prompt gönderir, JSON yanıt bekler (format="json").

    KAVRAM: Neden serbest metin yerine JSON?
    3B gibi küçük modeller "tam olarak şu cümleyi yaz" talimatına güvenilir
    şekilde uymuyor — kendi kelimeleriyle yazabiliyor. String arama (örn.
    "bulamadım" geçiyor mu?) bu yüzden kırılgan. format="json" ile modeli
    sabit bir şemaya (örn. {"bulundu": true/false}) zorlarsak, karar düğümü
    metne değil güvenilir bir bool alana bakar. mcp_agent.py'deki
    generate_bug_report() ile aynı teknik.
    """
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            },
            timeout=timeout,
        )
        raw = response.json().get("response", "{}")
        return json.loads(raw)
    except Exception:
        return {}


def rag_node(state: AgentState) -> AgentState:
    """
    DÜĞÜM 1: Önce belgelere bak (RAG = Göz/Hafıza).
    Var olan query_rag() fonksiyonunu tekrar kullanıyoruz — kod tekrarı yok.
    """
    question = state["question"]
    chunks, error = query_rag(question)

    if error and not chunks:
        state["rag_answer"] = None
        state["rag_sources"] = []
        state["trace"] = state["trace"] + [f"RAG: {error}"]
        return state

    context_text = "\n".join(f"[Kaynak: {c['source']}]\n{c['content']}" for c in chunks)

    prompt = f"""Sen bir oyun stüdyosu destek asistanısın.
KURAL: SADECE aşağıdaki belge parçalarına dayan. Uydurma.

BELGE PARÇALARI:
{context_text}

SORU: {question}

JSON formatında yanıt ver:
{{"bulundu": true veya false, "yanit": "..."}}

- "bulundu": Belge parçalarında bu soruyu cevaplayacak bilgi varsa true, yoksa false.
- "yanit": bulundu=true ise belgeye dayalı Türkçe yanıt; bulundu=false ise kısaca "Belgelerde bu konuda bilgi bulamadım." yaz."""

    result = _call_ollama_json(prompt)

    found = bool(result.get("bulundu", False))
    answer = result.get("yanit") or "Belgelerde bu konuda bilgi bulamadım."

    state["rag_answer"] = answer
    state["rag_sources"] = chunks
    state["rag_found"] = found
    state["trace"] = state["trace"] + [
        f"RAG: {len(chunks)} parça bulundu, model kararı: {'yeterli' if found else 'yetersiz'}"
    ]
    return state


def should_search_web(state: AgentState) -> str:
    """
    KARAR DÜĞÜMÜ (Conditional Edge): Ajanın "beyin" kısmı.
    RAG düğümünün ürettiği "bulundu" bayrağına göre dallanır —
    metin araması değil, yapılandırılmış bir karar.
    """
    if state.get("rag_found"):
        return "finalize"
    return "web_search"


def web_search_node(state: AgentState) -> AgentState:
    """
    DÜĞÜM 2: Belgede yoksa dış dünyaya çık (MCP'nin ruhu — DuckDuckGo ile).
    """
    question = state["question"]
    state["used_web"] = True

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(question, max_results=4))
    except Exception as e:
        results = []
        state["trace"] = state["trace"] + [f"Web arama hatasi: {e}"]

    if not results:
        state["web_answer"] = "Web'de de ilgili bilgi bulunamadı."
        state["web_sources"] = []
        state["trace"] = state["trace"] + ["Web: sonuç yok"]
        return state

    web_context = "\n".join(f"- {r.get('title', '')}: {r.get('body', '')}" for r in results)
    web_sources = [r.get("href", "") for r in results if r.get("href")]

    prompt = f"""Aşağıda '{question}' sorusu için web arama sonuçları var.
Bu sonuçlara dayanarak kısa, Türkçe bir yanıt yaz. Uydurma, sadece verilen bilgiyi özetle.

WEB SONUÇLARI:
{web_context}

YANIT:"""

    answer = _call_ollama(prompt)

    state["web_answer"] = answer
    state["web_sources"] = web_sources
    state["trace"] = state["trace"] + [f"Web: {len(results)} sonuç bulundu, yanıt üretildi"]
    return state


def finalize_node(state: AgentState) -> AgentState:
    """
    DÜĞÜM 3: Sonucu birleştir. Kullanıcıya hangi kaynaktan geldiğini şeffafça göster
    — RAG'ın "Sıfır Hallüsinasyon" ilkesi burada da korunuyor.
    """
    if state.get("used_web"):
        state["final_answer"] = (
            f"🌐 **Web'den bulundu** (belgelerde bilgi yoktu):\n\n{state.get('web_answer', '')}"
        )
    else:
        state["final_answer"] = f"📄 **Belgelerden yanıtlandı:**\n\n{state.get('rag_answer', '')}"

    state["trace"] = state["trace"] + ["Finalize: yanıt kullanıcıya hazırlandı"]
    return state


def build_agent_graph():
    """
    KAVRAM: StateGraph
    Düğümleri (node) ve aralarındaki geçiş kurallarını (edge) tanımlıyoruz.
    add_conditional_edges = "karar noktası": should_search_web fonksiyonunun
    dönüşüne göre farklı düğümlere dallanılır.
    """
    graph = StateGraph(AgentState)

    graph.add_node("rag", rag_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "rag")
    graph.add_conditional_edges(
        "rag",
        should_search_web,
        {"web_search": "web_search", "finalize": "finalize"},
    )
    graph.add_edge("web_search", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


def run_agent(question: str) -> AgentState:
    """Dışarıya açık tek fonksiyon: soru al, tam ajan akışını çalıştır, sonucu döndür."""
    app = build_agent_graph()
    initial_state: AgentState = {
        "question": question,
        "rag_answer": None,
        "rag_sources": [],
        "rag_found": False,
        "used_web": False,
        "web_answer": None,
        "web_sources": [],
        "final_answer": "",
        "trace": [],
    }
    return app.invoke(initial_state)


if __name__ == "__main__":
    # Terminalden hızlı test: python agent_graph.py "soru buraya"
    import sys

    q = " ".join(sys.argv[1:]) or "Oyunun çıkış tarihi nedir?"
    print(f"\nSORU: {q}\n")
    result = run_agent(q)
    print("--- İZ (trace) ---")
    for step in result["trace"]:
        print(f"  - {step}")
    print("\n--- SONUÇ ---")
    print(result["final_answer"])
