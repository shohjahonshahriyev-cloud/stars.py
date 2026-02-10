#!/usr/bin/env python3
"""
Telegram Stars Referal Bot - Simple Working Version
"""

import asyncio
import logging
import sys
import os
import re
from datetime import datetime
from typing import List

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Boolean, DateTime, BigInteger, Text, select, update, func
from pydantic_settings import BaseSettings

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Log yozish funksiyasi
def log_info(message: str):
    """Log yozish uchun qulay funktsiya"""
    logger.info(message)
    print(f"INFO: {message}")

def log_error(message: str):
    """Xatolik log yozish uchun qulay funktsiya"""
    logger.error(message)
    print(f"ERROR: {message}")

def log_debug(message: str):
    """Debug log yozish uchun qulay funktsiya"""
    logger.debug(message)
    print(f"DEBUG: {message}")

# ==================== CONFIG ====================
class Config(BaseSettings):
    bot_token: str = "8512569193:AAFF-vMCt4GSbldCSZd5JoJhJYE6M0F7_Mc"
    admin_id: int = 422057508   # Test uchun o'zgartirildi
    admin_username: str = "shohjahon_o5"
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///stars_bot.db").replace("postgresql://", "postgresql+asyncpg://")
    referral_reward: int = 3  # 3 stars
    minimum_withdrawal: int = 30  # 30 stars
    sponsor_channels: str = "@shohjahon_shahriyev"  # Default kanal
    is_railway: bool = os.getenv("RAILWAY_ENVIRONMENT", "").startswith("production") or os.getenv("IS_RAILWAY", "false").lower() == "true"

    @property
    def sponsor_channels_list(self) -> List[str]:
        if not self.sponsor_channels:
            return []
        return [ch.strip() for ch in self.sponsor_channels.split(",") if ch.strip()]

settings = Config()

# ==================== DATABASE ====================
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255))
    balance: Mapped[int] = mapped_column(Integer, default=0)  # Stars
    referral_count: Mapped[int] = mapped_column(Integer, default=0)
    referred_by: Mapped[int] = mapped_column(BigInteger, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Withdrawal(Base):
    __tablename__ = "withdrawals"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[int] = mapped_column(Integer)  # Stars
    user_info: Mapped[str] = mapped_column(Text)  # Foydalanuvchi ma'lumotlari
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Referral(Base):
    __tablename__ = "referrals"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger)
    referred_id: Mapped[int] = mapped_column(BigInteger)
    reward_given: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# ==================== INIT ====================
engine = create_async_engine(settings.database_url)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ==================== KEYBOARDS ====================
def main_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⭐ Balans"), KeyboardButton(text="👥 Referallar")],
            [KeyboardButton(text="🔗 Referal havola"), KeyboardButton(text="⭐ Stars yechib olish")],
            [KeyboardButton(text="📞 Admin bilan aloqa")]
        ],
        resize_keyboard=True
    )
    return keyboard

def restricted_menu():
    channels = settings.sponsor_channels_list
    print(f"DEBUG: restricted_menu channels: {channels}")
    
    if channels:
        channel_buttons = []
        for channel in channels:
            channel_url = f"https://t.me/{channel.lstrip('@')}"
            channel_buttons.append([InlineKeyboardButton(text=f"📺 {channel}", url=channel_url)])
        
        channel_buttons.append([InlineKeyboardButton(text=" Obunani tekshirish 🔍", callback_data="check_subscription")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=channel_buttons)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=" Obuna bo'lish ✅", url="#")],
            [InlineKeyboardButton(text=" Obunani tekshirish 🔍", callback_data="check_subscription")]
        ])
    
    return keyboard

def admin_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Foydalanuvchilar"), KeyboardButton(text="⭐ Balansni o'zgartirish")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="⚙️ Sozlamalar")],
            [KeyboardButton(text="📢 Xabar yuborish"), KeyboardButton(text="📺 Homiy kanallar")]
        ],
        resize_keyboard=True
    )
    return keyboard

