# app/routes/flights.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import json
from app import db, CLASSES, BAGGAGE_PRICE, csrf
from app.forms import BookingForm
from app.models import Flight, Favorite
from app.utils import generate_flights_for_date

bp = Blueprint('flights', __name__)


@bp.route('/flight/<flight_id>')
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
                                   flight=flight,
                                   is_favorite=is_favorite,
                                   similar=similar,
                                   booking_form=booking_form)
    except ValueError:
        pass

    abort(404)


@bp.route('/add_to_favorites', methods=['POST'])
@login_required
@csrf.exempt
def add_to_favorites():
    try:
        data = request.get_json()
        flight_id = data.get('flight_id')

        flight = None
        if flight_id:
            try:
                flight = db.session.get(Flight, int(flight_id))
            except (ValueError, TypeError):
                pass

        if not flight:
            from datetime import datetime
            import json

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

        existing_fav = Favorite.query.filter_by(user_id=current_user.id, flight_id=flight.id).first()
        if existing_fav:
            return jsonify({'success': False, 'error': 'Уже в избранном'}), 400

        favorite = Favorite(user_id=current_user.id, flight_id=flight.id)
        db.session.add(favorite)
        db.session.commit()

        return jsonify({'success': True, 'flight_id': flight.id, 'message': 'Рейс добавлен в избранное'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/remove_favorite/<int:flight_id>', methods=['POST'])
@login_required
@csrf.exempt
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
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/remove_favorite/<int:flight_id>', methods=['GET'])
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

    return redirect(request.referrer or url_for('profile.profile'))


@bp.route('/select_return_flight')
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
        return redirect(url_for('main.search'))

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
                           baggage_addon=baggage_addon)


@bp.route('/uploads/<filename>')
def uploaded_file(filename):
    from flask import send_from_directory
    import os
    from flask import current_app
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)



@bp.route('/add_favorite/<flight_id>')
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

    return redirect(request.referrer or url_for('flights.flight_detail', flight_id=flight.id))


@bp.route('/add_favorite/<flight_id>')
@login_required
def add_favorite_get(flight_id):
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
    else:
        flash('Рейс уже в избранном', 'info')

    return redirect(request.referrer or url_for('flights.flight_detail', flight_id=flight.id))