from sentence_transformers import SentenceTransformer
from fastapi import FastAPI
from pydantic import BaseModel
import numpy as np
import re

app = FastAPI()

# Тексты интентов (будем кодировать по требованию)
INTENT_TEXTS = {
    "DELIVERY": [
        "Вопрос о доставке через транспортную компанию",
        "Когда доставят заказ",
        "Отследить доставку",
        "Отследить доставку заказа",
        "Трек номер доставки",
        "Статус доставки заказа",
        "Где находится заказ в пути",
        "Транспортная компания доставка",
        "Отслеживание посылки",
        "Где мой заказ в доставке",
        "Трек номер",
        "Отследить посылку",
    ],
    "ORDER_INFO": [
        "Вопрос о заказе общая информация",
        "Статус заказа",
        "Информация о заказе",
        "Хочу узнать про заказ",
        "Мой заказ информация",
        "Проверить заказ",
        "Детали заказа",
        "Информация о моем заказе",
    ],
}

# Ленивая загрузка модели
_model = None

def get_model():
    """Ленивая загрузка модели - загружается только при первом использовании"""
    global _model
    if _model is None:
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _model

# Кэшированные эмбеддинги интентов
_intent_embeddings = None

def get_intent_embeddings():
    """Ленивая инициализация эмбеддингов интентов"""
    global _intent_embeddings
    if _intent_embeddings is None:
        model = get_model()
        _intent_embeddings = {
            intent: [model.encode(text) for text in texts]
            for intent, texts in INTENT_TEXTS.items()
        }
    return _intent_embeddings

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

@app.get("/test")
def test():
    return {"status": "ok", "message": "Server is working"}

@app.post("/classify")
def classify(request: TextRequest):
    text = request.text
    model = get_model()
    emb = model.encode(text)
    
    intent_embeddings_dict = get_intent_embeddings()

    best_intent = None
    best_score = 0

    # Для каждого интента берем максимальный score среди всех его вариантов
    for intent, intent_embeddings in intent_embeddings_dict.items():
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
