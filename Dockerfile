FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what the server imports. Data files (branded.db, food_db.csv) stay
# out: food data comes from Supabase at request time.
COPY app.py parse_recipe.py recipe_matcher.py supabase_food_source.py boosts.json ./

# Cloud Run sets PORT; 8080 is the local default.
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