def format_balance(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")

def generate_referral_link(user_id: int, bot_username: str) -> str:
    return f"https://t.me/{bot_username}?start={user_id}"

async def check_subscription(user_id: int, bot: Bot) -> bool:
    channels = settings.sponsor_channels_list
    print(f"DEBUG: Checking subscription for user {user_id} in channels: {channels}")
    
    if not channels:
        print("DEBUG: No sponsor channels configured, returning True")
        return True
    
    if settings.is_railway:
        print("DEBUG: Railway mode enabled, returning True")
        return True
    
    for channel in channels:
        try:
            print(f"DEBUG: Checking channel {channel} for user {user_id}")
            member = await asyncio.wait_for(
                bot.get_chat_member(channel, user_id), 
                timeout=5.0
            )
            print(f"DEBUG: User {user_id} status in {channel}: {member.status}")
            if member.status in ['left', 'kicked', 'banned']:
                print(f"DEBUG: User {user_id} not subscribed to {channel}")
                return False
            else:
                print(f"DEBUG: User {user_id} subscribed to {channel}")
        except asyncio.TimeoutError:
            print(f"DEBUG: Timeout checking {channel} for user {user_id}")
            return False
        except Exception as e:
            print(f"DEBUG: Error checking {channel} for user {user_id}: {e}")
            return False
    
    print(f"DEBUG: User {user_id} subscribed to all channels")
    return True

# ==================== HANDLERS ====================
dp = Dispatcher()

@dp.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery):
    channels = settings.sponsor_channels_list
    subscribed_channels = []
    unsubscribed_channels = []
    
    for channel in channels:
        try:
            member = await callback.bot.get_chat_member(channel, callback.from_user.id)
            if member.status in ['left', 'kicked', 'banned']:
                unsubscribed_channels.append(channel)
            else:
                subscribed_channels.append(channel)
        except Exception:
            unsubscribed_channels.append(channel)
    
    # Agar foydalanuvchi kanallardan chiqib ketsa, referral jarimasini qo'llash
    if unsubscribed_channels and len(subscribed_channels) < len(channels):
        await process_referral_penalty(callback.from_user.id, callback.bot)
    
    channel_buttons = []
    
    for channel in unsubscribed_channels:
        channel_url = f"https://t.me/{channel.lstrip('@')}"
        channel_buttons.append([InlineKeyboardButton(text=f"❌ {channel}", url=channel_url)])
    
    for channel in subscribed_channels:
        channel_buttons.append([InlineKeyboardButton(text=f"✅ {channel}", url="https://t.me/" + channel.lstrip('@'))])
    
    if unsubscribed_channels:
        channel_buttons.append([InlineKeyboardButton(text="🔄 Obunani qayta tekshirish", callback_data="check_subscription")])
    else:
        channel_buttons.append([InlineKeyboardButton(text="🎉 Barcha kanallarga obuna bo'ldingiz!", callback_data="check_subscription")])
    
    if unsubscribed_channels:
        text = f"❌ Obuna to'liq emas!\n\n"
        text += f"📊 Jami kanallar: {len(channels)} ta\n"
        text += f"✅ Obuna bo'lgan: {len(subscribed_channels)} ta\n"
        text += f"❌ Obuna bo'lmagan: {len(unsubscribed_channels)} ta\n\n"
        text += f"🔽 Obuna bo'lmagan kanallar:\n"
        for channel in unsubscribed_channels:
            text += f"• {channel}\n"
        text += f"\n📱 Quyi tugmalarni bosib obuna bo'ling!"
    else:
        text = f"🎉 TABRIKLAYMIZ!\n\n"
        text += f"✅ Siz barcha {len(channels)} ta kanalga obuna bo'ldingiz!\n"
        text += f"🚀 Endi botning barcha imkoniyatlaridan foydalanishingiz mumkin:\n\n"
        text += f"⭐ Balangizni ko'rish\n"
        text += f"👥 Referallaringizni ko'rish\n"
        text += f"🔗 Referal havola olish\n"
        text += f"⭐ Stars yechib olish\n\n"
        
        bot_username = (await callback.bot.get_me()).username
        referral_link = generate_referral_link(callback.from_user.id, bot_username)
        text += f"🔗 Sizning referal havolangiz:\n{referral_link}"
    
    if not unsubscribed_channels:
        await callback.message.delete()
        
        # Obuna bo'lgandan so'ng referral mukofotlarini berish
        await process_pending_referral_rewards(callback.from_user.id, callback.bot)
        
        await callback.bot.send_message(
            callback.from_user.id,
            text,
            reply_markup=main_menu()
        )
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=channel_buttons)
        await callback.message.edit_text(
            text,
            reply_markup=keyboard
        )
    
    await callback.answer("Obuna tekshirildi!")

@dp.message(CommandStart())
async def cmd_start(message: Message):
    referrer_id = None
    if message.text.startswith('/start '):
        try:
            referrer_id = int(message.text.split()[1])
        except (ValueError, IndexError):
            pass

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                referred_by=referrer_id,
                is_admin=(message.from_user.id == settings.admin_id)
            )
            session.add(user)
            await session.commit()

            # Yangi foydalanuvchi bo'lsa va referal ID bo'lsa
            if referrer_id and referrer_id != message.from_user.id:
                # Yangi session ochib referal mukofotini berish
                async with async_session_maker() as referral_session:
                    await handle_referral_reward(referral_session, referrer_id, message.from_user.id, message.bot)

        if message.from_user.id == settings.admin_id:
            await message.answer(
                f"👨‍💼 Admin paneliga xush kelibsiz, {message.from_user.first_name}!",
                reply_markup=admin_menu()
            )
            return

        bot_username = (await message.bot.get_me()).username
        referral_link = generate_referral_link(message.from_user.id, bot_username)
        
        if await check_subscription(message.from_user.id, message.bot):
            await message.answer(
                f"🎉 Xush kelibsiz, {message.from_user.first_name}!\n\n"
                f"⭐ Balans: {format_balance(user.balance)} ⭐\n"
                f"👥 Referallar: {user.referral_count} ta\n\n"
                f"🔗 Sizning referal havolangiz:\n{referral_link}\n\n"
                f"Har bir do'stingiz {settings.referral_reward} ⭐ olib keladi!",
                reply_markup=main_menu()
            )
        else:
            await message.answer(
                "👋 Assalomu alaykum!\n\n"
                "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
                "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
                reply_markup=restricted_menu()
            )

async def handle_referral_reward(session, referrer_id: int, referred_id: int, bot: Bot):
    result = await session.execute(
        select(Referral).where(
            Referral.referrer_id == referrer_id,
            Referral.referred_id == referred_id
        )
    )
    existing_referral = result.scalar_one_or_none()

    if existing_referral:
        return

    # Yangi foydalanuvchi ma'lumotlarini olish
    result = await session.execute(select(User).where(User.telegram_id == referred_id))
    referred_user = result.scalar_one_or_none()
    
    # Referal egasi ma'lumotlarini olish
    result = await session.execute(select(User).where(User.telegram_id == referrer_id))
    referrer = result.scalar_one_or_none()
    
    if not referrer or not referred_user:
        return

    # Referal yozuvini yaratish (mukofot hali berilmagan)
    referral = Referral(
        referrer_id=referrer_id,
        referred_id=referred_id,
        reward_given=False  # Dastlab mukofot berilmaydi
    )
    session.add(referral)
    await session.commit()
    
    # Referal egasiga bildirish xabari (mukofotsiz)
    try:
        await bot.send_message(
            referrer_id,
            f"🎉 YANGI REFERAL KELDI!\n\n"
            f"👤 Ismi: {referred_user.first_name}\n"
            f"🆔 ID: {referred_user.telegram_id}\n"
            (f"@{referred_user.username}\n" if referred_user.username else "") + "\n\n"
            f"⚠️ Mukofot obuna tasdiqlangandan keyin beriladi!\n"
            f"📊 Jami referallar: {referrer.referral_count} ta\n\n"
            f"� Ushbu foydalanuvchi homiy kanallariga obuna bo'lsa,\n"
            f"sizga {settings.referral_reward} ⭐ beriladi!"
        )
    except Exception as e:
        print(f"Error sending referral notification: {e}")

    # Yangi foydalanuvchiga ham xabar berish
    try:
        await bot.send_message(
            referred_id,
            f"🎉 Siz muvaffaqiyatli referal bo'ldingiz!\n\n"
            f"👤 Sizni @{referrer.username if referrer.username else 'admin'} taklif qildi\n"
            f"🎁 U {settings.referral_reward} ⭐ olishi uchun siz obuna bo'lishingiz kerak!\n\n"
            f"📺 Homiy kanallariga obuna bo'ling va mukofot oling!\n"
            f"🚀 Endi siz ham do'stlaringizni taklif qiling!"
        )
    except TelegramAPIError:
        pass

