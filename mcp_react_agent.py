"""
mcp_react_agent.py - MCP + LangGraph ReAct Agent
===================================================

KAVRAM: Bu dosya, trello_mcp_server.py'yi GERÇEK MCP protokolüyle bir
LangGraph ReAct agent'ına bağlar.

Fark: agent.py'deki ReAct döngüsü elle yazılmış (regex ile Thought/Action
parse ediliyor, tool listesi prompt içine elle yazılmış). Burada:
- create_react_agent() hazır bir LangGraph StateGraph kuruyor
- Tool'ları elle TANIMLAMIYORUZ — MCP server'dan OTOMATIK KEŞFEDİYORUZ
  (load_mcp_tools). trello_mcp_server.py'ye yeni bir @mcp.tool() eklersen,
  bu dosyada TEK SATIR bile değiştirmen gerekmez.

AKIŞ:
1. trello_mcp_server.py'yi bir alt-process olarak başlat (stdio)
2. MCP handshake yap (ClientSession.initialize)
3. Server'ın sunduğu tool'ları keşfet (load_mcp_tools)
4. Bu tool'ları Gemini (gemini-flash-latest) ile bir ReAct agent'a ver
5. Agent'ı çalıştır — gerektiğinde otomatik olarak score_bug_priority
   ve create_bug_card tool'larını çağırır
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import StructuredTool, tool
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI

from agent import (
    tool_web_search, 
    tool_rag_search, 
    tool_community_mood_radar,
    REACT_SYSTEM_PROMPT
)

load_dotenv(override=True)

PROJECT_DIR = Path(__file__).parent

SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,  # şu an çalışan python.exe ile aynı ortam (aynı kurulu paketler)
    args=["trello_mcp_server.py"],
    cwd=str(PROJECT_DIR),
)

# GUARDRAIL: Bu isimdeki tool'lar dış dünyada kalıcı bir eylem yapar
# (Trello'ya gerçek kart açar). Çalışmadan önce insan onayı istenir.
# agent.py'deki AVAILABLE_TOOLS[...]["critical"] alanının MCP karşılığı.
CRITICAL_TOOLS = {"create_bug_card"}
MAX_APPROVAL_ROUNDS = 3  # aynı onay isteği bu kadar tekrarlanırsa döngü durdurulur


def wrap_with_approval(tool: StructuredTool) -> StructuredTool:
    """
    KAVRAM: Human-in-the-loop (İnsan Onayı Döngüsü)

    LLM'e "kart açma" demek yetmiyor (bkz. az önceki test — talimata rağmen
    kart açtı). Bunun yerine kritik tool'u interrupt() ile sarmalıyoruz:
    tool çağrılmadan HEMEN ÖNCE graph'ın yürütmesi durur, çağıran tarafa
    (CLI'da input(), Streamlit'te bir buton) onay sorulur. Onay gelmeden
    gerçek MCP çağrısı asla yapılmaz — karar artık LLM'in insafına değil.
    """
    original_coroutine = tool.coroutine

    async def guarded(**kwargs):
        decision = interrupt({
            "tool": tool.name,
            "args": kwargs,
            "question": f"'{tool.name}' şu parametrelerle çalıştırılmak isteniyor: {kwargs}",
        })
        if str(decision).strip().lower() not in ("evet", "yes", "onay", "onayla", "true"):
            return (
                f"REDDEDİLDİ: Kullanıcı '{tool.name}' eylemini ONAYLAMADI. "
                f"Gerçek tool çalıştırılmadı. BU EYLEMİ TEKRAR DENEME — "
                f"kullanıcıya reddedildiğini bildirip Final Answer ile bitir."
            )
        return await original_coroutine(**kwargs)

    return StructuredTool.from_function(
        coroutine=guarded,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


def _content_to_text(content) -> str:
    """
    LangChain mesaj content'i bazen düz string, bazen content-block listesi
    ([{"type": "text", "text": "..."}]) olarak gelir — hem MCP tool sonuçlarında
    hem Gemini'nin kendi yanıtlarında bu ikinci formatı görüyoruz. İkisini de
    okunabilir tek bir metne indirgeriz.
    """
    if isinstance(content, list):
        return "\n".join(
            block.get("text", str(block)) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _extract_trace(messages: list) -> list[dict]:
    """
    LangGraph'ın create_react_agent'ı sonucundaki mesaj listesini (HumanMessage →
    AIMessage(tool_calls) → ToolMessage → ... → AIMessage) agent.py'deki
    steps formatına (thought/action/observation) çevirir — Otonom Ajan
    bölümündeki "Düşünme Süreci" paneliyle aynı görünüm için.
    """
    trace = []
    for msg in messages:
        msg_type = type(msg).__name__
        if msg_type == "AIMessage":
            if getattr(msg, "content", None):
                trace.append({"type": "thought", "content": _content_to_text(msg.content)})
            for tc in (getattr(msg, "tool_calls", None) or []):
                trace.append({"type": "action", "content": f"{tc['name']}({tc['args']})"})
        elif msg_type == "ToolMessage":
            trace.append({"type": "observation", "content": _content_to_text(msg.content)})
    return trace


@tool
def web_search(query: str) -> str:
    """DuckDuckGo ile internet araması yapar. Güncel bilgiler için kullanın."""
    return tool_web_search(query)

@tool
def rag_search(query: str) -> str:
    """Yerel ChromaDB oyun belgelerinde arama yapar. Yama, hikaye, mekanik, QA prosedürleri ve notları için KESİNLİKLE bu aracı kullanın."""
    return tool_rag_search(query)

@tool
def community_mood_radar(topic: str = "genel") -> str:
    """Tüm discord ve steam yorumlarını analiz edip topluluğun nabzını, en çok şikayet edilen 3 konuyu getirir."""
    return tool_community_mood_radar(topic)

LOCAL_TOOLS = [web_search, rag_search, community_mood_radar]

async def ask_agent_streamlit(question: str, allow_trello: bool, groq_key: str = "", history: list = None) -> tuple[str, list[str], list[dict]]:
    """
    Streamlit gibi tek-turlu ortamlar için basitleştirilmiş sürüm.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not groq_key and not gemini_key:
        return "HATA: GEMINI_API_KEY veya GROQ_API_KEY eksik.", [], []

    if groq_key:
        llm = ChatGroq(model="llama-3.3-70b-versatile", api_key=groq_key, temperature=0.2)
        # KULLANICI İSTEĞİ: Eğer Groq hata verirse (rate limit vb.) otomatik olarak Gemini'ye düş (Fallback)
        if gemini_key:
            gemini_llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", google_api_key=gemini_key, temperature=0.2)
            llm = llm.with_fallbacks([gemini_llm])
    else:
        llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", google_api_key=gemini_key, temperature=0.2)

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            raw_mcp_tools = await load_mcp_tools(session)
            tool_names = [t.name for t in raw_mcp_tools] + [t.name for t in LOCAL_TOOLS]

            if allow_trello:
                mcp_tools = raw_mcp_tools
            else:
                mcp_tools = [t for t in raw_mcp_tools if t.name not in CRITICAL_TOOLS]

            all_tools = mcp_tools + LOCAL_TOOLS

            agent = create_react_agent(llm, all_tools, prompt=REACT_SYSTEM_PROMPT)
            
            # Geçmişi LangChain formatına çevir
            formatted_messages = []
            if history:
                for msg in history:
                    role = msg["role"]
                    content = msg["content"]
                    # Sadece user ve assistant mesajlarını al
                    if role in ("user", "assistant"):
                        formatted_messages.append((role, content))
            
            formatted_messages.append(("user", question))

            try:
                result = await agent.ainvoke({"messages": formatted_messages})
            except Exception:
                # ACİL YEDEK: Gemini/Groq kota/hata verirse yerel Ollama'ya sessizce geç
                # (bulut kotasına bağlı değil — sunum güvenliği için).
                fallback_llm = ChatOllama(model="qwen2.5:3b", temperature=0.2)
                agent = create_react_agent(fallback_llm, all_tools, prompt=REACT_SYSTEM_PROMPT)
                result = await agent.ainvoke({"messages": formatted_messages})

            trace = _extract_trace(result["messages"])
            final_message = result["messages"][-1]
            return _content_to_text(final_message.content), tool_names, trace


