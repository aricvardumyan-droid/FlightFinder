import json
import os
import random
import uuid
from datetime import datetime, timedelta

import pytz
from PIL import Image
from flask import (Flask, render_template, redirect, url_for, flash, request,
                   jsonify, abort, send_from_directory)
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_restful import Api, Resource
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from wtforms import (StringField, PasswordField, SubmitField, BooleanField,
                     DateField, IntegerField, SelectField)
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, NumberRange

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))

app.config['SECRET_KEY'] = 'flightfinder-2026-super-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'flightfinder.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(basedir, 'templates'), exist_ok=True)
os.makedirs(os.path.join(basedir, 'static'), exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице'
api = Api(app)

CLASSES = {
    'economy': {'name': 'Эконом', 'multiplier': 1.0},
    'comfort': {'name': 'Комфорт', 'multiplier': 1.5},
    'business': {'name': 'Бизнес', 'multiplier': 2.5},
    'first': {'name': 'Первый класс', 'multiplier': 4.0}
}

BAGGAGE_PRICE = 5200


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='default_avatar.png')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    favorites = db.relationship('Favorite', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    searches = db.relationship('SearchHistory', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    bookings = db.relationship('Booking', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Airport(db.Model):
    __tablename__ = 'airports'

    id = db.Column(db.Integer, primary_key=True)
    iata_code = db.Column(db.String(3), unique=True, nullable=False)
    city_ru = db.Column(db.String(100), nullable=False)
    airport_name = db.Column(db.String(200), nullable=False)
    timezone = db.Column(db.String(50), nullable=False)
    region = db.Column(db.String(100), nullable=False)
    runway_length = db.Column(db.Integer, nullable=False)


class Flight(db.Model):
    __tablename__ = 'flights'

    id = db.Column(db.Integer, primary_key=True)
    airline = db.Column(db.String(100), nullable=False)
    flight_number = db.Column(db.String(20), nullable=False)

    origin_city = db.Column(db.String(100), nullable=False)
    origin_code = db.Column(db.String(3), nullable=False)
    origin_airport = db.Column(db.String(200), nullable=False, default='')
    origin_timezone = db.Column(db.String(50), nullable=False)
    destination_city = db.Column(db.String(100), nullable=False)
    destination_code = db.Column(db.String(3), nullable=False)
    destination_airport = db.Column(db.String(200), nullable=False, default='')
    destination_timezone = db.Column(db.String(50), nullable=False)

    departure_time = db.Column(db.DateTime, nullable=False)
    arrival_time = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)

    stops = db.Column(db.Integer, default=0)
    stop_info = db.Column(db.Text, nullable=True)
    baggage = db.Column(db.Boolean, default=True)
    base_price = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    favorited_by = db.relationship('Favorite', backref='flight', lazy='dynamic', cascade='all, delete-orphan')
    bookings = db.relationship('Booking', backref='flight', lazy='dynamic', cascade='all, delete-orphan')

    def get_price(self, travel_class='economy', baggage_addon=False):
        multiplier = CLASSES.get(travel_class, CLASSES['economy'])['multiplier']
        price = int(self.base_price * multiplier)
        if baggage_addon:
            price += BAGGAGE_PRICE
        return price

    @property
    def duration_str(self):
        hours = self.duration_minutes // 60
        minutes = self.duration_minutes % 60
        return f"{hours}ч {minutes}мин"

    @property
    def stops_str(self):
        if self.stops == 0:
            return "Без пересадок"
        elif self.stops == 1:
            return "1 пересадка"
        else:
            return f"{self.stops} пересадки"

    @property
    def stop_info_parsed(self):
        if not self.stop_info:
            return None
        if isinstance(self.stop_info, (dict, list)):
            return self.stop_info
        if isinstance(self.stop_info, str):
            try:
                return json.loads(self.stop_info)
            except:
                return self.stop_info
        return self.stop_info

    @stop_info_parsed.setter
    def stop_info_parsed(self, value):
        if value is None:
            self.stop_info = None
        elif isinstance(value, (dict, list)):
            self.stop_info = json.dumps(value, ensure_ascii=False)
        else:
            self.stop_info = str(value)

    @property
    def total_duration_minutes(self):
        if not self.stop_info_parsed or self.stops == 0:
            return self.duration_minutes

        stops_data = self.stop_info_parsed
        total_layover = 0
        if stops_data and isinstance(stops_data, list):
            for stop in stops_data:
                total_layover += stop.get('layover_minutes', 0)

        return self.duration_minutes + total_layover

    @property
    def total_duration_str(self):
        total_minutes = self.total_duration_minutes
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return f"{hours}ч {minutes}мин"


class Booking(db.Model):
    __tablename__ = 'bookings'

    id = db.Column(db.Integer, primary_key=True)
    booking_number = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    flight_id = db.Column(db.Integer, db.ForeignKey('flights.id'), nullable=False)

    adults = db.Column(db.Integer, default=1)
    children = db.Column(db.Integer, default=0)
    infants = db.Column(db.Integer, default=0)
    travel_class = db.Column(db.String(20), default='economy')
    baggage_addon = db.Column(db.Boolean, default=False)

    adults_price = db.Column(db.Integer, nullable=False)
    children_price = db.Column(db.Integer, nullable=False)
    infants_price = db.Column(db.Integer, default=0)
    baggage_price = db.Column(db.Integer, default=0)
    total_price = db.Column(db.Integer, nullable=False)

    status = db.Column(db.String(20), default='confirmed')
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)

    def generate_booking_number(self):
        return f"FLF-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


class Favorite(db.Model):
    __tablename__ = 'favorites'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    flight_id = db.Column(db.Integer, db.ForeignKey('flights.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'flight_id', name='unique_favorite'),)


class SearchHistory(db.Model):
    __tablename__ = 'search_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    origin = db.Column(db.String(100), nullable=False)
    destination = db.Column(db.String(100), nullable=False)
    departure_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=True)
    adults = db.Column(db.Integer, default=1)
    children = db.Column(db.Integer, default=0)
    infants = db.Column(db.Integer, default=0)
    travel_class = db.Column(db.String(20), default='economy')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class RoundTripBooking(db.Model):
    __tablename__ = 'round_trip_bookings'

    id = db.Column(db.Integer, primary_key=True)
    booking_number = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    outbound_flight_id = db.Column(db.Integer, db.ForeignKey('flights.id'), nullable=False)
    return_flight_id = db.Column(db.Integer, db.ForeignKey('flights.id'), nullable=True)

    adults = db.Column(db.Integer, default=1)
    children = db.Column(db.Integer, default=0)
    infants = db.Column(db.Integer, default=0)
    travel_class = db.Column(db.String(20), default='economy')
    baggage_addon = db.Column(db.Boolean, default=False)

    outbound_price = db.Column(db.Integer, nullable=False)
    return_price = db.Column(db.Integer, default=0)
    total_price = db.Column(db.Integer, nullable=False)

    status = db.Column(db.String(20), default='pending')
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)

    outbound_flight = db.relationship('Flight', foreign_keys=[outbound_flight_id])
    return_flight = db.relationship('Flight', foreign_keys=[return_flight_id])

    def generate_booking_number(self):
        return f"RTF-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    remember = BooleanField('Запомнить меня')
    submit = SubmitField('Войти')


class RegistrationForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired(), Length(min=2, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=6)])
    password2 = PasswordField('Повторите пароль', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Зарегистрироваться')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Это имя уже занято')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Этот email уже зарегистрирован')