async def process_pending_referral_rewards(user_id: int, bot: Bot):
    """Foydalanuvchi obuna bo'lganda, kutayotgan referral mukofotlarini berish"""
    async with async_session_maker() as session:
        # Foydalanuvchining referral larini topish
        result = await session.execute(
            select(Referral).where(
                Referral.referred_id == user_id,
                Referral.reward_given == False
            )
        )
        pending_referrals = result.scalars().all()
        
        if not pending_referrals:
            return
        
        for referral in pending_referrals:
            # Referal egasini topish
            referrer_result = await session.execute(
                select(User).where(User.telegram_id == referral.referrer_id)
            )
            referrer = referrer_result.scalar_one_or_none()
            
            if referrer:
                # Mukofot berish
                referrer.balance += settings.referral_reward
                referrer.referral_count += 1
                
                # Referral ni yangilash
                referral.reward_given = True
                
                await session.commit()
                
                # Referal egasiga xabar yuborish
                try:
                    await bot.send_message(
                        referrer.telegram_id,
                        f"🎉 MUKOFOT BERILDI!\n\n"
                        f"👤 {user_id} ID li foydalanuvchi homiy kanallariga obuna bo'ldi!\n"
                        f"⭐ Sizga {settings.referral_reward} ⭐ berildi!\n"
                        f"📊 Yangi balans: {referrer.balance} ⭐\n"
                        f"👥 Jami referallar: {referrer.referral_count} ta"
                    )
                except Exception as e:
                    print(f"Error sending reward notification: {e}")
                
                # Foydalanuvchiga ham xabar yuborish
                try:
                    await bot.send_message(
                        user_id,
                        f"🎉 TABRIKLAYMIZ!\n\n"
                        f"✅ Siz homiy kanallariga muvaffaqiyatli obuna bo'ldingiz!\n"
                        f"🎁 Sizni chaqirgan @{referrer.username if referrer.username else 'admin'}\n"
                        f"⭐ U {settings.referral_reward} ⭐ oldi!\n\n"
                        f"🚀 Endi siz ham do'stlaringizni taklif qiling!"
                    )
                except Exception as e:
                    print(f"Error sending user notification: {e}")

async def process_referral_penalty(user_id: int, bot: Bot):
    """Foydalanuvchi kanallardan chiqib ketsa, referral jarimasini qo'llash"""
    async with async_session_maker() as session:
        # Foydalanuvchining kim tomondan referral ekanligini topish
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        
        if not user or not user.referred_by:
            return
        
        # Referral egasini topish
        referrer_result = await session.execute(
            select(User).where(User.telegram_id == user.referred_by)
        )
        referrer = referrer_result.scalar_one_or_none()
        
        if not referrer:
            return
        
        # Referral jarimasini tekshirish (faqat bir marta)
        penalty_result = await session.execute(
            select(Referral).where(
                Referral.referrer_id == user.referred_by,
                Referral.referred_id == user_id,
                Referral.reward_given == True
            )
        )
        existing_referral = penalty_result.scalar_one_or_none()
        
        if existing_referral and referrer.balance >= settings.referral_reward:
            # Jarimani qo'llash
            referrer.balance -= settings.referral_reward
            referrer.referral_count = max(0, referrer.referral_count - 1)
            
            # Referral ni yangilash
            existing_referral.reward_given = False  # Jarima belgisi
            
            await session.commit()
            
            # Referral egasiga xabar
            try:
                await bot.send_message(
                    referrer.telegram_id,
                    f"⚠️ REFERAL JARIMASI!\n\n"
                    f"👤 {user.first_name} ({user.telegram_id})\n"
                    f"📺 Homiy kanallaridan chiqib ketdi!\n"
                    f"💸 {settings.referral_reward} ⭐ jarimlandi!\n"
                    f"📊 Yangi balans: {referrer.balance} ⭐\n"
                    f"👥 Jami referallar: {referrer.referral_count} ta\n\n"
                    f"🔄 U qayta obuna bo'lsa, mukofot qaytariladi!"
                )
                print(f"DEBUG: Penalty notification sent to referrer: {referrer.telegram_id}")
            except Exception as e:
                print(f"Error sending penalty notification: {e}")
            
            # Foydalanuvchiga xabar
            try:
                await bot.send_message(
                    user_id,
                    f"⚠️ DIQQAT!\n\n"
                    f"📺 Siz homiy kanallaridan chiqib ketdingiz!\n"
                    f"👤 Sizni chaqirgan: @{referrer.username if referrer.username else 'admin'}\n"
                    f"💸 Uning hisobidan {settings.referral_reward} ⭐ jarimlandi!\n"
                    f"📊 Yangi balans: {referrer.balance} ⭐\n"
                    f"� Jami referallar: {referrer.referral_count} ta\n\n"
                    f"� Qayta obuna bo'lsangiz, mukofot qaytariladi!\n"
                    f"📱 Obuna bo'lish uchun pastdagi tugmalardan foydalaning!"
                )
                print(f"DEBUG: Penalty notification sent to user: {user.telegram_id}")
            except Exception as e:
                print(f"Error sending user penalty notification: {e}")
        return
        
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        
        if user:
            await message.answer(
                f"⭐ Sizning balansingiz: {format_balance(user.balance)} ⭐\n\n"
                f"🎁 Referallar soni: {user.referral_count} ta"
            )

