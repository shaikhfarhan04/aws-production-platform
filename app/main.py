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
