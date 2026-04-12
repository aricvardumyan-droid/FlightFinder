# app/models.py
import json
import uuid
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from app import CLASSES, BAGGAGE_PRICE


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
        if baggage_addon and not self.baggage:
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
        try:
            return json.loads(self.stop_info)
        except:
            return self.stop_info

    @property
    def total_duration_minutes(self):
        if not self.stop_info_parsed or self.stops == 0:
            return self.duration_minutes
        total_layover = 0
        if isinstance(self.stop_info_parsed, list):
            for stop in self.stop_info_parsed:
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


class GeneratedFlightCache(db.Model):
    __tablename__ = 'generated_flight_cache'
    id = db.Column(db.Integer, primary_key=True)
    search_hash = db.Column(db.String(64), unique=True, nullable=False)
    flights_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)