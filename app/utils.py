# app/utils.py
import json
import os
import random
import uuid
from datetime import datetime, timedelta
import pytz
from PIL import Image
from flask import current_app
from werkzeug.utils import secure_filename
from app import db
from app.models import Airport, Flight, CLASSES, BAGGAGE_PRICE



def format_city_name(city_name):
    if not city_name:
        return city_name
    return city_name.strip().title()


def get_all_cities():
    airports = Airport.query.all()
    cities = set()
    for ap in airports:
        cities.add(ap.city_ru)
    return sorted(list(cities))


def get_airport_info(city_name):
    if not city_name:
        return {'exists': False, 'city': city_name}

    from app.models import Airport

    city_name_clean = format_city_name(city_name)

    airport = Airport.query.filter(Airport.city_ru == city_name_clean).first()
    if airport:
        return {
            'exists': True,
            'city': airport.city_ru,
            'code': airport.iata_code,
            'airport': airport.airport_name,
            'timezone': airport.timezone
        }

    airports = Airport.query.filter(Airport.city_ru.ilike(f'%{city_name_clean}%')).all()
    if airports:
        airport = airports[0]
        return {
            'exists': True,
            'city': airport.city_ru,
            'code': airport.iata_code,
            'airport': airport.airport_name,
            'timezone': airport.timezone
        }

    airport_by_code = Airport.query.filter(Airport.iata_code.ilike(f'%{city_name_clean}%')).first()
    if airport_by_code:
        return {
            'exists': True,
            'city': airport_by_code.city_ru,
            'code': airport_by_code.iata_code,
            'airport': airport_by_code.airport_name,
            'timezone': airport_by_code.timezone
        }

    return {'exists': False, 'city': city_name}


def check_city_has_airport(city_name):
    if not city_name:
        return False

    from app.models import Airport

    city_name_clean = format_city_name(city_name)

    airport = Airport.query.filter(Airport.city_ru == city_name_clean).first()
    if airport:
        return True

    airports = Airport.query.filter(Airport.city_ru.ilike(f'%{city_name_clean}%')).all()
    if airports:
        return True

    airport_by_code = Airport.query.filter(Airport.iata_code.ilike(f'%{city_name_clean}%')).first()
    if airport_by_code:
        return True

    return False


def get_alternative_cities(city_name):
    if not city_name:
        return []

    from app.models import Airport

    city_name_clean = format_city_name(city_name).lower()

    cities_in_db = Airport.query.with_entities(Airport.city_ru).distinct().all()
    cities_list = [city[0] for city in cities_in_db]

    alternatives = []
    for db_city in cities_list:
        db_city_lower = db_city.lower()
        if city_name_clean in db_city_lower or db_city_lower in city_name_clean:
            if db_city not in alternatives:
                alternatives.append(db_city)

    if not alternatives:
        alternatives = cities_list[:5]

    return alternatives

def get_all_airports():
    from app.models import Airport
    airports = Airport.query.all()
    return [(a.city_ru, a.iata_code) for a in airports]