class SearchForm(FlaskForm):
    origin = StringField('Откуда', validators=[DataRequired()], default='Москва')
    destination = StringField('Куда', validators=[DataRequired()])
    departure_date = DateField('Туда', validators=[DataRequired()], format='%Y-%m-%d')
    return_date = DateField('Обратно', format='%Y-%m-%d')
    round_trip = BooleanField('Обратный билет', default=True)
    adults = IntegerField('Взрослые (12+)', default=1, validators=[NumberRange(min=1, max=9)])
    children = IntegerField('Дети (2-11)', default=0, validators=[NumberRange(min=0, max=9)])
    infants = IntegerField('Младенцы (до 2 лет)', default=0, validators=[NumberRange(min=0, max=9)])
    travel_class = SelectField('Класс обслуживания',
                               choices=[('economy', 'Эконом'), ('comfort', 'Комфорт'),
                                        ('business', 'Бизнес'), ('first', 'Первый класс')],
                               default='economy')
    baggage_addon = BooleanField('Добавить багаж (+5200 ₽)', default=False)
    submit = SubmitField('Найти билеты')

    def validate_departure_date(self, field):
        if field.data and field.data < datetime.now().date():
            raise ValidationError('Дата вылета не может быть в прошлом')

    def validate_return_date(self, field):
        if field.data and self.departure_date.data and field.data < self.departure_date.data:
            raise ValidationError('Дата возврата не может быть раньше даты вылета')

    def validate_infants(self, field):
        if field.data > self.adults.data:
            raise ValidationError('Количество младенцев не может превышать количество взрослых')


class BookingForm(FlaskForm):
    adults = IntegerField('Взрослые (12+)', default=1, validators=[NumberRange(min=1, max=9)])
    children = IntegerField('Дети (2-11)', default=0, validators=[NumberRange(min=0, max=9)])
    infants = IntegerField('Младенцы (до 2 лет)', default=0, validators=[NumberRange(min=0, max=9)])
    travel_class = SelectField('Класс обслуживания',
                               choices=[('economy', 'Эконом'), ('comfort', 'Комфорт'),
                                        ('business', 'Бизнес'), ('first', 'Первый класс')],
                               default='economy')
    baggage_addon = BooleanField('Добавить багаж (+5200 ₽)', default=False)
    submit = SubmitField('Забронировать')

    def validate_infants(self, field):
        if field.data > self.adults.data:
            raise ValidationError('Количество младенцев не может превышать количество взрослых')


class FlightDetailAPI(Resource):
    def get(self, flight_id):
        try:
            flight = db.session.get(Flight, int(flight_id))
            if not flight:
                return {'success': False, 'error': 'Рейс не найден'}, 404

            stop_info = flight.stop_info_parsed

            travel_class = request.args.get('travel_class', 'economy')
            baggage_addon = request.args.get('baggage_addon', 'false').lower() == 'true'

            multiplier = CLASSES.get(travel_class, CLASSES['economy'])['multiplier']
            price = int(flight.base_price * multiplier)
            if baggage_addon and not flight.baggage:
                price += BAGGAGE_PRICE

            return {
                'success': True,
                'flight': {
                    'id': flight.id,
                    'airline': flight.airline,
                    'flight_number': flight.flight_number,
                    'origin_city': flight.origin_city,
                    'origin_code': flight.origin_code,
                    'origin_airport': flight.origin_airport,
                    'origin_timezone': flight.origin_timezone,
                    'destination_city': flight.destination_city,
                    'destination_code': flight.destination_code,
                    'destination_airport': flight.destination_airport,
                    'destination_timezone': flight.destination_timezone,
                    'departure_time': flight.departure_time.isoformat(),
                    'arrival_time': flight.arrival_time.isoformat(),
                    'duration_minutes': flight.duration_minutes,
                    'duration_str': flight.duration_str,
                    'total_duration_minutes': flight.total_duration_minutes,
                    'total_duration_str': flight.total_duration_str,
                    'stops': flight.stops,
                    'stops_str': flight.stops_str,
                    'stop_info': stop_info,
                    'baggage': flight.baggage,
                    'base_price': flight.base_price,
                    'price': price,
                    'travel_class': travel_class,
                    'baggage_addon': baggage_addon
                }
            }
        except Exception as e:
            print(f"Ошибка в FlightDetailAPI: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}, 500


api.add_resource(FlightDetailAPI, '/api/flight/<int:flight_id>')


class AvatarForm(FlaskForm):
    avatar = FileField('Выберите изображение', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Только изображения!')
    ])
    submit = SubmitField('Загрузить')


