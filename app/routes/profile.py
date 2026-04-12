# app/routes/profile.py
import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app import db, CLASSES, BAGGAGE_PRICE
from app.forms import AvatarForm
from app.models import Favorite, SearchHistory, Booking, RoundTripBooking
from app.utils import save_avatar

bp = Blueprint('profile', __name__)


@bp.route('/profile')
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
        all_bookings.append({'type': 'one_way', 'data': b, 'booking_date': b.booking_date})
    for b in round_trip_bookings:
        all_bookings.append({'type': 'round_trip', 'data': b, 'booking_date': b.booking_date})
    all_bookings.sort(key=lambda x: x['booking_date'], reverse=True)

    return render_template('profile.html',
                           user=current_user,
                           favorites=favorites,
                           history=history,
                           bookings=all_bookings,
                           avatar_form=avatar_form)


@bp.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    form = AvatarForm()
    if form.validate_on_submit() and form.avatar.data:
        if current_user.avatar != 'default_avatar.png':
            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], current_user.avatar)
            if os.path.exists(old_path):
                os.remove(old_path)
        filename = save_avatar(form.avatar.data)
        current_user.avatar = filename
        db.session.commit()
        flash('Аватар обновлен!', 'success')
    else:
        flash('Ошибка при загрузке', 'danger')
    return redirect(url_for('profile.profile'))


@bp.route('/clear_history')
@login_required
def clear_history():
    SearchHistory.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash('История очищена', 'success')
    return redirect(url_for('profile.profile'))