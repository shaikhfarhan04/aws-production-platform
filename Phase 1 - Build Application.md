Yes. We'll build **Phase 1 from scratch**, but in a way that will plug cleanly into the later AWS/EKS phases.

We'll use this stack:

```text
FastAPI
   │
   ├── PostgreSQL
   │
   └── Redis

Docker Compose
   │
   ├── app
   ├── postgres
   └── redis

pytest
   │
   └── automated tests
```

## Phase 1 target

By the end, you will have:

```text
aws-production-platform/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   └── redis_client.py
│
├── tests/
│   └── test_app.py
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .dockerignore
├── .gitignore
└── README.md
```

And these endpoints:

```text
GET  /health
GET  /api/v1/products
POST /api/v1/products
GET  /api/v1/products/{id}
```

We'll also verify:

```text
FastAPI  → PostgreSQL
FastAPI  → Redis
Docker    → FastAPI
Docker    → PostgreSQL
Docker    → Redis
pytest    → application
```

---

# Step 1 — Create the project

Since you're using Linux/VS Code now, open a terminal and run:

```bash
mkdir -p aws-production-platform
cd aws-production-platform

mkdir -p app tests
touch app/__init__.py
touch app/main.py
touch app/database.py
touch app/models.py
touch app/schemas.py
touch app/redis_client.py
touch tests/test_app.py

touch Dockerfile
touch docker-compose.yml
touch requirements.txt
touch .dockerignore
touch .gitignore
touch README.md
```

Check it:

```bash
tree
```

You should see:

```text
aws-production-platform
├── app
│   ├── __init__.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   ├── redis_client.py
│   └── schemas.py
├── tests
│   └── test_app.py
├── .dockerignore
├── .gitignore
├── Dockerfile
├── README.md
├── docker-compose.yml
└── requirements.txt
```

---

# Step 2 — Create Python virtual environment

```bash
python3 -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

You should see:

```text
(venv)
```

Verify:

```bash
python --version
pip --version
```

---

# Step 3 — Create `requirements.txt`

Put this in `requirements.txt`:

```text
fastapi
uvicorn[standard]
sqlalchemy
psycopg2-binary
redis
pydantic
pydantic-settings
pytest
httpx
```

Then install:

```bash
pip install -r requirements.txt
```

Verify:

```bash
pip list
```

---

# Step 4 — Database configuration

Create `app/database.py`:

```python
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://appuser:apppassword@localhost:5432/appdb",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
```

This gives us the abstraction we'll later connect to **Amazon RDS PostgreSQL**.

---

# Step 5 — Create the Product model

Create `app/models.py`:

```python
from sqlalchemy import Column, Integer, Numeric, String

from .database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
```

Our database table will become:

```text
products
--------------------------------
id
name
description
price
```

---

# Step 6 — Create Pydantic schemas

Create `app/schemas.py`:

```python
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ProductCreate(BaseModel):
    name: str
    description: str | None = None
    price: Decimal


class ProductResponse(ProductCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)
```

This separates:

```text
API request
     ↓
Pydantic schema
     ↓
SQLAlchemy model
     ↓
PostgreSQL
```

---

# Step 7 — Redis

Create `app/redis_client.py`:

```python
import os

import redis


REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379/0",
)

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)


def check_redis() -> bool:
    try:
        return redis_client.ping()
    except redis.RedisError:
        return False
```

Later this will become:

```text
FastAPI
   ↓
ElastiCache Redis
```

without needing to rewrite the application architecture.

---

# Step 8 — FastAPI application

Create `app/main.py`:

```python
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Product
from .redis_client import check_redis
from .schemas import ProductCreate, ProductResponse


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AWS Production Platform API",
    version="1.0.0",
)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "api",
        "redis": check_redis(),
    }


@app.get(
    "/api/v1/products",
    response_model=list[ProductResponse],
)
def get_products(db: Session = Depends(get_db)):
    return db.query(Product).all()


@app.post(
    "/api/v1/products",
    response_model=ProductResponse,
    status_code=201,
)
def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
):
    db_product = Product(
        name=product.name,
        description=product.description,
        price=product.price,
    )

    db.add(db_product)
    db.commit()
    db.refresh(db_product)

    return db_product