@app.route('/add_to_favorites', methods=['POST'])
@login_required
def add_to_favorites():
    try:
        data = request.get_json()
        print("=== ДОБАВЛЕНИЕ В ИЗБРАННОЕ ===")
        print("Получены данные:", data)

        flight_id = data.get('flight_id')

        flight = None
        if flight_id:
            try:
                flight = db.session.get(Flight, int(flight_id))
                print(f"Найден рейс по ID {flight_id}: {flight}")
            except (ValueError, TypeError) as e:
                print(f"Ошибка при поиске по ID: {e}")

        if not flight:
            print("Создаем новый рейс из данных")

            departure_time = data.get('departure_time')
            arrival_time = data.get('arrival_time')

            if isinstance(departure_time, str):
                try:
                    departure_time = datetime.fromisoformat(departure_time.replace('Z', '+00:00'))
                except:
                    departure_time = datetime.now()
            if isinstance(arrival_time, str):
                try:
                    arrival_time = datetime.fromisoformat(arrival_time.replace('Z', '+00:00'))
                except:
                    arrival_time = datetime.now()

            stop_info_data = data.get('stop_info')
            stop_info_json = None
            if stop_info_data:
                if isinstance(stop_info_data, (dict, list)):
                    stop_info_json = json.dumps(stop_info_data, ensure_ascii=False)
                elif isinstance(stop_info_data, str):
                    stop_info_json = stop_info_data

            flight = Flight(
                airline=data.get('airline', ''),
                flight_number=data.get('flight_number', ''),
                origin_city=data.get('origin_city', ''),
                origin_code=data.get('origin_code', ''),
                origin_airport=data.get('origin_airport', data.get('origin_city', '')),
                origin_timezone=data.get('origin_timezone', 'Europe/Moscow'),
                destination_city=data.get('destination_city', ''),
                destination_code=data.get('destination_code', ''),
                destination_airport=data.get('destination_airport', data.get('destination_city', '')),
                destination_timezone=data.get('destination_timezone', 'Europe/Moscow'),
                departure_time=departure_time,
                arrival_time=arrival_time,
                duration_minutes=data.get('duration_minutes', 0),
                stops=data.get('stops', 0),
                stop_info=stop_info_json,
                baggage=data.get('baggage', False),
                base_price=data.get('base_price', 0)
            )
            db.session.add(flight)
            db.session.flush()
            print(f"Создан новый рейс с ID: {flight.id}")

        existing_fav = Favorite.query.filter_by(user_id=current_user.id, flight_id=flight.id).first()
        if existing_fav:
            print("Рейс уже в избранном")
            return jsonify({'success': False, 'error': 'Уже в избранном'}), 400

        favorite = Favorite(user_id=current_user.id, flight_id=flight.id)
        db.session.add(favorite)
        db.session.commit()

        print(f"Рейс {flight.id} добавлен в избранное пользователя {current_user.id}")
        return jsonify({'success': True, 'flight_id': flight.id, 'message': 'Рейс добавлен в избранное'})

    except Exception as e:
        db.session.rollback()
        print(f"ОШИБКА при добавлении в избранное: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/cancel_booking_confirm/<int:booking_id>')
@login_required
def cancel_booking_confirm(booking_id):
    booking = Booking.query.get(booking_id)

    if not booking:
        round_trip_booking = RoundTripBooking.query.get(booking_id)
        if round_trip_booking:
            return render_template('cancel_booking_confirm_roundtrip.html', booking=round_trip_booking)
        else:
            abort(404)

    if booking.user_id != current_user.id:
        abort(404)

    if booking.status == 'cancelled':
        flash('Это бронирование уже отменено', 'info')
        return redirect(url_for('my_bookings'))

    return render_template('cancel_booking_confirm.html', booking=booking)


@app.route('/cancel_booking_with_captcha/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking_with_captcha(booking_id):
    booking = Booking.query.get(booking_id)

    if not booking:
        round_trip_booking = RoundTripBooking.query.get(booking_id)
        if round_trip_booking and round_trip_booking.user_id == current_user.id:
            captcha_answer = request.form.get('captcha_answer', '').strip()
            if captcha_answer == '4':
                round_trip_booking.status = 'cancelled'
                db.session.commit()
                flash('Бронирование успешно отменено', 'success')
            else:
                flash('Неправильный ответ. Отмена бронирования не выполнена.', 'danger')
            return redirect(url_for('my_round_trip_bookings'))
        else:
            abort(404)

    if not booking or booking.user_id != current_user.id:
        abort(404)

    captcha_answer = request.form.get('captcha_answer', '').strip()

    if captcha_answer == '4':
        booking.status = 'cancelled'
        db.session.commit()
        flash('Бронирование успешно отменено', 'success')
    else:
        flash('Неправильный ответ. Отмена бронирования не выполнена.', 'danger')

    return redirect(url_for('my_bookings'))


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def save_avatar(form_avatar):
    filename = secure_filename(form_avatar.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
    new_filename = f"avatar_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)

    image = Image.open(form_avatar)
    image.thumbnail((300, 300))
    image.save(filepath, optimize=True, quality=85)

    return new_filename


def create_default_avatar():
    avatar_path = os.path.join('static', 'default_avatar.png')
    if not os.path.exists(avatar_path):
        img = Image.new('RGB', (200, 200), color=(52, 152, 219))
        try:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((70, 90), "User", fill=(255, 255, 255))
        except:
            pass
        img.save(avatar_path)


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

    city_name_clean = format_city_name(city_name)

    airport = Airport.query.filter(
        Airport.city_ru == city_name_clean
    ).first()

    if airport:
        return {
            'exists': True,
            'city': airport.city_ru,
            'code': airport.iata_code,
            'airport': airport.airport_name,
            'timezone': airport.timezone
        }

    airports = Airport.query.filter(
        Airport.city_ru.ilike(f'%{city_name_clean}%')
    ).all()

    if airports:
        airport = airports[0]
        return {
            'exists': True,
            'city': airport.city_ru,
            'code': airport.iata_code,
            'airport': airport.airport_name,
            'timezone': airport.timezone
        }

    return {'exists': False, 'city': city_name}


def check_city_has_airport(city_name):
    if not city_name:
        return False

    city_name_clean = format_city_name(city_name)

    cities_in_db = Airport.query.with_entities(Airport.city_ru).distinct().all()
    cities_list = [city[0] for city in cities_in_db]

    if city_name_clean in cities_list:
        return True

    for db_city in cities_list:
        if city_name_clean.lower() in db_city.lower() or db_city.lower() in city_name_clean.lower():
            return True

    return False


def get_alternative_cities(city_name):
    if not city_name:
        return []

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


def generate_flights():
    airports = Airport.query.all()
    if len(airports) < 2:
        return

    cities = {}
    for ap in airports:
        if ap.city_ru not in cities:
            cities[ap.city_ru] = []
        cities[ap.city_ru].append(ap)

    city_names = list(cities.keys())

    airlines = [
        ("Аэрофлот", "SU"), ("S7 Airlines", "S7"), ("Уральские авиалинии", "U6"),
        ("Победа", "DP"), ("Россия", "FV"), ("Utair", "UT"), ("Nordwind", "N4"),
        ("Red Wings", "WZ"), ("Azur Air", "ZF"), ("Якутия", "R3"),
    ]

    flights = []
    start_date = datetime.now() + timedelta(days=1)

    for i in range(400):
        origin_city = random.choice(city_names)
        dest_city = random.choice(city_names)
        while dest_city == origin_city:
            dest_city = random.choice(city_names)

        origin_airport = random.choice(cities[origin_city])
        dest_airport = random.choice(cities[dest_city])

        airline = random.choice(airlines)
        days_offset = random.randint(1, 60)

        try:
            origin_tz = pytz.timezone(origin_airport.timezone)
            local_departure = datetime.now(origin_tz) + timedelta(days=days_offset, hours=random.randint(0, 20))
            departure_utc = local_departure.astimezone(pytz.UTC).replace(tzinfo=None)
        except Exception as e:
            continue

        stops_rand = random.random()
        if stops_rand < 0.55:
            stops = 0
            duration = random.randint(60, 300)
        elif stops_rand < 0.85:
            stops = 1
            duration = random.randint(180, 480)
        else:
            stops = 2
            duration = random.randint(360, 720)

        arrival_utc = departure_utc + timedelta(minutes=duration)
        base_price = random.randint(3000, 100000)
        baggage = random.random() < 0.8
        flight_number = f"{airline[1]}{random.randint(100, 999)}"

        stop_info = None
        if stops > 0:
            stop_info = generate_stop_info(origin_city, origin_airport.airport_name,
                                           dest_city, dest_airport.airport_name, stops)

        flight = Flight(
            airline=airline[0],
            flight_number=flight_number,
            origin_city=origin_city,
            origin_code=origin_airport.iata_code,
            origin_airport=origin_airport.airport_name,
            origin_timezone=origin_airport.timezone,
            destination_city=dest_city,
            destination_code=dest_airport.iata_code,
            destination_airport=dest_airport.airport_name,
            destination_timezone=dest_airport.timezone,
            departure_time=departure_utc,
            arrival_time=arrival_utc,
            duration_minutes=duration,
            stops=stops,
            stop_info=json.dumps(stop_info, ensure_ascii=False) if stop_info else None,
            baggage=baggage,
            base_price=base_price
        )
        flights.append(flight)

    if flights:
        try:
            db.session.bulk_save_objects(flights)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
    else:
        print("❌ Не удалось создать ни одного рейса")


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

                stop_info = f.stop_info_parsed

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
                    'total_duration_minutes': f.total_duration_minutes,
                    'total_duration_str': f.total_duration_str,
                    'stops': f.stops,
                    'stop_info': stop_info,
                    'baggage': f.baggage or baggage_addon,
                    'base_price': f.base_price,
                    'price': price,
                    'baggage_price': baggage_price,
                    'duration_str': f.duration_str,
                    'stops_str': f.stops_str
                })
            return result
    except Exception as e:
        print(f"Ошибка при поиске существующих рейсов: {e}")
        db.session.rollback()

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
            print(f"Ошибка при создании времени вылета: {e}")
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

        total_hours = total_duration // 60
        total_mins = total_duration % 60
        total_duration_str = f"{total_hours}ч {total_mins}мин"

        flight_hours = flight_duration // 60
        flight_mins = flight_duration % 60
        flight_duration_str = f"{flight_hours}ч {flight_mins}мин"

        flight_dict = {
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
            'duration_str': flight_duration_str,
            'total_duration_minutes': total_duration,
            'total_duration_str': total_duration_str,
            'stops': stops,
            'stop_info': stop_info_dict,
            'baggage': baggage or baggage_addon,
            'base_price': base_price,
            'price': price,
            'baggage_price': baggage_price,
            'stops_str': "Без пересадок" if stops == 0 else f"{stops} пересадка" if stops == 1 else f"{stops} пересадки"
        }
        generated_flights.append(flight_dict)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при сохранении рейсов: {e}")
        return []

    generated_flights.sort(key=lambda x: x['departure_time'])
    return generated_flights


def get_or_create_flight(flight_id):
    if not flight_id:
        return None

    try:
        flight_id_int = int(flight_id)
        flight = db.session.get(Flight, flight_id_int)
        if flight:
            return flight
    except (ValueError, TypeError):
        pass

    return None


def format_stop_info(stop_info):
    if not stop_info:
        return None
    if isinstance(stop_info, str):
        try:
            return json.loads(stop_info)
        except:
            return stop_info
    return stop_info


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


def calculate_total_price(flight, travel_class, adults, children, infants, baggage_addon=False):
    if hasattr(flight, 'get_price'):
        price_per_adult = flight.get_price(travel_class, baggage_addon)
    else:
        multiplier = CLASSES.get(travel_class, CLASSES['economy'])['multiplier']
        price_per_adult = int(flight['base_price'] * multiplier)
        if baggage_addon:
            price_per_adult += BAGGAGE_PRICE

    price_per_child = int(price_per_adult * 0.5)
    total = (adults * price_per_adult) + (children * price_per_child)

    return {
        'adults_price': price_per_adult,
        'children_price': price_per_child,
        'infants_price': 0,
        'baggage_price': BAGGAGE_PRICE if baggage_addon else 0,
        'total': total
    }


def get_flight_by_id(flight_id):
    if not flight_id:
        return None

    try:
        flight = db.session.get(Flight, int(flight_id))
        if flight:
            return flight
    except (ValueError, TypeError):
        pass

    try:
        all_cached = GeneratedFlightCache.query.all()
        for cached in all_cached:
            flights = json.loads(cached.flights_json)
            for f in flights:
                if str(f['id']) == str(flight_id):
                    departure_time = f['departure_time']
                    arrival_time = f['arrival_time']
                    if isinstance(departure_time, str):
                        departure_time = datetime.fromisoformat(departure_time)
                    if isinstance(arrival_time, str):
                        arrival_time = datetime.fromisoformat(arrival_time)

                    flight = Flight(
                        airline=f['airline'],
                        flight_number=f['flight_number'],
                        origin_city=f['origin_city'],
                        origin_code=f['origin_code'],
                        origin_airport=f.get('origin_airport', f['origin_city']),
                        origin_timezone=f.get('origin_timezone', 'Europe/Moscow'),
                        destination_city=f['destination_city'],
                        destination_code=f['destination_code'],
                        destination_airport=f.get('destination_airport', f['destination_city']),
                        destination_timezone=f.get('destination_timezone', 'Europe/Moscow'),
                        departure_time=departure_time,
                        arrival_time=arrival_time,
                        duration_minutes=f['duration_minutes'],
                        stops=f['stops'],
                        stop_info=json.dumps(f.get('stop_info')) if f.get('stop_info') else None,
                        baggage=f['baggage'],
                        base_price=f['base_price']
                    )
                    db.session.add(flight)
                    db.session.flush()
                    db.session.commit()
                    return flight
    except Exception as e:
        print(f"Ошибка при создании рейса из кэша: {e}")
        db.session.rollback()

    return None


@app.route('/')
def index():
    form = SearchForm()
    today = datetime.now().date()
    form.departure_date.data = today
    form.return_date.data = today + timedelta(days=7)
    form.origin.data = 'Москва'

    popular = db.session.query(
        Flight.origin_city, Flight.origin_code,
        db.func.count(Flight.id).label('count')
    ).group_by(Flight.origin_city).order_by(db.desc('count')).limit(6).all()

    deals = Flight.query.order_by(Flight.base_price).limit(3).all()

    return render_template('index.html', form=form, popular=popular, deals=deals,
                           now=datetime.now(), timedelta=timedelta, CLASSES=CLASSES)


@app.route('/search', methods=['GET', 'POST'])
def search():
    form = SearchForm()

    if request.method == 'GET':
        today = datetime.now().date()
        form.departure_date.data = today
        form.return_date.data = today + timedelta(days=7)
        form.origin.data = 'Москва'
        form.round_trip.data = True

    if form.validate_on_submit():
        origin = format_city_name(form.origin.data)
        destination = format_city_name(form.destination.data)

        origin_has_airport = check_city_has_airport(origin)
        destination_has_airport = check_city_has_airport(destination)

        if not origin_has_airport:
            alternatives = get_alternative_cities(origin)
            if alternatives:
                flash(f'❌ В городе "{origin}" нет аэропорта. Возможно, вы имели в виду: {", ".join(alternatives)}',
                      'danger')
            else:
                flash(f'❌ В городе "{origin}" нет аэропорта. Пожалуйста, выберите другой город.', 'danger')
            return render_template('search.html', form=form, now=datetime.now(), timedelta=timedelta, CLASSES=CLASSES)

        if not destination_has_airport:
            alternatives = get_alternative_cities(destination)
            if alternatives:
                flash(f'❌ В городе "{destination}" нет аэропорта. Возможно, вы имели в виду: {", ".join(alternatives)}',
                      'danger')
            else:
                flash(f'❌ В городе "{destination}" нет аэропорта. Пожалуйста, выберите другой город.', 'danger')
            return render_template('search.html', form=form, now=datetime.now(), timedelta=timedelta, CLASSES=CLASSES)

        if current_user.is_authenticated:
            history = SearchHistory(
                user_id=current_user.id,
                origin=origin,
                destination=destination,
                departure_date=form.departure_date.data,
                return_date=form.return_date.data,
                adults=form.adults.data,
                children=form.children.data,
                infants=form.infants.data,
                travel_class=form.travel_class.data
            )
            db.session.add(history)
            db.session.commit()

        departure_str = form.departure_date.data.strftime('%Y-%m-%d')
        return_date_str = form.return_date.data.strftime('%Y-%m-%d')

        return redirect(url_for('results',
                                origin=origin,
                                destination=destination,
                                departure=departure_str,
                                return_date=return_date_str,
                                round_trip='true',
                                adults=form.adults.data,
                                children=form.children.data,
                                infants=form.infants.data,
                                travel_class=form.travel_class.data,
                                baggage_addon='true' if form.baggage_addon.data else 'false'
                                ))

    return render_template('search.html', form=form, now=datetime.now(), timedelta=timedelta, CLASSES=CLASSES)


@app.route('/results')
def results():
    origin = format_city_name(request.args.get('origin', 'Москва'))
    destination = format_city_name(request.args.get('destination', ''))
    departure_str = request.args.get('departure', '')
    return_str = request.args.get('return_date', '')
    round_trip = request.args.get('round_trip', 'true').lower() == 'true'
    adults = request.args.get('adults', 1, type=int)
    children = request.args.get('children', 0, type=int)
    infants = request.args.get('infants', 0, type=int)
    travel_class = request.args.get('travel_class', 'economy')
    baggage_addon = request.args.get('baggage_addon', 'false').lower() == 'true'

    print(f"=== RESULTS ПАРАМЕТРЫ ===")
    print(f"origin: {origin}, destination: {destination}")
    print(f"round_trip: {round_trip}, return_str: '{return_str}'")
    print(f"departure_str: {departure_str}")

    min_price = request.args.get('min_price', 0, type=int)
    max_price = request.args.get('max_price', 200000, type=int)
    stops = request.args.getlist('stops')
    baggage_only = request.args.get('baggage_only', False, type=bool)
    sort_by = request.args.get('sort_by', 'price_asc')
    departure_time_filter = request.args.get('departure_time', '')

    try:
        dep_date = datetime.strptime(departure_str, '%Y-%m-%d').date()
        if dep_date < datetime.now().date():
            dep_date = datetime.now().date()
    except (ValueError, TypeError):
        dep_date = datetime.now().date()

    origin_has_airport = check_city_has_airport(origin)
    destination_has_airport = check_city_has_airport(destination)

    if not origin_has_airport or not destination_has_airport:
        flash('❌ Один из указанных городов не имеет аэропорта', 'danger')
        return redirect(url_for('search'))

    outbound_flights = generate_flights_for_date(origin, destination, dep_date, travel_class, baggage_addon)
    print(f"Найдено рейсов туда: {len(outbound_flights)}")

    return_flights = []
    if round_trip and return_str and return_str.strip():
        try:
            ret_date = datetime.strptime(return_str, '%Y-%m-%d').date()
            if ret_date < dep_date:
                ret_date = dep_date + timedelta(days=7)
            return_flights = generate_flights_for_date(destination, origin, ret_date, travel_class, baggage_addon)
            print(f"Найдено рейсов обратно: {len(return_flights)}")
        except (ValueError, TypeError) as e:
            print(f"Ошибка парсинга return_date: {e}")

    def apply_filters(flights):
        filtered = []
        for f in flights:
            if f['price'] < min_price or f['price'] > max_price:
                continue
            if stops and str(f['stops']) not in stops:
                continue
            if baggage_only and not f['baggage']:
                continue
            if departure_time_filter:
                try:
                    origin_tz = pytz.timezone(f['origin_timezone'])
                    dt_utc_aware = pytz.UTC.localize(f['departure_time'])
                    local_departure = dt_utc_aware.astimezone(origin_tz)
                    hour = local_departure.hour
                    if departure_time_filter == 'morning' and not (6 <= hour < 12):
                        continue
                    elif departure_time_filter == 'day' and not (12 <= hour < 18):
                        continue
                    elif departure_time_filter == 'evening' and not (18 <= hour < 24):
                        continue
                    elif departure_time_filter == 'night' and not (0 <= hour < 6):
                        continue
                except Exception as e:
                    print(f"Ошибка фильтрации: {e}")
                    continue
            filtered.append(f)

        if sort_by == 'price_asc':
            filtered.sort(key=lambda x: x['price'])
        elif sort_by == 'price_desc':
            filtered.sort(key=lambda x: -x['price'])
        elif sort_by == 'departure_asc':
            filtered.sort(key=lambda x: x['departure_time'])
        elif sort_by == 'duration_asc':
            filtered.sort(key=lambda x: x['duration_minutes'])

        return filtered

    outbound_filtered = apply_filters(outbound_flights)
    return_filtered = apply_filters(return_flights)

    all_prices = []
    for f in outbound_flights + return_flights:
        all_prices.append(f['price'])
    min_price_all = min(all_prices) if all_prices else 0
    max_price_all = max(all_prices) if all_prices else 200000

    return render_template('results.html',
                           flights=outbound_filtered,
                           return_flights=return_filtered,
                           round_trip=round_trip,
                           min_price_all=min_price_all,
                           max_price_all=max_price_all,
                           selected_min=min_price,
                           selected_max=max_price,
                           selected_stops=stops,
                           baggage_only=baggage_only,
                           sort_by=sort_by,
                           departure_time_filter=departure_time_filter,
                           origin=origin,
                           destination=destination,
                           departure=departure_str,
                           return_date=return_str,
                           adults=adults,
                           children=children,
                           infants=infants,
                           travel_class=travel_class,
                           baggage_addon=baggage_addon,
                           CLASSES=CLASSES,
                           BAGGAGE_PRICE=BAGGAGE_PRICE,
                           pytz=pytz)


@app.route('/flight/<flight_id>')
def flight_detail(flight_id):
    try:
        flight = db.session.get(Flight, int(flight_id))
        if flight:
            is_favorite = False
            if current_user.is_authenticated:
                is_favorite = Favorite.query.filter_by(user_id=current_user.id, flight_id=flight.id).first() is not None

            similar = Flight.query.filter(
                Flight.origin_city == flight.origin_city,
                Flight.destination_city == flight.destination_city,
                Flight.id != flight.id
            ).limit(3).all()

            booking_form = BookingForm()
            return render_template('flight_detail.html',
                                   flight=flight, is_favorite=is_favorite, similar=similar,
                                   booking_form=booking_form, CLASSES=CLASSES, BAGGAGE_PRICE=BAGGAGE_PRICE)
    except ValueError:
        pass

    abort(404)


@app.route('/book/<flight_id>', methods=['POST'])
@login_required
def book_flight(flight_id):
    try:
        flight = db.session.get(Flight, int(flight_id))
    except (ValueError, TypeError):
        flight = None

    if not flight:
        flash('Рейс не найден', 'danger')
        return redirect(url_for('search'))

    form = BookingForm()
    if form.validate_on_submit():
        adults = form.adults.data
        children = form.children.data
        infants = form.infants.data
        travel_class = form.travel_class.data
        baggage_addon = form.baggage_addon.data

        multiplier = CLASSES.get(travel_class, CLASSES['economy'])['multiplier']
        price_per_adult = int(flight.base_price * multiplier)
        if baggage_addon and not flight.baggage:
            price_per_adult += BAGGAGE_PRICE

        price_per_child = int(price_per_adult * 0.5)
        total_price = (adults * price_per_adult) + (children * price_per_child)

        booking = Booking(
            user_id=current_user.id,
            flight_id=flight.id,
            adults=adults,
            children=children,
            infants=infants,
            travel_class=travel_class,
            baggage_addon=baggage_addon,
            adults_price=price_per_adult,
            children_price=price_per_child,
            infants_price=0,
            baggage_price=BAGGAGE_PRICE if baggage_addon else 0,
            total_price=total_price,
            status='confirmed'
        )
        booking.booking_number = booking.generate_booking_number()

        db.session.add(booking)
        db.session.commit()

        flash(f'Билет успешно забронирован! Номер брони: {booking.booking_number}', 'success')
        return redirect(url_for('my_bookings'))

    flash('Ошибка при бронировании', 'danger')
    return redirect(url_for('flight_detail', flight_id=flight.id))


@app.route('/my_bookings')
@login_required
def my_bookings():
    regular_bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    round_trip_bookings = RoundTripBooking.query.filter_by(user_id=current_user.id).order_by(
        RoundTripBooking.booking_date.desc()).all()

    all_bookings = []
    for b in regular_bookings:
        all_bookings.append({
            'type': 'one_way',
            'data': b,
            'booking_date': b.booking_date
        })
    for b in round_trip_bookings:
        all_bookings.append({
            'type': 'round_trip',
            'data': b,
            'booking_date': b.booking_date
        })
    all_bookings.sort(key=lambda x: x['booking_date'], reverse=True)

    return render_template('my_bookings.html',
                           bookings=all_bookings,
                           CLASSES=CLASSES,
                           BAGGAGE_PRICE=BAGGAGE_PRICE)


@app.route('/cancel_booking/<int:booking_id>')
@login_required
def cancel_booking(booking_id):
    booking = db.session.get(Booking, booking_id)
    if not booking or booking.user_id != current_user.id:
        abort(404)
    booking.status = 'cancelled'
    db.session.commit()
    flash('Бронирование отменено', 'info')
    return redirect(url_for('my_bookings'))


@app.route('/add_favorite/<flight_id>')
@login_required
def add_favorite(flight_id):
    try:
        flight = db.session.get(Flight, int(flight_id))
    except ValueError:
        flight = None

    if not flight:
        abort(404)

    existing = Favorite.query.filter_by(user_id=current_user.id, flight_id=flight.id).first()
    if not existing:
        fav = Favorite(user_id=current_user.id, flight_id=flight.id)
        db.session.add(fav)
        db.session.commit()
        flash('Добавлено в избранное', 'success')

    return redirect(request.referrer or url_for('flight_detail', flight_id=flight.id))


@app.route('/remove_favorite/<int:flight_id>', methods=['POST'])
@login_required
def remove_favorite_post(flight_id):
    try:
        flight = db.session.get(Flight, flight_id)
        if not flight:
            return jsonify({'success': False, 'error': 'Рейс не найден'}), 404

        fav = Favorite.query.filter_by(user_id=current_user.id, flight_id=flight.id).first()
        if fav:
            db.session.delete(fav)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Удалено из избранного'})
        else:
            return jsonify({'success': False, 'error': 'Рейс не найден в избранном'}), 404
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при удалении из избранного: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/remove_favorite/<int:flight_id>', methods=['GET'])
@login_required
def remove_favorite_get(flight_id):
    try:
        flight = db.session.get(Flight, flight_id)
        if flight:
            fav = Favorite.query.filter_by(user_id=current_user.id, flight_id=flight.id).first()
            if fav:
                db.session.delete(fav)
                db.session.commit()
                flash('Удалено из избранного', 'success')
            else:
                flash('Рейс не найден в избранном', 'warning')
        else:
            flash('Рейс не найден', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('profile'))


@app.route('/profile')
@login_required
def profile():
    avatar_form = AvatarForm()
    favorites = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    history = SearchHistory.query.filter_by(user_id=current_user.id).order_by(SearchHistory.created_at.desc()).limit(
        10).all()

    regular_bookings = Booking.query.filter_by(user_id=current_user.id, status='confirmed').all()
    round_trip_bookings = RoundTripBooking.query.filter_by(user_id=current_user.id, status='confirmed').all()

    all_bookings = []
    for b in regular_bookings:
        all_bookings.append({
            'type': 'one_way',
            'data': b,
            'booking_date': b.booking_date
        })
    for b in round_trip_bookings:
        all_bookings.append({
            'type': 'round_trip',
            'data': b,
            'booking_date': b.booking_date
        })

    all_bookings.sort(key=lambda x: x['booking_date'], reverse=True)

    return render_template('profile.html',
                           user=current_user,
                           favorites=favorites,
                           history=history,
                           bookings=all_bookings,
                           avatar_form=avatar_form,
                           CLASSES=CLASSES,
                           BAGGAGE_PRICE=BAGGAGE_PRICE)


@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    form = AvatarForm()
    if form.validate_on_submit() and form.avatar.data:
        if current_user.avatar != 'default_avatar.png':
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], current_user.avatar)
            if os.path.exists(old_path):
                os.remove(old_path)
        filename = save_avatar(form.avatar.data)
        current_user.avatar = filename
        db.session.commit()
        flash('Аватар обновлен!', 'success')
    else:
        flash('Ошибка при загрузке', 'danger')
    return redirect(url_for('profile'))


