import asyncio
import io
import qrcode
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import CommandStart, Command, StateFilter, CommandObject
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select, delete
from database import init_db, async_session, User, Item, CartItem, PromoCode, Order

TOKEN = "8319864308:AAGn0dJhTbzmMn4vfTvuLMqak4eGhgRTRLA"
GITHUB_PAGES_URL = "https://meedeepdoc.github.io/smartdress-app/"
ADMIN_ID = 2126567606

dp = Dispatcher()

async def is_user_admin(tg_id, session):
    if tg_id == ADMIN_ID: return True
    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    return user.is_admin if user else False

class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user: return await handler(event, data)
            
        async with async_session() as session:
            db_user = await session.scalar(select(User).where(User.tg_id == user.id))
            if not db_user:
                db_user = User(tg_id=user.id, username=user.username)
                session.add(db_user)
                await session.commit()
                
            if db_user.is_banned and user.id != ADMIN_ID:
                if isinstance(event, types.Message):
                    await event.answer("🚫 Ваш аккаунт заблокирован за нарушение правил сервиса.")
                elif isinstance(event, types.CallbackQuery):
                    await event.answer("🚫 Аккаунт заблокирован.", show_alert=True)
                return 
        return await handler(event, data)

dp.message.middleware(BanMiddleware())
dp.callback_query.middleware(BanMiddleware())

class PromoState(StatesGroup):
    waiting_for_promo = State()

class AdminState(StatesGroup):
    waiting_for_item_data = State()
    waiting_for_item_photo = State() 
    waiting_for_edit_sizes = State()
    waiting_for_edit_photo = State() # НОВОЕ: Изменение фото существующего товара
    waiting_for_promo_create = State()
    waiting_for_admin_balance = State()
    waiting_for_ban_id = State()
    waiting_for_unban_id = State()
    waiting_for_admin_grant = State()
    waiting_for_admin_revoke = State()

def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Каталог (Бот)", callback_data="catalog_page_0")],
        [InlineKeyboardButton(text="📱 Витрина (Web App)", web_app=WebAppInfo(url=GITHUB_PAGES_URL))],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🛍 Корзина", callback_data="cart")],
        [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")]
    ])

