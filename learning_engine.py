from dataclasses import dataclass
from typing import Dict, List
import random
import re


@dataclass
class EvaluationResult:
    is_correct: bool
    partial_match: bool
    feedback: str
    normalized_user: str
    normalized_correct: str


class LearningEngine:
    """Логика уровня, проверки ответов и рекомендаций."""

    def __init__(self):
        self.topics = {
            "beginner": ["Present Simple", "To be", "Articles (a/an/the)", "Plural nouns", "Basic pronouns"],
            "intermediate": ["Past Simple", "Present Continuous", "Future Simple", "Comparatives", "Modal verbs"],
            "advanced": ["Present Perfect", "Past Perfect", "Conditionals", "Passive Voice", "Reported Speech"],
        }

    def get_user_level(self, accuracy: float, total_exercises: int) -> str:
        if total_exercises < 10:
            return "beginner"
        if accuracy >= 0.85 and total_exercises >= 50:
            return "advanced"
        if accuracy >= 0.70 and total_exercises >= 20:
            return "intermediate"
        return "beginner"

    def recommend_topics(self, user_level: str, weak_topics: List[str]) -> List[str]:
        if weak_topics:
            return weak_topics[:3]
        return self.topics.get(user_level, self.topics["beginner"])[:5]

    def calculate_difficulty(self, user_stats: Dict) -> float:
        accuracy = float(user_stats.get("accuracy", 0.5) or 0.5)
        total = int(user_stats.get("total_exercises", 0) or 0)

        if total < 5:
            return 0.3
        if accuracy >= 0.9:
            return min(0.9, 0.55 + (total / 120.0))
        if accuracy <= 0.5:
            return max(0.2, 0.45 - (total / 250.0))
        return 0.5

    def normalize_answer(self, text: str) -> str:
        text = (text or "").strip().lower()
        text = re.sub(r"(?!\b\w+'\w+\b)[^\w\s']", " ", text, flags=re.UNICODE)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def evaluate_answer(self, user_answer: str, correct_answer: str) -> EvaluationResult:
        user_clean = self.normalize_answer(user_answer)
        correct_clean = self.normalize_answer(correct_answer)

        is_correct = (user_clean == correct_clean)
        partial = False
        if not is_correct:
            partial = self._check_partial_match(user_clean, correct_clean)

        feedback = self._generate_feedback(is_correct, partial)
        return EvaluationResult(is_correct, partial, feedback, user_clean, correct_clean)

    def _check_partial_match(self, user: str, correct: str) -> bool:
        if not user or not correct:
            return False
        u = set(user.split())
        c = set(correct.split())
        if not c:
            return False
        return (len(u.intersection(c)) / len(c)) >= 0.6

    def _generate_feedback(self, is_correct: bool, partial: bool) -> str:
        if is_correct:
            return random.choice([
                "🎉 Отлично! Так держать!",
                "✅ Правильно! Ты молодец!",
                "🌟 Превосходно! Продолжай!",
                "👏 Браво! Верный ответ!",
            ])
        if partial:
            return random.choice([
                "🤏 Почти! Небольшая неточность — проверь форму/порядок слов.",
                "📝 Хорошая попытка! Подправь детали.",
                "💡 Ты на верном пути — уточни ответ.",
            ])
        return random.choice([
            "❌ Не совсем. Давай разберём и попробуем ещё раз!",
            "🔄 Почти получилось — попробуй снова.",
            "📚 Ничего страшного! Ошибки — часть обучения.",
        ])

    def motivation_message(self, streak_days: int, accuracy: float) -> str:
        if streak_days >= 14:
            return "🔥 Вау! 14+ дней подряд — это железная дисциплина!"
        if streak_days >= 7:
            return "🔥 Огонь! Неделя подряд — супер!"
        if streak_days >= 3:
            return "💪 Отлично! Уже несколько дней подряд!"

        if accuracy >= 0.9:
            return "🌟 Феноменальная точность!"
        if accuracy >= 0.7:
            return "👍 Хорошие результаты — заметный прогресс!"
        return "📈 Каждое упражнение приближает к цели."
