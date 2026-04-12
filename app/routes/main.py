# app/routes/main.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db, CLASSES, BAGGAGE_PRICE
from app.forms import SearchForm
from app.models import SearchHistory, Flight
from app.utils import (format_city_name, check_city_has_airport, get_alternative_cities,
                       generate_flights_for_date, calculate_flight_price)

bp = Blueprint('main', __name__)


@bp.route('/')
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

    return render_template('index.html', form=form, popular=popular, deals=deals)


@bp.route('/search', methods=['GET', 'POST'])
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
                flash(f'В городе "{origin}" нет аэропорта. Возможно, вы имели в виду: {", ".join(alternatives)}',
                      'danger')
            else:
                flash(f'В городе "{origin}" нет аэропорта', 'danger')
            return render_template('search.html', form=form)

        if not destination_has_airport:
            alternatives = get_alternative_cities(destination)
            if alternatives:
                flash(f'В городе "{destination}" нет аэропорта. Возможно, вы имели в виду: {", ".join(alternatives)}',
                      'danger')
            else:
                flash(f'В городе "{destination}" нет аэропорта', 'danger')
            return render_template('search.html', form=form)

        if current_user.is_authenticated:
            history = SearchHistory(
                user_id=current_user.id,
                origin=origin,
                destination=destination,
                departure_date=form.departure_date.data,
                return_date=form.return_date.data if form.return_date.data else None,
                adults=form.adults.data,
                children=form.children.data,
                infants=form.infants.data,
                travel_class=form.travel_class.data
            )
            db.session.add(history)
            db.session.commit()

        departure_str = form.departure_date.data.strftime('%Y-%m-%d')
        return_date_str = form.return_date.data.strftime('%Y-%m-%d') if form.return_date.data else ''

        return redirect(url_for('main.results',
                                origin=origin,
                                destination=destination,
                                departure=departure_str,
                                return_date=return_date_str,
                                round_trip='true' if form.round_trip.data else 'false',
                                adults=form.adults.data,
                                children=form.children.data,
                                infants=form.infants.data,
                                travel_class=form.travel_class.data,
                                baggage_addon='true' if form.baggage_addon.data else 'false'))

    return render_template('search.html', form=form)


@bp.route('/results')
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

    if not check_city_has_airport(origin) or not check_city_has_airport(destination):
        flash('Один из указанных городов не имеет аэропорта', 'danger')
        return redirect(url_for('main.search'))

    outbound_flights = generate_flights_for_date(origin, destination, dep_date, travel_class, baggage_addon)

    return_flights = []
    if round_trip and return_str and return_str.strip():
        try:
            ret_date = datetime.strptime(return_str, '%Y-%m-%d').date()
            if ret_date < dep_date:
                ret_date = dep_date + timedelta(days=7)
            return_flights = generate_flights_for_date(destination, origin, ret_date, travel_class, baggage_addon)
        except (ValueError, TypeError):
            pass

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
                    import pytz
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
                except:
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
                           baggage_addon=baggage_addon)



@bp.route('/select_flight/<flight_id>')
def select_flight(flight_id):
    from app.utils import get_flight_by_id

    flight_type = request.args.get('type', 'outbound')

    flight = get_flight_by_id(flight_id)

    if not flight:
        flash('Рейс не найден', 'danger')
        return redirect(url_for('main.search'))

    if flight_type == 'outbound':
        return_date = request.args.get('return_date')
        origin = request.args.get('origin')
        destination = request.args.get('destination')

        if return_date and origin and destination:
            return redirect(url_for('flights.select_return_flight',
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
            return redirect(url_for('bookings.confirm_booking',
                                    outbound_id=flight.id,
                                    adults=request.args.get('adults', 1),
                                    children=request.args.get('children', 0),
                                    infants=request.args.get('infants', 0),
                                    travel_class=request.args.get('travel_class', 'economy'),
                                    baggage_addon=request.args.get('baggage_addon', 'false')))

    return redirect(url_for('flights.flight_detail', flight_id=flight.id))