@dp.message(F.text == "👥 Referallar")
async def cmd_referrals(message: Message):
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(Referral).where(Referral.referrer_id == message.from_user.id)
        )
        referrals = result.scalars().all()
        
        if not referrals:
            await message.answer(
                "👥 Sizda hali referallar yo'q\n\n"
                "🔗 Do'stlaringizni referal havolangiz orqali taklif qiling:\n"
                f"🎁 Har bir referal uchun {format_balance(settings.referral_reward)} ⭐ bonus beriladi!"
            )
            return
        
        text = f"👥 Sizning referallaringiz:\n\n"
        text += f"📊 Jami referallar: {len(referrals)} ta\n\n"
        
        for i, referral in enumerate(referrals, 1):
            user_result = await session.execute(
                select(User).where(User.telegram_id == referral.referred_id)
            )
            referred_user = user_result.scalar_one_or_none()
            
            if referred_user:
                status = "✅ Mukofot berilgan" if referral.reward_given else "⏳ Mukofot kutilmoqda"
                text += f"{i}. {referred_user.first_name}"
                if referred_user.username:
                    text += f" (@{referred_user.username})"
                text += f"\n   ID: {referred_user.telegram_id}"
                text += f"\n   Sana: {referral.created_at.strftime('%d.%m.%Y')}"
                text += f"\n   {status}\n\n"
        
        await message.answer(text)

@dp.message(F.text == "🔗 Referal havola")
async def cmd_referral_link(message: Message):
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return
    
    bot_username = (await message.bot.get_me()).username
    referral_link = generate_referral_link(message.from_user.id, bot_username)
    
    # Foydalanuvchi admin bilan muloqotligini tekshirish
    if message.from_user.id == settings.admin_id:
        await message.answer(
            f"🔗 Sizning referal havolangiz:\n\n"
            f"`{referral_link}`\n\n"
            f"🎁 Siz adminsiz, shuning uchun referal havolangiz ishlamaydi!\n"
            f"📊 Jami referallar: {len(referrals)} ta\n"
            f"⭐ Jami daromad: {format_balance(len(referrals) * settings.referral_reward)} ⭐"
        )
        return
    
    await message.answer(
        f"🔗 Sizning referal havolangiz:\n\n"
        f"`{referral_link}`\n\n"
        f"🎁 Har bir referal uchun {format_balance(settings.referral_reward)} ⭐ bonus!",
        parse_mode="Markdown"
    )

@dp.message(F.text == "⭐ Balans")
async def cmd_balance(message: Message):
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return
    
    # Foydalanuvchi admin bilan muloqotligini tekshirish
    if message.from_user.id == settings.admin_id:
        await message.answer(
            "🎁 Admin paneliga xush kelibsiz!\n\n"
            "📊 Balansni o'zgartirish uchun /balans komandasidan foydalaning."
        )
        return
    
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Sizning ma'lumotlaringiz topilmadi!")
            return
        
        await message.answer(
            f"⭐ Sizning balansingiz: {format_balance(user.balance)} ⭐\n"
            f"🎁 Referallar soni: {user.referral_count} ta\n"
            f"💰 Minimal yechib olish: {format_balance(settings.minimum_withdrawal)} ⭐\n"
            f"🔗 Sizning referal havolangiz: {generate_referral_link(message.from_user.id, (await message.bot.get_me()).username)}\n\n"
            f"⭐ Stars yechib olish uchun pastdagi tugmani bosing!"
        )
        
        # Stars yechib olish tugmasini qo'shish
        if user.balance >= settings.minimum_withdrawal:
            await message.answer(
                "⭐ Stars yechib olish uchun ariza qoldiring!\n\n"
                "📝 Quyidagi formatda yuboring:\n\n"
                "💰 Miqdor: (masalan: 30)\n"
                "👤 Foydalanuvchi nomi: @username\n"
                "🆔 Telegram ID: 123456789\n\n"
                f"⚠️ Diqqat: Maksimal miqdor - {format_balance(user.balance)} ⭐"
            )
        else:
            await message.answer(
                f"❌ Balansingiz yetarli emas!\n\n"
                f"💰 Sizning balansingiz: {format_balance(user.balance)} ⭐\n"
                f"⭐ Minimal yechib olish: {format_balance(settings.minimum_withdrawal)} ⭐\n\n"
                f"🔗 Yana referallar taklif qiling!"
            )

@dp.message(F.text == "⭐ Stars yechib olish")
async def cmd_withdraw(message: Message):
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return
    
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Sizning ma'lumotlaringiz topilmadi!")
            return
        
        if user.balance < settings.minimum_withdrawal:
            await message.answer(
                f"❌ Balansingiz yetarli emas!\n\n"
                f"💰 Sizning balansingiz: {format_balance(user.balance)} ⭐\n"
                f"⭐ Minimal yechib olish: {format_balance(settings.minimum_withdrawal)} ⭐\n\n"
                f"🔗 Yana referallar taklif qiling!"
            )
            return
        
        await message.answer(
            "⭐ Stars yechib olish uchun ariza qoldiring:\n\n"
            "📝 Quyidagi formatda yuboring:\n\n"
            f"💰 Miqdor: (masalan: {format_balance(user.balance)})\n"
            "👤 Foydalanuvchi nomi: @username\n"
            "🆔 Telegram ID: 123456789\n\n"
            f"⚠️ Diqqat: Maksimal miqdor - {format_balance(user.balance)} ⭐"
        )
        
        # Foydalanuvchini ariza qoldirish rejimiga o'tkazamiz
        # Bu yerda state ishlatish kerak, lekin hozircha oddiy usul

