# app/routes/bookings.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db, CLASSES, BAGGAGE_PRICE
from app.forms import BookingForm, ConfirmBookingForm
from app.models import Booking, RoundTripBooking, Flight
from app.utils import calculate_flight_price, get_flight_by_id
from app import csrf

bp = Blueprint('bookings', __name__)


@bp.route('/my_bookings')
@login_required
def my_bookings():
    regular_bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    round_trip_bookings = RoundTripBooking.query.filter_by(user_id=current_user.id).order_by(
        RoundTripBooking.booking_date.desc()).all()

    all_bookings = []
    for b in regular_bookings:
        all_bookings.append({'type': 'one_way', 'data': b, 'booking_date': b.booking_date})
    for b in round_trip_bookings:
        all_bookings.append({'type': 'round_trip', 'data': b, 'booking_date': b.booking_date})
    all_bookings.sort(key=lambda x: x['booking_date'], reverse=True)

    return render_template('my_bookings.html', bookings=all_bookings)


@bp.route('/book/<flight_id>', methods=['POST'])
@login_required
def book_flight(flight_id):
    try:
        flight = db.session.get(Flight, int(flight_id))
    except (ValueError, TypeError):
        flight = None

    if not flight:
        flash('Рейс не найден', 'danger')
        return redirect(url_for('main.search'))

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
        return redirect(url_for('bookings.my_bookings'))

    flash('Ошибка при бронировании', 'danger')
    return redirect(url_for('flights.flight_detail', flight_id=flight.id))


@bp.route('/cancel_booking_confirm/<int:booking_id>')
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
        return redirect(url_for('bookings.my_bookings'))

    return render_template('cancel_booking_confirm.html', booking=booking)


@bp.route('/cancel_booking_with_captcha/<int:booking_id>', methods=['POST'])
@login_required
@csrf.exempt
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
            return redirect(url_for('bookings.my_round_trip_bookings'))
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

    return redirect(url_for('bookings.my_bookings'))


@bp.route('/my_round_trip_bookings')
@login_required
def my_round_trip_bookings():
    bookings = RoundTripBooking.query.filter_by(user_id=current_user.id).order_by(
        RoundTripBooking.booking_date.desc()).all()
    return render_template('round_trip_bookings.html', bookings=bookings)


@bp.route('/confirm_booking')
def confirm_booking():
    outbound_id = request.args.get('outbound_id')
    return_id = request.args.get('return_id')

    outbound_flight = get_flight_by_id(outbound_id)
    return_flight = get_flight_by_id(return_id) if return_id else None

    if not outbound_flight:
        flash('Ошибка: рейс туда не найден', 'danger')
        return redirect(url_for('main.search'))

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

    form = ConfirmBookingForm()

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
                           form=form)


@bp.route('/complete_booking', methods=['POST'])
@login_required
@csrf.exempt
def complete_booking():
    # Валидация CSRF
    form = ConfirmBookingForm()
    if not form.validate_on_submit():
        flash('Ошибка валидации формы. Пожалуйста, попробуйте снова.', 'danger')
        return redirect(url_for('main.search'))

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
        return redirect(url_for('main.search'))

    if not outbound_flight:
        flash('Ошибка: рейс не найден', 'danger')
        return redirect(url_for('main.search'))

    multiplier = CLASSES.get(travel_class, CLASSES['economy'])['multiplier']
    outbound_price_per_adult = int(outbound_flight.base_price * multiplier)
    if baggage_addon and not outbound_flight.baggage:
        outbound_price_per_adult += BAGGAGE_PRICE

    outbound_price_per_child = int(outbound_price_per_adult * 0.5)
    outbound_total = (adults * outbound_price_per_adult) + (children * outbound_price_per_child)

    return_total = 0
    if return_flight:
        return_price_per_adult = int(return_flight.base_price * multiplier)
        if baggage_addon and not return_flight.baggage:
            return_price_per_adult += BAGGAGE_PRICE
        return_price_per_child = int(return_price_per_adult * 0.5)
        return_total = (adults * return_price_per_adult) + (children * return_price_per_child)

    total_price = outbound_total + return_total

    booking = RoundTripBooking(
        user_id=current_user.id,
        outbound_flight_id=outbound_flight.id,
        return_flight_id=return_flight.id if return_flight else None,
        adults=adults,
        children=children,
        infants=infants,
        travel_class=travel_class,
        baggage_addon=baggage_addon,
        outbound_price=outbound_total,
        return_price=return_total,
        total_price=total_price,
        status='confirmed'
    )
    booking.booking_number = booking.generate_booking_number()
    db.session.add(booking)
    db.session.commit()

    flash(f'Билеты успешно забронированы! Номер брони: {booking.booking_number}', 'success')
    return redirect(url_for('bookings.my_round_trip_bookings'))


@bp.route('/cancel_booking/<int:booking_id>')
@login_required
def cancel_booking(booking_id):
    booking = db.session.get(Booking, booking_id)
    if not booking or booking.user_id != current_user.id:
        abort(404)
    booking.status = 'cancelled'
    db.session.commit()
    flash('Бронирование отменено', 'info')
    return redirect(url_for('bookings.my_bookings'))