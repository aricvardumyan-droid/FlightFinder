from app import create_app, db
from app.models import Airport, Flight

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("База данных создана")

        if Airport.query.count() == 0:
            print("Добавляем аэропорты...")
            from app.utils import add_airports_from_list

            add_airports_from_list()
        else:
            print(f"Аэропорты уже есть: {Airport.query.count()}")

        if Flight.query.count() == 0:
            print("Генерируем рейсы...")
            from app.utils import generate_flights

            generate_flights()
        else:
            print(f"Рейсы уже есть: {Flight.query.count()}")

    print("Сервер запущен на http://127.0.0.1:5000")
    app.run(debug=True)