@dp.message(F.text == "📞 Admin bilan aloqa")
async def cmd_contact_admin(message: Message):
    print(f"DEBUG: Admin contact button pressed by user {message.from_user.id}")
    
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return
    
    # Admin bilan muloqot xabari
    await message.answer(
        "📞 Admin bilan bog'lanish:\n\n"
        f"👤 Admin: @{settings.admin_username}\n"
        f"🆔 Admin ID: {settings.admin_id}\n\n"
        "📝 Savollaringiz bo'lsa yozing!\n\n"
        "⏰ Admin tez orada javob beradi"
    )
    
    # Adminga xabar yuborish
    try:
        await message.bot.send_message(
            settings.admin_id,
            f"📞 FOYDALANUVCHI MULOQOT SO'RADI!\n\n"
            f"👤 Ism: {message.from_user.first_name}\n"
            f"🆔 ID: {message.from_user.id}\n"
            f"👤 Username: @{message.from_user.username or 'none'}\n\n"
            f"📞 Admin bilan bog'lanish tugmasini bosdi!"
        )
        print(f"DEBUG: Admin notification sent for user {message.from_user.id}")
    except Exception as e:
        print(f"ERROR: Failed to send admin notification: {e}")

@dp.message(F.from_user.id != settings.admin_id)
async def handle_withdraw_request(message: Message):
    """Foydalanuvchining arizasini qabul qilish"""
    text = message.text.strip()
    
    # Agar ariza formatida bo'lsa (miqdor, username yoki ID bor)
    # Lekin tugma matnlari bo'lmasin
    button_texts = ["⭐ Balans", "👥 Referallar", "🔗 Referal havola", "⭐ Stars yechib olish", "📞 Admin bilan aloqa"]
    
    if text not in button_texts and (any(keyword in text.lower() for keyword in ['miqdor:', 'username:', 'id:']) or '💰' in text or any(char.isdigit() for char in text)):
        print(f"DEBUG: Ariza formati topildi: {text}")
        async with async_session_maker() as session:
            result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
            user = result.scalar_one_or_none()
            
            if user:
                print(f"DEBUG: Foydalanuvchi topildi: {user.first_name}, balance: {user.balance}")
                # Miqdorni ajratib olish
                amount = user.balance  # Default - butun balans
                for line in text.split('\n'):
                    if 'miqdor:' in line.lower() or '💰' in line:
                        try:
                            # Raqamlarni ajratib olish
                            numbers = re.findall(r'\d+', line)
                            if numbers:
                                amount = int(numbers[0])
                                print(f"DEBUG: Miqdor topildi: {amount}")
                                break
                        except:
                            pass
                
                if amount < settings.minimum_withdrawal:
                    await message.answer(
                        f"❌ Miqdor yetarli emas!\n\n"
                        f"⭐ Minimal yechib olish: {format_balance(settings.minimum_withdrawal)} ⭐\n"
                        f"💰 Siz kiritgan: {format_balance(amount)} ⭐"
                    )
                    return
                
                if amount > user.balance:
                    await message.answer(
                        f"❌ Balansingiz yetarli emas!\n\n"
                        f"💰 Sizning balansingiz: {format_balance(user.balance)} ⭐\n"
                        f"💰 Siz kiritgan: {format_balance(amount)} ⭐"
                    )
                    return
                
                print(f"DEBUG: Arizani yaratishga tayyor: amount={amount}")
                # Arizani yaratish
                withdrawal = Withdrawal(
                    user_id=user.telegram_id,
                    amount=amount,
                    user_info=text,  # Bu yerda foydalanuvchi ma'lumotlari saqlanadi
                    status="pending"
                )
                session.add(withdrawal)
                await session.commit()
                print(f"DEBUG: Ariza bazaga saqlandi: {withdrawal.id}")
                
                # Adminga xabar yuborish
                try:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"withdraw_action_{withdrawal.id}_approve"),
                            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"withdraw_action_{withdrawal.id}_reject")
                        ]
                    ])
                    
                    await message.bot.send_message(
                        settings.admin_id,
                        f"🆕 YANGI ARIZA!\n\n"
                        f"👤 Foydalanuvchi: {user.first_name}\n"
                        f"🆔 ID: {user.telegram_id}\n"
                        f"💰 Miqdor: {format_balance(amount)} ⭐\n"
                        f"📝 Ariza matni: {text}\n"
                        f"📅 Sana: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                        f"⚠️ Arizani tekshirib, tasdiqlang yoki rad eting!",
                        reply_markup=keyboard
                    )
                    print(f"✅ Ariza adminga yuborildi: {user.first_name}")
                except Exception as e:
                    print(f"❌ Adminga yuborishda xatolik: {e}")
                
                # Foydalanuvchiga javob
                await message.answer(
                    f"✅ Arizangiz qabul qilindi!\n\n"
                    f"💰 Miqdor: {format_balance(amount)} ⭐\n"
                    f"📝 Arizangiz adminga yuborildi\n\n"
                    f"⏳ Admin tekshirib, tasdiqlaydi (1-24 soat)\n"
                )
                
                # Balansni kamaytirish
                user.balance -= amount
                await session.commit()
                print(f"DEBUG: Balans kamaytirildi: {user.balance}")
            else:
                print(f"DEBUG: Foydalanuvchi topilmadi: {message.from_user.id}")
                await message.answer("❌ Sizning ma'lumotlaringiz topilmadi!")
    else:
        print(f"DEBUG: Ariza formati emas: {text}")
        await message.answer(
            "❌ Ariza formati noto'g'ri!\n\n"
            "📝 To'g'ri format:\n"
            "💰 Miqdor: 30\n"
            "👤 Foydalanuvchi nomi: @username\n"
            "🆔 Telegram ID: 123456789\n\n"
            "⚠️ Iltimos, qayta urinib ko'ring!"
        )

@dp.message(F.text == "📞 Admin bilan aloqa")
async def cmd_contact_admin(message: Message):
    print(f"DEBUG: Admin contact button pressed by user {message.from_user.id}")
    
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return
    
    # Admin bilan muloqot xabari
    await message.answer(
        "📞 Admin bilan bog'lanish:\n\n"
        f"👤 Admin: @{settings.admin_username}\n"
        f"🆔 Admin ID: {settings.admin_id}\n\n"
        "📝 Savollaringiz bo'lsa yozing!\n\n"
        "⏰ Admin tez orada javob beradi"
    )
    
    # Adminga xabar yuborish
    try:
        await message.bot.send_message(
            settings.admin_id,
            f"📞 FOYDALANUVCHI MULOQOT SO'RADI!\n\n"
            f"👤 Ism: {message.from_user.first_name}\n"
            f"🆔 ID: {message.from_user.id}\n"
            f"👤 Username: @{message.from_user.username or 'none'}\n\n"
            f"📞 Admin bilan bog'lanish tugmasini bosdi!"
        )
        print(f"DEBUG: Admin notification sent for user {message.from_user.id}")
    except Exception as e:
        print(f"ERROR: Failed to send admin notification: {e}")

