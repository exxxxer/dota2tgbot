import os
import asyncio
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENDOTA = "https://api.opendota.com/api"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

def log_dialog(user_id: int, role: str, text: str):
    with open(f"{user_id}.log", "a", encoding="utf-8") as file:
        file.write(f"{role}: {text}\n")

async def send_answer(message: Message, text: str):
    log_dialog(message.from_user.id, "BOT", text)
    await message.answer(text, parse_mode="HTML")


def normalize(text: str):
    return text.lower().replace("-", " ").replace("_", " ").strip()


def format_duration(seconds: int) -> str:
    minutes = seconds // 60
    sec = seconds % 60
    return f"{minutes}:{sec:02d}"


def format_datetime(timestamp: int) -> str:
    """
    Переводит Unix-время матча в локальное время компьютера,
    на котором запущен бот.
    """
    return datetime.fromtimestamp(timestamp).strftime("%d.%m.%Y %H:%M")


def is_player_win(match: dict) -> bool:
    """
    В OpenDota player_slot < 128 означает Radiant,
    player_slot >= 128 означает Dire.
    """
    player_slot = match.get("player_slot", 0)
    radiant_win = match.get("radiant_win", False)

    is_radiant = player_slot < 128

    return radiant_win == is_radiant


def get_kda(kills: int, deaths: int, assists: int) -> str:
    if deaths == 0:
        return f"{kills}/{deaths}/{assists} ∞"
    
    kda = round((kills + assists) / deaths, 2)
    return f"{kills}/{deaths}/{assists} ({kda})"


def get_rank_name(rank_tier: int) -> str:
    """
    Преобразует числовой код ранга в его имя.
    Первая цифра - ранг, вторая - звёздочка/подуровень.
    """
    ranks = {
        0: "Ранг не определён",
        1: "Рекрут",
        2: "Страж", 
        3: "Рыцарь",
        4: "Герой",
        5: "Легенда",
        6: "Властелин",
        7: "Божество",
        8: "Титан",
    }
    
    if not rank_tier or rank_tier == 0:
        return "Ранг не определён"
    
    # Извлекаем основной ранг (первая цифра)
    rank = rank_tier // 10
    # Извлекаем подуровень (вторая цифра)
    star = rank_tier % 10
    
    rank_name = ranks.get(rank, "Ранг не определён")
    
    if star > 0:
        return f"{rank_name} [{star}]"
    
    return rank_name


@router.message(Command("start"))
async def start(message: Message):
    log_dialog(message.from_user.id, "USER", message.text)

    text = (
        "Привет! Я DotaMetaBot.\n\n"
        "Команды:\n"
        "/player ID — статистика игрока\n"
        "/match ID — информация о матче\n"
        "/hero имя — информация о герое\n"
        "/meta — топ героев по winrate\n"
        "/draft — анализ драфта\n"
        "/news — последние новости Dota 2 через HTML-скрапинг\n"
    )

    await send_answer(message, text)

def get_hero_winrate(hero: dict) -> float:
    """
    Берем winrate героя в Immortal bracket.
    Если данных мало, используем pro stats.
    Если и их нет, ставим 50%.
    """

    immortal_picks = hero.get("8_pick", 0)
    immortal_wins = hero.get("8_win", 0)

    if immortal_picks and immortal_picks > 0:
        return immortal_wins / immortal_picks * 100

    pro_picks = hero.get("pro_pick", 0)
    pro_wins = hero.get("pro_win", 0)

    if pro_picks and pro_picks > 0:
        return pro_wins / pro_picks * 100

    return 50.0


def get_hero_popularity(hero: dict) -> float:
    """
    Популярность героя в Immortal bracket.
    Чем чаще героя пикают, тем выше уверенность в статистике.
    """

    return hero.get("8_pick", 0)


def calculate_team_score(team_heroes: list) -> float:
    """
    Считает силу команды по простому принципу:
    - средний winrate героев
    - небольшой бонус за популярность
    - небольшой бонус за разнообразие ролей
    """

    winrates = []
    total_popularity = 0
    roles = set()

    for hero in team_heroes:
        winrate = get_hero_winrate(hero)
        popularity = get_hero_popularity(hero)

        winrates.append(winrate)
        total_popularity += popularity

        for role in hero.get("roles", []):
            roles.add(role)

    average_winrate = sum(winrates) / len(winrates)

    popularity_bonus = min(total_popularity / 10000, 5)

    role_bonus = min(len(roles) * 0.5, 4)

    final_score = average_winrate + popularity_bonus + role_bonus

    return final_score