def get_back_button(): return [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
def get_cancel_admin_button(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin")]])

def generate_qr(order_id: int) -> BufferedInputFile:
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(f"SMARTDRESS_ORDER_{order_id}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return BufferedInputFile(img_byte_arr.getvalue(), filename=f"order_{order_id}.png")

@dp.message(CommandStart())
async def start_cmd(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        args = command.args
        if args and args.startswith("add_"):
            parts = args.split("_")
            item_id = int(parts[1])
            size = parts[2] if len(parts) > 2 else "M"
            session.add(CartItem(user_tg_id=message.from_user.id, item_id=item_id, selected_size=size))
            await session.commit()
            await message.answer("✅ Товар добавлен в корзину из Web App!")
    await message.answer("Добро пожаловать в SmartDress! Выбирай действие:", reply_markup=get_main_menu())

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try: await callback.message.delete()
    except: pass
    await callback.message.answer("Главное меню:", reply_markup=get_main_menu())

@dp.callback_query(F.data.startswith("catalog"))
async def show_catalog(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    page = int(parts[2]) if len(parts) > 2 else 0
    ITEMS_PER_PAGE = 5
    
    async with async_session() as session:
        items = await session.scalars(select(Item))
        all_items = list(items)
        total_pages = (len(all_items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        current_items = all_items[start_idx:end_idx]
        
        keyboard = []
        for item in current_items:
            sizes = [s.strip() for s in item.available_sizes.split(",") if s.strip()]
            status = "✅" if item.is_available and sizes else "❌"
            keyboard.append([InlineKeyboardButton(text=f"{status} {item.title} ({item.price}₽)", callback_data=f"item_{item.id}_{page}")])
        
        nav_buttons = []
        if page > 0: nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"catalog_page_{page-1}"))
        if page < total_pages - 1: nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"catalog_page_{page+1}"))
        if nav_buttons: keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")])
        
    text = f"🛍 <b>Каталог (Стр. {page+1}/{total_pages}):</b>\n<i>Нажми на товар, чтобы посмотреть фото и выбрать размер</i>"
    try: await callback.message.delete()
    except: pass
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")

@dp.callback_query(F.data.startswith("item_"))
async def show_item_card(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    item_id = int(parts[1])
    page = parts[2] if len(parts) > 2 else "0"
    
    async with async_session() as session:
        item = await session.scalar(select(Item).where(Item.id == item_id))
        if not item: return await callback.answer("Товар не найден", show_alert=True)
            
        sizes = [s.strip() for s in item.available_sizes.split(",") if s.strip()]
        is_available = item.is_available and len(sizes) > 0
        status_text = "🟢 В наличии" if is_available else "🔴 Нет в наличии"
        caption = f"✨ <b>{item.title}</b>\n\n💰 Стоимость: {item.price}₽ / день\n📦 Статус: {status_text}\n"
        
        keyboard = []
        if is_available:
            caption += f"\n<i>Выберите ваш размер:</i>"
            size_buttons = [InlineKeyboardButton(text=f"Размер {s}", callback_data=f"add_{item.id}_{s}") for s in sizes]
            for i in range(0, len(size_buttons), 2): keyboard.append(size_buttons[i:i+2])
        else:
            caption += f"\n<i>К сожалению, все размеры разобрали.</i>"
        
        keyboard.append([InlineKeyboardButton(text="🔙 Вернуться в каталог", callback_data=f"catalog_page_{page}")])
        
        try: await callback.message.delete()
        except: pass
        
        try:
            await callback.message.answer_photo(photo=item.image_url, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        except Exception:
            await callback.message.answer(text=f"🖼 <i>(Фото временно недоступно)</i>\n\n{caption}", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    item_id = int(parts[1])
    size = parts[2] if len(parts) > 2 else "M"
    
    async with async_session() as session:
        item = await session.scalar(select(Item).where(Item.id == item_id))
        sizes_in_db = [s.strip() for s in item.available_sizes.split(",") if s.strip()]
        if not item.is_available or size not in sizes_in_db:
            return await callback.answer("Этот размер уже арендован!", show_alert=True)
        session.add(CartItem(user_tg_id=callback.from_user.id, item_id=item_id, selected_size=size))
        await session.commit()
    await callback.answer(f"✅ Товар добавлен в корзину (Размер: {size})!", show_alert=True)

@dp.callback_query(F.data == "cart")
async def show_cart(callback: types.CallbackQuery):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.tg_id == callback.from_user.id))
        cart_items = await session.scalars(select(CartItem).where(CartItem.user_tg_id == callback.from_user.id))
        items_in_cart = list(cart_items)
        
        if not items_in_cart:
            markup = InlineKeyboardMarkup(inline_keyboard=[get_back_button()])
            try: await callback.message.delete()
            except: pass
            return await callback.message.answer("Твоя корзина пуста 😔", reply_markup=markup)

        total_price = 0
        text = f"💳 <b>Твой баланс: {user.balance}₽</b>\n\n🛍 <b>Твоя корзина:</b>\n"
        for c_item in items_in_cart:
            item = await session.scalar(select(Item).where(Item.id == c_item.item_id))
            text += f"• {item.title} (Размер: {c_item.selected_size}) - {item.price}₽\n"
            total_price += item.price
            
        if user.discount_percent > 0:
            discount_amount = int(total_price * (user.discount_percent / 100))
            final_price = total_price - discount_amount
            text += f"\n🎁 Применена скидка: {user.discount_percent}% (-{discount_amount}₽)\n💰 <b>Итого к оплате:</b> {final_price}₽ / день"
        else:
            text += f"\n💰 <b>Итого:</b> {total_price}₽ / день"

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", callback_data="checkout")],
            [InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="ask_clear_cart")],
            get_back_button()
        ])
        
        try: await callback.message.delete()
        except: pass
        await callback.message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "checkout")
