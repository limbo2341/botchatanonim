import aiohttp

from config.settings import settings


class GameSearchService:
    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
    RAWG_URL = "https://api.rawg.io/api/games"

    async def analyze_query(self, user_query: str) -> str:
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key.strip()}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "google/gemma-3-27b-it:free",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты AI для поиска игр. "
                        "Из описания пользователя выдели вероятное название игры "
                        "или хорошие ключевые слова для поиска. "
                        "Отвечай только коротким поисковым запросом."
                    )
                },
                {
                    "role": "user",
                    "content": user_query
                }
            ]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.OPENROUTER_URL,
                headers=headers,
                json=payload
            ) as response:

                data = await response.json()

                return data["choices"][0]["message"]["content"]

    async def search_game(self, user_query: str):
        optimized_query = await self.analyze_query(user_query)

        params = {
            "key": settings.rawg_api_key.strip(),
            "search": optimized_query,
            "page_size": 5
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                self.RAWG_URL,
                params=params
            ) as response:

                data = await response.json()

                return data.get("results", [])
