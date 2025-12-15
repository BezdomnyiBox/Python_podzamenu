from sentence_transformers import SentenceTransformer
from fastapi import FastAPI
from pydantic import BaseModel
import numpy as np
import re

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

app = FastAPI()

# Инициализация интентов с несколькими вариантами для лучшей классификации
INTENTS = {
    "DELIVERY": [
        model.encode("Вопрос о доставке через транспортную компанию"),
        model.encode("Когда доставят заказ"),
        model.encode("Отследить доставку"),
        model.encode("Отследить доставку заказа"),
        model.encode("Трек номер доставки"),
        model.encode("Статус доставки заказа"),
        model.encode("Где находится заказ в пути"),
        model.encode("Транспортная компания доставка"),
        model.encode("Отслеживание посылки"),
        model.encode("Где мой заказ в доставке"),
        model.encode("Трек номер"),
        model.encode("Отследить посылку"),
    ],
    "ORDER_INFO": [
        model.encode("Вопрос о заказе общая информация"),
        model.encode("Статус заказа"),
        model.encode("Информация о заказе"),
        model.encode("Хочу узнать про заказ"),
        model.encode("Мой заказ информация"),
        model.encode("Проверить заказ"),
        model.encode("Детали заказа"),
        model.encode("Информация о моем заказе"),
    ],
}

def cosine(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def extract_order_number(text: str) -> str | None:
    """Извлекает номер заказа из текста (форматы: #123, заказ 123, номер 123 и т.д.)"""
    # Паттерны для поиска номера заказа
    patterns = [
        r'#(\d+)',  # #123
        r'заказ[а\s]+(?:№|номер)?\s*(\d+)',  # заказ №123, заказ 123
        r'номер[а\s]+(?:заказа)?\s*(\d+)',  # номер заказа 123
        r'заказ[а\s]+(\d+)',  # заказ 123
        r'(\d{4,})',  # длинные числа (4+ цифры) могут быть номерами заказов
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    
    return None

class TextRequest(BaseModel):
    text: str

@app.post("/classify")
def classify(request: TextRequest):
    text = request.text
    emb = model.encode(text)

    best_intent = None
    best_score = 0

    # Для каждого интента берем максимальный score среди всех его вариантов
    for intent, intent_embeddings in INTENTS.items():
        # Если это список эмбеддингов, берем максимальный score
        if isinstance(intent_embeddings, list):
            max_score = max(cosine(emb, intent_emb) for intent_emb in intent_embeddings)
        else:
            max_score = cosine(emb, intent_embeddings)
        
        if max_score > best_score:
            best_score = max_score
            best_intent = intent

    # Извлекаем номер заказа, если он есть в тексте
    order_number = extract_order_number(text)
    
    response = {
        "intent": best_intent,
        "confidence": float(best_score)
    }
    
    # Если определен интент ORDER_INFO или найден номер заказа, добавляем его в ответ
    if order_number:
        response["order_number"] = order_number
    
    return response