@router.message(Command("player"))
async def player(message: Message):
    log_dialog(message.from_user.id, "USER", message.text)

    parts = message.text.split()

    if len(parts) < 2:
        await send_answer(message, "Пример: /player 123456789")
        return

    player_id = parts[1]

    try:
        # Основная информация об игроке
        player_response = requests.get(
            f"{OPENDOTA}/players/{player_id}",
            timeout=10
        )
        player_data = player_response.json()

        profile = player_data.get("profile", {})
        name = profile.get("personaname", "Неизвестно")
        rank_tier = player_data.get("rank_tier", 0)
        rank_name = get_rank_name(rank_tier)

        # Список всех героев
        heroes_response = requests.get(
            f"{OPENDOTA}/heroes",
            timeout=10
        )
        heroes_data = heroes_response.json()

        hero_names = {}
        for hero in heroes_data:
            hero_names[hero.get("id")] = hero.get("localized_name")

        # Герои игрока
        player_heroes_response = requests.get(
            f"{OPENDOTA}/players/{player_id}/heroes",
            timeout=10
        )
        player_heroes = player_heroes_response.json()

        top_heroes = sorted(
            player_heroes,
            key=lambda hero: hero.get("games", 0),
            reverse=True
        )[:5]

        heroes_text = ""

        for hero in top_heroes:
            hero_id = hero.get("hero_id")
            hero_name = hero_names.get(hero_id, f"Hero ID {hero_id}")

            games = hero.get("games", 0)
            wins = hero.get("win", 0)

            if games > 0:
                winrate = round((wins / games) * 100, 1)
            else:
                winrate = 0

            heroes_text += (
                f"{hero_name}\n"
                f"Игры: {games}, Победы: {wins}, Winrate: {winrate}%\n\n"
            )

        if heroes_text == "":
            heroes_text = "Нет данных по героям.\n"

        # Последние матчи
        matches_response = requests.get(
            f"{OPENDOTA}/players/{player_id}/matches?limit=10",
            timeout=10
        )
        matches = matches_response.json()

        matches_text = ""

        for match in matches:
            match_id = match.get("match_id")
            hero_id = match.get("hero_id")
            hero_name = hero_names.get(hero_id, f"Hero ID {hero_id}")

            kills = match.get("kills", 0)
            deaths = match.get("deaths", 0)
            assists = match.get("assists", 0)

            kda = get_kda(kills, deaths, assists)

            duration = format_duration(match.get("duration", 0))
            start_time = format_datetime(match.get("start_time", 0))

            win = is_player_win(match)
            result = "✅" if win else "❌"

            matches_text += (
                f"{hero_name} — {result}\n"
                f"Дата: {start_time}\n"
                f"Длительность: {duration}\n"
                f"KDA: {kda}\n"
                f"Match ID: {match_id}\n\n"
            )

        if matches_text == "":
            matches_text = "Нет данных по последним матчам.\n"

        text = (
            f"Игрок: {name}\n"
            f"ID: {player_id}\n"
            f"Ранг: {rank_name}\n\n"
            f"Топ героев по количеству игр:\n\n"
            f"{heroes_text}"
            f"Последние матчи:\n\n"
            f"{matches_text}"
        )

        # Telegram не любит слишком длинные сообщения
        if len(text) > 4000:
            parts = [text[i:i + 4000] for i in range(0, len(text), 4000)]
            for part in parts:
                await send_answer(message, part)
        else:
            await send_answer(message, text)

    except Exception as e:
        await send_answer(message, f"Ошибка при получении данных игрока: {e}")


