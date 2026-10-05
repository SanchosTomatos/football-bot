import telebot
import urllib.request
import urllib.parse
import urllib.error
import json
import time
import sqlite3
import threading
import random
import os
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import os

# Указываем точный путь к файлу .env (замени на свой путь!)
env_path = r"C:\Users\Fam\Desktop\проект 9 класс\My_bot_AMVERA\.env"
load_dotenv(dotenv_path=env_path)

# === НАСТРОЙКИ (БЕЗОПАСНОЕ ХРАНЕНИЕ КЛЮЧЕЙ) ===
TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"
DB_NAME = 'data/bot_database.db'  # Путь для Amvera (постоянное хранилище)
DEVELOPER_USERNAME = "Fallen_angel_discord"

# Проверка наличия ключей
if not TOKEN or not API_KEY:
    raise ValueError("❌ Не найдены BOT_TOKEN или FOOTBALL_API_KEY в переменных окружения!")

# === АВТОМАТИЧЕСКОЕ ПЕРЕПОДКЛЮЧЕНИЕ ===
class AutoReconnectBot(telebot.TeleBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reconnect_delay = 5
    
    def infinity_polling(self, *args, **kwargs):
        print("🚀 Запуск polling с автоматическим переподключением...")
        while True:
            try:
                super().infinity_polling(*args, **kwargs)
            except Exception as e:
                error_msg = str(e)
                if any(keyword in error_msg for keyword in [
                    'ConnectionResetError', 'Connection aborted', 
                    'timed out', 'ConnectionError', '10054',
                    'Max retries exceeded'
                ]):
                    print(f"\n⚠️ СЕТЕВАЯ ОШИБКА: {error_msg[:100]}")
                    print(f"⏳ Переподключение через {self.reconnect_delay} секунд...\n")
                    time.sleep(self.reconnect_delay)
                else:
                    print(f"\n❌ ДРУГАЯ ОШИБКА: {e}")
                    time.sleep(self.reconnect_delay)

bot = AutoReconnectBot(TOKEN)

user_data = {}
last_match = {}
team_cache = {}
db_lock = threading.Lock()

# Создаём папку data, если её нет (для Amvera)
if not os.path.exists('data'):
    os.makedirs('data')

# === ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ===
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS teams_cache
                      (search_term TEXT PRIMARY KEY, team_id INTEGER, team_name TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS teams_stats
                      (team_id INTEGER PRIMARY KEY, points INTEGER, goals_scored INTEGER,
                       goals_conceded INTEGER, results TEXT, matches INTEGER, updated_at REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                      (user_id INTEGER PRIMARY KEY, username TEXT, requests_count INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()
    print("✅ База данных готова.")

init_db()

# === СЛОВАРЬ ПЕРЕВОДОВ ===
russian_to_english = {
    'барселона': 'Barcelona', 'барса': 'Barcelona',
    'реал мадрид': 'Real Madrid', 'реал': 'Real Madrid',
    'атлетико мадрид': 'Atletico Madrid', 'атлетико': 'Atletico Madrid',
    'манчестер юнайтед': 'Manchester United', 'ман юнайтед': 'Manchester United', 'мю': 'Manchester United',
    'манчестер сити': 'Manchester City', 'ман сити': 'Manchester City', 'мс': 'Manchester City',
    'ливерпуль': 'Liverpool', 'арсенал': 'Arsenal', 'челси': 'Chelsea',
    'тоттенхэм': 'Tottenham Hotspur', 'шпоры': 'Tottenham Hotspur',
    'бавария': 'Bayern Munich', 'боруссия дортмунд': 'Borussia Dortmund', 'боруссия': 'Borussia Dortmund',
    'ювентус': 'Juventus', 'интер': 'Inter Milan', 'милан': 'AC Milan',
    'псж': 'Paris Saint-Germain', 'париж': 'Paris Saint-Germain',
    'порту': 'FC Porto', 'бенфика': 'Benfica', 'аякс': 'Ajax',
}

LEAGUES = {
    'PL':  '🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League (Англия)',
    'PD':  '🇪🇸 La Liga (Испания)',
    'BL1': '🇩🇪 Bundesliga (Германия)',
    'SA':  '🇮🇹 Serie A (Италия)',
    'FL1': '🇫🇷 Ligue 1 (Франция)',
    'PPL': '🇵🇹 Primeira Liga (Португалия)',
    'CL':  '🏆 Champions League',
}

# === КЛАВИАТУРЫ ===
def main_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("⚽ Рассчитать прогноз")
    markup.add("📊 Статистика команды")
    markup.add("🏆 Таблица лиги")
    markup.add("🎲 Случайный матч")
    markup.add("ℹ️ Помощь")
    return markup

def cancel_markup():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("❌ Отмена")
    return markup

def prediction_buttons(team1_full, team2_full, winner):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn1 = telebot.types.InlineKeyboardButton("🔄 Другой матч", callback_data="new_match")
    winner_name = team1_full if winner == 1 else team2_full
    btn2 = telebot.types.InlineKeyboardButton(f"📊 Статистика {winner_name}", callback_data=f"stats_{winner}")
    btn3 = telebot.types.InlineKeyboardButton(f"📅 След. матч {team1_full}", callback_data=f"next_{team1_full}")
    btn4 = telebot.types.InlineKeyboardButton(f"📅 След. матч {team2_full}", callback_data=f"next_{team2_full}")
    markup.add(btn1, btn2, btn3, btn4)
    return markup

def stats_buttons(team_name):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn1 = telebot.types.InlineKeyboardButton(f"⚽ Матч с {team_name}", callback_data=f"match_with_{team_name}")
    btn2 = telebot.types.InlineKeyboardButton(f"📅 Следующий матч", callback_data=f"next_{team_name}")
    btn3 = telebot.types.InlineKeyboardButton("🏠 В меню", callback_data="main_menu")
    markup.add(btn1, btn2, btn3)
    return markup

def league_choice_buttons():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    buttons = [telebot.types.InlineKeyboardButton(name, callback_data=f"league_{code}") for code, name in LEAGUES.items()]
    markup.add(*buttons)
    markup.add(telebot.types.InlineKeyboardButton("🏠 Назад в меню", callback_data="main_menu"))
    return markup

def league_table_buttons(league_code):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    btn1 = telebot.types.InlineKeyboardButton("🔄 Обновить", callback_data=f"league_{league_code}")
    btn2 = telebot.types.InlineKeyboardButton("🏆 Другая лига", callback_data="show_leagues")
    markup.add(btn1, btn2)
    markup.add(telebot.types.InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu"))
    return markup

def help_buttons():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn1 = telebot.types.InlineKeyboardButton(
        "💬 Написать разработчику", 
        url=f"https://t.me/{DEVELOPER_USERNAME}"
    )
    btn2 = telebot.types.InlineKeyboardButton("🏠 В главное меню", callback_data="main_menu")
    markup.add(btn1, btn2)
    return markup

# === РАБОТА С БАЗОЙ ДАННЫХ ===
def log_user(user_id, username):
    try:
        with db_lock:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
            cursor.execute("UPDATE users SET requests_count = requests_count + 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Ошибка логирования: {e}")

def get_team_from_db(search_term):
    try:
        with db_lock:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT team_id, team_name FROM teams_cache WHERE search_term = ?", (search_term,))
            result = cursor.fetchone()
            conn.close()
            return result
    except:
        return None

def save_team_to_db(search_term, team_id, team_name):
    try:
        with db_lock:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO teams_cache (search_term, team_id, team_name) VALUES (?, ?, ?)", 
                           (search_term, team_id, team_name))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Ошибка сохранения в БД: {e}")

def get_stats_from_db(team_id):
    try:
        with db_lock:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT points, goals_scored, goals_conceded, results, matches, updated_at FROM teams_stats WHERE team_id = ?", (team_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                if time.time() - row[5] < 86400:
                    return {
                        'points': row[0], 'goals_scored': row[1], 'goals_conceded': row[2],
                        'results': row[3].split(','), 'matches': row[4]
                    }
        return None
    except:
        return None

def save_stats_to_db(team_id, stats):
    try:
        with db_lock:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('''INSERT OR REPLACE INTO teams_stats 
                              (team_id, points, goals_scored, goals_conceded, results, matches, updated_at) 
                              VALUES (?, ?, ?, ?, ?, ?, ?)''',
                           (team_id, stats['points'], stats['goals_scored'], stats['goals_conceded'],
                            ','.join(stats['results']), stats['matches'], time.time()))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"Ошибка сохранения статистики: {e}")

# === ОБРАБОТЧИКИ КОМАНД ===
@bot.message_handler(commands=['start'])
def start(message):
    log_user(message.chat.id, message.from_user.username)
    bot.send_message(message.chat.id, 
        "👋 Привет! Я футбольный прогнозист.\n\n"
        "Я могу:\n"
        "• Предсказать результат матча\n"
        "• Показать статистику команды\n"
        "• Показать полную таблицу любой лиги\n"
        "• Предложить случайный матч дня\n\n"
        "Выберите действие:", 
        reply_markup=main_menu())

@bot.message_handler(commands=['help'])
def help_cmd(message):
    log_user(message.chat.id, message.from_user.username)
    help_text = (
        "📖 *Как пользоваться ботом:*\n\n"
        "⚽ *Прогноз матча:*\n"
        "1. Нажмите 'Рассчитать прогноз'\n"
        "2. Введите первую команду (можно на русском)\n"
        "3. Введите вторую команду\n"
        "4. Получите прогноз с вероятностями!\n\n"
        "📊 *Статистика команды:*\n"
        "Показывает результаты последних 5 матчей, "
        "разделение на домашние/гостевые игры и следующий матч.\n\n"
        "🏆 *Таблица лиги:*\n"
        "Полная таблица любого чемпионата с цветовыми зонами "
        "(Лига Чемпионов, Лига Европы, зона вылета).\n\n"
        "🎲 *Случайный матч:*\n"
        "Бот сам выберет интересный матч для прогноза.\n\n"
        "💬 *Связь с разработчиком:*\n"
        "Если у вас возник вопрос, ошибка или предложение — "
        "нажмите кнопку ниже, чтобы написать мне напрямую. "
        "Я отвечу на все вопросы и помогу решить любые проблемы!\n\n"
        "*Примеры команд:* `Барселона`, `Реал`, `МЮ`, `Arsenal`"
    )
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown', reply_markup=help_buttons())

@bot.message_handler(commands=['random'])
def random_match_cmd(message):
    random_match(message)

@bot.message_handler(func=lambda message: message.text == "⚽ Рассчитать прогноз")
def predict_start(message):
    log_user(message.chat.id, message.from_user.username)
    if message.chat.id in user_data: del user_data[message.chat.id]
    user_data[message.chat.id] = {'step': 1}
    bot.send_message(message.chat.id, 
        "Введите ПЕРВУЮ команду:\n\n"
        "Можно на русском или английском!\n"
        "Примеры: Барселона, Реал, МЮ, Arsenal", 
        reply_markup=cancel_markup())

@bot.message_handler(func=lambda message: message.text == "📊 Статистика команды")
def stats_start(message):
    log_user(message.chat.id, message.from_user.username)
    if message.chat.id in user_data: del user_data[message.chat.id]
    user_data[message.chat.id] = {'step': 'stats'}
    bot.send_message(message.chat.id, "Введите название команды:", reply_markup=cancel_markup())

@bot.message_handler(func=lambda message: message.text == "🏆 Таблица лиги")
def league_table_start(message):
    log_user(message.chat.id, message.from_user.username)
    bot.send_message(message.chat.id, "🏆 *Выберите чемпионат:*", parse_mode='Markdown', reply_markup=league_choice_buttons())

@bot.message_handler(func=lambda message: message.text == "🎲 Случайный матч")
def random_match_btn(message):
    random_match(message)

@bot.message_handler(func=lambda message: message.text == "ℹ️ Помощь")
def help_button(message):
    help_cmd(message)

@bot.message_handler(func=lambda message: message.text == "❌ Отмена")
def cancel(message):
    if message.chat.id in user_data: 
        del user_data[message.chat.id]
    bot.send_message(message.chat.id, "Действие отменено.", reply_markup=main_menu())

# === ОБРАБОТЧИК INLINE-КНОПОК ===
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    print(f"📱 Callback: {call.data}")
    
    try:
        if call.data == "main_menu":
            bot.send_message(chat_id, "🏠 Главное меню. Выберите действие:", reply_markup=main_menu())
        elif call.data == "new_match":
            if chat_id in user_data: del user_data[chat_id]
            user_data[chat_id] = {'step': 1}
            bot.send_message(chat_id, "🔄 Начинаем новый прогноз!\n\nВведите ПЕРВУЮ команду:", reply_markup=cancel_markup())
        elif call.data.startswith("stats_"):
            winner_num = int(call.data.split("_")[1])
            if chat_id in last_match and 'teams' in last_match[chat_id]:
                team_name = last_match[chat_id]['teams'][winner_num - 1]
                bot.send_message(chat_id, f"⏳ Загружаю: {team_name}...")
                process_stats(chat_id, team_name)
            else:
                bot.send_message(chat_id, "Введите название команды:", reply_markup=cancel_markup())
                if chat_id not in user_data: user_data[chat_id] = {}
                user_data[chat_id]['step'] = 'stats'
        elif call.data.startswith("match_with_"):
            team_name = call.data.replace("match_with_", "", 1)
            if chat_id in user_data: del user_data[chat_id]
            user_data[chat_id] = {'step': 2, 'team1': team_name}
            bot.send_message(chat_id, f"✅ Первая: {team_name}\n\nВведите ВТОРУЮ:", reply_markup=cancel_markup())
        elif call.data.startswith("next_"):
            team_name = call.data.replace("next_", "", 1)
            bot.send_message(chat_id, f"⏳ Ищу следующий матч {team_name}...")
            show_next_match(chat_id, team_name)
        elif call.data == "show_leagues":
            bot.send_message(chat_id, "🏆 *Выберите чемпионат:*", parse_mode='Markdown', reply_markup=league_choice_buttons())
        elif call.data.startswith("league_"):
            league_code = call.data.replace("league_", "", 1)
            league_name = LEAGUES.get(league_code, league_code)
            bot.edit_message_text(f"⏳ Загружаю полную таблицу {league_name}...", chat_id, call.message.message_id)
            show_league_table(chat_id, league_code, league_name, call.message.message_id)
        
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"❌ Ошибка в callback_handler: {e}")
        try:
            bot.answer_callback_query(call.id)
        except:
            pass

# === ОСНОВНАЯ ЛОГИКА ВВОДА ===
@bot.message_handler(func=lambda message: message.chat.id in user_data)
def process_input(message):
    chat_id = message.chat.id
    user_state = user_data[chat_id]
    
    print(f"📝 Ввод: '{message.text}' (step={user_state.get('step')})")
    
    if message.text == "❌ Отмена":
        cancel(message)
        return
    
    if user_state.get('step') == 1:
        user_state['team1'] = message.text.strip()
        user_state['step'] = 2
        bot.send_message(chat_id, f"✅ Принято: {message.text}\n\nТеперь введите ВТОРУЮ команду:", reply_markup=cancel_markup())
    elif user_state.get('step') == 2:
        team2_name = message.text.strip()
        team1_name = user_state.get('team1', '')
        print(f"🔎 Ищем: {team1_name} vs {team2_name}")
        process_prediction(chat_id, team1_name, team2_name)
    elif user_state.get('step') == 'stats':
        print("   🟢 Дошел до шага stats.")
        try:
            bot.send_message(chat_id, "⏳ Загружаю...")
        except Exception as e:
            print(f"   ❌ ОШИБКА СЕТИ: {e}")
        
        process_stats(chat_id, message.text.strip())
        if chat_id in user_data: del user_data[chat_id]

def random_match(message):
    log_user(message.chat.id, message.from_user.username)
    top_teams = [
        ('Barcelona', 'Real Madrid'), ('Manchester City', 'Liverpool'),
        ('Bayern Munich', 'Borussia Dortmund'), ('Juventus', 'Inter Milan'),
        ('Paris Saint-Germain', 'Marseille'), ('Arsenal', 'Chelsea')
    ]
    team1, team2 = random.choice(top_teams)
    bot.send_message(message.chat.id, f"🎲 Случайный матч: *{team1}* vs *{team2}*\n\nНачинаю анализ...", parse_mode='Markdown')
    
    if message.chat.id in user_data: del user_data[message.chat.id]
    user_data[message.chat.id] = {'step': 2, 'team1': team1}
    process_prediction(message.chat.id, team1, team2)

def process_prediction(chat_id, team1_name, team2_name):
    loading_msg = bot.send_message(chat_id, "⏳ Анализирую данные (личные встречи, форма, домашнее преимущество)...")
    
    team1_id, team1_full = find_team(team1_name)
    team2_id, team2_full = find_team(team2_name)
    
    print(f"📊 Найдено: {team1_full} (ID: {team1_id}) и {team2_full} (ID: {team2_id})")
    
    if not team1_id:
        bot.send_message(chat_id, f"❌ Команда '{team1_name}' не найдена.", reply_markup=main_menu())
        try: bot.delete_message(chat_id, loading_msg.message_id)
        except: pass
        return
    
    if not team2_id:
        bot.send_message(chat_id, f"❌ Команда '{team2_name}' не найдена.", reply_markup=main_menu())
        try: bot.delete_message(chat_id, loading_msg.message_id)
        except: pass
        return
    
    stats1 = get_team_stats_detailed(team1_id, team1_full)
    stats2 = get_team_stats_detailed(team2_id, team2_full)
    h2h_data = get_head_to_head(team1_id, team2_id, team1_full, team2_full)
    
    if not stats1 or not stats2:
        bot.send_message(chat_id, "⚠️ Не удалось получить статистику. Подождите 1 минуту.", reply_markup=main_menu())
        try: bot.delete_message(chat_id, loading_msg.message_id)
        except: pass
        return
    
    prob1, draw, prob2 = calculate_probability_advanced(stats1, stats2, h2h_data)
    winner = 1 if prob1 > prob2 and prob1 > draw else (2 if prob2 > prob1 and prob2 > draw else 0)
    
    last_match[chat_id] = {'teams': [team1_full, team2_full]}
    
    response = f"🏆 *ПРОГНОЗ НА МАТЧ*\n\n*{team1_full}* vs *{team2_full}*\n\n"
    
    if h2h_data and h2h_data['matches'] > 0:
        response += f"⚔️ *Личные встречи (последние {h2h_data['matches']}):*\n"
        response += f"   {team1_full}: *{h2h_data['team1_wins']} побед*\n"
        response += f"   Ничьи: *{h2h_data['draws']}*\n"
        response += f"   {team2_full}: *{h2h_data['team2_wins']} побед*\n\n"
    
    response += f"📊 *Форма (последние 5 матчей):*\n\n🔹 *{team1_full}:*\n"
    response += f"   Результаты: {' '.join(stats1['results'])}\n"
    response += f"   Очки: {stats1['points']} | Голы: {stats1['goals_scored']}/{stats1['goals_conceded']}\n"
    response += f"   🏠 Дома: {stats1['home_points']} очк | ✈️ В гостях: {stats1['away_points']} очк\n\n"
    response += f"🔸 *{team2_full}:*\n"
    response += f"   Результаты: {' '.join(stats2['results'])}\n"
    response += f"   Очки: {stats2['points']} | Голы: {stats2['goals_scored']}/{stats2['goals_conceded']}\n"
    response += f"   🏠 Дома: {stats2['home_points']} очк | ✈️ В гостях: {stats2['away_points']} очк\n\n"
    response += f"🎯 *Вероятность исхода (улучшенный алгоритм):*\n"
    response += f"   Победа {team1_full}: *{prob1:.1f}%*\n   Ничья: *{draw:.1f}%*\n   Победа {team2_full}: *{prob2:.1f}%*\n\n"
    
    if winner == 1: response += f"🥇 Фаворит: *{team1_full}*"
    elif winner == 2: response += f"🥇 Фаворит: *{team2_full}*"
    else: response += "🤝 Матч будет равным!"
    
    bot.send_message(chat_id, response, parse_mode='Markdown', reply_markup=prediction_buttons(team1_full, team2_full, winner))
    try: bot.delete_message(chat_id, loading_msg.message_id)
    except: pass

def process_stats(chat_id, team_name):
    print(f"   🚀 Вызов process_stats для команды: {team_name}")
    team_id, team_full = find_team(team_name)
    if not team_id:
        bot.send_message(chat_id, f"❌ Команда '{team_name}' не найдена.", reply_markup=main_menu())
        return
    
    stats = get_team_stats_detailed(team_id, team_full)
    if not stats:
        bot.send_message(chat_id, "⚠️ Не удалось получить статистику.", reply_markup=main_menu())
        return
    
    response = f"📊 *Статистика {team_full}*\n\n"
    response += f"Последние {stats['matches']} матчей:\nРезультаты: {' '.join(stats['results'])}\n\n"
    response += f"⚽ Забито: {stats['goals_scored']}\n🛡️ Пропущено: {stats['goals_conceded']}\n"
    response += f"📈 Разница: {stats['goals_scored'] - stats['goals_conceded']:+d}\n🏆 Очки: {stats['points']}\n\n"
    response += f"🏠 *Дома:* {stats['home_points']} очков ({stats['home_won']}В {stats['home_draw']}Н {stats['home_lost']}П)\n"
    response += f"✈️ *В гостях:* {stats['away_points']} очков ({stats['away_won']}В {stats['away_draw']}Н {stats['away_lost']}П)"
    
    bot.send_message(chat_id, response, parse_mode='Markdown', reply_markup=stats_buttons(team_full))

def show_next_match(chat_id, team_name):
    team_id, team_full = find_team(team_name)
    if not team_id:
        bot.send_message(chat_id, f"❌ Команда '{team_name}' не найдена.", reply_markup=main_menu())
        return
    
    headers = {'X-Auth-Token': API_KEY}
    url = f"{BASE_URL}/teams/{team_id}/matches?status=SCHEDULED&limit=3"
    data = fetch_url(url, headers)
    
    if not data or not data.get('matches'):
        bot.send_message(chat_id, f"📅 У {team_full} нет запланированных матчей в ближайшее время.", reply_markup=main_menu())
        return
    
    matches = data['matches'][:3]
    response = f"📅 *Ближайшие матчи {team_full}:*\n\n"
    
    for match in matches:
        date_str = match['utcDate'][:10]
        time_str = match['utcDate'][11:16]
        competition = match['competition']['name']
        home_team = match['homeTeam']['name']
        away_team = match['awayTeam']['name']
        response += f"🏟️ *{competition}*\n📆 {date_str} в {time_str} (UTC)\n   {home_team} vs {away_team}\n\n"
    
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn = telebot.types.InlineKeyboardButton("🏠 В меню", callback_data="main_menu")
    markup.add(btn)
    bot.send_message(chat_id, response, parse_mode='Markdown', reply_markup=markup)

def get_head_to_head(team1_id, team2_id, team1_name, team2_name):
    headers = {'X-Auth-Token': API_KEY}
    url = f"{BASE_URL}/teams/{team1_id}/matches?status=FINISHED&limit=20"
    data = fetch_url(url, headers)
    if not data: return None
    
    matches = data.get('matches', [])
    team1_wins, team2_wins, draws, h2h_matches = 0, 0, 0, 0
    
    for match in matches:
        home = match['homeTeam']['name']
        away = match['awayTeam']['name']
        if (home == team1_name and away == team2_name) or (home == team2_name and away == team1_name):
            h2h_matches += 1
            home_score = match['score']['fullTime']['home']
            away_score = match['score']['fullTime']['away']
            if home == team1_name:
                if home_score > away_score: team1_wins += 1
                elif home_score < away_score: team2_wins += 1
                else: draws += 1
            else:
                if away_score > home_score: team1_wins += 1
                elif away_score < home_score: team2_wins += 1
                else: draws += 1
            if h2h_matches >= 5: break
    
    return {'matches': h2h_matches, 'team1_wins': team1_wins, 'team2_wins': team2_wins, 'draws': draws} if h2h_matches > 0 else None

def get_team_stats_detailed(team_id, team_name):
    db_stats = get_stats_from_db(team_id)
    if db_stats:
        print(f"   ⚡ Статистика {team_name} взята из БД")
        db_stats.setdefault('home_points', 0)
        db_stats.setdefault('home_won', 0)
        db_stats.setdefault('home_draw', 0)
        db_stats.setdefault('home_lost', 0)
        db_stats.setdefault('away_points', 0)
        db_stats.setdefault('away_won', 0)
        db_stats.setdefault('away_draw', 0)
        db_stats.setdefault('away_lost', 0)
        return db_stats

    headers = {'X-Auth-Token': API_KEY}
    url = f"{BASE_URL}/teams/{team_id}/matches?status=FINISHED&limit=5"
    data = fetch_url(url, headers)
    if not data: return None
    
    matches = data.get('matches', [])
    points, goals_scored, goals_conceded, results = 0, 0, 0, []
    home_points, home_won, home_draw, home_lost = 0, 0, 0, 0
    away_points, away_won, away_draw, away_lost = 0, 0, 0, 0
    
    for match in matches:
        is_home = (match['homeTeam']['name'] == team_name)
        team_score = match['score']['fullTime']['home'] if is_home else match['score']['fullTime']['away']
        opponent_score = match['score']['fullTime']['away'] if is_home else match['score']['fullTime']['home']
        
        goals_scored += team_score
        goals_conceded += opponent_score
        
        if team_score > opponent_score:
            points += 3; results.append("В")
            if is_home: home_points += 3; home_won += 1
            else: away_points += 3; away_won += 1
        elif team_score == opponent_score:
            points += 1; results.append("Н")
            if is_home: home_points += 1; home_draw += 1
            else: away_points += 1; away_draw += 1
        else:
            results.append("П")
            if is_home: home_lost += 1
            else: away_lost += 1
    
    stats = {
        'points': points, 'goals_scored': goals_scored, 'goals_conceded': goals_conceded,
        'results': results, 'matches': len(matches),
        'home_points': home_points, 'home_won': home_won, 'home_draw': home_draw, 'home_lost': home_lost,
        'away_points': away_points, 'away_won': away_won, 'away_draw': away_draw, 'away_lost': away_lost
    }
    save_stats_to_db(team_id, stats)
    print(f"   ✅ Статистика {team_name} получена из API и сохранена в БД")
    return stats

def calculate_probability_advanced(stats1, stats2, h2h_data):
    avg1 = stats1['points'] / max(stats1['matches'], 1)
    avg2 = stats2['points'] / max(stats2['matches'], 1)
    diff1 = (stats1['goals_scored'] - stats1['goals_conceded']) / max(stats1['matches'], 1)
    diff2 = (stats2['goals_scored'] - stats2['goals_conceded']) / max(stats2['matches'], 1)
    
    r1 = avg1 + (diff1 * 0.5)
    r2 = avg2 + (diff2 * 0.5)
    r1 = r1 * 1.15
    
    if len(stats1['results']) >= 2: r1 += sum(1 for r in stats1['results'][-2:] if r == 'В') * 0.3
    if len(stats2['results']) >= 2: r2 += sum(1 for r in stats2['results'][-2:] if r == 'В') * 0.3
    
    if h2h_data and h2h_data['matches'] > 0:
        h2h_factor = 0.2
        if h2h_data['team1_wins'] > h2h_data['team2_wins']: r1 += h2h_factor * (h2h_data['team1_wins'] - h2h_data['team2_wins'])
        elif h2h_data['team2_wins'] > h2h_data['team1_wins']: r2 += h2h_factor * (h2h_data['team2_wins'] - h2h_data['team1_wins'])
    
    total = r1 + r2
    if total <= 0: return 40.0, 20.0, 40.0
    
    p1 = (r1 / total) * 100
    p2 = (r2 / total) * 100
    d = abs(r1 - r2)
    draw = 25.0 if d < 0.5 else (20.0 if d < 1.5 else 15.0)
    
    return p1 * (100 - draw) / 100, draw, p2 * (100 - draw) / 100

def show_league_table(chat_id, league_code, league_name, message_id=None):
    headers = {'X-Auth-Token': API_KEY}
    url = f"{BASE_URL}/competitions/{league_code}/standings"
    data = fetch_url(url, headers)
    if not data:
        bot.send_message(chat_id, "⚠️ Не удалось загрузить таблицу.", reply_markup=main_menu())
        return
    
    standings = data.get('standings', [])
    total_table = None
    for standing in standings:
        if standing.get('type') == 'TOTAL':
            total_table = standing.get('table', [])
            break
    if not total_table and standings: total_table = standings[0].get('table', [])
    if not total_table: return
    
    season_year = data.get('season', {}).get('startDate', '2024')[:4]
    response = format_mobile_table(total_table, league_name, season_year, league_code)
    
    try:
        if message_id: bot.edit_message_text(response, chat_id, message_id, parse_mode='Markdown', reply_markup=league_table_buttons(league_code))
        else: bot.send_message(chat_id, response, parse_mode='Markdown', reply_markup=league_table_buttons(league_code))
    except Exception as e:
        print(f"❌ Ошибка отправки таблицы: {e}")
        bot.send_message(chat_id, "❌ Ошибка форматирования.", reply_markup=main_menu())

def format_mobile_table(teams, league_name, season_year, league_code):
    zones = {'PL': {'champions_league': 4, 'europa_league': 5, 'relegation': 18}, 'PD': {'champions_league': 4, 'europa_league': 5, 'relegation': 18}, 'BL1': {'champions_league': 4, 'europa_league': 5, 'relegation': 16}, 'SA': {'champions_league': 4, 'europa_league': 5, 'relegation': 18}, 'FL1': {'champions_league': 3, 'europa_league': 4, 'relegation': 18}, 'PPL': {'champions_league': 2, 'europa_league': 3, 'relegation': 16}, 'CL': {'champions_league': 8, 'europa_league': 8, 'relegation': 36}}
    zone_info = zones.get(league_code, {'champions_league': 4, 'europa_league': 5, 'relegation': 18})
    
    table = f"🏆 *{league_name}*\n📅 Сезон {season_year}/{int(season_year)+1}\n\n"
    for i, entry in enumerate(teams):
        pos = entry.get('position', i + 1)
        team_name = entry.get('team', {}).get('shortName') or entry.get('team', {}).get('name', '?')
        played, won, draw, lost, points = entry.get('playedGames', 0), entry.get('won', 0), entry.get('draw', 0), entry.get('lost', 0), entry.get('points', 0)
        
        if pos == 1: pos_emoji = "🥇"
        elif pos == 2: pos_emoji = "🥈"
        elif pos == 3: pos_emoji = "🥉"
        elif pos <= zone_info['champions_league']: pos_emoji = "🟢"
        elif pos <= zone_info['europa_league']: pos_emoji = "🔵"
        elif pos >= zone_info['relegation']: pos_emoji = "🔴"
        else: pos_emoji = "⚪"
        
        table += f"{pos_emoji} *{pos}. {team_name}*\n   {played} матчей | {won}В {draw}Н {lost}П | *{points} очков*\n\n"
    
    table += "━━━━━━━━━━━━━━━━━━━━\n*Легенда:* 🟢 ЛЧ | 🔵 ЛЕ | 🔴 Вылет | ⚪ Середина\n"
    table += f"📊 _Показаны все {len(teams)} команд_"
    return table

def translate_russian_team_name(team_name):
    team_name_lower = team_name.lower().strip()
    if team_name_lower in russian_to_english: return russian_to_english[team_name_lower]
    for ru, en in russian_to_english.items():
        if ru in team_name_lower or team_name_lower in ru: return en
    return team_name

def fetch_url(url, headers, retries=2):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"   ⚠️ Лимит API (429). Ждём 3 секунды...")
                time.sleep(3); continue
            return None
        except Exception as e:
            print(f"   ⚠️ Ошибка запроса: {e}")
            return None
    return None

def find_team(team_name):
    name_lower = team_name.lower().strip()
    print(f"\n{'='*50}")
    print(f"🔍 НАЧАЛО ПОИСКА: '{team_name}'")
    print(f"{'='*50}")
    
    if name_lower in team_cache:
        print(f"   ⚡ ШАГ 1: Найдено в ОПЕРАТИВНОМ КЭШЕ: {team_cache[name_lower][1]}")
        return team_cache[name_lower]
    else:
        print(f"   ⏭️ ШАГ 1: В оперативном кэше не найдено")
    
    print(f"   🗄️ ШАГ 2: Проверяю базу данных...")
    db_result = get_team_from_db(name_lower)
    if db_result:
        print(f"   ⚡ ШАГ 2: Найдено в БАЗЕ ДАННЫХ: {db_result[1]}")
        team_cache[name_lower] = db_result
        return db_result
    else:
        print(f"   ⏭️ ШАГ 2: В базе данных не найдено")

    headers = {'X-Auth-Token': API_KEY}
    english_name = translate_russian_team_name(team_name)
    search_term = english_name.lower().strip()
    print(f"   🌐 ШАГ 3: Ищем в API: '{team_name}' -> '{english_name}' (поиск: '{search_term}')")
    
    best_match, best_score = None, 0
    
    def score_team(team):
        name = team.get('name', '').lower()
        short_name = team.get('shortName', '').lower()
        tla = team.get('tla', '').lower()
        if short_name and search_term == short_name: return 1000
        elif tla and search_term == tla: return 900
        elif name == search_term: return 800
        elif short_name and search_term in short_name: return 500
        elif name.endswith(search_term): return 100 - len(name)
        elif search_term in name.split(): return 50
        elif search_term in name: return 10
        return 0

    print(f"   🌐 ШАГ 3.1: Делаю прямой запрос к API...")
    try:
        url = f"{BASE_URL}/teams?name={urllib.parse.quote(english_name)}"
        print(f"      URL: {url}")
        data = fetch_url(url, headers)
        if data:
            teams = data.get('teams', [])
            print(f"      ✅ Получено {len(teams)} команд от API")
            for team in teams:
                s = score_team(team)
                if s > best_score:
                    best_score, best_match = s, team
                    print(f"         → {team['name']} (score: {s})")
        else:
            print(f"      ❌ API не вернул данные (возможно, лимит или сеть)")
    except Exception as e:
        print(f"      ❌ Ошибка при запросе: {e}")

    if best_score < 500:
        print(f"   🌐 ШАГ 3.2: Прямой поиск не дал результата (score={best_score}). Ищу по лигам...")
        for league in ['PL', 'PD', 'BL1', 'SA', 'FL1', 'PPL', 'CL', 'ELC']:
            print(f"      Проверяю лигу {league}...")
            try:
                url = f"{BASE_URL}/competitions/{league}/teams"
                data = fetch_url(url, headers)
                if data:
                    for team in data.get('teams', []):
                        s = score_team(team)
                        if s > best_score:
                            best_score, best_match = s, team
                            print(f"         → {team['name']} в лиге {league} (score: {s})")
                time.sleep(0.3)
            except Exception as e:
                print(f"      ❌ Ошибка в лиге {league}: {e}")
                continue

    if best_match:
        result = (best_match['id'], best_match['name'])
        team_cache[name_lower] = result
        save_team_to_db(name_lower, result[0], result[1])
        print(f"   ✅ ИТОГ: Найдено '{best_match['name']}' (score: {best_score}). Сохранено в БД.")
        print(f"{'='*50}\n")
        return result
    
    print(f"   ❌ ИТОГ: Команда НЕ НАЙДЕНА")
    print(f"{'='*50}\n")
    return None, None

print("🚀 Бот с безопасным хранением ключей запущен!")
bot.infinity_polling()
