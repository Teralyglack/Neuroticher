import aiohttp
import json
import logging
import os
import uuid
import base64
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()


class OpenAIAPI:

    def __init__(self):
        # Загрузка данных для GigaChat
        self.client_id: Optional[str] = os.getenv("GIGACHAT_CLIENT_ID")
        self.client_secret: Optional[str] = os.getenv("GIGACHAT_CLIENT_SECRET")
        self.access_token: Optional[str] = None
        self.token_expires: Optional[datetime] = None

        self.base_url = "https://gigachat.devices.sberbank.ru/api/v1"
        self.auth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

        # Модель GigaChat
        self.model = os.getenv("GIGACHAT_MODEL", "GigaChat")

        if not (self.client_id and self.client_secret):
            logging.warning("GigaChat credentials not found. Some features will be disabled.")

        self.conversation_history: Dict[int, List[Dict[str, str]]] = {}

        self.developer_prompt = {
            "role": "system",
            "content": (
                "Ты — профессиональный репетитор английского языка для русскоговорящих студентов. "
                "Пиши дружелюбно и по делу.\n\n"
                "ВАЖНО (Telegram HTML):\n"
                "- Используй только теги <b>, <i>, <code> (без Markdown).\n"
                "- Не используй ссылки и другие HTML-теги.\n"
                "- Давай примеры и короткие правила."
            ),
        }

    async def _get_access_token(self) -> Optional[str]:
        """Получение access token для GigaChat API с OAuth"""
        if not self.client_id or not self.client_secret:
            logging.error("GigaChat credentials are missing")
            return None

        # Проверяем, есть ли действующий токен
        if self.access_token and self.token_expires and self.token_expires > datetime.now():
            return self.access_token

        try:
            async with aiohttp.ClientSession() as session:
                # Создаем уникальный RqUID
                rquid = str(uuid.uuid4())

                # Кодируем client_id:client_secret в base64
                auth_string = f"{self.client_id}:{self.client_secret}"
                auth_bytes = auth_string.encode('ascii')
                base64_auth = base64.b64encode(auth_bytes).decode('ascii')

                headers = {
                    'Authorization': f'Basic {base64_auth}',
                    'RqUID': rquid,
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Accept': 'application/json'
                }

                data = {
                    'scope': 'GIGACHAT_API_PERS'
                }

                logging.info(f"Requesting GigaChat token with RqUID: {rquid}")

                async with session.post(
                        self.auth_url,
                        headers=headers,
                        data=data,
                        ssl=False  # Для тестов, в проде нужно использовать True с сертификатами
                ) as response:
                    response_text = await response.text()
                    logging.info(f"GigaChat auth response: {response.status}")

                    if response.status == 200:
                        result = json.loads(response_text)
                        self.access_token = result.get('access_token')
                        expires_in = result.get('expires_in', 1800)
                        self.token_expires = datetime.now() + timedelta(seconds=expires_in)

                        if self.access_token:
                            logging.info(f"Successfully obtained GigaChat token, expires in {expires_in} seconds")
                            return self.access_token
                        else:
                            logging.error("No access_token in response")
                            return None
                    else:
                        logging.error(f"GigaChat auth error {response.status}: {response_text}")
                        return None

        except Exception as e:
            logging.error(f"GigaChat auth exception: {e}")
            return None

    def _get_conversation(self, user_id: int) -> List[Dict[str, str]]:
        """Получение истории диалога для пользователя"""
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = [self.developer_prompt]
        return self.conversation_history[user_id]

    async def _call_gigachat_api(self, messages: List[Dict[str, str]], temperature: float = 0.7,
                                 max_tokens: int = 900) -> Optional[str]:
        """Вызов GigaChat API"""
        access_token = await self._get_access_token()
        if not access_token:
            logging.error("No access token available")
            return None

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'stream': False
        }

        logging.info(f"Calling GigaChat API with model: {self.model}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                        ssl=False,
                        timeout=30
                ) as response:
                    response_text = await response.text()

                    if response.status == 200:
                        result = json.loads(response_text)
                        choices = result.get('choices', [])
                        if choices:
                            message = choices[0].get('message', {})
                            content = message.get('content', '').strip()
                            logging.info(f"GigaChat API success, response length: {len(content)}")
                            return content
                        else:
                            logging.error(f"No choices in GigaChat response: {result}")
                            return None
                    else:
                        logging.error(f"GigaChat API error {response.status}: {response_text}")
                        return None

        except Exception as e:
            logging.error(f"GigaChat API exception: {e}")
            return None

    async def ask_question(self, user_id: int, question: str) -> str:
        """Задать вопрос AI"""
        if not self.client_id or not self.client_secret:
            return "⚠️ GigaChat не настроен. Добавьте GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET в .env"

        conversation = self._get_conversation(user_id)

        # Ограничиваем историю диалога
        if len(conversation) > 10:
            conversation = [conversation[0]] + conversation[-9:]

        # Добавляем новый вопрос
        conversation.append({"role": "user", "content": question})

        try:
            answer = await self._call_gigachat_api(conversation)
            if answer:
                # Добавляем ответ в историю
                conversation.append({"role": "assistant", "content": answer})
                self.conversation_history[user_id] = conversation
                return answer
            else:
                return "⚠️ Не удалось получить ответ от GigaChat. Попробуйте позже."
        except Exception as e:
            logging.error(f"GigaChat ask_question error: {e}")
            return "⚠️ AI временно недоступен. Проверьте настройки GigaChat."

    async def check_homework(self, text: str) -> str:
        """Проверка домашнего задания"""
        if not self.client_id or not self.client_secret:
            return "⚠️ GigaChat не настроен. Добавьте GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET в .env"

        prompt = (
            "Проверь текст по английскому и дай обратную связь на русском.\n\n"
            "Структура:\n"
            "1) 🎯 <b>ОБЩАЯ ОЦЕНКА</b> (0-10)\n"
            "2) 🔧 <b>ОШИБКИ И ИСПРАВЛЕНИЯ</b> (<code>Grammar</code>/<code>Vocabulary</code>/<code>Punctuation</code>/<code>Style</code>)\n"
            "3) ✨ <b>УЛУЧШЕННАЯ ВЕРСИЯ</b>\n"
            "4) 💡 <b>РЕКОМЕНДАЦИИ</b> (3-5 пунктов)\n\n"
            f"Текст для проверки:\n{text}"
        )

        messages = [
            {"role": "system", "content": "Ты — строгий, но доброжелательный преподаватель английского."},
            {"role": "user", "content": prompt},
        ]

        try:
            answer = await self._call_gigachat_api(messages, temperature=0.3, max_tokens=1400)
            return answer or "⚠️ Не удалось проверить текст. Попробуйте позже."
        except Exception as e:
            logging.error(f"GigaChat check_homework error: {e}")
            return "⚠️ Не удалось проверить текст. Проверьте настройки GigaChat."

    async def generate_exercise_structured(
            self,
            topic: str,
            level: str,
            exercise_type: str,
            weak_areas: Optional[List[str]] = None,
            difficulty: float = 0.5,
    ) -> Dict[str, Any]:
        """Генерация структурированного упражнения"""
        if not self.client_id or not self.client_secret:
            return self._fallback_exercise(topic, level, exercise_type)

        weak = ""
        if weak_areas:
            weak = f"Учти слабые места ученика: {', '.join(weak_areas)}.\n"

        # Преобразуем тип упражнения в понятный формат
        type_map = {
            "grammar": "грамматическое упражнение",
            "vocab": "упражнение на словарный запас",
            "translate": "упражнение на перевод с русского на английский"
        }

        exercise_type_desc = type_map.get(exercise_type, "упражнение")

        prompt = (
            f"Создай {exercise_type_desc} по английскому языку.\n\n"
            f"Тема: {topic}\n"
            f"Уровень: {level}\n"
            f"Сложность: {difficulty}/1.0\n"
            f"{weak}"
            "Формат ответа должен быть строго в следующем JSON формате:\n"
            "{\n"
            '  "title": "Заголовок упражнения",\n'
            '  "instruction": "Инструкция для ученика",\n'
            '  "question": "Текст задания",\n'
            '  "correct_answer": "Правильный ответ",\n'
            '  "explanation": "Краткое объяснение почему это правильный ответ",\n'
            '  "tips": ["Подсказка 1", "Подсказка 2", "Подсказка 3"]\n'
            "}\n\n"
            "Ответ должен содержать только JSON, без дополнительного текста."
        )

        messages = [
            {"role": "system",
             "content": "Ты — преподаватель английского. Твоя задача — создавать учебные упражнения. Отвечай ТОЛЬКО в формате JSON как указано выше."},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self._call_gigachat_api(messages, temperature=0.7, max_tokens=900)
            if not response:
                return self._fallback_exercise(topic, level, exercise_type)

            # Очищаем ответ от лишних символов
            response = response.strip()

            # Удаляем markdown обратные кавычки если есть
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]

            response = response.strip()

            try:
                ex = json.loads(response)

                # Проверяем обязательные поля
                required_fields = ["title", "instruction", "question", "correct_answer"]
                for field in required_fields:
                    if field not in ex:
                        ex[field] = f"Missing {field}"

                # Нормализуем tips
                if "tips" not in ex or not isinstance(ex["tips"], list):
                    ex["tips"] = []

                # Добавляем explanation если его нет
                if "explanation" not in ex:
                    ex["explanation"] = ""

                logging.info(f"Successfully parsed exercise: {ex['title']}")
                return ex

            except json.JSONDecodeError as je:
                logging.error(f"JSON decode error: {je}")
                logging.error(f"Response was: {response}")
                return self._fallback_exercise(topic, level, exercise_type)

        except Exception as e:
            logging.error(f"GigaChat generate_exercise error: {e}")
            return self._fallback_exercise(topic, level, exercise_type)

    def clear_conversation(self, user_id: int) -> bool:
        """Очистка истории диалога"""
        if user_id in self.conversation_history:
            self.conversation_history[user_id] = [self.developer_prompt]
            return True
        return False

    def _fallback_exercise(self, topic: str, level: str, exercise_type: str) -> Dict[str, Any]:
        """Резервные упражнения на случай недоступности API"""
        logging.info(f"Using fallback exercise for {exercise_type}")

        if exercise_type == "translate":
            return {
                "title": "Перевод RU→EN",
                "instruction": "Переведи на английский. Ответ одной строкой.",
                "question": "Я изучаю английский каждый день, потому что хочу говорить свободно.",
                "correct_answer": "I study English every day because I want to speak fluently.",
                "explanation": "Present Simple для регулярных действий; because вводит причину.",
                "tips": ["Проверь порядок слов: S + V + ...", "Проверь орфографию"],
            }
        if exercise_type == "vocab":
            return {
                "title": "Словарь",
                "instruction": "Выбери правильный вариант. Ответ — буква A/B/C.",
                "question": "Choose the correct word:\nI ____ a cup of tea every morning.\nA) do\nB) drink\nC) play",
                "correct_answer": "B",
                "explanation": "С напитками используем <code>drink</code>.",
                "tips": ["Сначала определи часть речи", "Вспомни устойчивые сочетания"],
            }
        return {
            "title": "Грамматика",
            "instruction": "Заполни пропуск. Ответ одной строкой.",
            "question": "She ____ to school every day. (go)",
            "correct_answer": "goes",
            "explanation": "В Present Simple с he/she/it добавляем -s/-es.",
            "tips": ["he/she/it → +s/-es", "Проверь орфографию (go → goes)"],
        }