# Admin handlers
@dp.callback_query(F.data.startswith("withdraw_action_"))
async def admin_withdraw_action(callback: CallbackQuery):
    """Admin arizani tasdiqlaydi yoki rad etdi"""
    print(f"DEBUG: Callback received: {callback.data}")
    print(f"DEBUG: Admin ID: {callback.from_user.id}, Required: {settings.admin_id}")
    
    if callback.from_user.id != settings.admin_id:
        print(f"DEBUG: Admin check failed - not admin")
        await callback.answer("❌ Siz admin emassiz!")
        return
    
    print(f"DEBUG: Admin check passed")
    
    # Callback formatini tekshirish: withdraw_action_1_approve
    if not callback.data.startswith("withdraw_action_"):
        log_error(f"Invalid callback prefix: {callback.data}")
        await callback.answer("❌ Noto'g'ri callback format!")
        return
    
    # Ma'lumotlarni ajratish
    parts = callback.data.split("_")
    if len(parts) != 3:
        log_error(f"Invalid callback format: {callback.data}, parts: {parts}")
        await callback.answer("❌ Noto'g'ri callback format!")
        return
    
    action = parts[2]  # approve yoki reject
    withdrawal_id_str = parts[1]
    
    # ID ni tekshirish - faqat raqam va minimal 2 xonali
    if not withdrawal_id_str.isdigit():
        log_error(f"Invalid withdrawal ID: {withdrawal_id_str}")
        await callback.answer("❌ Noto'g'ri callback format! ID kamida 2 ta raqamdan iborat bo'lishi kerak.")
        return
    
    withdrawal_id = int(withdrawal_id_str)
    log_info(f"Action={action}, Withdrawal ID={withdrawal_id}")
    
    # Callback answer qilish
    await callback.answer("✅ Ariza boshqarildi!")
    log_info(f"Action completed: {action}")
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(Withdrawal).where(Withdrawal.id == withdrawal_id)
        )
        withdrawal = result.scalar_one_or_none()
        
        if not withdrawal:
            print(f"DEBUG: Withdrawal not found: {withdrawal_id}")
            await callback.answer("❌ Ariza topilmadi!")
            return
        
        print(f"DEBUG: Withdrawal found: {withdrawal.id}, status={withdrawal.status}")
        
        # Foydalanuvchini topish
        user_result = await session.execute(
            select(User).where(User.telegram_id == withdrawal.user_id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            print(f"DEBUG: User not found: {withdrawal.user_id}")
            await callback.answer("❌ Foydalanuvchi topilmadi!")
            return
        
        print(f"DEBUG: User found: {user.first_name}")
        
        if action == "approve":
            withdrawal.status = "approved"
            await session.commit()
            print(f"DEBUG: Withdrawal approved, status updated to {withdrawal.status}")
            
            # Foydalanuvchiga xabar
            try:
                await callback.bot.send_message(
                    withdrawal.user_id,
                    f"🎉 ARIZANGIZ TASDIQLANDI!\n\n"
                    f"💰 Miqdor: {format_balance(withdrawal.amount)} ⭐\n"
                    f"📝 Ma'lumotlar: {withdrawal.user_info}\n\n"
                    f"✅ Admin tomonidan tasdiqlandi!\n"
                    f"🚀 Pul yuborilmoqda...\n\n"
                    f"📞 Savollar: @{settings.admin_username}"
                )
                print(f"DEBUG: User notification sent")
            except Exception as e:
                print(f"Error sending user notification: {e}")
            
            await callback.message.edit_text(
                f"✅ ARIZA TASDIQLANDI!\n\n"
                f"👤 Foydalanuvchi: {user.first_name}\n"
                f"💰 Miqdor: {format_balance(withdrawal.amount)} ⭐\n"
                f"📝 Ma'lumotlar: {withdrawal.user_info}\n\n"
                f"🎉 Pul yuborildi!"
            )
            print(f"DEBUG: Admin message updated")
            
        elif action == "reject":
            withdrawal.status = "rejected"
            print(f"DEBUG: Withdrawal rejected, status updated to {withdrawal.status}")
            
            # Pulni qaytarib berish
            user.balance += withdrawal.amount
            await session.commit()
            print(f"DEBUG: Balance restored: {user.balance}")
            
            # Foydalanuvchiga xabar
            try:
                await callback.bot.send_message(
                    withdrawal.user_id,
                    f"❌ ARIZANGIZ RAD ETILDI!\n\n"
                    f"💰 Miqdor: {format_balance(withdrawal.amount)} ⭐\n"
                    f"📝 Ma'lumotlar: {withdrawal.user_info}\n\n"
                    f"❌ Admin tomonidan rad etildi\n"
                    f"💸 Pul balansingizga qaytarildi\n"
                    f"📊 Yangi balans: {format_balance(user.balance)} ⭐\n\n"
                    f"📞 Savollar: @{settings.admin_username}"
                )
                print(f"DEBUG: User rejection notification sent")
            except Exception as e:
                print(f"Error sending user rejection notification: {e}")
            
            await callback.message.edit_text(
                f"❌ ARIZA RAD ETILDI!\n\n"
                f"👤 Foydalanuvchi: {user.first_name}\n"
                f"💰 Miqdor: {format_balance(withdrawal.amount)} ⭐\n"
                f"📝 Ma'lumotlar: {withdrawal.user_info}\n\n"
                f"💸 Pul balansga qaytarildi"
            )
            print(f"DEBUG: Admin rejection message updated")
        
        await callback.answer("✅ Ariza boshqarildi!")
        print(f"DEBUG: Action completed: {action}")

@dp.message(F.text == "👥 Foydalanuvchilar")
async def admin_users_list(message: Message):
    if message.from_user.id != settings.admin_id:
        return
    
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return

    async with async_session_maker() as session:
        # Umumiy statistika
        user_count_result = await session.execute(select(func.count(User.id)))
        total_users = user_count_result.scalar()
        
        balance_result = await session.execute(select(func.sum(User.balance)))
        total_balance = balance_result.scalar() or 0
        
        # Oxirgi foydalanuvchilar
        result = await session.execute(
            select(User).order_by(User.created_at.desc()).limit(10)
        )
        users = result.scalars().all()

        # Umumiy statistika xabari
        stats_text = f"📊 **UMUMIY STATISTIKA**\n\n"
        stats_text += f"👥 Jami foydalanuvchilar: {total_users} ta\n"
        stats_text += f"⭐ Jami balans: {format_balance(total_balance)} ⭐\n"
        stats_text += f"📊 O'rtacha balans: {format_balance(total_balance // total_users if total_users > 0 else 0)} ⭐\n\n"
        
        # Oxirgi foydalanuvchilar
        stats_text += "👥 **OXIRGI FOYDALANUVCHILAR**\n\n"
        
        for user in users:
            stats_text += f"👤 {user.first_name} (@{user.username or 'none'})\n"
            stats_text += f"⭐ Balans: {format_balance(user.balance)} ⭐\n"
            stats_text += f"🆔 ID: {user.telegram_id}\n"
            stats_text += f"👥 Referallar: {user.referral_count} ta\n\n"

        await message.answer(stats_text)

@dp.message(F.text == "⭐ Balansni o'zgartirish")
async def admin_balance_change(message: Message):
    if message.from_user.id != settings.admin_id:
        return
    
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return
    
    await message.answer(
        "⭐ Balansni o'zgartirish:\n\n"
        "Format: `user_id +/-summa`\n\n"
        "Masalan:\n"
        "123456789 +50\n"
        "123456789 -20"
    )

@dp.message(F.text == "📊 Statistika")
async def admin_statistics(message: Message):
    if message.from_user.id != settings.admin_id:
        return
    
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return

    async with async_session_maker() as session:
        user_count_result = await session.execute(select(func.count(User.id)))
        user_count = user_count_result.scalar()

        balance_result = await session.execute(select(func.sum(User.balance)))
        total_balance = balance_result.scalar() or 0

        text = f"📊 **Bot statistikasi:**\n\n"
        text += f"👥 Jami foydalanuvchilar: {user_count} ta\n"
        text += f"⭐ Jami balans: {format_balance(total_balance)} ⭐\n\n"
        text += f"⭐ Minimal yechib olish: {format_balance(settings.minimum_withdrawal)} ⭐\n"
        text += f"🎁 Referal mukofoti: {format_balance(settings.referral_reward)} ⭐"

        await message.answer(text)

@dp.message(F.text == "⚙️ Sozlamalar")
async def admin_settings(message: Message):
    if message.from_user.id != settings.admin_id:
        return
    
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return
    
    text = f"⚙️ Bot sozlamalari:\n\n"
    text += f"🤖 Admin: @{settings.admin_username}\n"
    text += f"🆔 Admin ID: {settings.admin_id}\n"
    text += f"⭐ Referal mukofoti: {settings.referral_reward} ⭐\n"
    text += f"⭐ Minimal yechib olish: {settings.minimum_withdrawal} ⭐\n"
    text += f"📺 Sponsor kanallar: {len(settings.sponsor_channels_list)} ta\n"
    railway_status = "Ha" if settings.is_railway else "Yo'q"
    text += f"🚀 Railway rejimi: {railway_status}"
    
    await message.answer(text)

@dp.message(F.text == "📢 Xabar yuborish")
async def admin_broadcast(message: Message):
    if message.from_user.id != settings.admin_id:
        return
    
    if not await check_subscription(message.from_user.id, message.bot):
        await message.answer(
            "🔒 Botdan to'liq foydalanish uchun homiy kanallarimizga obuna bo'ling!\n\n"
            "📺 Obuna bo'lgandan so'ng barcha funktsiyalar mavjud bo'ladi.",
            reply_markup=restricted_menu()
        )
        return
    
    await message.answer(
        "📢 Xabar yuborish:\n\n"
        "Yubormoqchi bo'lgan xabaringizni yozing.\n"
        "Xabar barcha foydalanuvchilarga yuboriladi.\n\n"
        "❌ Bekor qilish uchun 'bekor' deb yozing."
    )

@dp.message(F.text == "📺 Homiy kanallar")
async def admin_sponsor_channels(message: Message):
    if message.from_user.id != settings.admin_id:
        return

    current_channels = settings.sponsor_channels_list
    if current_channels:
        text = f"📺 Joriy homiy kanallar:\n\n"
        for i, channel in enumerate(current_channels, 1):
            text += f"{i}. {channel}\n"
        text += f"\nJami: {len(current_channels)} ta kanal\n\n"
        text += "🔧 Kanallarni boshqarish:\n"
        text += "• Kanal qo'shish: /addchannel @kanal_nomi\n"
        text += "• Kanal o'chirish: /removechannel @kanal_nomi\n"
        text += "• Barcha kanallarni o'chirish: /clearchannels"
    else:
        text = "📺 Homiy kanallar yo'q\n\n"
        text += "🔧 Kanal qo'shish uchun:\n"
        text += "/addchannel @kanal_nomi"
    
    await message.answer(text)

# Command handlers
@dp.message(Command("addchannel"))
async def add_sponsor_channel(message: Message):
    print(f"DEBUG: addchannel command received: '{message.text}'")
    if message.from_user.id != settings.admin_id:
        await message.answer("❌ Siz admin emassiz!")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ Noto'g'ri format!\n\n"
            "To'g'ri format:\n"
            "/addchannel @kanal_nomi"
        )
        return

    channel = parts[1].strip()
    if not channel.startswith('@'):
        channel = '@' + channel

    current_channels = settings.sponsor_channels_list
    print(f"DEBUG: Current channels before adding: {current_channels}")
    print(f"DEBUG: Adding channel: {channel}")
    
    if channel in current_channels:
        await message.answer(f"❌ Kanal allaqachon qo'shilgan: {channel}")
        return

    current_channels.append(channel)
    settings.sponsor_channels = ','.join(current_channels)
    
    print(f"DEBUG: Updated sponsor_channels: {settings.sponsor_channels}")
    print(f"DEBUG: Updated sponsor_channels_list: {settings.sponsor_channels_list}")
    
    await message.answer(
        f"✅ Kanal muvaffaqiyatli qo'shildi!\n\n"
        f"📺 {channel}\n"
        f"📊 Jami kanallar: {len(current_channels)} ta\n"
        f"💾 Bot qayta ishga tushganda ham eslab qolinadi"
    )

@dp.message(Command("removechannel"))
async def remove_sponsor_channel(message: Message):
    print(f"DEBUG: removechannel command received: '{message.text}'")
    if message.from_user.id != settings.admin_id:
        await message.answer("❌ Siz admin emassiz!")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ Noto'g'ri format!\n\n"
            "To'g'ri format:\n"
            "/removechannel @kanal_nomi"
        )
        return

    channel = parts[1].strip()
    if not channel.startswith('@'):
        channel = '@' + channel

    current_channels = settings.sponsor_channels_list
    if channel not in current_channels:
        await message.answer(f"❌ Kanal topilmadi: {channel}")
        return

    current_channels.remove(channel)
    settings.sponsor_channels = ','.join(current_channels)
    
    await message.answer(
        f"✅ Kanal muvaffaqiyatli o'chirildi!\n\n"
        f"📺 {channel}\n"
        f"📊 Qolgan kanallar: {len(current_channels)} ta\n"
        f"💾 Bot qayta ishga tushganda ham eslab qolinadi"
    )

