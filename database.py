import datetime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Boolean, DateTime, select

engine = create_async_engine("sqlite+aiosqlite:///db.sqlite3", echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(Integer, unique=True)
    username: Mapped[str] = mapped_column(String, nullable=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)

class Item(Base):
    __tablename__ = 'items'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    price: Mapped[int] = mapped_column(Integer)
    available_sizes: Mapped[str] = mapped_column(String, default="S,M,L")
    image_url: Mapped[str] = mapped_column(String) 
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)

class CartItem(Base):
    __tablename__ = 'cart_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(Integer)
    selected_size: Mapped[str] = mapped_column(String, default="M")

class PromoCode(Base):
    __tablename__ = 'promocodes'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    reward: Mapped[int] = mapped_column(Integer)
    is_percent: Mapped[bool] = mapped_column(Boolean, default=False)

class Order(Base):
    __tablename__ = 'orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="Готов к выдаче на ПВЗ")
    items_summary: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

async def populate_db():
    async with async_session() as session:
        result = await session.execute(select(Item))
        if not result.scalars().first():
            # Прямые API ссылки без защиты от ботов - 100% загрузка
            session.add_all([
                Item(title="Кожаная куртка (Женская)", price=500, available_sizes="XS,S,M,L,XL", image_url="https://fakestoreapi.com/img/81XH0e8fefL._AC_UY879_.jpg"),
                Item(title="Дождевик-тренч", price=1200, available_sizes="S,M,XL", image_url="https://fakestoreapi.com/img/71HblAHs5xL._AC_UY879_-2.jpg"),
                Item(title="Хлопковая куртка", price=450, available_sizes="M,L,XL,XXL", image_url="https://fakestoreapi.com/img/71z3kpMAYsL._AC_UY879_.jpg"),
                Item(title="Спортивная футболка", price=900, available_sizes="XS,S,L", image_url="https://fakestoreapi.com/img/51Y5NI-I5jL._AC_UX679_.jpg"),
                Item(title="Рюкзак унисекс (Доп. аксессуар)", price=350, available_sizes="УНИВЕРСАЛЬНЫЙ", image_url="https://fakestoreapi.com/img/81fPKd-2AYL._AC_SL1500_.jpg"),
                Item(title="Повседневная мужская футболка", price=850, available_sizes="S,M,L,XL", image_url="https://fakestoreapi.com/img/71-3HjGNDUL._AC_SY879._SX._UX._SY._UY_.jpg"),
                Item(title="Теплая куртка", price=400, available_sizes="S,M,L", image_url="https://fakestoreapi.com/img/71li-ujtlAL._AC_UX679_.jpg"),
                Item(title="Худи оверсайз", price=400, available_sizes="XS,S,M", image_url="https://fakestoreapi.com/img/71YXzeOuslL._AC_UY879_.jpg"),
                Item(title="Летняя женская блузка", price=450, available_sizes="S,M,L", image_url="https://fakestoreapi.com/img/51eg55uWmdL._AC_UX679_.jpg"),
                Item(title="Свитер тонкой вязки", price=1100, available_sizes="M,L,XL", image_url="https://fakestoreapi.com/img/61pHAEJ4NML._AC_UX679_.jpg")
            ])
            session.add_all([
                PromoCode(code="START2026", reward=1000, is_percent=False),
                PromoCode(code="SALE15", reward=15, is_percent=True)
            ])
            await session.commit()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await populate_db()