async def process_checkout(callback: types.CallbackQuery):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.tg_id == callback.from_user.id))
        cart_items = await session.scalars(select(CartItem).where(CartItem.user_tg_id == callback.from_user.id))
        items_in_cart = list(cart_items)
        
        total_price = 0
        order_summary = "" 
        for c in items_in_cart:
            item = await session.scalar(select(Item).where(Item.id == c.item_id))
            total_price += item.price
            order_summary += f"• {item.title} (Размер: {c.selected_size})\n"
        
        final_price = total_price
        if user.discount_percent > 0:
            final_price -= int(total_price * (user.discount_percent / 100))

        if user.balance >= final_price:
            user.balance -= final_price
            user.discount_percent = 0 
            
            for c in items_in_cart:
                item = await session.scalar(select(Item).where(Item.id == c.item_id))
                sizes = [s.strip() for s in item.available_sizes.split(",") if s.strip()]
                if c.selected_size in sizes: sizes.remove(c.selected_size)
                item.available_sizes = ",".join(sizes)
                if not item.available_sizes: item.is_available = False 
            
            new_order = Order(user_tg_id=callback.from_user.id, items_summary=order_summary)
            session.add(new_order)
            await session.execute(delete(CartItem).where(CartItem.user_tg_id == callback.from_user.id))
            await session.commit()
            
            qr_photo = generate_qr(new_order.id)
            try: await callback.message.delete()
            except: pass
            await callback.message.answer_photo(photo=qr_photo, caption=f"🎉 <b>Заказ #{new_order.id} оформлен!</b>\n\nВы арендовали:\n{order_summary}\nПокажите этот QR-код на ПВЗ.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[get_back_button()]))
        else:
            await callback.answer(f"❌ Недостаточно средств! Нужно: {final_price}₽. Баланс: {user.balance}₽", show_alert=True)

@dp.callback_query(F.data == "ask_clear_cart")
async def ask_clear_cart(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, очистить", callback_data="confirm_clear_cart")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cart")]
    ])
    try: await callback.message.delete()
    except: pass
    await callback.message.answer("⚠️ <b>Вы уверены, что хотите очистить корзину?</b>", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "confirm_clear_cart")
async def confirm_clear_cart(callback: types.CallbackQuery):
    async with async_session() as session:
        await session.execute(delete(CartItem).where(CartItem.user_tg_id == callback.from_user.id))
        await session.commit()
    await callback.answer("✅ Корзина очищена!")
    markup = InlineKeyboardMarkup(inline_keyboard=[get_back_button()])
    try: await callback.message.delete()
    except: pass
    await callback.message.answer("Твоя корзина пуста 😔", reply_markup=markup)

@dp.callback_query(F.data == "my_orders")
async def show_my_orders(callback: types.CallbackQuery):
    async with async_session() as session:
        orders = await session.scalars(select(Order).where(Order.user_tg_id == callback.from_user.id).order_by(Order.id.desc()))
        orders_list = list(orders)

    if not orders_list:
        text = "📦 У тебя пока нет активных заказов."
        markup = InlineKeyboardMarkup(inline_keyboard=[get_back_button()])
    else:
        text = "📦 <b>Твои заказы:</b>\nВыбери заказ, чтобы открыть QR-код:"
        keyboard = [[InlineKeyboardButton(text=f"Заказ #{order.id} ({order.status})", callback_data=f"view_order_{order.id}")] for order in orders_list]
        keyboard.append(get_back_button())
        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    try: await callback.message.delete()
    except: pass
    await callback.message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("view_order_"))
async def view_single_order(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        order = await session.scalar(select(Order).where(Order.id == order_id, Order.user_tg_id == callback.from_user.id))

    if not order: return await callback.answer("Заказ не найден!", show_alert=True)

    qr_photo = generate_qr(order.id)
    caption = f"📦 <b>Заказ #{order.id}</b>\n\n<b>Позиции:</b>\n{order.items_summary}\nСтатус: {order.status}\n\nПокажи этот QR-код сотруднику ПВЗ."
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 К списку заказов", callback_data="my_orders")]])
    try: await callback.message.delete()
    except: pass
    await callback.message.answer_photo(photo=qr_photo, caption=caption, parse_mode="HTML", reply_markup=markup)

@dp.callback_query(F.data == "profile")
async def show_profile(callback: types.CallbackQuery):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.tg_id == callback.from_user.id))
        discount_text = f"\n🎁 Активная скидка: {user.discount_percent}%" if user.discount_percent > 0 else ""
        text = f"👤 <b>Профиль (ID: <code>{user.tg_id}</code>)</b>\n\n💰 Твой баланс: {user.balance}₽{discount_text}\n"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Пополнить баланс", callback_data="topup_menu")],
            [InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="enter_promo")],
            get_back_button()
        ])
        try: await callback.message.delete()
        except: pass
        await callback.message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "topup_menu")