@app.get(
    "/api/v1/products/{product_id}",
    response_model=ProductResponse,
)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    return product
```

---

# Step 9 — Test locally first

Before Docker, we'll make sure the application itself works.

For local testing, you'll need PostgreSQL and Redis running.

If you already have them installed:

```bash
sudo systemctl start postgresql
sudo systemctl start redis-server
```

Create the database/user if necessary:

```bash
sudo -u postgres psql
```

Then:

```sql
CREATE USER appuser WITH PASSWORD 'apppassword';
CREATE DATABASE appdb OWNER appuser;
\q
```

Start Redis:

```bash
redis-cli ping
```

Expected:

```text
PONG
```

---

# Step 10 — Start FastAPI

From the project root:

```bash
uvicorn app.main:app --reload
```

You should get something similar to:

```text
Uvicorn running on http://127.0.0.1:8000
```

Open:

```text
http://127.0.0.1:8000/docs
```

FastAPI should display Swagger UI.

Test:

```text
GET /health
```

Expected:

```json
{
  "status": "healthy",
  "service": "api",
  "redis": true
}
```

---

# Step 11 — Create a product

From Swagger, call:

```text
POST /api/v1/products
```

with:

```json
{
  "name": "AWS DevOps Course",
  "description": "Production DevOps training",
  "price": 4999.00
}
```

Expected response:

```json
{
  "name": "AWS DevOps Course",
  "description": "Production DevOps training",
  "price": 4999.00,
  "id": 1
}
```

Then:

```text
GET /api/v1/products
```

should return the product.

---

# Step 12 — Dockerize it

Now we'll move from:

```text
Python
PostgreSQL
Redis
```

to:

```text
Docker Compose
├── api
├── postgres
└── redis
```

Create `Dockerfile`:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

# Step 13 — Docker Compose

Create `docker-compose.yml`:

```yaml
services:

  api:
    build: .
    container_name: aws-platform-api
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://appuser:apppassword@postgres:5432/appdb
      REDIS_URL: redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    image: postgres:16
    container_name: aws-platform-postgres
    environment:
      POSTGRES_USER: appuser
      POSTGRES_PASSWORD: apppassword
      POSTGRES_DB: appdb
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U appuser -d appdb"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: aws-platform-redis
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  postgres_data:
  redis_data:
```

Now the application no longer depends on PostgreSQL or Redis being installed directly on your machine.

---

# Step 14 — Build and run

Stop the local Uvicorn process first.

Then:

```bash
docker compose up --build
```

Check containers:

```bash
docker compose ps
```

We want:

```text
NAME                    STATUS
aws-platform-api        running
aws-platform-postgres   running
aws-platform-redis      running
```

Test:

```bash
curl http://localhost:8000/health
```

Expected:

```json
{
  "status": "healthy",
  "service": "api",
  "redis": true
}
```

---

# Step 15 — Test PostgreSQL through the API

Create a product:

```bash
curl -X POST http://localhost:8000/api/v1/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Docker Course",
    "description": "Hands-on Docker training",
    "price": 2999.00
  }'
```

Then:

```bash
curl http://localhost:8000/api/v1/products
```

---

# Step 16 — Verify Redis

Run:

```bash
docker exec -it aws-platform-redis redis-cli ping
```

Expected:

```text
PONG
```

This proves:

```text
FastAPI
   |
   +---- PostgreSQL
   |
   +---- Redis
```

is working inside Docker.

---

# Step 17 — Pytest

Now create `tests/test_app.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_get_products():
    response = client.get("/api/v1/products")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_create_product():
    payload = {
        "name": "Test Product",
        "description": "Created by pytest",
        "price": 100.00,
    }

    response = client.post(
        "/api/v1/products",
        json=payload,
    )

    assert response.status_code == 201

    data = response.json()

    assert data["name"] == "Test Product"
    assert data["price"] == 100.0
```

Run:

```bash
pytest -v
```

Our target is:

```text
3 passed
```

---

# Step 18 — `.gitignore`

Create:

```text
venv/
__pycache__/
.pytest_cache/
*.pyc
.env
.git/
.idea/
.vscode/
```

Do **not** commit passwords or AWS credentials.

---

# Step 19 — `.dockerignore`

```text
venv/
__pycache__/
.pytest_cache/
.git/
.github/
.env
tests/
README.md
```

---

# Step 20 — Phase 1 validation

When we're done, we'll run:

```bash
pytest -v
```

```bash
docker compose build
```

```bash
docker compose up -d
```

```bash
docker compose ps
```

```bash
curl http://localhost:8000/health
```

```bash
curl http://localhost:8000/api/v1/products
```

and:

```bash
docker compose down
```

The final architecture for Phase 1 is:

```text
                 Developer
                     |
                     v
               FastAPI API
                     |
            ┌────────┴────────┐
            │                 │
            v                 v
       PostgreSQL           Redis
            │                 │
            └──── Docker ─────┘
                     |
                Docker Compose
                     |
                   pytest
```

**Don't move to Phase 2 yet.** First build these files and run the validation commands. If anything fails, paste the **exact terminal output** here and we'll fix it before proceeding.
