import asyncio
import os
import io
import logging
import random
import sqlite3
import time
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BotCommand, BufferedInputFile
from aiohttp import web

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TOKEN = os.getenv("BOT_TOKEN") 

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- СТАН ГРИ В МАФІЮ ---
mafia_lobby = {}      
mafia_roles = {}      
is_mafia_running = False

# --- ТАЙМЕРИ ТА НАЛАШТУВАННЯ ---
RPG_COOLDOWN = 60  # 1 хвилина між походами
user_last_dungeon = {}
PREGNANCY_DURATION = 7 * 86400  # 7 днів у секундах

# --- БАЗА ДАНИХ ---
def init_db():
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            gender TEXT DEFAULT 'm'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reputation (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            karma INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS marriages (
            user1_id INTEGER PRIMARY KEY,
            user1_name TEXT,
            user2_id INTEGER,
            user2_name TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS families (
            family_name TEXT PRIMARY KEY,
            owner_id INTEGER,
            owner_name TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_members (
            user_id INTEGER PRIMARY KEY,
            family_name TEXT,
            user_name TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            timestamp REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rpg_players (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            p_class TEXT DEFAULT 'Лицар',
            level INTEGER DEFAULT 1,
            exp INTEGER DEFAULT 0,
            hp INTEGER DEFAULT 120,
            max_hp INTEGER DEFAULT 120,
            attack INTEGER DEFAULT 12,
            defense INTEGER DEFAULT 5,
            gold INTEGER DEFAULT 50,
            weapon TEXT DEFAULT 'Іржавий меч',
            armor TEXT DEFAULT 'Шкіряний панцир'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pregnancies (
            mother_id INTEGER PRIMARY KEY,
            mother_name TEXT,
            father_id INTEGER,
            father_name TEXT,
            start_time REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS children (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mother_id INTEGER,
            father_id INTEGER,
            child_name TEXT,
            gender TEXT
        )
    """)
    conn.commit()
    conn.close()

# --- ФУНКЦІЇ БАЗИ ДАНИХ ---
def log_message(user_id: int, username: str):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO message_logs (user_id, username, timestamp) VALUES (?, ?, ?)", 
                   (user_id, username, time.time()))
    conn.commit()
    conn.close()

def set_user_gender(user_id: int, username: str, gender: str):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, username, gender) VALUES (?, ?, ?)", 
                   (user_id, username, gender))
    conn.commit()
    conn.close()

def get_user_gender(user_id: int):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT gender FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 'm'

def add_karma(user_id: int, username: str, amount: int = 1):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT karma FROM reputation WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO reputation (user_id, username, karma) VALUES (?, ?, ?)", (user_id, username, amount))
    else:
        cursor.execute("UPDATE reputation SET karma = karma + ?, username = ? WHERE user_id = ?", (amount, username, user_id))
    conn.commit()
    conn.close()

def get_top_users():
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, karma FROM reputation ORDER BY karma DESC LIMIT 5")
    top = cursor.fetchall()
    conn.close()
    return top

def get_marriage(user_id: int):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user1_id, user1_name, user2_id, user2_name FROM marriages WHERE user1_id = ? OR user2_id = ?", (user_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row

def create_marriage(u1_id, u1_name, u2_id, u2_name):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO marriages (user1_id, user1_name, user2_id, user2_name) VALUES (?, ?, ?, ?)", (u1_id, u1_name, u2_id, u2_name))
    conn.commit()
    conn.close()

def break_marriage(user_id: int):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM marriages WHERE user1_id = ? OR user2_id = ?", (user_id, user_id))
    conn.commit()
    conn.close()

def create_family(family_name: str, owner_id: int, owner_name: str):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO families (family_name, owner_id, owner_name) VALUES (?, ?, ?)", (family_name, owner_id, owner_name))
        cursor.execute("INSERT OR REPLACE INTO family_members (user_id, family_name, user_name) VALUES (?, ?, ?)", (owner_id, family_name, owner_name))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def get_rpg_player(user_id: int, username: str):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, p_class, level, exp, hp, max_hp, attack, defense, gold, weapon, armor FROM rpg_players WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("""
            INSERT INTO rpg_players (user_id, username, p_class, level, exp, hp, max_hp, attack, defense, gold, weapon, armor)
            VALUES (?, ?, 'Лицар', 1, 0, 120, 120, 12, 5, 50, 'Іржавий меч', 'Шкіряний панцир')
        """, (user_id, username))
        conn.commit()
        cursor.execute("SELECT user_id, username, p_class, level, exp, hp, max_hp, attack, defense, gold, weapon, armor FROM rpg_players WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    conn.close()
    return row

def update_rpg_player(user_id: int, **kwargs):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    values = list(kwargs.values()) + [user_id]
    cursor.execute(f"UPDATE rpg_players SET {fields} WHERE user_id = ?", values)
    conn.commit()
    conn.close()

# --- ВАГІТНІСТЬ ТА ДІТИ ---
def start_pregnancy(mother_id, mother_name, father_id, father_name):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO pregnancies (mother_id, mother_name, father_id, father_name, start_time) VALUES (?, ?, ?, ?, ?)",
                   (mother_id, mother_name, father_id, father_name, time.time()))
    conn.commit()
    conn.close()

def get_pregnancy(user_id):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT mother_id, mother_name, father_id, father_name, start_time FROM pregnancies WHERE mother_id = ? OR father_id = ?", (user_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row

def finish_pregnancy(mother_id, father_id, child_name, gender):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pregnancies WHERE mother_id = ?", (mother_id,))
    cursor.execute("INSERT INTO children (mother_id, father_id, child_name, gender) VALUES (?, ?, ?, ?)", (mother_id, father_id, child_name, gender))
    conn.commit()
    conn.close()

def get_children(user_id):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT child_name, gender FROM children WHERE mother_id = ? OR father_id = ?", (user_id, user_id))
    rows = cursor.fetchall()
    conn.close()
    return rows

# --- ГЕНЕРАТОР ГРАФІКІВ ---
def generate_activity_chart(username: str, data_points: list):
    fig, ax = plt.subplots(figsize=(6, 3.2), facecolor='#171a21')
    ax.set_facecolor('#171a21')
    ax.plot(data_points, color='#f3c653', linewidth=2.5, marker='o', markersize=4, markerfacecolor='#ffffff')
    ax.fill_between(range(len(data_points)), data_points, color='#f3c653', alpha=0.25)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#4e5568')
    ax.spines['bottom'].set_color('#4e5568')
    ax.tick_params(colors='#8c95a8', labelsize=8)
    ax.grid(color='#262b36', linestyle='--', linewidth=0.5, alpha=0.7)
    plt.title(f"Статистика ✦{username}✦", color='#ffffff', fontsize=11, fontweight='bold', pad=10)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, facecolor=fig.get_facecolor(), edgecolor='none')
    buf.seek(0)
    plt.close(fig)
    return buf.read()


# --- БУНКЕР ТА СЮЖЕТНІ ПОВЕРХИ ---
PROFESSIONS = ["Програміст", "Лікар", "Пожежник", "Кухар", "Еколог", "Психолог", "Будівельник", "Електрик"]
HEALTH_CONDITIONS = ["Повністю здоровий", "Астма", "Слабке серце", "Зір -4", "Алергія", "Хронічна втома"]
HOBBIES = ["Виживання", "Альпінізм", "Риболовля", "Стрільба з лука", "Садівництво", "Радіоаматорство"]
PHOBIAS = ["Клаустрофобія", "Арахнофобія", "Акрофобія", "Соціофобія", "Ніксофобія", "Немає фобій"]
INVENTORY = ["Аптечка", "Мисливський ніж", "Ліхтарик", "Мотузка", "Рація", "Консерви", "Фільтр для води"]

FLOORS = {
    1: {
        "name": "🦇 Поверх 1: Забуті Печери",
        "monsters": [
            {"name": "Дикий Кажан 🦇", "hp": 35, "atk": 6, "exp": 25, "gold": 15, "img": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600"},
            {"name": "Гоблін-Розбійник 👺", "hp": 50, "atk": 9, "exp": 40, "gold": 25, "img": "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600"}
        ],
        "boss": {"name": "Бос: Гоблін-Ватажок 👑👺", "hp": 120, "atk": 18, "exp": 120, "gold": 90, "img": "https://images.unsplash.com/photo-1563089145-599997674d42?w=600"}
    },
    2: {
        "name": "🏰 Поверх 2: Темна Цитадель",
        "monsters": [
            {"name": "Скелет-Воїн 💀", "hp": 80, "atk": 14, "exp": 60, "gold": 40, "img": "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?w=600"},
            {"name": "Орк-Берсерк 👹", "hp": 100, "atk": 18, "exp": 85, "gold": 60, "img": "https://images.unsplash.com/photo-1563089145-599997674d42?w=600"}
        ],
        "boss": {"name": "Бос: Лицар-Ренегат ⚔️💀", "hp": 200, "atk": 28, "exp": 250, "gold": 180, "img": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600"}
    },
    3: {
        "name": "🔥 Поверх 3: Вогненна Безодня",
        "monsters": [
            {"name": "Лавовий Слимак 🌋", "hp": 130, "atk": 22, "exp": 110, "gold": 80, "img": "https://images.unsplash.com/photo-1579783902614-a3fb3927b675?w=600"},
            {"name": "Демонічний Псих 👿", "hp": 150, "atk": 26, "exp": 140, "gold": 100, "img": "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600"}
        ],
        "boss": {"name": "Бос: Архімаг Тьми 🧙‍♂️🔥", "hp": 320, "atk": 40, "exp": 450, "gold": 320, "img": "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?w=600"}
    },
    4: {
        "name": "🧊 Поверх 4: Льодяний Пік",
        "monsters": [
            {"name": "Сніжний Елементаль ❄️", "hp": 180, "atk": 30, "exp": 180, "gold": 130, "img": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600"},
            {"name": "Крижаний Вовк 🐺🧊", "hp": 210, "atk": 35, "exp": 220, "gold": 160, "img": "https://images.unsplash.com/photo-1564466809058-bf4114d55352?w=600"}
        ],
        "boss": {"name": "Бос: Крижаний Голем 🗿❄️", "hp": 450, "atk": 55, "exp": 700, "gold": 500, "img": "https://images.unsplash.com/photo-1563089145-599997674d42?w=600"}
    },
    5: {
        "name": "🐉 Поверх 5: Лігво Дракона Хаосу (Фінал)",
        "monsters": [
            {"name": "Елітний Страж Дракона 🐉", "hp": 260, "atk": 42, "exp": 300, "gold": 220, "img": "https://images.unsplash.com/photo-1579783902614-a3fb3927b675?w=600"}
        ],
        "boss": {"name": "ФІНАЛЬНИЙ БОС: Дракон Хаосу 🐉🔥👑", "hp": 700, "atk": 75, "exp": 1500, "gold": 1000, "img": "https://images.unsplash.com/photo-1579783902614-a3fb3927b675?w=600"}
    }
}

CHEST_IMG = "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600"
SHOP_IMG = "https://images.unsplash.com/photo-1555680202-c86f0e12f086?w=600"

SHOP_ITEMS = {
    "1": {"name": "Міфічний Меч 🗡✨", "type": "weapon", "atk": 30, "cost": 150},
    "2": {"name": "С посох Архімага 🪄🔮", "type": "weapon", "atk": 50, "cost": 300},
    "3": {"name": "Місцеві Лати 🛡", "type": "armor", "def": 15, "cost": 180},
    "4": {"name": "Драконяча Броня 🛡🔥", "type": "armor", "def": 30, "cost": 350}
}


# --- ОБРОБНИКИ КОМАНД ---

@dp.message((F.text == "/start") | (F.text == "/старт") | (F.text == "/допомога"))
async def start_handler(message: Message):
    await message.answer(
        "Привіт! Я Minazuki Flood 🤖\n\n"
        "⚔️ **RPG Підземелля (5 поверхів + Класи + Боси):**\n"
        "• `/клас` — обрати свій клас (Лицар, Маг, Медик, Лучник)\n"
        "• `/похід` — вирушити в підземелля на битву\n"
        "• `/герой` — профіль вашого персонажа\n"
        "• `/магазин` — придбати спорядження\n"
        "• `/купити [1-4]` — купити предмет\n"
        "• `/відпочинок` — відновити здоров'я (HP)\n\n"
        "👶 **Сім'я та Вагітність:**\n"
        "• `/дитина` — спробувати завагітніти (тільки жінки у шлюбі!)\n"
        "• `/вагітність` — стан вагітності (триває 7 днів)\n"
        "• `/народити [Ім'я]` — народити малюка після 7 днів\n"
        "• `/діти` — список ваших дітей\n"
        "• `/дитячий_магазин` — товари для вагітності й дітей\n\n"
        "💍 **Шлюби та Сім'ї:** `/одружитися`, `/пара`, `/розлучитися`, `/створити_сімю [Назва]`\n"
        "❤️ **Взаємодії:** `/обійняти`, `/комплімент`, `/поцілувати`, `/кусь`, `/погладити`, `/підтримати`\n"
        "📊 **Статистика:** `/профіль` (або 'хто я'), `/день`, `/тиждень`, `/місяць`, `/весь_час`\n"
        "🕵️‍♂️ **Інше:** `/бункер`, `/рег_мафія`, `/старт_мафія`, `/топ_репутації`"
    )

# --- ВИБІР КЛАСУ ТА RPG ---
@dp.message(F.text == "/клас")
async def choose_class_menu(message: Message):
    await message.answer(
        "🛡️ **Оберіть свій клас героя:**\n\n"
        "1️⃣ **Лицар** — високий захист та HP (`/клас лицар`)\n"
        "2️⃣ **Маг** — руйнівна атака (`/клас маг`)\n"
        "3️⃣ **Медик** — здатність лікуватися (`/клас медик`)\n"
        "4️⃣ **Лучник** — швидкість і крит. ушкодження (`/клас лучник`)"
    )

@dp.message(F.text.startswith("/клас "))
async def set_class_handler(message: Message):
    c_name = message.text.split(maxsplit=1)[1].strip().capitalize()
    classes_dict = {
        "Лицар": {"hp": 150, "atk": 12, "def": 8, "weapon": "Меч Лицаря", "armor": "Лати"},
        "Маг": {"hp": 90, "atk": 22, "def": 3, "weapon": "Посох Учня", "armor": "Мантія"},
        "Медик": {"hp": 130, "atk": 10, "def": 6, "weapon": "Скальпель", "armor": "Халат"},
        "Лучник": {"hp": 110, "atk": 18, "def": 4, "weapon": "Мисливський лук", "armor": "Шкірянка"}
    }
    if c_name not in classes_dict:
        return await message.answer("⚠️ Невірний клас! Виберіть: Лицар, Маг, Медик або Лучник.")
    
    stats = classes_dict[c_name]
    uid = message.from_user.id
    get_rpg_player(uid, message.from_user.first_name)
    update_rpg_player(uid, p_class=c_name, hp=stats["hp"], max_hp=stats["hp"], attack=stats["atk"], defense=stats["def"], weapon=stats["weapon"], armor=stats["armor"])
    await message.answer(f"🎉 Вітаю! Ви успішно обрали клас **{c_name}**! Характеристики оновлено.")

@dp.message((F.text == "/герой") | (F.text == "/персонаж"))
async def rpg_hero_handler(message: Message):
    p = get_rpg_player(message.from_user.id, message.from_user.first_name)
    _, name, p_class, lvl, exp, hp, max_hp, atk, df, gold, weapon, armor = p
    next_exp = lvl * 120
    floor_num = min(5, (lvl // 3) + 1)
    
    text = (
        f"🗡 **Герой @{name} [{p_class}]:**\n\n"
        f"🏔 Поверх підземелля: **{floor_num} з 5**\n"
        f"🎖 Рівень: **{lvl}** (EXP: {exp}/{next_exp})\n"
        f"❤️ Здоров'я: **{hp}/{max_hp} HP**\n"
        f"⚔️ Атака: **{atk}** | 🛡 Захист: **{df}**\n"
        f"💰 Золото: **{gold}** монет\n\n"
        f"🗡 Зброя: {weapon}\n"
        f"🛡 Броня: {armor}"
    )
    await message.answer(text)

@dp.message((F.text == "/похід") | (F.text == "/підземелля"))
async def rpg_dungeon_handler(message: Message):
    uid = message.from_user.id
    now = time.time()

    if uid in user_last_dungeon and (now - user_last_dungeon[uid]) < RPG_COOLDOWN:
        rem = int(RPG_COOLDOWN - (now - user_last_dungeon[uid]))
        return await message.answer(f"⏳ Герой відпочиває. Зачекайте **{rem} сек.** перед наступним походом.")

    p = get_rpg_player(uid, message.from_user.first_name)
    _, name, p_class, lvl, exp, hp, max_hp, atk, df, gold, weapon, armor = p

    if hp <= 15:
        return await message.answer("⚠️ У вас дуже мало HP! Напишіть `/відпочинок`, щоб відновити сили.")

    user_last_dungeon[uid] = now
    floor_idx = min(5, (lvl // 3) + 1)
    current_floor = FLOORS[floor_idx]

    if random.random() < 0.15:
        found_gold = random.randint(40, 100)
        update_rpg_player(uid, gold=gold + found_gold)
        return await message.answer_photo(
            photo=CHEST_IMG,
            caption=f"📦 **{current_floor['name']}**\n\n@{name}, ви знайшли **Загублений Скарб**! 💰 Отримано **+{found_gold}** золота!"
        )

    is_boss = random.random() < 0.25
    enemy = current_floor["boss"].copy() if is_boss else random.choice(current_floor["monsters"]).copy()
    e_name, e_hp, e_atk, e_img = enemy["name"], enemy["hp"], enemy["atk"], enemy["img"]

    crit = 1.5 if p_class == 'Лучник' and random.random() < 0.3 else 1.0
    player_damage = max(1, int((atk + random.randint(-3, 6)) * crit))
    monster_damage = max(1, e_atk - df + random.randint(-2, 3))

    e_hp -= player_damage
    if e_hp <= 0:
        gained_exp = enemy["exp"]
        gained_gold = enemy["gold"]
        new_exp = exp + gained_exp
        new_gold = gold + gained_gold
        
        lvl_up_text = ""
        if new_exp >= lvl * 120:
            lvl += 1
            max_hp += 30
            hp = max_hp
            atk += 7
            df += 3
            lvl_up_text = f"\n\n🎉 **РІВЕНЬ ПІДВИЩЕНО!** Ви тепер **{lvl} рівня**! Стати зросли! ✨"

        update_rpg_player(uid, level=lvl, exp=new_exp, gold=new_gold, hp=hp, max_hp=max_hp, attack=atk, defense=df)
        boss_title = "👑 **ПЕРЕМОГА НАД БОСОМ ПОВЕРХУ!** 👑\n" if is_boss else ""
        crit_msg = "💥 **КРИТИЧНИЙ УДАР!** " if crit > 1 else ""

        caption = (
            f"🏔 **{current_floor['name']}**\n\n"
            f"{boss_title}"
            f"⚔️ Бій проти **{e_name}**!\n"
            f"{crit_msg}Ви завдали **{player_damage}** шкоди!\n\n"
            f"🏆 **Перемога!** Вражаюча здобич:\n"
            f"➕ **+{gained_exp}** EXP | **+{gained_gold}** 💰 золота.{lvl_up_text}"
        )
        await message.answer_photo(photo=e_img, caption=caption)
    else:
        new_hp = max(0, hp - monster_damage)
        if p_class == 'Медик':
            new_hp = min(max_hp, new_hp + 10)
            
        update_rpg_player(uid, hp=new_hp)
        caption = (
            f"🏔 **{current_floor['name']}**\n\n"
            f"⚔️ Сутичка з **{e_name}**!\n"
            f"Ви завдали {player_damage} шкоди, але ворог вдарив у відповідь на **-{monster_damage} HP**!\n\n"
            f"💔 Залишок здоров'я: **{new_hp}/{max_hp} HP**."
        )
        await message.answer_photo(photo=e_img, caption=caption)

@dp.message(F.text == "/магазин")
async def rpg_shop_handler(message: Message):
    text = "🛒 **Лавка легендарного спорядження:**\n\n"
    for k, v in SHOP_ITEMS.items():
        if v["type"] == "weapon":
            text += f"**{k}.** {v['name']} — ⚔️ +{v['atk']} (💰 {v['cost']})\n"
        else:
            text += f"**{k}.** {v['name']} — 🛡 +{v['def']} (💰 {v['cost']})\n"
    text += "\nКупити: `/купити 1`, `/купити 2` тощо."
    await message.answer_photo(photo=SHOP_IMG, caption=text)

@dp.message(F.text.startswith("/купити"))
async def rpg_buy_handler(message: Message):
    args = message.text.split()
    if len(args) < 2 or args[1] not in SHOP_ITEMS:
        return await message.answer("⚠️ Вкажіть номер: `/купити 1`")
    
    item = SHOP_ITEMS[args[1]]
    p = get_rpg_player(message.from_user.id, message.from_user.first_name)
    uid, _, _, _, _, _, _, atk, df, gold, _, _ = p

    if gold < item["cost"]:
        return await message.answer(f"❌ Недостатньо золота! Потрібно {item['cost']}, а у вас лише {gold}.")

    new_gold = gold - item["cost"]
    if item["type"] == "weapon":
        update_rpg_player(uid, gold=new_gold, weapon=item["name"], attack=atk + item["atk"])
        await message.answer(f"✅ Успішно придбано **{item['name']}**! ⚔️ Атака зросла!")
    else:
        update_rpg_player(uid, gold=new_gold, armor=item["name"], defense=df + item["def"])
        await message.answer(f"✅ Успішно придбано **{item['name']}**! 🛡 Захист зріс!")

@dp.message((F.text == "/відпочинок") | (F.text == "/лікування"))
async def rpg_rest_handler(message: Message):
    p = get_rpg_player(message.from_user.id, message.from_user.first_name)
    update_rpg_player(p[0], hp=p[6])
    await message.answer(f"🏕 Герой розклав табір, відпочив і повністю відновив сили! (**{p[6]}/{p[6]} HP**)")


# --- ВАГІТНІСТЬ ТА СІМ'Я ---
@dp.message((F.text == "/baby") | (F.text == "/дитина"))
async def baby_handler(message: Message):
    user = message.from_user
    marriage = get_marriage(user.id)
    if not marriage:
        return await message.answer("💔 Дитину можна завести тільки у шлюбі (`/одружитися`)!")

    u1_id, u1_name, u2_id, u2_name = marriage
    g1, g2 = get_user_gender(u1_id), get_user_gender(u2_id)

    if g1 == 'f':
        mother_id, mother_name = u1_id, u1_name
        father_id, father_name = u2_id, u2_name
    elif g2 == 'f':
        mother_id, mother_name = u2_id, u2_name
        father_id, father_name = u1_id, u1_name
    else:
        return await message.answer("⚠️ У вашій парі немає жінки! Змініть стать командою `/стать ж`.")

    if get_pregnancy(mother_id):
        return await message.answer("🤰 Пара вже очікує на дитину! Перевірте стан через `/вагітність`.")

    if random.choice([True, False]):
        start_pregnancy(mother_id, mother_name, father_id, father_name)
        await message.answer(f"🎉 Вітаємо! @{mother_name} завагітніла від @{father_name}! 🤰✨\nВагітність триватиме **7 днів**. Перевіряйте статус через `/вагітність`!")
    else:
        await message.answer("👩‍❤️‍👨 Спроба була, але поки не вдалося. Спробуйте знову через деякий час! 😉")

@dp.message((F.text == "/pregnancy") | (F.text == "/вагітність"))
async def pregnancy_status_handler(message: Message):
    preg = get_pregnancy(message.from_user.id)
    if not preg:
        return await message.answer("🤷‍♀️ Ваша пара наразі не очікує малюка.")

    m_id, m_name, f_id, f_name, start_t = preg
    passed_sec = time.time() - start_t
    rem_sec = PREGNANCY_DURATION - passed_sec

    if rem_sec <= 0:
        await message.answer(f"🎉 7 днів минуло! @{m_name} готова народити! Напишіть `/народити [Ім'я дитини]`")
    else:
        passed_days = int(passed_sec // 86400) + 1
        hours_left = int(rem_sec // 3600)
        await message.answer(
            f"🤰 **Стан вагітності @{m_name}:**\n\n"
            f"📅 День: **{passed_days} з 7**\n"
            f"⏳ Залишилося часу: **{hours_left} год.**\n"
            f"👨 Тато: @{f_name}\n\n"
            f"💡 Пришвидшити можна в `/дитячий_магазин`!"
        )

@dp.message(F.text.startswith("/народити"))
async def give_birth_handler(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("⚠️ Вкажіть ім'я дитини! Наприклад: `/народити Олексій`")

    child_name = parts[1].strip()
    preg = get_pregnancy(message.from_user.id)
    if not preg:
        return await message.answer("❌ Ваша пара не вагітна.")

    m_id, m_name, f_id, f_name, start_t = preg
    if (time.time() - start_t) < PREGNANCY_DURATION:
        return await message.answer("⏳ 7 днів ще не минуло! Дитина ще формується.")

    gender = random.choice(["Хлопчик 👦", "Дівчинка 👧"])
    finish_pregnancy(m_id, f_id, child_name, gender)
    await message.answer(f"👶🎉 **У РОДИНІ ПОПОВНЕННЯ!**\nУ @{m_name} та @{f_name} народився(лася) **{child_name}** ({gender})! ❤️✨")

@dp.message((F.text == "/діти") | (F.text == "/діточки"))
async def my_children_handler(message: Message):
    kids = get_children(message.from_user.id)
    if not kids:
        return await message.answer("🧸 У вас поки немає дітей.")

    text = "🧸 **Ваші діти:**\n\n"
    for name, g in kids:
        text += f"• **{name}** ({g})\n"
    await message.answer(text)

@dp.message(F.text == "/дитячий_магазин")
async def baby_shop_handler(message: Message):
    text = (
        "🛍 **Дитячий Магазин та Товари для Сім'ї:**\n\n"
        "1️⃣ **🍼 Дитяча суміш** — Пришвидшує вагітність на 12 годин (💰 100 золота)\n"
        "2️⃣ **🧸 М'яке ведмежа** — Дарує +50 репутації родині (💰 150 золота)\n"
        "3️⃣ **🎂 Святковий торт** — Влаштовує сімейне свято (💰 200 золота)\n\n"
        "Щоб купити: `/купити_дитяче 1`, `/купити_дитяче 2`..."
    )
    await message.answer(text)

@dp.message(F.text.startswith("/купити_дитяче"))
async def buy_baby_item(message: Message):
    args = message.text.split()
    if len(args) < 2 or args[1] not in ["1", "2", "3"]:
        return await message.answer("⚠️ Вкажіть номер: `/купити_дитяче 1`")

    uid = message.from_user.id
    p = get_rpg_player(uid, message.from_user.first_name)
    gold = p[9]

    if args[1] == "1":
        if gold < 100: return await message.answer("❌ Потрібно 100 золота!")
        preg = get_pregnancy(uid)
        if not preg: return await message.answer("⚠️ Ваша пара не вагітна.")
        update_rpg_player(uid, gold=gold-100)
        conn = sqlite3.connect("minazuki_bot.db")
        c = conn.cursor()
        c.execute("UPDATE pregnancies SET start_time = start_time - 43200 WHERE mother_id = ? OR father_id = ?", (uid, uid))
        conn.commit(); conn.close()
        await message.answer("🍼 Ви дали дитячу суміш! Час вагітності скорочено на 12 годин! ✨")

    elif args[1] == "2":
        if gold < 150: return await message.answer("❌ Потрібно 150 золота!")
        update_rpg_player(uid, gold=gold-150)
        add_karma(uid, message.from_user.first_name, 50)
        await message.answer("🧸 Ви подарували ведмедика! +50 до репутації родини! ❤️")

    elif args[1] == "3":
        if gold < 200: return await message.answer("❌ Потрібно 200 золота!")
        update_rpg_player(uid, gold=gold-200)
        await message.answer("🎂🎉 Ви влаштували незабутнє сімейне свято з тортом у чаті!")


# --- РЕАКЦІЇ, СТАТЬ ТА ШЛЮБИ ---
@dp.message((F.text.startswith("/gender")) | (F.text.startswith("/стать")))
async def gender_handler(message: Message):
    args = message.text.split()
    if len(args) < 2 or args[1].lower() not in ['ч', 'ж', 'm', 'f']:
        return await message.answer("⚠️ Вкажіть стать: `/стать ч` або `/стать ж`")
    g_code = 'f' if args[1].lower() in ['ж', 'f'] else 'm'
    set_user_gender(message.from_user.id, message.from_user.first_name, g_code)
    await message.answer(f"✅ Стать змінено на {'жіночу 👩' if g_code == 'f' else 'чоловічу 👨'}")

@dp.message((F.text == "/hug") | (F.text == "/обійняти"))
async def hug_h(message: Message):
    if message.reply_to_message:
        await message.answer(f"🤗 @{message.from_user.first_name} обійняв(ла) @{message.reply_to_message.from_user.first_name}!")

@dp.message((F.text == "/compliment") | (F.text == "/комплімент"))
async def comp_h(message: Message):
    if message.reply_to_message:
        await message.answer(f"💖 @{message.from_user.first_name} зробив комплімент @{message.reply_to_message.from_user.first_name}!")

@dp.message((F.text == "/kiss") | (F.text == "/поцілувати"))
async def kiss_h(message: Message):
    if message.reply_to_message:
        await message.answer(f"💋 @{message.from_user.first_name} поцілував(ла) @{message.reply_to_message.from_user.first_name}!")

@dp.message((F.text == "/bite") | (F.text == "/кусь"))
async def bite_h(message: Message):
    if message.reply_to_message:
        await message.answer(f"🦷 @{message.from_user.first_name} зробив 'кусь' для @{message.reply_to_message.from_user.first_name}!")

@dp.message((F.text == "/pat") | (F.text == "/погладити"))
async def pat_h(message: Message):
    if message.reply_to_message:
        await message.answer(f"👋 @{message.from_user.first_name} погладив(ла) @{message.reply_to_message.from_user.first_name}!")

@dp.message((F.text == "/support") | (F.text == "/підтримати"))
async def supp_h(message: Message):
    if message.reply_to_message:
        await message.answer(f"🫂 @{message.from_user.first_name} підтримав(ла) @{message.reply_to_message.from_user.first_name}!")

@dp.message((F.text == "/marry") | (F.text == "/одружитися"))
async def marry_handler(message: Message):
    if not message.reply_to_message:
        return await message.answer("⚠️ Використовуйте реплаєм на повідомлення партнера!")
    sender, target = message.from_user, message.reply_to_message.from_user
    if sender.id == target.id:
        return await message.answer("❤️ Не можна одружитися з собою!")
    if get_marriage(sender.id) or get_marriage(target.id):
        return await message.answer("💔 Хтось із вас уже в шлюбі!")
    create_marriage(sender.id, sender.first_name, target.id, target.first_name)
    await message.answer(f"💒 @{sender.first_name} та @{target.first_name} одружилися! 💍✨")

@dp.message((F.text == "/couple") | (F.text == "/пара"))
async def couple_handler(message: Message):
    m = get_marriage(message.from_user.id)
    if not m:
        return await message.answer("💍 Ви не одружені.")
    partner = m[3] if message.from_user.id == m[0] else m[1]
    await message.answer(f"💖 Ваша пара: **@{partner}**")

@dp.message((F.text == "/divorce") | (F.text == "/розлучитися"))
async def divorce_handler(message: Message):
    if not get_marriage(message.from_user.id):
        return await message.answer("🤷‍♂️ Ви не одружені.")
    break_marriage(message.from_user.id)
    await message.answer("💔 Шлюб розірвано.")

@dp.message((F.text.startswith("/create_family")) | (F.text.startswith("/створити_сімю")))
async def create_fam_handler(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("⚠️ Вкажіть назву: `/створити_сімю [Назва]`")
    if create_family(parts[1].strip(), message.from_user.id, message.from_user.first_name):
        await message.answer(f"🏰 Сім'я **'{parts[1].strip()}'** створена!")
    else:
        await message.answer("❌ Назва зайнята.")


# --- СТАТИСТИКА ТА ПРОФІЛЬ ---
@dp.message((F.text.lower() == "хто я") | (F.text == "/whoami") | (F.text == "/stats") | (F.text == "/профіль"))
async def who_am_i_handler(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    uid, name = target.id, target.first_name

    g_code = get_user_gender(uid)
    gender_text = "Жіноча 👩" if g_code == 'f' else "Чоловіча 👨"

    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT karma FROM reputation WHERE user_id = ?", (uid,))
    k_row = cursor.fetchone()
    karma = k_row[0] if k_row else 0

    cursor.execute("SELECT user1_name, user2_name FROM marriages WHERE user1_id = ? OR user2_id = ?", (uid, uid))
    m_row = cursor.fetchone()
    marriage_text = f"💍 Одружений(а) з @{m_row[1] if name == m_row[0] else m_row[0]}" if m_row else "💍 Не одружений(а)"

    cursor.execute("SELECT family_name FROM family_members WHERE user_id = ?", (uid,))
    f_row = cursor.fetchone()
    family_text = f"🏰 Сім'я: {f_row[0]}" if f_row else "🏰 Поза сім'єю"

    now = time.time()
    cursor.execute("SELECT COUNT(*) FROM message_logs WHERE user_id = ? AND timestamp >= ?", (uid, now - 86400))
    d_msg = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM message_logs WHERE user_id = ? AND timestamp >= ?", (uid, now - 604800))
    w_msg = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM message_logs WHERE user_id = ? AND timestamp >= ?", (uid, now - 2592000))
    m_msg = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM message_logs WHERE user_id = ?", (uid,))
    total_msg = cursor.fetchone()[0]
    conn.close()

    caption = (
        f"📊 **Статистика ✦{name}✦**\n\n"
        f"👤 Стать: {gender_text}\n"
        f"– день: **{d_msg}**\n"
        f"– тиждень: **{w_msg}**\n"
        f"– місяць: **{m_msg}**\n"
        f"– весь час: **{total_msg}**\n\n"
        f"⭐ Репутація: {karma} од.\n"
        f"{marriage_text}\n"
        f"{family_text}"
    )

    chart_points = [max(1, d_msg // 4), max(2, w_msg // 3), max(3, m_msg // 5), max(5, total_msg // 2), max(2, d_msg + 3)]
    photo_bytes = generate_activity_chart(name, chart_points)
    photo_file = BufferedInputFile(photo_bytes, filename="stats.png")

    await message.answer_photo(photo=photo_file, caption=caption)

def get_period_stats(since_time=None):
    conn = sqlite3.connect("minazuki_bot.db")
    cursor = conn.cursor()
    if since_time:
        cursor.execute("SELECT username, COUNT(*) as cnt FROM message_logs WHERE timestamp >= ? GROUP BY user_id ORDER BY cnt DESC LIMIT 10", (since_time,))
    else:
        cursor.execute("SELECT username, COUNT(*) as cnt FROM message_logs GROUP BY user_id ORDER BY cnt DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()

    if not rows: return "   _За цей період поки немає активності._", 0
    res, total_sum = "", 0
    for idx, (uname, count) in enumerate(rows, 1):
        name = uname if uname else "Гравець"
        res += f"{idx}. @{name} — {count}\n"
        total_sum += count
    return res, total_sum

@dp.message((F.text == "/день"))
async def stats_day_handler(message: Message):
    top_list, total = get_period_stats(time.time() - 86400)
    await message.answer(f"📊 **Статистика за день:**\n\n{top_list}\nЗагальна кількість: {total}")

@dp.message((F.text == "/тиждень"))
async def stats_week_handler(message: Message):
    top_list, total = get_period_stats(time.time() - 604800)
    await message.answer(f"📊 **Статистика за тиждень:**\n\n{top_list}\nЗагальна кількість: {total}")

@dp.message((F.text == "/місяць"))
async def stats_month_handler(message: Message):
    top_list, total = get_period_stats(time.time() - 2592000)
    await message.answer(f"📊 **Статистика за місяць:**\n\n{top_list}\nЗагальна кількість: {total}")

@dp.message((F.text == "/весь_час"))
async def stats_all_handler(message: Message):
    top_list, total = get_period_stats(None)
    await message.answer(f"📊 **Статистика за весь час:**\n\n{top_list}\nЗагальна кількість: {total}")


# --- РЕПУТАЦІЯ ТА БУНКЕР ---
@dp.message((F.text == "/bunker") | (F.text == "/бункер"))
async def bunker_handler(message: Message):
    card = (
        f"☢️ **Бункер для {message.from_user.first_name}:**\n"
        f"🛠 Професія: {random.choice(PROFESSIONS)}\n"
        f"❤️ Здоров'я: {random.choice(HEALTH_CONDITIONS)}\n"
        f"🎯 Хобі: {random.choice(HOBBIES)}\n"
        f"⚠️ Фобія: {random.choice(PHOBIAS)}\n"
        f"🎒 Багаж: {random.choice(INVENTORY)}"
    )
    await message.answer(card)

@dp.message(F.reply_to_message & (F.text.lower().in_({"+", "спс", "спасибі", "дякую"})))
async def give_karma_handler(message: Message):
    if message.reply_to_message.from_user.id == message.from_user.id: return
    add_karma(message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name, 1)
    await message.answer(f"👍 Репутація @{message.reply_to_message.from_user.first_name} підвищена! (+1)")

@dp.message((F.text == "/top") | (F.text == "/топ_репутації"))
async def top_handler(message: Message):
    top = get_top_users()
    if not top: return await message.answer("🏆 Немає даних.")
    text = "🏆 **Топ репутації:**\n\n"
    for idx, (uname, karma) in enumerate(top, 1): text += f"{idx}. {uname} — {karma} од.\n"
    await message.answer(text)

@dp.message()
async def all_messages_handler(message: Message):
    if message.from_user: log_message(message.from_user.id, message.from_user.first_name)


# --- ЗАПУСК БОТА ---
async def main():
    print(">>> 1. Старт...", flush=True)
    init_db()
    commands = [
        BotCommand(command="start", description="Головне меню"),
        BotCommand(command="profile", description="Моя статистика з графіком"),
        BotCommand(command="child", description="👶 Завести дитину (у шлюбі)"),
        BotCommand(command="pregnancy", description="🤰 Стан вагітності (7 днів)"),
        BotCommand(command="born", description="🍼 Народити дитину"),
        BotCommand(command="children", description="🧸 Мої діти"),
        BotCommand(command="shop_family", description="🛍 Магазин товарів для сім'ї"),
        BotCommand(command="class", description="🛡️ Обрати клас героя"),
        BotCommand(command="dungeon", description="⚔️ Підземелля (5 поверхів)"),
        BotCommand(command="hero", description="🗡 Профіль RPG героя"),
        BotCommand(command="shop", description="🛒 Магазин спорядження"),
        BotCommand(command="rest", description="🏕 Відновити HP"),
        BotCommand(command="marry", description="Запропонувати шлюб"),
        BotCommand(command="couple", description="Моя пара"),
        BotCommand(command="bunker", description="Гра Бункер")
    ]
    await bot.set_my_commands(commands)
    await bot.delete_webhook(drop_pending_updates=True)

      print(">>> Повний бот запрацював з абсолютно всіма функціями!", flush=True)
    asyncio.create_task(web_server())
    await dp.start_polling(bot)

    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(">>> Зупинено.")