@router.message(Command("match"))
async def match(message: Message):
    log_dialog(message.from_user.id, "USER", message.text)

    parts = message.text.split()

    if len(parts) < 2:
        await send_answer(message, "Пример: /match 7894561230")
        return

    match_id = parts[1]

    try:
        response = requests.get(f"{OPENDOTA}/matches/{match_id}", timeout=10)
        data = response.json()

        # Основная информация о матче
        duration = data.get("duration", 0)
        duration_formatted = format_duration(duration)
        radiant_win = data.get("radiant_win")
        winner = "☀️ Radiant" if radiant_win else "🌙 Dire"

        # Получаем информацию о героях
        heroes_response = requests.get(f"{OPENDOTA}/heroes", timeout=10)
        heroes_data = heroes_response.json()
        
        hero_names = {}
        for hero in heroes_data:
            hero_names[hero.get("id")] = hero.get("localized_name")

        # Формируем информацию о командах
        players = data.get("players", [])
        
        radiant_team = []
        dire_team = []

        for player in players:
            player_slot = player.get("player_slot", 0)
            is_radiant = player_slot < 128
            
            hero_id = player.get("hero_id")
            hero_name = hero_names.get(hero_id, f"Hero ID {hero_id}")
            
            kills = player.get("kills", 0)
            deaths = player.get("deaths", 0)
            assists = player.get("assists", 0)
            
            level = player.get("level", 0)
            net_worth = player.get("net_worth", 0)
            gold = player.get("gold", 0)
            last_hits = player.get("last_hits", 0)
            denies = player.get("denies", 0)
            gpm = player.get("gold_per_min", 0)
            xpm = player.get("xp_per_min", 0)
            
            kda = get_kda(kills, deaths, assists)
            
            player_info = {
                "hero": hero_name,
                "kda": kda,
                "level": level,
                "net_worth": net_worth,
                "gold": gold,
                "last_hits": last_hits,
                "denies": denies,
                "gpm": gpm,
                "xpm": xpm
            }
            
            if is_radiant:
                radiant_team.append(player_info)
            else:
                dire_team.append(player_info)

        # Формируем текст ответа
        radiant_gold = sum(p["gold"] for p in radiant_team)
        dire_gold = sum(p["gold"] for p in dire_team)
        
        radiant_kills = sum(int(p["kda"].split("/")[0]) for p in radiant_team)
        dire_kills = sum(int(p["kda"].split("/")[0]) for p in dire_team)

        text = (
            f"Матч: {match_id}\n"
            f"Победитель: {winner}\n"
            f"Длительность: {duration_formatted}\n\n"
            f"☀️ Radiant (Убийств: {radiant_kills}, Золото: {radiant_gold})\n"
        )

        for player in radiant_team:
            text += (
                f"  {player['hero']}\n"
                f"    KDA: {player['kda']} | Lvl: {player['level']} | NW: {player['net_worth']}\n"
                f"    LH: {player['last_hits']} | Denies: {player['denies']} | GPM: {player['gpm']}\n\n"
            )

        text += f"🌙 Dire (Убийств: {dire_kills}, Золото: {dire_gold})\n"

        for player in dire_team:
            text += (
                f"  {player['hero']}\n"
                f"    KDA: {player['kda']} | Lvl: {player['level']} | NW: {player['net_worth']}\n"
                f"    LH: {player['last_hits']} | Denies: {player['denies']} | GPM: {player['gpm']}\n\n"
            )

        if len(text) > 4000:
            parts = [text[i:i + 4000] for i in range(0, len(text), 4000)]
            for part in parts:
                await send_answer(message, part)
        else:
            await send_answer(message, text)

    except Exception as e:
        await send_answer(message, f"Ошибка при получении данных матча: {e}")

