
from __init__ import reg_app, mysql

app = reg_app()

with app.app_context():
    cursor = None

    try:
        cursor = mysql.connection.cursor()

        cursor.execute("SELECT DATABASE()")
        print("Connected Database:", cursor.fetchone())

        cursor.execute("SHOW TABLES")
        print("Database Tables:")

        for table in cursor.fetchall():
            print(table)

        print("MySQL Connection Successful!")

    except Exception as e:
        print("Database Error:", e)

    finally:
        if cursor is not None:
            cursor.close()
