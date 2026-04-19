"""
Custom tools used by the CrewAI swarm.
"""

from crewai.tools import tool
from duckduckgo_search import DDGS


@tool("Internet Search Tool")
def internet_search(query: str) -> str:
    """
    Search the web for the provided query using DuckDuckGo.
    Returns the top 5 results with title, link, and snippet.
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "No results found for your query."
        output = []
        for idx, item in enumerate(results, start=1):
            title = item.get("title", "No title")
            link = item.get("href", item.get("url", "No link"))
            snippet = item.get("body", item.get("snippet", "No description."))
            output.append(
                f"Result {idx}:\nTitle: {title}\nLink: {link}\nSnippet: {snippet}\n"
            )
        return "\n".join(output).strip()
    except Exception as e:
        return f"Error while searching the internet: {e}"
