from ..tool import Tool
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

class WebSearchTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "WebSearch"
        self.description = "Search information on the internet"

        self.arguments = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string"
                },
                "limit": {
                    "type": "integer",
                    "default": 10
                }
            },
            "required": ["query"]
        }

    def execute(self, args):
        query = args["query"]
        limit = args.get("limit", 10)

        try:
            url = (
                "https://html.duckduckgo.com/html/?q="
                + quote(query)
            )

            headers = {
                "User-Agent": (
                    "Mozilla/5.0"
                )
            }

            response = requests.get(
                url,
                headers=headers,
                timeout=15,
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            results = []

            for result in soup.select(
                ".result"
            )[:limit]:

                title_el = result.select_one(
                    ".result__title"
                )

                link_el = result.select_one(
                    ".result__url"
                )

                snippet_el = result.select_one(
                    ".result__snippet"
                )

                results.append({
                    "title": (
                        title_el.get_text(
                            " ",
                            strip=True,
                        )
                        if title_el
                        else ""
                    ),
                    "url": (
                        link_el.get_text(
                            strip=True
                        )
                        if link_el
                        else ""
                    ),
                    "snippet": (
                        snippet_el.get_text(
                            " ",
                            strip=True,
                        )
                        if snippet_el
                        else ""
                    ),
                })

            return {
                "query": query,
                "count": len(results),
                "results": results,
            }

        except Exception as e:
            return {
                "error": str(e),
                "query": query,
            }
class WebVisitTool(Tool):
    def __init__(self):
        super().__init__()

        self.name = "WebVisit"
        self.description = "Visit a web page and return its content or main text"

        self.arguments = {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string"
                },
                "text_only": {
                    "type": "boolean",
                    "default": True
                }
            },
            "required": ["url"]
        }

    def execute(self, args):
        url = args["url"]
        text_only = args.get("text_only", True)

        try:
            headers = {
                "User-Agent": "Mozilla/5.0"
            }

            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            if text_only:
                soup = BeautifulSoup(response.text, "html.parser")
                for script_or_style in soup(["script", "style"]):
                    script_or_style.decompose()
                text = soup.get_text(separator="\n", strip=True)
                return {
                    "url": url,
                    "content": text
                }
            else:
                return {
                    "url": url,
                    "content": response.text
                }

        except Exception as e:
            return {
                "error": str(e),
                "url": url
            }