@router.message(Command("hero"))
async def hero(message: Message):
    log_dialog(message.from_user.id, "USER", message.text)

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await send_answer(message, "Пример: /hero pudge или /hero crystal maiden")
        return

    user_hero = normalize(parts[1])

    try:
        response = requests.get(f"{OPENDOTA}/heroes", timeout=10)
        heroes = response.json()

        hero_data = None
        hero_id = None
        
        for h in heroes:
            name = h.get("localized_name", "")
            api_name = h.get("name", "")

            if user_hero == normalize(name) or user_hero in normalize(name) or user_hero in normalize(api_name):
                hero_data = h
                hero_id = h.get("id")
                break

        if not hero_data:
            await send_answer(message, "Герой не найден. Попробуй написать имя на английском.")
            return

        roles = ", ".join(hero_data.get("roles", []))

        # Получаем про статистику и общий wr
        hero_stats_response = requests.get(f"{OPENDOTA}/heroStats", timeout=10)
        hero_stats = hero_stats_response.json()
        
        pro_wr = 50.0
        general_wr = 50.0
        
        for stat in hero_stats:
            if stat.get("id") == hero_id:
                pro_pick = stat.get("pro_pick", 0)
                pro_win = stat.get("pro_win", 0)
                if pro_pick > 0:
                    pro_wr = (pro_win / pro_pick) * 100
                
                # Общий wr из всех рангов
                total_picks = 0
                total_wins = 0
                for bracket in range(1, 9):
                    pick_key = f"{bracket}_pick"
                    win_key = f"{bracket}_win"
                    total_picks += stat.get(pick_key, 0)
                    total_wins += stat.get(win_key, 0)
                
                if total_picks > 0:
                    general_wr = (total_wins / total_picks) * 100
                break

        # Получаем матчапы
        matchups_response = requests.get(f"{OPENDOTA}/heroes/{hero_id}/matchups", timeout=10)
        matchups = matchups_response.json()
        
        # Сортируем по винрейту (как на сайте)
        matchups_sorted = sorted(
            matchups, 
            key=lambda x: (x.get("wins", 0) / max(x.get("games_played", 1), 1)) * 100, 
            reverse=True
        )
        
        best_matchups = matchups_sorted[:5]
        worst_matchups = matchups_sorted[-5:][::-1]

        text = (
            f"Герой: {hero_data.get('localized_name')}\n"
            f"Тип атаки: {hero_data.get('attack_type')}\n"
            f"Роли: {roles}\n"
            f"ID героя: {hero_data.get('id')}\n\n"
            f"Pro WR: {pro_wr:.1f}%\n"
            f"Общий WR: {general_wr:.1f}%\n\n"
            f"Лучшие матчапы (против):\n"
        )
        
        for matchup in best_matchups:
            against_id = matchup.get("hero_id")
            games = matchup.get("games_played", 0)
            wins = matchup.get("wins", 0)
            wr = (wins / games * 100) if games > 0 else 0
            
            # Находим имя противника
            against_name = "Unknown"
            for h in heroes:
                if h.get("id") == against_id:
                    against_name = h.get("localized_name")
                    break
            
            text += f"vs {against_name}: {wr:.1f}% ({games})\n"
        
        text += f"\nХудшие матчапы (против):\n"
        
        for matchup in worst_matchups:
            against_id = matchup.get("hero_id")
            games = matchup.get("games_played", 0)
            wins = matchup.get("wins", 0)
            wr = (wins / games * 100) if games > 0 else 0
            
            # Находим имя противника
            against_name = "Unknown"
            for h in heroes:
                if h.get("id") == against_id:
                    against_name = h.get("localized_name")
                    break
            
            text += f"vs {against_name}: {wr:.1f}% ({games})\n"

        await send_answer(message, text)

    except Exception as e:
        await send_answer(message, f"Ошибка: {e}")

@router.message(Command("meta"))
async def meta(message: Message):
    log_dialog(message.from_user.id, "USER", message.text)

    try:
        response = requests.get(
            "https://api.opendota.com/api/heroStats",
            timeout=10
        )

        heroes = response.json()

        total_picks = sum(hero.get("pro_pick", 0) for hero in heroes)
        total_pro_matches = total_picks / 10

        meta_heroes = []

        for hero in heroes:
            name = hero.get("localized_name")
            pro_pick = hero.get("pro_pick", 0)
            pro_ban = hero.get("pro_ban", 0)
            pro_win = hero.get("pro_win", 0)

            pick_ban_count = pro_pick + pro_ban

            if pro_pick > 0:
                winrate = pro_win / pro_pick * 100
            else:
                winrate = 0

            if total_pro_matches > 0:
                pick_ban_percent = pick_ban_count / total_pro_matches * 100
            else:
                pick_ban_percent = 0

            if pick_ban_count > 0:
                meta_heroes.append({
                    "name": name,
                    "winrate": winrate,
                    "pick_ban_percent": pick_ban_percent,
                    "pick_ban_count": pick_ban_count,
                    "pro_pick": pro_pick,
                    "pro_ban": pro_ban
                })

        sorted_heroes = sorted(
            meta_heroes,
            key=lambda x: x["pick_ban_percent"],
            reverse=True
        )

        sorted_heroes = [
            hero for hero in sorted_heroes
            if hero["winrate"] > 50
        ]

        text = "Топ метовых героев с WR больше 50%:\n\n"

        for hero in sorted_heroes[:10]:
            text += (
                f"{hero['name']}\n"
                f"WR: {hero['winrate']:.1f}% | "
                f"Pick+Ban: {hero['pick_ban_percent']:.1f}% "
                f"{hero['pick_ban_count']}\n\n"
            )

        if not sorted_heroes:
            text = "Нет героев с WR больше 50%."

        await send_answer(message, text)

    except Exception as e:
        await send_answer(message, f"Ошибка: {e}")

