# app/forms.py
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, BooleanField, DateField, IntegerField, SelectField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, NumberRange
from datetime import datetime


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
        from app.models import User
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Это имя уже занято')

    def validate_email(self, email):
        from app.models import User
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


class AvatarForm(FlaskForm):
    avatar = FileField('Выберите изображение', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Только изображения!')
    ])
    submit = SubmitField('Загрузить')

class ConfirmBookingForm(FlaskForm):
    submit = SubmitField('Подтвердить бронирование')