def save_avatar(form_avatar):
    filename = secure_filename(form_avatar.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
    new_filename = f"avatar_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], new_filename)
    image = Image.open(form_avatar)
    image.thumbnail((300, 300))
    image.save(filepath, optimize=True, quality=85)
    return new_filename


def create_default_avatar():
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
    os.makedirs(static_dir, exist_ok=True)
    avatar_path = os.path.join(static_dir, 'default_avatar.png')
    if not os.path.exists(avatar_path):
        img = Image.new('RGB', (200, 200), color=(52, 152, 219))
        try:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((70, 90), "User", fill=(255, 255, 255))
        except:
            pass
        img.save(avatar_path)


def generate_stop_info(origin_city, origin_airport, dest_city, dest_airport, stops_count):
    if stops_count == 0:
        return None

    all_cities = get_all_cities()
    stop_cities = [c for c in all_cities if c != origin_city and c != dest_city]

    if not stop_cities:
        return None

    stops_list = []
    used_cities = []

    for i in range(min(stops_count, len(stop_cities))):
        available_cities = [c for c in stop_cities if c not in used_cities]
        if not available_cities:
            break
        stop_city = random.choice(available_cities)
        used_cities.append(stop_city)
        stop_airport_info = get_airport_info(stop_city)
        stop_airport_name = stop_airport_info.get('airport', stop_city) if stop_airport_info else stop_city
        layover_time = random.randint(45, 240)
        layover_hours = layover_time // 60
        layover_mins = layover_time % 60
        layover_str = f"{layover_hours}ч {layover_mins}мин" if layover_hours > 0 else f"{layover_mins}мин"
        stops_list.append({
            'number': i + 1,
            'city': stop_city,
            'airport': stop_airport_name,
            'layover_minutes': layover_time,
            'layover_str': layover_str
        })
    return stops_list


def calculate_flight_price(flight, travel_class, adults, children, infants, baggage_addon):
    if not flight:
        return {'total': 0, 'adults_price': 0, 'children_price': 0}

    if hasattr(flight, 'get_price'):
        price_per_adult = flight.get_price(travel_class, baggage_addon)
    else:
        multiplier = CLASSES.get(travel_class, CLASSES['economy'])['multiplier']
        price_per_adult = int(flight['base_price'] * multiplier)
        if baggage_addon and not flight.get('baggage', False):
            price_per_adult += BAGGAGE_PRICE

    price_per_child = int(price_per_adult * 0.5)
    total = (adults * price_per_adult) + (children * price_per_child)

    return {
        'adults_price': price_per_adult,
        'children_price': price_per_child,
        'total': total
    }



def generate_flights_for_date(origin, destination, date, travel_class, baggage_addon):
    origin_info = get_airport_info(origin)
    dest_info = get_airport_info(destination)

    if not origin_info['exists'] or not dest_info['exists']:
        return []

    try:
        start_datetime = datetime.combine(date, datetime.min.time())
        end_datetime = datetime.combine(date + timedelta(days=1), datetime.min.time())

        existing_flights = Flight.query.filter(
            Flight.origin_city == origin_info['city'],
            Flight.destination_city == dest_info['city'],
            Flight.departure_time >= start_datetime,
            Flight.departure_time < end_datetime
        ).all()

        if existing_flights:
            result = []
            for f in existing_flights:
                multiplier = CLASSES.get(travel_class, CLASSES['economy'])['multiplier']
                price = int(f.base_price * multiplier)
                baggage_price = 0
                if baggage_addon and not f.baggage:
                    price += BAGGAGE_PRICE
                    baggage_price = BAGGAGE_PRICE

                result.append({
                    'id': f.id,
                    'airline': f.airline,
                    'flight_number': f.flight_number,
                    'origin_city': f.origin_city,
                    'origin_code': f.origin_code,
                    'origin_airport': f.origin_airport,
                    'origin_timezone': f.origin_timezone,
                    'destination_city': f.destination_city,
                    'destination_code': f.destination_code,
                    'destination_airport': f.destination_airport,
                    'destination_timezone': f.destination_timezone,
                    'departure_time': f.departure_time,
                    'arrival_time': f.arrival_time,
                    'duration_minutes': f.duration_minutes,
                    'duration_str': f.duration_str,
                    'total_duration_minutes': f.total_duration_minutes,
                    'total_duration_str': f.total_duration_str,
                    'stops': f.stops,
                    'stop_info': f.stop_info_parsed,
                    'baggage': f.baggage or baggage_addon,
                    'base_price': f.base_price,
                    'price': price,
                    'baggage_price': baggage_price,
                    'stops_str': f.stops_str
                })
            return result
    except Exception as e:
        print(f"Ошибка: {e}")
        db.session.rollback()

    # Генерация новых рейсов
    airlines_list = [
        ("Аэрофлот", "SU"), ("S7 Airlines", "S7"), ("Уральские авиалинии", "U6"),
        ("Победа", "DP"), ("Россия", "FV"), ("Utair", "UT"), ("Nordwind", "N4"),
        ("Red Wings", "WZ"), ("Azur Air", "ZF"), ("Якутия", "R3"),
    ]

    num_flights = random.randint(8, 15)
    generated_flights = []

    for i in range(num_flights):
        airline_name, airline_code = random.choice(airlines_list)
        flight_number = f"{airline_code}{random.randint(100, 999)}"

        try:
            origin_tz = pytz.timezone(origin_info['timezone'])
            hour = random.randint(0, 23)
            minute = random.choice([0, 15, 30, 45])
            local_departure = datetime.combine(date, datetime.min.time()) + timedelta(hours=hour, minutes=minute)
            local_departure_aware = origin_tz.localize(local_departure)
            departure_utc = local_departure_aware.astimezone(pytz.UTC).replace(tzinfo=None)
        except Exception as e:
            continue

        flight_duration = random.randint(60, 480)

        stops_rand = random.random()
        if stops_rand < 0.55:
            stops = 0
            stop_info_dict = None
            total_layover = 0
        elif stops_rand < 0.85:
            stops = 1
            stop_info_dict = generate_stop_info(origin_info['city'], origin_info['airport'],
                                                dest_info['city'], dest_info['airport'], stops)
            total_layover = sum(stop.get('layover_minutes', 0) for stop in stop_info_dict) if stop_info_dict else 0
        else:
            stops = 2
            stop_info_dict = generate_stop_info(origin_info['city'], origin_info['airport'],
                                                dest_info['city'], dest_info['airport'], stops)
            total_layover = sum(stop.get('layover_minutes', 0) for stop in stop_info_dict) if stop_info_dict else 0

        total_duration = flight_duration + total_layover
        arrival_utc = departure_utc + timedelta(minutes=total_duration)

        base_price = random.randint(3000, 80000)
        baggage = random.random() < 0.7

        flight = Flight(
            airline=airline_name,
            flight_number=flight_number,
            origin_city=origin_info['city'],
            origin_code=origin_info['code'],
            origin_airport=origin_info['airport'],
            origin_timezone=origin_info['timezone'],
            destination_city=dest_info['city'],
            destination_code=dest_info['code'],
            destination_airport=dest_info['airport'],
            destination_timezone=dest_info['timezone'],
            departure_time=departure_utc,
            arrival_time=arrival_utc,
            duration_minutes=flight_duration,
            stops=stops,
            stop_info=json.dumps(stop_info_dict, ensure_ascii=False) if stop_info_dict else None,
            baggage=baggage,
            base_price=base_price
        )

        db.session.add(flight)
        db.session.flush()

        multiplier = CLASSES.get(travel_class, CLASSES['economy'])['multiplier']
        price = int(base_price * multiplier)
        baggage_price = 0
        if baggage_addon and not baggage:
            price += BAGGAGE_PRICE
            baggage_price = BAGGAGE_PRICE

        generated_flights.append({
            'id': flight.id,
            'airline': airline_name,
            'flight_number': flight_number,
            'origin_city': origin_info['city'],
            'origin_code': origin_info['code'],
            'origin_airport': origin_info['airport'],
            'origin_timezone': origin_info['timezone'],
            'destination_city': dest_info['city'],
            'destination_code': dest_info['code'],
            'destination_airport': dest_info['airport'],
            'destination_timezone': dest_info['timezone'],
            'departure_time': departure_utc,
            'arrival_time': arrival_utc,
            'duration_minutes': flight_duration,
            'duration_str': f"{flight_duration // 60}ч {flight_duration % 60}мин",
            'total_duration_minutes': total_duration,
            'total_duration_str': f"{total_duration // 60}ч {total_duration % 60}мин",
            'stops': stops,
            'stop_info': stop_info_dict,
            'baggage': baggage or baggage_addon,
            'base_price': base_price,
            'price': price,
            'baggage_price': baggage_price,
            'stops_str': "Без пересадок" if stops == 0 else f"{stops} пересадка" if stops == 1 else f"{stops} пересадки"
        })

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return []

    generated_flights.sort(key=lambda x: x['departure_time'])
    return generated_flights


def get_flight_by_id(flight_id):
    if not flight_id:
        return None
    try:
        return db.session.get(Flight, int(flight_id))
    except (ValueError, TypeError):
        return None


def add_airports_from_list():
    airports_data = [
        {"iata": "ABA", "city_ru": "Абакан", "airport": "Абакан", "timezone": "Asia/Krasnoyarsk", "region": "Хакасия",
         "runway": 3250},
        {"iata": "AAQ", "city_ru": "Анапа", "airport": "Анапа (Витязево)", "timezone": "Europe/Moscow",
         "region": "Краснодарский край", "runway": 2500},
        {"iata": "ARH", "city_ru": "Архангельск", "airport": "Архангельск (Талаги)", "timezone": "Europe/Moscow",
         "region": "Архангельская область", "runway": 2500},
        {"iata": "ASF", "city_ru": "Астрахань", "airport": "Астрахань (имени Б. Н. Кустодиева)",
         "timezone": "Europe/Astrakhan", "region": "Астраханская область", "runway": 3200},
        {"iata": "BAX", "city_ru": "Барнаул", "airport": "Барнаул (Михайловка)", "timezone": "Asia/Barnaul",
         "region": "Алтайский край", "runway": 2850},
        {"iata": "EGO", "city_ru": "Белгород", "airport": "Белгород (имени В. Г. Шухова)", "timezone": "Europe/Moscow",
         "region": "Белгородская область", "runway": 2500},
        {"iata": "BQS", "city_ru": "Благовещенск", "airport": "Благовещенск (Игнатьево)", "timezone": "Asia/Yakutsk",
         "region": "Амурская область", "runway": 3000},
        {"iata": "BTK", "city_ru": "Братск", "airport": "Братск", "timezone": "Asia/Irkutsk",
         "region": "Иркутская область", "runway": 3160},
        {"iata": "BZK", "city_ru": "Брянск", "airport": "Брянск", "timezone": "Europe/Moscow",
         "region": "Брянская область", "runway": 2400},
        {"iata": "VVO", "city_ru": "Владивосток", "airport": "Владивосток (Кневичи)", "timezone": "Asia/Vladivostok",
         "region": "Приморский край", "runway": 3500},
        {"iata": "OGZ", "city_ru": "Владикавказ", "airport": "Владикавказ (Беслан)", "timezone": "Europe/Moscow",
         "region": "Северная Осетия", "runway": 3000},
        {"iata": "VOG", "city_ru": "Волгоград", "airport": "Волгоград (Сталинград)", "timezone": "Europe/Volgograd",
         "region": "Волгоградская область", "runway": 3280},
        {"iata": "VOZ", "city_ru": "Воронеж", "airport": "Воронеж (имени Петра I)", "timezone": "Europe/Moscow",
         "region": "Воронежская область", "runway": 2300},
        {"iata": "RGK", "city_ru": "Горно-Алтайск", "airport": "Горно-Алтайск", "timezone": "Asia/Barnaul",
         "region": "Республика Алтай", "runway": 2300},
        {"iata": "GRV", "city_ru": "Грозный", "airport": "Грозный (Северный)", "timezone": "Europe/Moscow",
         "region": "Чеченская Республика", "runway": 2500},
        {"iata": "SVX", "city_ru": "Екатеринбург", "airport": "Екатеринбург (Кольцово)",
         "timezone": "Asia/Yekaterinburg", "region": "Свердловская область", "runway": 3026},
        {"iata": "ZIA", "city_ru": "Жуковский", "airport": "Жуковский (Раменское)", "timezone": "Europe/Moscow",
         "region": "Московская область", "runway": 5403},
        {"iata": "IJK", "city_ru": "Ижевск", "airport": "Ижевск", "timezone": "Europe/Samara", "region": "Удмуртия",
         "runway": 2500},
        {"iata": "IKT", "city_ru": "Иркутск", "airport": "Иркутск", "timezone": "Asia/Irkutsk",
         "region": "Иркутская область", "runway": 3565},
        {"iata": "KZN", "city_ru": "Казань", "airport": "Казань (имени Габдуллы Тукая)", "timezone": "Europe/Moscow",
         "region": "Татарстан", "runway": 3750},
        {"iata": "KGD", "city_ru": "Калининград", "airport": "Калининград (Храброво)", "timezone": "Europe/Kaliningrad",
         "region": "Калининградская область", "runway": 3350},
        {"iata": "KLF", "city_ru": "Калуга", "airport": "Калуга (Грабцево)", "timezone": "Europe/Moscow",
         "region": "Калужская область", "runway": 2200},
        {"iata": "KEJ", "city_ru": "Кемерово", "airport": "Кемерово (имени А. А. Леонова)",
         "timezone": "Asia/Novokuznetsk", "region": "Кемеровская область", "runway": 3200},
        {"iata": "KRR", "city_ru": "Краснодар", "airport": "Краснодар (Пашковский)", "timezone": "Europe/Moscow",
         "region": "Краснодарский край", "runway": 3000},
        {"iata": "KJA", "city_ru": "Красноярск", "airport": "Красноярск (Емельяново)", "timezone": "Asia/Krasnoyarsk",
         "region": "Красноярский край", "runway": 3700},
        {"iata": "URS", "city_ru": "Курск", "airport": "Курск (Восточный)", "timezone": "Europe/Moscow",
         "region": "Курская область", "runway": 2500},
        {"iata": "LPK", "city_ru": "Липецк", "airport": "Липецк", "timezone": "Europe/Moscow",
         "region": "Липецкая область", "runway": 2300},
        {"iata": "MCX", "city_ru": "Махачкала", "airport": "Махачкала (Уйташ)", "timezone": "Europe/Moscow",
         "region": "Дагестан", "runway": 2640},
        {"iata": "MRV", "city_ru": "Минеральные Воды", "airport": "Минеральные Воды (имени М. Ю. Лермонтова)",
         "timezone": "Europe/Moscow", "region": "Ставропольский край", "runway": 3900},
        {"iata": "VKO", "city_ru": "Москва", "airport": "Внуково", "timezone": "Europe/Moscow", "region": "Москва",
         "runway": 3500},
        {"iata": "DME", "city_ru": "Москва", "airport": "Домодедово", "timezone": "Europe/Moscow", "region": "Москва",
         "runway": 3794},
        {"iata": "SVO", "city_ru": "Москва", "airport": "Шереметьево", "timezone": "Europe/Moscow", "region": "Москва",
         "runway": 3703},
        {"iata": "MMK", "city_ru": "Мурманск", "airport": "Мурманск (имени Николая II)", "timezone": "Europe/Moscow",
         "region": "Мурманская область", "runway": 2500},
        {"iata": "NAL", "city_ru": "Нальчик", "airport": "Нальчик", "timezone": "Europe/Moscow",
         "region": "Кабардино-Балкария", "runway": 2200},
        {"iata": "NJC", "city_ru": "Нижневартовск", "airport": "Нижневартовск", "timezone": "Asia/Yekaterinburg",
         "region": "Ханты-Мансийский АО", "runway": 3200},
        {"iata": "NBC", "city_ru": "Нижнекамск", "airport": "Нижнекамск (Бегишево)", "timezone": "Europe/Moscow",
         "region": "Татарстан", "runway": 2506},
        {"iata": "GOJ", "city_ru": "Нижний Новгород", "airport": "Нижний Новгород (Стригино)",
         "timezone": "Europe/Moscow", "region": "Нижегородская область", "runway": 2805},
        {"iata": "NOZ", "city_ru": "Новокузнецк", "airport": "Новокузнецк (Спиченково)",
         "timezone": "Asia/Novokuznetsk", "region": "Кемеровская область", "runway": 2680},
        {"iata": "OVB", "city_ru": "Новосибирск", "airport": "Новосибирск (Толмачёво)", "timezone": "Asia/Novosibirsk",
         "region": "Новосибирская область", "runway": 3597},
        {"iata": "OMS", "city_ru": "Омск", "airport": "Омск (Центральный)", "timezone": "Asia/Omsk",
         "region": "Омская область", "runway": 2500},
        {"iata": "REN", "city_ru": "Оренбург", "airport": "Оренбург (Центральный)", "timezone": "Asia/Yekaterinburg",
         "region": "Оренбургская область", "runway": 2500},
        {"iata": "PEE", "city_ru": "Пермь", "airport": "Пермь (Большое Савино)", "timezone": "Asia/Yekaterinburg",
         "region": "Пермский край", "runway": 3200},
        {"iata": "PKC", "city_ru": "Петропавловск-Камчатский", "airport": "Петропавловск-Камчатский (Елизово)",
         "timezone": "Asia/Kamchatka", "region": "Камчатский край", "runway": 3400},
        {"iata": "ROV", "city_ru": "Ростов-на-Дону", "airport": "Ростов-на-Дону (Платов)", "timezone": "Europe/Moscow",
         "region": "Ростовская область", "runway": 3600},
        {"iata": "KUF", "city_ru": "Самара", "airport": "Самара (Курумоч)", "timezone": "Europe/Samara",
         "region": "Самарская область", "runway": 3000},
        {"iata": "LED", "city_ru": "Санкт-Петербург", "airport": "Пулково", "timezone": "Europe/Moscow",
         "region": "Санкт-Петербург", "runway": 3782},
        {"iata": "GSV", "city_ru": "Саратов", "airport": "Саратов (Гагарин)", "timezone": "Europe/Saratov",
         "region": "Саратовская область", "runway": 3000},
        {"iata": "AER", "city_ru": "Сочи", "airport": "Сочи (Адлер)", "timezone": "Europe/Moscow",
         "region": "Краснодарский край", "runway": 2850},
        {"iata": "STW", "city_ru": "Ставрополь", "airport": "Ставрополь (Шпаковское)", "timezone": "Europe/Moscow",
         "region": "Ставропольский край", "runway": 2600},
        {"iata": "SGC", "city_ru": "Сургут", "airport": "Сургут (имени Ф. К. Салманова)",
         "timezone": "Asia/Yekaterinburg", "region": "ХМАО", "runway": 2780},
        {"iata": "SCW", "city_ru": "Сыктывкар", "airport": "Сыктывкар (имени П. А. Истомина)",
         "timezone": "Europe/Moscow", "region": "Коми", "runway": 2500},
        {"iata": "TOF", "city_ru": "Томск", "airport": "Томск (Богашёво)", "timezone": "Asia/Tomsk",
         "region": "Томская область", "runway": 2500},
        {"iata": "TJM", "city_ru": "Тюмень", "airport": "Тюмень (Рощино)", "timezone": "Asia/Yekaterinburg",
         "region": "Тюменская область", "runway": 3000},
        {"iata": "UUD", "city_ru": "Улан-Удэ", "airport": "Улан-Удэ (Мухино)", "timezone": "Asia/Irkutsk",
         "region": "Бурятия", "runway": 2997},
        {"iata": "ULV", "city_ru": "Ульяновск", "airport": "Ульяновск (Баратаевка)", "timezone": "Europe/Ulyanovsk",
         "region": "Ульяновская область", "runway": 3820},
        {"iata": "UFA", "city_ru": "Уфа", "airport": "Уфа (имени Мустая Карима)", "timezone": "Asia/Yekaterinburg",
         "region": "Башкортостан", "runway": 3760},
        {"iata": "KHV", "city_ru": "Хабаровск", "airport": "Хабаровск (Новый)", "timezone": "Asia/Vladivostok",
         "region": "Хабаровский край", "runway": 4000},
        {"iata": "HMA", "city_ru": "Ханты-Мансийск", "airport": "Ханты-Мансийск", "timezone": "Asia/Yekaterinburg",
         "region": "Ханты-Мансийский АО", "runway": 2800},
        {"iata": "CSY", "city_ru": "Чебоксары", "airport": "Чебоксары (имени А. Г. Николаева)",
         "timezone": "Europe/Moscow", "region": "Чувашия", "runway": 2512},
        {"iata": "CEK", "city_ru": "Челябинск", "airport": "Челябинск (Баландино)", "timezone": "Asia/Yekaterinburg",
         "region": "Челябинская область", "runway": 3200},
        {"iata": "HTA", "city_ru": "Чита", "airport": "Чита (Кадала)", "timezone": "Asia/Chita",
         "region": "Читинская область", "runway": 2800},
        {"iata": "YKS", "city_ru": "Якутск", "airport": "Якутск (имени Платона Ойунского)", "timezone": "Asia/Yakutsk",
         "region": "Якутия", "runway": 3400},
        {"iata": "IAR", "city_ru": "Ярославль", "airport": "Ярославль (Туношна)", "timezone": "Europe/Moscow",
         "region": "Ярославская область", "runway": 3000},
    ]

    for ap_data in airports_data:
        existing = Airport.query.filter_by(iata_code=ap_data["iata"]).first()
        if not existing:
            airport = Airport(
                iata_code=ap_data["iata"],
                city_ru=ap_data["city_ru"],
                airport_name=ap_data["airport"],
                timezone=ap_data["timezone"],
                region=ap_data["region"],
                runway_length=ap_data["runway"]
            )
            db.session.add(airport)

    db.session.commit()
    print(f"✅ Добавлено аэропортов: {len(airports_data)}")


def generate_flights():
    airports = Airport.query.all()
    if len(airports) < 2:
        print("❌ Недостаточно аэропортов")
        return

    airlines = [
        ("Аэрофлот", "SU"), ("S7 Airlines", "S7"), ("Уральские авиалинии", "U6"),
        ("Победа", "DP"), ("Россия", "FV"), ("Utair", "UT"),
    ]

    flights = []
    for i in range(200):
        origin = random.choice(airports)
        dest = random.choice([a for a in airports if a.id != origin.id])
        airline = random.choice(airlines)
        days_offset = random.randint(1, 60)

        try:
            origin_tz = pytz.timezone(origin.timezone)
            local_departure = datetime.now(origin_tz) + timedelta(days=days_offset, hours=random.randint(0, 20))
            departure_utc = local_departure.astimezone(pytz.UTC).replace(tzinfo=None)
        except:
            departure_utc = datetime.now() + timedelta(days=days_offset)

        duration = random.randint(60, 480)
        arrival_utc = departure_utc + timedelta(minutes=duration)

        flight = Flight(
            airline=airline[0],
            flight_number=f"{airline[1]}{random.randint(100, 999)}",
            origin_city=origin.city_ru,
            origin_code=origin.iata_code,
            origin_airport=origin.airport_name,
            origin_timezone=origin.timezone,
            destination_city=dest.city_ru,
            destination_code=dest.iata_code,
            destination_airport=dest.airport_name,
            destination_timezone=dest.timezone,
            departure_time=departure_utc,
            arrival_time=arrival_utc,
            duration_minutes=duration,
            stops=0,
            baggage=random.random() < 0.7,
            base_price=random.randint(3000, 100000)
        )
        flights.append(flight)

    if flights:
        db.session.bulk_save_objects(flights)
        db.session.commit()
        print(f"✅ Сгенерировано рейсов: {len(flights)}")