async def show_topup(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ Telegram Stars (Скоро)", callback_data="topup_stub")],
        [InlineKeyboardButton(text="💳 Банковская карта (Скоро)", callback_data="topup_stub")],
        [InlineKeyboardButton(text="🔙 Назад в профиль", callback_data="profile")]
    ])
    try: await callback.message.delete()
    except: pass
    await callback.message.answer("💎 <b>Пополнение баланса</b>\n\nВыберите способ оплаты:", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "topup_stub")
async def stub_topup(callback: types.CallbackQuery):
    await callback.answer("В MVP эта функция работает в демо-режиме.", show_alert=True)

@dp.callback_query(F.data == "enter_promo")
async def ask_promo(callback: types.CallbackQuery, state: FSMContext):
    try: await callback.message.delete()
    except: pass
    await callback.message.answer("Введите промокод:", reply_markup=get_cancel_admin_button())
    await state.set_state(PromoState.waiting_for_promo)

@dp.message(StateFilter(PromoState.waiting_for_promo))
async def check_promo(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    await state.clear()
    
    async with async_session() as session:
        promo = await session.scalar(select(PromoCode).where(PromoCode.code == code))
        if promo:
            user = await session.scalar(select(User).where(User.tg_id == message.from_user.id))
            if promo.is_percent:
                user.discount_percent = promo.reward
                text_answer = f"✅ Промокод '{code}' применен! Скидка {promo.reward}%."
            else:
                user.balance += promo.reward
                text_answer = f"✅ Промокод '{code}' применен! Начислено {promo.reward}₽."
            await session.commit()
            await message.answer(text_answer, reply_markup=get_main_menu())
        else:
            await message.answer("❌ Промокод не найден.", reply_markup=get_main_menu())

def get_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_list_users"),
         InlineKeyboardButton(text="📋 Заказы", callback_data="admin_all_orders")],
        [InlineKeyboardButton(text="📦 Добавить товар", callback_data="admin_add_item")],
        [InlineKeyboardButton(text="✏️ Изменить размер", callback_data="admin_edit_items_list"),
         InlineKeyboardButton(text="📸 Изменить фото", callback_data="admin_edit_photo_list")],
        [InlineKeyboardButton(text="🎁 Создать промокод", callback_data="admin_add_promo"),
         InlineKeyboardButton(text="💰 Выдать баланс", callback_data="admin_add_balance")],
        [InlineKeyboardButton(text="🚫 Блок юзера", callback_data="admin_ban_user"),
         InlineKeyboardButton(text="✅ Разблок юзера", callback_data="admin_unban_user")],
        [InlineKeyboardButton(text="👑 Выдать админку", callback_data="admin_grant_admin"),
         InlineKeyboardButton(text="❌ Забрать админку", callback_data="admin_revoke_admin")],
        [InlineKeyboardButton(text="🏠 Выйти в меню", callback_data="main_menu")]
    ])

@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        is_admin = await is_user_admin(message.from_user.id, session)
        if not is_admin:
            return await message.answer("❌ У вас нет прав администратора.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu")]]))
        users_count = len((await session.scalars(select(User))).all())
    await message.answer(f"👑 <b>Админ-панель</b>\nПользователей в БД: {users_count}", reply_markup=get_admin_menu(), parse_mode="HTML")

