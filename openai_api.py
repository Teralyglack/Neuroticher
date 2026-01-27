import json
import logging
import os
from typing import Any, Dict, List, Optional

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from dotenv import load_dotenv

load_dotenv()

class GigaChatAPI:
    def __init__(self):
        self.api_key = os.getenv("GIGACHAT_API_KEY")
        self.scope = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
        
        if not self.api_key:
            logging.warning("GigaChat API key not found!")
            self.client = None
            return
        
        try:
            self.client = GigaChat(
                credentials=self.api_key,
                scope=self.scope,
                model="GigaChat",  # или "GigaChat-Pro"
                verify_ssl_certs=False
            )
            logging.info("✅ GigaChat client initialized successfully")
        except Exception as e:
            logging.error(f"❌ Failed to initialize GigaChat: {e}")
            self.client = None
        
        # История диалогов
        self.conversation_history: Dict[int, List[Messages]] = {}
        
        # Системный промпт для репетитора
        self.system_prompt = Messages(
            role=MessagesRole.SYSTEM,
            content=(
                "Ты — профессиональный репетитор английского языка для русскоговорящих студентов. "
                "Ты дружелюбный, терпеливый и мотивирующий. "
                "Объясняй понятно, с примерами и практическими советами.\n\n"
                "Форматирование для Telegram:\n"
                "- Используй <b>жирный текст</b> для важных правил\n"
                "- Используй <i>курсив</i> для примеров\n"
                "- Используй <code>код</code> для слов/словосочетаний\n"
                "- Давай примеры после каждого правила\n"
                "- Будь лаконичным, но информативным"
            )
        )
    
    def _get_conversation(self, user_id: int) -> List[Messages]:
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = [self.system_prompt]
        return self.conversation_history[user_id]
    
    async def ask_question(self, user_id: int, question: str) -> str:
        """Задать вопрос нейросети"""
        if not self.client:
            return "⚠️ GigaChat не настроен. Проверьте API ключ в .env"
        
        try:
            conversation = self._get_conversation(user_id)
            
            # Добавляем вопрос пользователя
            conversation.append(Messages(
                role=MessagesRole.USER,
                content=question
            ))
            
            # Ограничиваем историю
            if len(conversation) > 10:
                conversation = [conversation[0]] + conversation[-9:]
            
            # Создаём чат
            chat = Chat(
                messages=conversation,
                temperature=0.7,
                max_tokens=1500
            )
            
            # Отправляем запрос
            response = await self.client.achat(chat)
            answer = response.choices[0].message.content
            
            # Сохраняем ответ в историю
            conversation.append(Messages(
                role=MessagesRole.ASSISTANT,
                content=answer
            ))
            
            self.conversation_history[user_id] = conversation
            return answer
            
        except Exception as e:
            logging.error(f"GigaChat error: {e}")
            return f"⚠️ Ошибка GigaChat: {str(e)[:100]}..."
    
    async def explain_topic(self, topic: str) -> str:
        """Объяснить тему"""
        if not self.client:
            return "⚠️ GigaChat не настроен"
        
        prompt = f"""Объясни тему по английскому языку: {topic}

Структура:
1. <b>Простое определение</b> (одним предложением)
2. <b>Когда используется</b> (3-5 случаев с примерами)
3. <b>Как образуется</b> (формула и примеры)
4. <b>Частые ошибки</b> и как их избежать
5. <b>Мини-упражнение</b> (вопрос без ответа для самопроверки)

Будь дружелюбным и мотивирующим!"""
        
        try:
            chat = Chat(
                messages=[
                    Messages(role=MessagesRole.SYSTEM, 
                            content="Ты — опытный репетитор английского."),
                    Messages(role=MessagesRole.USER, content=prompt)
                ],
                temperature=0.6,
                max_tokens=1800
            )
            
            response = await self.client.achat(chat)
            return response.choices[0].message.content
            
        except Exception as e:
            logging.error(f"GigaChat explain error: {e}")
            return f"⚠️ Не удалось объяснить тему '{topic}'"

    # ... добавьте другие методы из openai_api.py (check_homework, generate_exercise и т.д.)

    def clear_conversation(self, user_id: int) -> bool:
        if user_id in self.conversation_history:
            self.conversation_history[user_id] = [self.system_prompt]
            return True
        return False

# Быстрый тест
if __name__ == "__main__":
    import asyncio
    async def test():
        gpt = GigaChatAPI()
        result = await gpt.ask_question(123, "Привет! Объясни Present Simple")
        print(result[:200])
    
    asyncio.run(test())