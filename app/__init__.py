# app/__init__.py
import os
from datetime import datetime, timedelta
from flask import Flask, render_template
from flask_login import LoginManager
from flask_restful import Api, Resource
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask import request
from flask_login import login_required, current_user

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
api = Api()

CLASSES = {
    'economy': {'name': 'Эконом', 'multiplier': 1.0},
    'comfort': {'name': 'Комфорт', 'multiplier': 1.5},
    'business': {'name': 'Бизнес', 'multiplier': 2.5},
    'first': {'name': 'Первый класс', 'multiplier': 4.0}
}
BAGGAGE_PRICE = 5200


def create_app():
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')

    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    app.config['SECRET_KEY'] = 'flightfinder-2026-super-secret-key'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'flightfinder.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(basedir, 'instance'), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Пожалуйста, войдите'
    csrf.init_app(app)

    from app.routes import main, auth, bookings, profile, flights
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(bookings.bp)
    app.register_blueprint(profile.bp)
    app.register_blueprint(flights.bp)

    from app.models import Airport, Flight, Favorite

    class AirportAPI(Resource):
        def get(self):
            query = request.args.get('q', '').lower()
            if len(query) < 2:
                return {'results': []}
            cities = Airport.query.filter(
                Airport.city_ru.ilike(f'{query}%')
            ).with_entities(Airport.city_ru, Airport.iata_code, Airport.airport_name).distinct().limit(10).all()
            return {'results': [
                {'id': f"{city}|{code}", 'text': f"{city} ({code})", 'city': city, 'code': code, 'airport': airport}
                for city, code, airport in cities]}

    class DestinationAPI(Resource):
        def get(self):
            origin = request.args.get('origin', '').lower()
            query = request.args.get('q', '').lower()
            if len(origin) < 2 or len(query) < 2:
                return {'results': []}
            destinations = Airport.query.filter(
                Airport.city_ru.ilike(f'{query}%')
            ).filter(Airport.city_ru != origin).with_entities(
                Airport.city_ru, Airport.iata_code, Airport.airport_name
            ).distinct().limit(10).all()
            return {'results': [
                {'id': f"{city}|{code}", 'text': f"{city} ({code})", 'city': city, 'code': code, 'airport': airport}
                for city, code, airport in destinations]}

    class FlightDetailAPI(Resource):
        def get(self, flight_id):
            try:
                flight = db.session.get(Flight, int(flight_id))
                if not flight:
                    return {'success': False, 'error': 'Рейс не найден'}, 404

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
                        'stop_info': flight.stop_info_parsed,
                        'baggage': flight.baggage,
                        'base_price': flight.base_price,
                        'price': price,
                    }
                }
            except Exception as e:
                return {'success': False, 'error': str(e)}, 500

    class UserFavoritesAPI(Resource):
        @login_required
        def get(self):
            try:
                favorites = Favorite.query.filter_by(user_id=current_user.id).all()
                favorite_ids = [fav.flight_id for fav in favorites]
                return {'success': True, 'favorites': favorite_ids}
            except Exception as e:
                return {'success': False, 'error': str(e)}, 500

    api.add_resource(AirportAPI, '/api/airports')
    api.add_resource(DestinationAPI, '/api/destinations')
    api.add_resource(FlightDetailAPI, '/api/flight/<int:flight_id>')
    api.add_resource(UserFavoritesAPI, '/api/user_favorites')
    api.init_app(app)

    # Фильтры шаблонов
    import pytz
    @app.template_filter('local_time')
    def local_time_filter(dt_utc, timezone_str):
        if not dt_utc or not timezone_str:
            return dt_utc
        try:
            tz = pytz.timezone(timezone_str)
            dt_utc_aware = pytz.UTC.localize(dt_utc)
            return dt_utc_aware.astimezone(tz)
        except:
            return dt_utc

    @app.context_processor
    def utility_processor():
        return {
            'now': datetime.now(),
            'timedelta': timedelta,
            'CLASSES': CLASSES,
            'BAGGAGE_PRICE': BAGGAGE_PRICE,
            'pytz': pytz
        }

    @app.errorhandler(404)
    def not_found(e):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        return render_template('500.html'), 500

    return app


@login_manager.user_loader
def load_user(user_id):
    from app.models import User
    return db.session.get(User, int(user_id))