@router.message(Command("draft"))
async def draft_analysis(message: Message):
    log_dialog(message.from_user.id, "USER", message.text)

    try:
        command_text = message.text.replace("/draft", "", 1).strip()

        if " vs " not in command_text:
            await send_answer(
                message,
                "Пример:\n"
                "/draft rubick,pangolier,windranger,hoodwink,lone druid "
                "vs kunkka,keeper of the light,dawnbreaker,death prophet,crystal maiden"
            )
            return

        radiant_text, dire_text = command_text.split(" vs ", 1)

        radiant_names = [name.strip() for name in radiant_text.split(",") if name.strip()]
        dire_names = [name.strip() for name in dire_text.split(",") if name.strip()]

        if len(radiant_names) != 5 or len(dire_names) != 5:
            await send_answer(
                message,
                "Нужно указать ровно 5 героев за Свет и 5 героев за Тьму."
            )
            return

        response = requests.get(
            "https://api.opendota.com/api/heroStats",
            timeout=10
        )

        heroes = response.json()

        hero_map = {}
        for hero in heroes:
            name = hero.get("localized_name", "")
            hero_map[normalize(name)] = hero

        radiant_heroes = []
        dire_heroes = []
        not_found = []

        for name in radiant_names:
            key = normalize(name)
            if key in hero_map:
                radiant_heroes.append(hero_map[key])
            else:
                not_found.append(name)

        for name in dire_names:
            key = normalize(name)
            if key in hero_map:
                dire_heroes.append(hero_map[key])
            else:
                not_found.append(name)

        if not_found:
            await send_answer(
                message,
                "Не нашел героев:\n" + "\n".join(not_found)
            )
            return

        radiant_score = calculate_team_score(radiant_heroes)
        dire_score = calculate_team_score(dire_heroes)

        total = radiant_score + dire_score

        radiant_chance = round((radiant_score / total) * 100, 1)
        dire_chance = round((dire_score / total) * 100, 1)

        radiant_list = ", ".join([hero["localized_name"] for hero in radiant_heroes])
        dire_list = ", ".join([hero["localized_name"] for hero in dire_heroes])

        if radiant_chance > dire_chance:
            prediction = "Вероятнее победит Свет."
        elif dire_chance > radiant_chance:
            prediction = "Вероятнее победит Тьма."
        else:
            prediction = "Шансы примерно равны."

        text = (
            "Анализ драфта:\n\n"
            f"Свет:\n{radiant_list}\n\n"
            f"Тьма:\n{dire_list}\n\n"
            f"Шанс Света: {radiant_chance}%\n"
            f"Шанс Тьмы: {dire_chance}%\n\n"
            f"{prediction}"
        )

        await send_answer(message, text)

    except Exception as e:
        await send_answer(message, f"Ошибка анализа драфта: {e}")

@router.message(Command("news"))
async def dota_news(message: Message):
    log_dialog(message.from_user.id, "USER", message.text)

    try:
        url = "https://www.cybersport.ru/tags/dota-2"

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            await send_answer(message, f"Ошибка при получении страницы: {response.status_code}")
            return

        soup = BeautifulSoup(response.text, "html.parser")

        news_items = []

        links = soup.select("a[href]")

        for link in links:
            title = link.get_text(" ", strip=True)
            href = link.get("href")

            if not title or not href:
                continue

            if len(title) < 20:
                continue

            if href.startswith("/"):
                href = "https://www.cybersport.ru" + href

            if "dota" not in title.lower() and "dota-2" not in href.lower():
                continue

            if title not in [item["title"] for item in news_items]:
                news_items.append({
                    "title": title,
                    "url": href
                })

            if len(news_items) == 5:
                break

        if not news_items:
            await send_answer(
                message,
                "Не удалось найти новости. Возможно, сайт изменил HTML-разметку."
            )
            return

        text = "Последние новости Dota 2 через HTML-скрапинг:\n\n"

        for index, item in enumerate(news_items, start=1):
            text += (
                f"{index}. {item['title']}\n"
                f"{item['url']}\n\n"
            )

        await send_answer(message, text)

    except Exception as e:
        await send_answer(message, f"Ошибка HTML-скрапинга: {e}")        

@router.message()
async def unknown(message: Message):
    log_dialog(message.from_user.id, "USER", message.text)
    await send_answer(message, "Неизвестная команда. Напиши /start")


async def main():
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())