@dp.message(Command("clearchannels"))
async def clear_sponsor_channels(message: Message):
    print(f"DEBUG: clearchannels command received: '{message.text}'")
    if message.from_user.id != settings.admin_id:
        await message.answer("❌ Siz admin emassiz!")
        return

    settings.sponsor_channels = ""
    
    await message.answer(
        "✅ Barcha homiy kanallar o'chirildi!\n\n"
        "📺 Endi hech qanday kanal yo'q\n"
        "🔧 Yangi kanal qo'shish uchun:\n"
        "/addchannel @kanal_nomi"
    )

# Balance change handler
@dp.message(F.text.regexp(r'^\d+ [+-]\d+$'))
async def process_balance_change(message: Message):
    if message.from_user.id != settings.admin_id:
        return

    try:
        parts = message.text.split()
        user_id = int(parts[0])
        operation = parts[1]
        amount = int(operation[1:])

        async with async_session_maker() as session:
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                await message.answer(f"❌ Foydalanuvchi topilmadi: {user_id}")
                return
            
            if operation.startswith('+'):
                user.balance += amount
            else:
                if user.balance < amount:
                    await message.answer(f"❌ Yetarli balans yo'q! Joriy balans: {format_balance(user.balance)} ⭐")
                    return
                user.balance -= amount
            
            await session.commit()
            
            await message.answer(
                f"✅ Balans muvaffaqiyatli o'zgartirildi!\n\n"
                f"👤 Foydalanuvchi: {user.first_name}\n"
                f"⭐ Miqdor: {operation}{format_balance(amount)} ⭐\n"
                f"📊 Yangi balans: {format_balance(user.balance)} ⭐"
            )
            
    except Exception as e:
        await message.answer(f"❌ Xatolik: {str(e)}")