@dp.callback_query(F.data == "cancel_admin")
async def cancel_admin_action(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try: await callback.message.delete()
    except: pass
    async with async_session() as session:
        is_admin = await is_user_admin(callback.from_user.id, session)
        if is_admin: await callback.message.answer("Действие отменено.", reply_markup=get_admin_menu())
        else: await callback.message.answer("Действие отменено.", reply_markup=get_main_menu())

@dp.callback_query(F.data.startswith("admin_"))
async def admin_actions(callback: types.CallbackQuery, state: FSMContext):
    async with async_session() as session:
        if not await is_user_admin(callback.from_user.id, session):
            return await callback.answer("У вас нет прав!", show_alert=True)

    action = callback.data.replace("admin_", "")
    
    if action == "add_item":
        await callback.message.answer("Шаг 1/2. Введите: Название, Цена, Доступные Размеры\n*(напр: Красная Юбка, 300, XS,S,M)*", reply_markup=get_cancel_admin_button(), parse_mode="Markdown")
        await state.set_state(AdminState.waiting_for_item_data)
        
    elif action == "edit_items_list":
        async with async_session() as session:
            items = await session.scalars(select(Item))
            keyboard = [[InlineKeyboardButton(text=item.title, callback_data=f"admin_edit_item_{item.id}")] for item in items]
            keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin")])
            await callback.message.answer("Выберите товар для редактирования РАЗМЕРОВ:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

    elif action.startswith("edit_item_"):
        item_id = int(action.split("_")[2])
        await state.update_data(edit_item_id=item_id)
        await callback.message.answer("Введите **новые доступные размеры** через запятую (например: `S,M,L`).\n\n⚠️ Если товара **нет в наличии**, отправьте цифру `0`.", parse_mode="Markdown", reply_markup=get_cancel_admin_button())
        await state.set_state(AdminState.waiting_for_edit_sizes)
        
    elif action == "edit_photo_list":
        async with async_session() as session:
            items = await session.scalars(select(Item))
            keyboard = [[InlineKeyboardButton(text=item.title, callback_data=f"admin_edit_photo_{item.id}")] for item in items]
            keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin")])
            await callback.message.answer("Выберите товар для загрузки нового ФОТО:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

    elif action.startswith("edit_photo_"):
        item_id = int(action.split("_")[2])
        await state.update_data(edit_item_id=item_id)
        await callback.message.answer("Отправьте **новую фотографию** (картинку) в чат:", reply_markup=get_cancel_admin_button())
        await state.set_state(AdminState.waiting_for_edit_photo)
        
    elif action == "add_promo":
        await callback.message.answer("Введите: ПРОМОКОД, Значение\n*(напр: WINTER, 15%)*", reply_markup=get_cancel_admin_button(), parse_mode="Markdown")
        await state.set_state(AdminState.waiting_for_promo_create)
        
    elif action == "add_balance":
        await callback.message.answer("Введите: ID пользователя, Сумма\n*(напр: 12345678, 500)*", reply_markup=get_cancel_admin_button(), parse_mode="Markdown")
        await state.set_state(AdminState.waiting_for_admin_balance)
        
    elif action == "ban_user":
        await callback.message.answer("Введите Telegram ID для блокировки:", reply_markup=get_cancel_admin_button())
        await state.set_state(AdminState.waiting_for_ban_id)
        
    elif action == "unban_user":
        await callback.message.answer("Введите Telegram ID для разблокировки:", reply_markup=get_cancel_admin_button())
        await state.set_state(AdminState.waiting_for_unban_id)
        
    elif action == "grant_admin":
        if callback.from_user.id != ADMIN_ID: return await callback.answer("Только Создатель!", show_alert=True)
        await callback.message.answer("Введите Telegram ID пользователя для выдачи прав:", reply_markup=get_cancel_admin_button())
        await state.set_state(AdminState.waiting_for_admin_grant)
        
    elif action == "revoke_admin":
        if callback.from_user.id != ADMIN_ID: return await callback.answer("Только Создатель!", show_alert=True)
        await callback.message.answer("Введите Telegram ID пользователя для снятия прав:", reply_markup=get_cancel_admin_button())
        await state.set_state(AdminState.waiting_for_admin_revoke)
            
    elif action == "list_users":
        async with async_session() as session:
            users = await session.scalars(select(User))
            text = "👥 <b>Список пользователей:</b>\n\n"
            for u in users:
                status = "🚫" if u.is_banned else "✅"
                admin_badge = "👑 " if u.is_admin or u.tg_id == ADMIN_ID else ""
                name = u.username if u.username else "Без юзернейма"
                text += f"{status} {admin_badge}<code>{u.tg_id}</code> | @{name} | Баланс: {u.balance}₽\n"
            await callback.message.answer(text, parse_mode="HTML", reply_markup=get_admin_menu())
            
    elif action == "all_orders":
        async with async_session() as session:
            orders = await session.scalars(select(Order).order_by(Order.id.desc()).limit(10))
            orders_list = list(orders)
            if not orders_list:
                text = "В системе пока нет заказов."
            else:
                text = "📋 <b>Последние 10 заказов (CRM):</b>\n\n"
                for o in orders_list:
                    text += f"📦 <b>Заказ #{o.id}</b> | Юзер ID: <code>{o.user_tg_id}</code>\n<b>Позиции:</b>\n{o.items_summary}Статус: {o.status}\n\n"
            await callback.message.answer(text, parse_mode="HTML", reply_markup=get_admin_menu())
    await callback.answer()

async def check_admin_middleware(message, session):
    return await is_user_admin(message.from_user.id, session)

@dp.message(StateFilter(AdminState.waiting_for_item_data))
async def add_item_data(message: types.Message, state: FSMContext):
    async with async_session() as session:
        if not await check_admin_middleware(message, session): return
    try:
        parts = message.text.split(",")
        title, price = parts[0].strip(), int(parts[1].strip())
        sizes = ",".join([s.strip().upper() for s in parts[2:]])
        await state.update_data(title=title, price=price, sizes=sizes)
        await message.answer("Шаг 2/2. Отправьте **фотографию** товара (загрузите картинку прямо в чат):", reply_markup=get_cancel_admin_button(), parse_mode="Markdown")
        await state.set_state(AdminState.waiting_for_item_photo)
    except Exception:
        await message.answer("❌ Ошибка формата. Нужно: Название, Цена, Размеры", reply_markup=get_admin_menu())
        await state.clear()

@dp.message(StateFilter(AdminState.waiting_for_item_photo), F.photo)
async def add_item_photo(message: types.Message, state: FSMContext):
    async with async_session() as session:
        if not await check_admin_middleware(message, session): return
    file_id = message.photo[-1].file_id
    data = await state.get_data()
    async with async_session() as session:
        session.add(Item(title=data['title'], price=data['price'], available_sizes=data['sizes'], image_url=file_id, is_available=True))
        await session.commit()
    await message.answer(f"✅ Товар '{data['title']}' успешно добавлен!", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(StateFilter(AdminState.waiting_for_item_photo))
async def add_item_photo_invalid(message: types.Message):
    await message.answer("❌ Отправьте именно **фотографию**, а не текст.", reply_markup=get_cancel_admin_button())

@dp.message(StateFilter(AdminState.waiting_for_edit_photo), F.photo)
async def save_edited_photo(message: types.Message, state: FSMContext):
    async with async_session() as session:
        if not await check_admin_middleware(message, session): return
        
    file_id = message.photo[-1].file_id
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    
    async with async_session() as session:
        item = await session.scalar(select(Item).where(Item.id == item_id))
        if item:
            item.image_url = file_id
            await session.commit()
            await message.answer(f"✅ Фото для '{item.title}' успешно обновлено!", reply_markup=get_admin_menu())
        else:
            await message.answer("❌ Товар не найден.", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(StateFilter(AdminState.waiting_for_edit_photo))
async def save_edited_photo_invalid(message: types.Message):
    await message.answer("❌ Пожалуйста, отправьте именно **фотографию** (картинку), а не текст.", reply_markup=get_cancel_admin_button())

@dp.message(StateFilter(AdminState.waiting_for_edit_sizes))
async def save_edited_sizes(message: types.Message, state: FSMContext):
    async with async_session() as session:
        if not await check_admin_middleware(message, session): return
    text = message.text.strip().upper()
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    async with async_session() as session:
        item = await session.scalar(select(Item).where(Item.id == item_id))
        if not item:
            await message.answer("Ошибка: Товар не найден.", reply_markup=get_admin_menu())
            return await state.clear()
        if text == "0":
            item.available_sizes = ""
            item.is_available = False
            await session.commit()
            await message.answer(f"✅ Товар '{item.title}' теперь **НЕТ В НАЛИЧИИ**.", parse_mode="Markdown", reply_markup=get_admin_menu())
        else:
            sizes = ",".join([s.strip() for s in text.split(",") if s.strip()])
            item.available_sizes, item.is_available = sizes, True
            await session.commit()
            await message.answer(f"✅ Размеры для '{item.title}' обновлены: **{sizes}**", parse_mode="Markdown", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(StateFilter(AdminState.waiting_for_promo_create))
async def add_promo_save(message: types.Message, state: FSMContext):
    async with async_session() as session:
        if not await check_admin_middleware(message, session): return
    try:
        code, val = message.text.split(",")
        clean_code, is_percent = code.strip().upper(), "%" in val
        reward = int(val.strip().replace("%", ""))
        async with async_session() as session:
            session.add(PromoCode(code=clean_code, reward=reward, is_percent=is_percent))
            await session.commit()
        await message.answer(f"✅ Промокод '{clean_code}' создан!", reply_markup=get_admin_menu())
    except:
        await message.answer("❌ Ошибка формата.", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(StateFilter(AdminState.waiting_for_admin_balance))
async def add_balance_save(message: types.Message, state: FSMContext):
    async with async_session() as session:
        if not await check_admin_middleware(message, session): return
    try:
        tg_id_str, amount_str = message.text.split(",")
        tg_id, amount = int(tg_id_str.strip()), int(amount_str.strip())
        async with async_session() as session:
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            if user:
                user.balance += amount
                await session.commit()
                await message.answer(f"✅ Баланс пользователя {tg_id} пополнен на {amount}₽.", reply_markup=get_admin_menu())
            else:
                await message.answer("❌ Пользователь не найден.", reply_markup=get_admin_menu())
    except:
        await message.answer("❌ Ошибка формата.", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(StateFilter(AdminState.waiting_for_ban_id))
async def ban_user_save(message: types.Message, state: FSMContext):
    async with async_session() as session:
        if not await check_admin_middleware(message, session): return
    try:
        tg_id = int(message.text.strip())
        if tg_id == ADMIN_ID: return await message.answer("🛡️ Нельзя заблокировать себя!", reply_markup=get_admin_menu())
        async with async_session() as session:
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            if user:
                user.is_banned = True
                await session.commit()
                await message.answer(f"Пользователь <code>{tg_id}</code> ЗАБЛОКИРОВАН 🚫", parse_mode="HTML", reply_markup=get_admin_menu())
            else:
                await message.answer("❌ Пользователь не найден.", reply_markup=get_admin_menu())
    except:
        await message.answer("❌ Пришлите только цифры.", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(StateFilter(AdminState.waiting_for_unban_id))
async def unban_user_save(message: types.Message, state: FSMContext):
    async with async_session() as session:
        if not await check_admin_middleware(message, session): return
    try:
        tg_id = int(message.text.strip())
        async with async_session() as session:
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            if user:
                user.is_banned = False
                await session.commit()
                await message.answer(f"Пользователь <code>{tg_id}</code> РАЗБЛОКИРОВАН ✅", parse_mode="HTML", reply_markup=get_admin_menu())
            else:
                await message.answer("❌ Пользователь не найден.", reply_markup=get_admin_menu())
    except:
        await message.answer("❌ Пришлите только цифры ID.", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(StateFilter(AdminState.waiting_for_admin_grant), F.from_user.id == ADMIN_ID)
async def grant_admin_save(message: types.Message, state: FSMContext):
    try:
        tg_id = int(message.text.strip())
        async with async_session() as session:
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            if user:
                user.is_admin = True
                await session.commit()
                await message.answer(f"👑 Пользователь <code>{tg_id}</code> назначен Администратором!", parse_mode="HTML", reply_markup=get_admin_menu())
            else:
                await message.answer("❌ Пользователь не найден.", reply_markup=get_admin_menu())
    except:
        await message.answer("❌ Пришлите только цифры ID.", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(StateFilter(AdminState.waiting_for_admin_revoke), F.from_user.id == ADMIN_ID)
async def revoke_admin_save(message: types.Message, state: FSMContext):
    try:
        tg_id = int(message.text.strip())
        if tg_id == ADMIN_ID: return await message.answer("🛡️ Себя разжаловать нельзя!", reply_markup=get_admin_menu())
        async with async_session() as session:
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            if user:
                user.is_admin = False
                await session.commit()
                await message.answer(f"📉 Пользователь <code>{tg_id}</code> больше не Администратор.", parse_mode="HTML", reply_markup=get_admin_menu())
            else:
                await message.answer("❌ Пользователь не найден.", reply_markup=get_admin_menu())
    except:
        await message.answer("❌ Пришлите только цифры ID.", reply_markup=get_admin_menu())
    await state.clear()

@dp.message()
async def catch_all(message: types.Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Открыть меню", callback_data="main_menu")]])
    await message.answer("🤔 Я не понимаю эту команду. Пожалуйста, используйте кнопки меню:", reply_markup=markup)

async def main():
    await init_db()
    bot = Bot(token=TOKEN)
    print("Бот готов к запуску!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())