@app.route('/clear_history')
@login_required
def clear_history():
    SearchHistory.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash('История очищена', 'success')
    return redirect(url_for('profile'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash('Добро пожаловать!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('profile'))
        else:
            flash('Неверный email или пароль', 'danger')
    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Регистрация успешна! Теперь можно войти', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/select_flight/<flight_id>')
def select_flight(flight_id):
    flight_type = request.args.get('type', 'outbound')

    flight = get_flight_by_id(flight_id)

    if not flight:
        flash('Рейс не найден', 'danger')
        return redirect(url_for('search'))

    if flight_type == 'outbound':
        return_date = request.args.get('return_date')
        origin = request.args.get('origin')
        destination = request.args.get('destination')

        if return_date and origin and destination:
            return redirect(url_for('select_return_flight',
                                    outbound_id=flight.id,
                                    return_date=return_date,
                                    origin=origin,
                                    destination=destination,
                                    travel_class=request.args.get('travel_class', 'economy'),
                                    adults=request.args.get('adults', 1),
                                    children=request.args.get('children', 0),
                                    infants=request.args.get('infants', 0),
                                    baggage_addon=request.args.get('baggage_addon', 'false')))
        else:
            return redirect(url_for('confirm_booking',
                                    outbound_id=flight.id,
                                    adults=request.args.get('adults', 1),
                                    children=request.args.get('children', 0),
                                    infants=request.args.get('infants', 0),
                                    travel_class=request.args.get('travel_class', 'economy'),
                                    baggage_addon=request.args.get('baggage_addon', 'false')))

    return redirect(url_for('flight_detail', flight_id=flight.id))


@app.route('/select_return_flight')
def select_return_flight():
    outbound_id = request.args.get('outbound_id')
    return_date = request.args.get('return_date')
    origin = request.args.get('origin')
    destination = request.args.get('destination')
    travel_class = request.args.get('travel_class', 'economy')
    adults = request.args.get('adults', 1, type=int)
    children = request.args.get('children', 0, type=int)
    infants = request.args.get('infants', 0, type=int)
    baggage_addon = request.args.get('baggage_addon', 'false').lower() == 'true'

    try:
        outbound_flight = db.session.get(Flight, int(outbound_id))
    except (ValueError, TypeError):
        outbound_flight = None

    if not outbound_flight:
        flash('Рейс туда не найден', 'danger')
        return redirect(url_for('search'))

    try:
        ret_date = datetime.strptime(return_date, '%Y-%m-%d').date()
    except:
        ret_date = datetime.now().date() + timedelta(days=7)

    return_flights = generate_flights_for_date(origin, destination, ret_date, travel_class, baggage_addon)

    return render_template('select_return.html',
                           outbound_flight=outbound_flight,
                           return_flights=return_flights,
                           outbound_id=outbound_id,
                           return_date=return_date,
                           travel_class=travel_class,
                           adults=adults,
                           children=children,
                           infants=infants,
                           baggage_addon=baggage_addon,
                           CLASSES=CLASSES,
                           BAGGAGE_PRICE=BAGGAGE_PRICE,
                           pytz=pytz)


@app.route('/confirm_booking')
def confirm_booking():
    outbound_id = request.args.get('outbound_id')
    return_id = request.args.get('return_id')

    outbound_flight = get_flight_by_id(outbound_id)
    return_flight = get_flight_by_id(return_id) if return_id else None

    if not outbound_flight:
        flash('Ошибка: рейс туда не найден', 'danger')
        return redirect(url_for('search'))

    adults = request.args.get('adults', 1, type=int)
    children = request.args.get('children', 0, type=int)
    infants = request.args.get('infants', 0, type=int)
    travel_class = request.args.get('travel_class', 'economy')
    baggage_addon = request.args.get('baggage_addon', 'false').lower() == 'true'

    outbound_prices = calculate_flight_price(outbound_flight, travel_class, adults, children, infants, baggage_addon)
    return_prices = calculate_flight_price(return_flight, travel_class, adults, children, infants,
                                           baggage_addon) if return_flight else {'total': 0, 'adults_price': 0,
                                                                                 'children_price': 0}

    total_price = outbound_prices['total'] + return_prices['total']

    return render_template('confirm_booking.html',
                           outbound_flight=outbound_flight,
                           return_flight=return_flight,
                           outbound_prices=outbound_prices,
                           return_prices=return_prices,
                           total_price=total_price,
                           adults=adults,
                           children=children,
                           infants=infants,
                           travel_class=travel_class,
                           baggage_addon=baggage_addon,
                           CLASSES=CLASSES,
                           BAGGAGE_PRICE=BAGGAGE_PRICE)


@app.route('/complete_booking', methods=['POST'])
@login_required
def complete_booking():
    outbound_id = request.form.get('outbound_id')
    return_id = request.form.get('return_id')
    adults = int(request.form.get('adults', 1))
    children = int(request.form.get('children', 0))
    infants = int(request.form.get('infants', 0))
    travel_class = request.form.get('travel_class', 'economy')
    baggage_addon = request.form.get('baggage_addon', 'false').lower() == 'true'

    try:
        outbound_flight = db.session.get(Flight, int(outbound_id))
        return_flight = db.session.get(Flight, int(return_id)) if return_id else None
    except (ValueError, TypeError):
        flash('Ошибка: неверный номер рейса', 'danger')
        return redirect(url_for('search'))

    if not outbound_flight:
        flash('Ошибка: рейс не найден', 'danger')
        return redirect(url_for('search'))

    outbound_prices = calculate_flight_price(outbound_flight, travel_class, adults, children, infants, baggage_addon)
    return_prices = calculate_flight_price(return_flight, travel_class, adults, children, infants,
                                           baggage_addon) if return_flight else {'total': 0}

    total_price = outbound_prices['total'] + return_prices['total']

    booking = RoundTripBooking(
        user_id=current_user.id,
        outbound_flight_id=outbound_flight.id,
        return_flight_id=return_flight.id if return_flight else None,
        adults=adults,
        children=children,
        infants=infants,
        travel_class=travel_class,
        baggage_addon=baggage_addon,
        outbound_price=outbound_prices['total'],
        return_price=return_prices['total'],
        total_price=total_price,
        status='confirmed'
    )
    booking.booking_number = booking.generate_booking_number()
    db.session.add(booking)
    db.session.commit()

    flash(f'Билеты успешно забронированы! Номер брони: {booking.booking_number}', 'success')
    return redirect(url_for('my_round_trip_bookings'))


@app.route('/my_round_trip_bookings')
@login_required
def my_round_trip_bookings():
    bookings = RoundTripBooking.query.filter_by(user_id=current_user.id).order_by(
        RoundTripBooking.booking_date.desc()).all()
    return render_template('round_trip_bookings.html',
                           bookings=bookings,
                           CLASSES=CLASSES,
                           BAGGAGE_PRICE=BAGGAGE_PRICE)


class AirportAPI(Resource):
    def get(self):
        query = request.args.get('q', '').lower()
        if len(query) < 2:
            return {'results': []}
        cities = Airport.query.filter(
            Airport.city_ru.ilike(f'{query}%')
        ).with_entities(Airport.city_ru, Airport.iata_code, Airport.airport_name).distinct().limit(10).all()
        return {'results': [
            {'id': f"{city}|{code}", 'text': f"{city} ({code})", 'city': city, 'code': code, 'airport': airport} for
            city, code, airport in cities]}


class UserFavoritesAPI(Resource):
    @login_required
    def get(self):
        try:
            favorites = Favorite.query.filter_by(user_id=current_user.id).all()
            favorite_ids = [fav.flight_id for fav in favorites]
            return {'success': True, 'favorites': favorite_ids}
        except Exception as e:
            return {'success': False, 'error': str(e)}, 500


api.add_resource(UserFavoritesAPI, '/api/user_favorites')


class DestinationAPI(Resource):
    def get(self):
        origin = request.args.get('origin', '').lower()
        query = request.args.get('q', '').lower()
        if len(origin) < 2 or len(query) < 2:
            return {'results': []}
        destinations = Airport.query.filter(
            Airport.city_ru.ilike(f'{query}%')
        ).filter(Airport.city_ru != origin).with_entities(Airport.city_ru, Airport.iata_code,
                                                          Airport.airport_name).distinct().limit(10).all()
        return {'results': [
            {'id': f"{city}|{code}", 'text': f"{city} ({code})", 'city': city, 'code': code, 'airport': airport} for
            city, code, airport in destinations]}


api.add_resource(AirportAPI, '/api/airports')
api.add_resource(DestinationAPI, '/api/destinations')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return render_template('500.html'), 500


@app.template_filter('local_time')
def local_time_filter(dt_utc, timezone_str):
    if not dt_utc or not timezone_str:
        return dt_utc
    try:
        tz = pytz.timezone(timezone_str)
        dt_utc_aware = pytz.UTC.localize(dt_utc)
        return dt_utc_aware.astimezone(tz)
    except Exception as e:
        print(f"Ошибка конвертации времени: {e}")
        return dt_utc


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if Airport.query.count() == 0:
            add_airports_from_list()
        create_default_avatar()
        if Flight.query.count() == 0:
            generate_flights()

    print("http://127.0.0.1:5000")
    app.run(debug=True)