async def ask_agent_interactive(question: str, thread_id: str = "cli-session") -> tuple[str, list[str]]:
    """
    Soruyu ReAct agent'a sorar. Kritik bir tool'a denk gelirse CLI üzerinden
    (input() ile) onay ister. (yanıt, keşfedilen_tool_adları) döner.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return "HATA: .env dosyasında GEMINI_API_KEY eksik.", []

    llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", google_api_key=gemini_key, temperature=0.2)
    checkpointer = InMemorySaver()

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            raw_tools = await load_mcp_tools(session)
            tool_names = [t.name for t in raw_tools]
            tools = [
                wrap_with_approval(t) if t.name in CRITICAL_TOOLS else t
                for t in raw_tools
            ]

            agent = create_react_agent(llm, tools, checkpointer=checkpointer)
            config = {"configurable": {"thread_id": thread_id}}

            result = await agent.ainvoke({"messages": [("user", question)]}, config=config)

            # Graph bir interrupt() ile durduysa "__interrupt__" anahtarı döner.
            # GUARDRAIL: LLM ısrarla aynı onayı tekrar isteyebilir — burada da
            # bir iterasyon tavanı var (agent.py'deki MAX_ITERATIONS'ın eşdeğeri).
            for _ in range(MAX_APPROVAL_ROUNDS):
                if not result.get("__interrupt__"):
                    break
                payload = result["__interrupt__"][0].value
                print(f"\n[ONAY GEREKLİ] {payload['question']}")
                answer = input("Onaylıyor musun? (evet/hayır): ")
                result = await agent.ainvoke(Command(resume=answer), config=config)

            final_message = result["messages"][-1]
            return _content_to_text(final_message.content), tool_names


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or (
        "Oyuncular patron savaşında oyunun donduğunu bildiriyor. "
        "Bunu değerlendir ve gerekiyorsa Trello'ya bug kartı aç."
    )
    print(f"\nSORU: {q}\n")
    answer, tool_names = asyncio.run(ask_agent_interactive(q))
    print(f"\n[MCP] Keşfedilen tool'lar: {tool_names}")
    print("\n--- AJAN YANITI ---")
    print(answer)