# Admin broadcast handlers
@dp.message(F.from_user.id == settings.admin_id, F.forward_from_chat)
async def handle_admin_forward_broadcast(message: Message):
    try:
        async with async_session_maker() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
            
            success_count = 0
            error_count = 0
            
            for user in users:
                try:
                    await message.bot.forward_message(
                        chat_id=user.telegram_id,
                        from_chat_id=message.forward_from_chat.id,
                        message_id=message.forward_from_message_id
                    )
                    success_count += 1
                except Exception:
                    error_count += 1
            
            await message.answer(
                f"✅ Forward xabar yuborildi!\n\n"
                f"📊 Muvaffaqiyatli: {success_count} ta\n"
                f"❌ Xatolik: {error_count} ta\n"
                f"👥 Jami: {len(users)} ta foydalanuvchi"
            )
            
    except Exception:
        await message.answer("❌ Forward xabar yuborishda xatolik yuz berdi!")

@dp.message(F.from_user.id == settings.admin_id, F.text & ~F.command)
async def handle_admin_text_broadcast(message: Message):
    message_text = message.text.strip()
    
    print(f"DEBUG: Admin text received: '{message_text}'")
    
    button_texts = [
        "👥 Foydalanuvchilar", "⭐ Balansni o'zgartirish", "📊 Statistika", 
        "⚙️ Sozlamalar", "📢 Xabar yuborish", "📺 Homiy kanallar"
    ]
    
    if message_text in button_texts:
        print(f"DEBUG: Button text detected, skipping broadcast")
        return
    
    if message_text.lower() == 'bekor':
        await message.answer("❌ Xabar yuborish bekor qilindi.")
        return
    
    print(f"DEBUG: Starting broadcast to all users")
    try:
        async with async_session_maker() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
            
            success_count = 0
            error_count = 0
            
            for user in users:
                try:
                    await message.bot.send_message(
                        user.telegram_id,
                        f"📢 ADMIN XABARI\n\n{message_text}"
                    )
                    success_count += 1
                except Exception:
                    error_count += 1
            
            await message.answer(
                f"✅ Xabar yuborildi!\n\n"
                f"📊 Muvaffaqiyatli: {success_count} ta\n"
                f"❌ Xatolik: {error_count} ta\n"
                f"👥 Jami: {len(users)} ta foydalanuvchi"
            )
            
    except Exception:
        await message.answer("❌ Xabar yuborishda xatolik yuz berdi!")

# ==================== MAIN ====================
async def main():
    await init_db()
    bot = Bot(token=settings.bot_token)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Bot to'xtatildi")
    except Exception as e:
        print(f"❌ Xatolik: {e}")
        sys.exit(1)
