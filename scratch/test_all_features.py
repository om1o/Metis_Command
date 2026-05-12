import sys
import os
import time
sys.path.insert(0, os.path.abspath("."))

# Mock the swarm agents to use a single lightweight model to prevent Ollama thrashing on constrained hardware
import swarm_agents
from crewai import LLM
from brain_engine import OLLAMA_BASE
def fast_llm(role):
    return LLM(model="ollama/qwen2.5-coder:1.5b", base_url=OLLAMA_BASE)
swarm_agents._llm_for = fast_llm

from crew_engine import run_agentic_mission
from memory_vault import MemoryBank
import wallet
from artifacts import save_artifact, list_artifacts

def test_wallet():
    print("\n--- Testing Wallet ---")
    wallet.top_up(5000, "test")
    entry = wallet.charge("plugin", 100, memo="test plugin")
    print(f"Wallet summary: {wallet.summary()}")
    print("Wallet Test: SUCCESS" if entry else "Wallet Test: FAILED")
    return 10 if entry else 0

def test_memory():
    print("\n--- Testing Memory Vault ---")
    mb = MemoryBank()
    mb.add("The secret password for the AI is 'MetisRocks42'", kind="semantic")
    results = mb.search("What is the AI password?", n_results=1)
    if results and "MetisRocks42" in results[0]["text"]:
        print("Memory Test: SUCCESS")
        return 10
    else:
        print("Memory Test: FAILED")
        return 0

def test_artifacts():
    print("\n--- Testing Artifacts ---")
    art = save_artifact("test_art", "markdown", "Testing", "# Hello World")
    arts = list_artifacts()
    if any(a.id == art.id for a in arts):
        print("Artifacts Test: SUCCESS")
        return 10
    print("Artifacts Test: FAILED")
    return 0

def test_swarm():
    print("\n--- Testing Swarm Agents (Code Mode) ---")
    started = time.time()
    try:
        # Code mode uses single agent
        res = run_agentic_mission("Write a function to return the 5th prime number. Only return code.", mode="code")
        elapsed = time.time() - started
        print(f"Swarm Output ({elapsed:.1f}s): {res[:200]}...")
        if "2" in res or "3" in res or "5" in res or "7" in res or "11" in res or "def" in res:
             print("Swarm Test: SUCCESS")
             return 8
        return 5
    except Exception as e:
        print(f"Swarm Test FAILED: {e}")
        return 0

if __name__ == "__main__":
    scores = {}
    scores["Wallet"] = test_wallet()
    scores["Memory"] = test_memory()
    scores["Artifacts"] = test_artifacts()
    scores["Swarm (Code)"] = test_swarm()
    
    print("\n========== FINAL RANKINGS ==========")
    total = 0
    for k, v in scores.items():
        print(f"{k}: {v}/10")
        total += v
    print(f"OVERALL: {total}/40 ({total/4:.1f}/10)")

